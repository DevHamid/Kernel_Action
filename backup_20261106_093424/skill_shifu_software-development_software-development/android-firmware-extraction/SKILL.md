---
name: android-firmware-extraction
description: Use when extracting firmware from Android partition images.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [android, firmware, ota, sparse-image, ext4, extraction]
---

# Android Firmware Extraction

Rebuild a raw partition image from an AOSP OTA payload, then locate and extract
firmware files without root, loop mounts, `simg2img`, `unzip`, or `file`.

## When to Use

Use this when files must come out of an Android image and the host cannot mount
anything: OTA payloads (`.new.dat.br` + `.transfer.list`), sparse `.img` dumps,
raw partition images, or vendor/firmware partitions pushed up for inspection.
The usual trigger is "the firmware is missing from the device — find it in the
Android image," on a host with no root and no Android platform tools.

## Always-on rules

- **Prove the image before parsing it.** Validate the ext4 superblock — magic
  `0xEF53` at file offset 1080, then read `s_blocks_count` (sb+4) ×
  `1024 << s_log_block_size` (sb+24). A valid superblock at offset 1024 confirms
  the block-addressing interpretation is correct before any directory walk.
- **Never trust the transfer-list header's block count as the image bound.**
  Derive the bound from the maximum end value across all commands, then
  cross-check against the superblock. The header can disagree with the ranges.
- **Install decompressors with pip, not the system package manager**, when the
  host has no root: `python3 -m pip install brotli`. For sparse `.img` inputs
  use the bundled pure-Python converter instead of the absent `simg2img`.
- **Answer "is this file even in this image?" with a byte scan before writing a
  filesystem parser — but only for a filesystem that stores names in plaintext.**
  ext4 `dir_entry` records store filenames in plaintext, so one pass over the raw
  image settles it in minutes. **FAT does not:** directory entries are 8.3
  uppercase, space-padded (`MBA     MBN`, `MODEM    MDT`), so a scan for
  `mba.mbn` or `modem.mdt` returns zero hits on an image that contains them, and
  the zero count reads as "wrong partition" rather than "wrong search string".
  Scan for the 8.3 form, or just parse the filesystem — `scripts/fat16_extract.py`
  does it in one call.
- **Identify the filesystem from the boot sector BEFORE choosing a parser.**
  `MSDOS5.0` at offset 3 plus a valid BPB means FAT; magic `0xEF53` at offset
  1080 means ext4. A Qualcomm `firmware-update.zip` member named `NON-HLOS.bin`
  is a VFAT image of the whole firmware partition — the same payload the `modem`
  partition carries — not a sparse image and not a raw eMMC dump.
- **A VFAT firmware image holds the whole subsystem set, not just the target
  subsystem.** `NON-HLOS.bin` carries ADSP/CDSP/WLAN/VENUS/QMI trustlets
  alongside the modem files, so a ~107 MB image can contain a ~57 MB modem
  payload. Sum the target subsystem's own files (`MBA.MBN` + `MODEM.MDT` +
  `MODEM.b*`) instead of quoting the image size, and name the other subsystems
  when reporting so the size is not read as the answer.
- **`msadp` does not exist on sdm660.** It is the one optional file in the Q6
  firmware contract and it is absent from this platform's firmware entirely. Do
  not treat its absence as a failed extraction, and do not report it as a gap.
- **Never pre-allocate with `truncate()` and then seek past the end** — it
  silently extends the file, so the size looks plausible while the content is
  wrong. Size the output from the computed bound.

## Procedure

### 1. Identify the payload
`<name>.new.dat.br` + `<name>.transfer.list` + `<name>.patch.dat` is an AOSP OTA
payload. A **zero-byte `patch.dat` means a FULL image** — no patch application
needed, everything is in `new.dat`.

Work in a writable directory; upload targets are frequently root-owned and
read-only for the agent user.

### 2. Decompress
```bash
python3 -m pip install brotli   # only if the module is absent
python3 - <<'EOF'
import brotli
d = brotli.Decompressor()
with open('x.new.dat.br','rb') as f, open('x.new.dat','wb') as o:
    while True:
        c = f.read(1<<20)
        if not c: break
        o.write(d.process(c))
EOF
```

### 3. Parse the transfer list
Line 1 = version, line 2 = block count, line 3 = stash count, then commands:
```
new   <nvals>,<start1>,<end1>,<start2>,<end2>,...
zero  <nvals>,<start1>,<end1>,...
erase <nvals>,<start1>,<end1>,...
```
- `nvals` is always **even**; the values are `(start, end-EXCLUSIVE)` pairs.
- For `new`, payload is read **sequentially** from `<name>.new.dat` in the
  order the ranges appear, and written to the listed **destination** ranges.
