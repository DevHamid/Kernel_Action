# Extracting files from an AOSP OTA payload (no root, no AOSP tools)

Scope: turning what the user actually uploads — `*.new.dat.br` +
`*.patch.dat` + `*.transfer.list` — into a raw partition image, and reading
files out of it. Companion to `q6-subsystem-bringup.md` §6, which it corrects
on one important point.

## 1. Recognise the payload shape first — it is NOT a sparse image

A `.dat.br` + `.transfer.list` + `.patch.dat` triple is an **OTA block-based
payload**, not an Android sparse image. `scripts/simg2img.py` does not apply
and will reject it on the magic check. Do not reach for it because the
extension says "image".

**`vendor.patch.dat` at 0 bytes means a FULL image, not an incremental.**
There is nothing to apply; every byte of the target comes from `new.dat`.
A non-zero `patch.dat` would mean the opposite and a much longer job.

## 2. Decompress the brotli stream

No `brotli` module and no `brotli` binary on a stock host. The fix is one
command, and it works:

```sh
python3 -m pip install brotli
```

Then stream it in chunks rather than loading the whole file — the output is
~2.4x the compressed size and the host may be memory-tight:

```python
import brotli
d = brotli.Decompressor()
while chunk := f.read(1 << 20):
    o.write(d.process(chunk))
```

## 3. The `transfer.list` grammar — the part that costs the most time

Run `scripts/ota_transfer_list_to_raw.py <dir> <name>` for this; the rules
below are what it encodes and what to check by hand.

```
line 1: version
line 2: block count            <-- NOT RELIABLE, see §5
line 3: max stash blocks
line 4+: <verb> <nvals>,<v1>,<v2>,...,<vN>
```

- **`nvals` is always EVEN, and it counts the VALUES that follow, not ranges.**
  `new 2,42248,42760` is one range; `new 264,10396,10398,...` is 132 ranges.
  Reading `nvals` as a range count is the single most expensive misreading
  available here, because every line then parses "successfully" and produces
  a plausible-looking wrong image.
- **The values pair up as `(start, end)` with end EXCLUSIVE.** Not
  `(start, count)`. Assert `end > start` on every pair while parsing.
- **For `new`, the payload is read SEQUENTIALLY from `.new.dat` in the order
  the ranges appear, and written to the ranges as DESTINATIONS.** This is the
  counter-intuitive half: the scattered numbers are where the data GOES, not
  where it comes from.
- `zero` and `erase` use the same range grammar and write zeros.

## 4. Two gates that prove the parse — run both before trusting the image

Both are one-liners and both are cheap. Neither is optional.

**(a) The range sum must equal the source file exactly.**

```python
sum(e - s for every range in every 'new' line) * blk_sz == len(new_dat)
```

A match to the byte proves the pairing and the sequential-read semantics at
once. A mismatch means the grammar is still wrong — stop and re-derive.

**(b) Locate a real filesystem superblock and prove it lands at block 0.**

Scan the source stream for the ext4 magic: the superblock sits at filesystem
offset 1024, `s_magic` (0xEF53, bytes `53 ef`) at superblock offset 56, and
superblocks are block-aligned, so scan offsets where
`(off - 1080) % blk_sz == 0`:

```python
blk = off - 1080
if blk >= 0 and blk % blk_sz == 0 and buf[off:off+2] == b'\x53\xef':
    inodes, blocks = struct.unpack('<II', buf[blk+1024:blk+1032])
```

Then walk the sequential cursor through the `new` commands to find which one
covers that source block, and map the offset within it to a destination block.
**The destination must be 0.** That single check is what distinguishes
"ranges are destinations" from "ranges are sources" — the two interpretations
are indistinguishable from the range sum alone, and only one of them puts the
superblock where a filesystem needs it.

Validate the finished image the same way: read offset 1024 of the raw file and
confirm `s_magic == 0xEF53` plus a sane `s_blocks_count`.

## 5. Do not size the image from the header

`total_blocks` on line 2 has been wrong by more than 3x on this payload. Size
the output from the **maximum `end` value across ALL commands** (`new`,
`zero`, and `erase` alike — erase runs to the partition tail).

The ext4 superblock's `s_blocks_count` is then the authority for the
*filesystem* size; the partition may legitimately be slightly larger, which
is why the two numbers differ and why that difference is not an error.

## 6. Answer "is the file even in here" with a byte scan, not a parser

**Before writing any filesystem walker, scan the raw image for the literal
filenames.** ext4 `dir_entry` stores names in plaintext, so one pass answers
the decisive question — `mba.mbn`, `modem.mdt`, `modem.b`, `wlanmdsp`,
`bdwlan` — in seconds and needs no parser at all. An empty result closes the
whole line of investigation, which is exactly what happened: the vendor image
carried none of the modem firmware.

This ordering matters because the ext4 walker is where the time goes. Group
descriptor parsing has real traps (32- vs 64-byte descriptors,
`bg_inode_table_hi` at `+40` as u32 when present, `s_inode_size` at
superblock `+88`), and every one of them produces a confident wrong answer.
Run the filename scan first; only build the walker if the scan says the files
are present.

**A hit on a filename is not the file.** `/dev/block/.../by-name/msadp` in a
SELinux `file_contexts` and `bdwlan.%03x` inside the cnss-daemon binary are
both string matches with no firmware behind them. Print the surrounding
bytes and classify each hit before treating it as evidence.

## 7. Learn the partition layout from the image itself

Scan the vendor image for `by-name/<name>` — the SELinux `file_contexts`
enumerates every partition. That is how you discover which partition holds
what without a device or a partition table:

```
/dev/block/bootdevice/by-name/modem   /vendor/firmware_mnt   vfat   ro,...
```

**On sdm660/wayne the modem firmware is NOT in `vendor.img`.** It lives in
the **`modem` partition**, a VFAT filesystem mounted at
`/vendor/firmware_mnt` — `mba.mbn`, `modem.mdt`, `modem.bNN` and `msadp` are
all in there. `vendor.img` carries the cnss-daemon binary and the SELinux
contexts but no modem firmware. `dsp` and `bluetooth` are separate partitions
for their own firmware. Ask for the `modem` partition image by name; do not
ask for "the vendor image again".

## 8. Reporting discipline

- State which format the upload actually is before extracting. "You gave me
  an OTA payload, not a sparse image" is a useful sentence; silently picking
  the wrong pipeline is not.
- Say plainly when the firmware is absent from what was supplied, and name
  the partition that has it. "Not in this image, it is in the `modem`
  partition" is the finding; "extraction failed" is not.
- Grade the parse as proven only once both §4 gates pass. A raw image that
  merely has the right size is not a verified image.
