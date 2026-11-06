# Boot-image forensics procedure

## Header layout
struct '<8s10I16s512s32s1024s'. page_size at index 8, kernel_size at index 1, ramdisk_size at index 3. Kernel payload starts at page_size (4096). Ramdisk starts at page-aligned offset after kernel. Header field byte offsets: kernel_size at 8, ramdisk_size at 16, id (32 bytes) at 576, name at 48, cmdline at 64.

## Component extraction
- kernel: bytes[page_size : page_size + kernel_size]
- ramdisk: bytes[ramdisk_offset : ramdisk_offset + ramdisk_size], ramdisk_offset = page_size + align(kernel_size, page_size)
- appended DTB: bytes after the ramdisk region (if any present)

## Header id field: two packer families, identify before rewriting
Never assume the id field is sha1. Two formulas appear on this tree; compute BOTH and compare against the stored bytes before packing anything:

- **sha1 family** — `sha1(kernel || <I kernel_size || ramdisk || <I ramdisk_size || second || <I second_size || header[0:1632] with id zeroed)`, stored as 20 bytes followed by 12 zero bytes.
- **sha256 family** — `sha256(kernel || ramdisk)` over the bare byte concatenation, no sizes and no header mixed in; stored as a full 32 non-zero bytes.

Discriminator: read bytes 576:608. If bytes 596:608 are all zero the image came from the sha1 packer; if all 32 bytes are non-zero try the sha256 formula first. Verify by exact match on the stored field — a mismatch means the image was produced by a third tool, not that your slice offsets are wrong.

```python
import struct, hashlib
def header_id(data):
    ks, ka, rs, ra, ss, sa, ta, ps = struct.unpack('<8I', data[8:40])
    k_off = ps
    r_off = ((ks + ps - 1) // ps) * ps + ps
    s_off = r_off + ((rs + ps - 1) // ps) * ps
    kernel, ramdisk = data[k_off:k_off+ks], data[r_off:r_off+rs]
    second = data[s_off:s_off+ss] if ss else b''
    hdr = bytearray(data[:1632]); hdr[576:608] = b'\x00' * 32
    h = hashlib.sha1()
    h.update(kernel); h.update(struct.pack('<I', ks))
    h.update(ramdisk); h.update(struct.pack('<I', rs))
    h.update(second); h.update(struct.pack('<I', ss))
    h.update(bytes(hdr))
    return h.hexdigest(), hashlib.sha256(kernel + ramdisk).hexdigest()
```

## Ramdisk cpio: entry-level diff, not size diff
A ramdisk size delta alone proves nothing — a Magisk injection and a legitimate ramdisk edit both change the size. Walk both cpios and diff by entry, printing `name | mode | size | sha1(data) | SAME/DIFF/ONLY-S/ONLY-D`. Modes are hex in the newc header (`070701` magic, inode 6:14, mode 14:22, filesize 54:62, namesize 94:102) — compare them case-insensitively, since one packer writes upper-case hex and another lower-case, which makes every entry look DIFF on a string compare while the data is identical.

```python
def walk(b):
    off, out = 0, []
    while off < len(b) and b[off:off+6] == b'070701':
        hdr = b[off:off+110]
        namesize, filesize = int(hdr[94:102], 16), int(hdr[54:62], 16)
        name = b[off+110:off+110+namesize-1].decode()
        doff = off + 110 + namesize; doff += (4 - (doff % 4)) % 4
        out.append((name, hdr[14:22].decode(), filesize,
                    hashlib.sha1(b[doff:doff+filesize]).hexdigest()))
        off = doff + filesize; off += (4 - (off % 4)) % 4
        if name == 'TRAILER!!!': break
    return out
```

## Proving a ramdisk is Magisk-injected (positive proof)
Entry presence is circumstantial; the decisive test is that `.backup/init.xz` decompresses to a binary byte-identical to the clean image's `init`. `lzma.decompress(entry_data)` then sha1 both. Equal sha1 = the original init was preserved and replaced by a patched stub, i.e. Magisk is present and the pstore shadowing applies. A clean ramdisk's `init` is the original (~3 MB) with no `.backup/` and no `overlay.d/sbin/` at all.

## Assembling a boot image from parts (donor header + foreign kernel/ramdisk)
When building a new boot.img by splicing a donor header with a kernel from one source and a ramdisk from another:
1. Copy the donor header bytes verbatim (magic, addresses, cmdline, tags, name).
2. Patch only kernel_size (offset 8), ramdisk_size (offset 16), and the id field (offset 576) — recompute the id with the formula the donor image actually used (see the header-id section above; sha256(kernel || ramdisk) is the common one on this tree).
3. **Pad the patched header to page_size before the kernel slice.** The kernel must start at offset page_size (4096); a header shorter than page_size leaves a gap that shifts both kernel and ramdisk offsets and breaks the roundtrip. Verify by re-parsing the output image: kernel slice must equal the source kernel and the parsed ramdisk_size must equal the intended ramdisk size.
4. Pad the kernel to page boundary, then the ramdisk to page boundary.

## Magisk detection in a ramdisk
Do not trust an image's label or filename about whether it is stripped of Magisk — inspect the ramdisk cpio entries directly. Magisk machinery appears as: `.backup/` (with `init.xz`, `.magisk`, `.rmlist`) and `overlay.d/sbin/magisk32.xz` / `magisk64.xz` / `stub.xz`. A clean ramdisk has neither; its `init` is the original binary (often larger, ~3MB vs ~687KB for the Magisk-patched stub).

## Bootability discriminators (no unpack tools needed)
- gzip kernel: first two bytes 1f 8b — correct for QC trees with appended DTB
- zlib payload: first byte 78 — wrong, bootloops
- DTB present: FDT magic \xd0\x0d\xfe\xed inside the kernel slice after gzip data
- raw Image: ARMd at offset 56, zero FDT magics — only safe when DTB comes from a dtbo partition

## Component comparison between two images
1. Compare ramdisk bytes directly — byte-identical or not.
2. Decompress both kernel payloads with zlib (wbits=31) and compare decompressed bytes.
3. Check DTB offset/size in each; compare property-level values (ramoops reg, console-size, pmsg-size) — node presence alone is not evidence of equality.
4. Assert header fields (page_size, kernel_addr, ramdisk_addr, tags_addr, cmdline, ramdisk SHA-1) are byte-identical before shipping.

## Control image != production base
A control image (stock kernel + your DTB, or your kernel + stock DTB) is a bisection tool, not a daily driver. It carries a donor ramdisk and a donor kernel version that are not yours. Flashing it as a base inherits the wrong ramdisk and wrong kernel version. Use it only to isolate bootloop cause, then replace with your own kernel + your own DTB + your own ramdisk. A legitimate "fast + clean" base combines the stock kernel with a de-Magisked ramdisk, not the Magisk-carrying control.

## Neutral packer proof
Before trusting any custom boot image, rebuild the stock image from scratch through your packer (stock kernel + stock DTB + stock header) and assert byte-identical to the real stock boot.img with matching SHA-256. If the packer changes any byte it shouldn't, fix the packer before bisecting the kernel.