- `zero`/`erase` write zeros to their destination ranges.

### 4. Verify the interpretation BEFORE building
Two independent checks; both must pass:
1. Sum of all `new` range sizes == `size(new.dat) / block_size`.
2. Locate the ext4 superblock in the decompressed stream, walk the `new`
   commands accumulating the sequential cursor, and confirm the destination it
   maps to is **block 0**.

If either fails, the pairing or the source/destination roles are wrong — fix
the parser, do not build the image.

### 5. Rebuild the raw image
Size the output to `max_end_value × block_size`, apply every command, then
validate the superblock at offset 1024. See `scripts/rebuild_ota_image.py`.

### 6. Locate the target files
Byte-scan the raw image for the target filenames. Report hits and, for each,
dump the surrounding printable runs to classify it — a hit inside a SELinux
`file_contexts` string (`/dev/block/.../by-name/<part>`) is a *partition
reference*, not a file.

### 7. When a file is absent, find the right partition
Extract the device's partition list from the vendor image (SELinux contexts
contain `by-name/<partition>` for every partition), and read the `fstab` entries
for mount point and filesystem type. **Qualcomm devices commonly keep modem
firmware in a separate VFAT `modem` partition mounted at `/vendor/firmware_mnt`,
not in `vendor`** — confirm with the device's own fstab before requesting
another upload.

### 8. Parsing a VFAT (FAT12/16) image
Fastboot packages and firmware-update zips deliver the firmware partition as a
VFAT image. Walk it directly — no mount, no root, no `mtools`:

```bash
python3 scripts/fat16_extract.py NON-HLOS.bin outdir/
```

The script reads the BPB, classifies FAT12 vs FAT16 by cluster count, walks the
FAT chain for every file, reconstructs LFN long names, and prints a manifest of
path / size / sha256-prefix. FAT32 is detected and refused (its root directory
is a cluster chain, not the fixed region this handles).

BPB offsets, for a hand-rolled check: bytes/sector 11, sectors/cluster 13,
reserved sectors 14, FAT count 16, root entries 17, sectors/FAT 22, total
sectors 19 (16-bit) or 32 (32-bit). Root directory starts at
`(rsvd + nfat*spf) * bps` and is `rootent*32` bytes; data starts at
`root_start + ceil(rootent*32/bps)`. Cluster N's data is at
`(data_start + (N-2)*spc) * bps`, and the chain end is `>= 0xFFF8`.

**Report the target subsystem's own byte total, not the image size** — see the
pitfalls. On sdm660 the modem set is `MBA.MBN`, `MODEM.MDT`, `MODEM.b00…b28`
(with gaps in the numbering — the `.MDT` segment table defines what loads, not
contiguity), `MODEMR.JSN`, `MODEMUW.JSN`, and the `MODEM_PR/MCFG/CONFIGS/`
region tree (`MCFG_HW/GENERIC`, `MCFG_SW/GENERIC/{AF,APAC,CHINA,EU,KOREA,LATAM,
MEA,RUSSIA,SA,SEA,COMMON}`).

## Pitfalls

- **Do not read `new <a>,<b>,<c>` as `dest,src_start,src_end`.** The first
  number is a value count; the remaining values pair into ranges.
- **Do not read the values as individual block numbers.** They pair into
  ranges; the even-arity invariant and the sum check expose the misread.
- **Do not assume the header's `total_blocks` bounds the image.** Compute the
  bound from the ranges and confirm with the superblock.
- **Do not build an ext4 directory walker on an unverified image.** Group
  descriptor offsets (`bg_inode_table_hi`) are easy to get wrong and produce
  plausible-looking garbage; validate against the superblock first, and prefer
  the filename scan when it answers the question.
- **Do not treat a zero hit count as "the tool is broken."** It is the answer:
  the file is in another partition. Go to step 7. **But first re-run the scan in
  the filesystem's own name encoding** — a FAT zero-count for `modem.mdt` is a
  wrong search string, not a wrong partition, because FAT stores `MODEM    MDT`.
- **Do not assume a gap in `MODEM.bNN` numbering is a failed extraction.**
  Segments are defined by the `.MDT` header's segment table; `B15`/`B19` are
  routinely absent on a given build and load nothing. Verify the segment list
  from the `.MDT` before reporting missing files.
- **Do not report a whole-partition byte total as the subsystem's size.** The
  image carries every subsystem's firmware; sum only the files the target
  subsystem loads.
- **Do not look for `msadp` on sdm660.** It is absent from the platform's
  firmware entirely, and its absence is not a symptom of anything.
