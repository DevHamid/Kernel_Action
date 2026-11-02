#!/usr/bin/env python3
"""Rebuild a clean (Magisk-free) boot image from a Magisk-patched one.

Usage:
    python3 build_clean_boot.py <patched.img> <reference_clean.img> <out.img>

Why: Magisk-patched ramdisks carry .backup/init.xz + overlay.d/sbin/magisk*.xz and
replace `init` with a patched stub. Android boot header v0 stores a content id at
byte 576. On this device (tuna/wayne) the id is sha256(kernel || ramdisk) - NOT the
AOSP mkbootimg sha1(kernel+size+ramdisk+size+second+size+header). A stale/foreign id
makes the bootloader reject or mis-handle the image.

Steps:
  1. Parse both images (header v0, page size from header).
  2. Rebuild ramdisk as newc cpio: take the clean reference's entry headers verbatim
     (preserves ino/mode/uid/gid/mtime), substitute `init` with the decompressed
     .backup/init.xz from the patched image, drop .backup/ and overlay.d/.
  3. Reassemble: header + kernel + ramdisk, each page-padded.
  4. id = sha256(kernel || ramdisk); write at offset 576.
"""
import hashlib
import lzma
import struct
import sys


def parse(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:8] != b"ANDROID!":
        raise SystemExit(f"{path}: not an ANDROID! boot image")
    (ks, ka, rs, ra, ss, sa, ta, ps) = struct.unpack("<8I", raw[8:40])
    k_off = ps
    r_off = ((ks + ps - 1) // ps) * ps + ps
    s_off = r_off + ((rs + ps - 1) // ps) * ps
    return {
        "raw": raw,
        "header": raw[:1632],
        "kernel_size": ks,
        "kernel": raw[k_off:k_off + ks],
        "ramdisk_size": rs,
        "ramdisk": raw[r_off:r_off + rs],
        "second_size": ss,
        "second": raw[s_off:s_off + ss] if ss else b"",
        "page_size": ps,
    }


def cpio_entries(blob):
    """Walk a newc cpio archive, returning (name, header110, data) tuples."""
    out = []
    off = 0
    while off + 110 <= len(blob):
        if blob[off:off + 6] != b"070701":
            break
        hdr = blob[off:off + 110]
        namesize = int(hdr[94:102], 16)
        filesize = int(hdr[54:62], 16)
        name = blob[off + 110:off + 110 + namesize - 1].decode()
        data_off = off + 110 + namesize
        data_off += (4 - (data_off % 4)) % 4
        out.append((name, hdr, blob[data_off:data_off + filesize]))
        off = data_off + filesize
        off += (4 - (off % 4)) % 4
        if name == "TRAILER!!!":
            break
    return out


def cpio_record(hdr, name, data):
    h = bytearray(hdr)
    struct.pack_into(">8s", h, 54, b"%08X" % len(data))
    struct.pack_into(">8s", h, 94, b"%08X" % (len(name) + 1))
    out = bytes(h) + name.encode() + b"\x00"
    out += b"\x00" * ((4 - (len(out) % 4)) % 4)
    out += data
    out += b"\x00" * ((4 - (len(data) % 4)) % 4)
    return out


def pad(blob, page):
    return blob + b"\x00" * ((page - (len(blob) % page)) % page)


def build(patched_path, clean_ref_path, out_path):
    patched = parse(patched_path)
    ref = parse(clean_ref_path)

    if patched["kernel"] != ref["kernel"]:
        print("WARN: kernels differ between patched and reference image")

    ref_entries = cpio_entries(ref["ramdisk"])
    ref_by_name = {e[0]: e for e in ref_entries}
    patched_entries = cpio_entries(patched["ramdisk"])

    orig_init = None
    for name, _hdr, data in patched_entries:
        if name == ".backup/init.xz":
            orig_init = lzma.decompress(data)
            break
    if orig_init is None:
        raise SystemExit("patched ramdisk has no .backup/init.xz - nothing to restore")

    rebuilt = b""
    for name, hdr, data in patched_entries:
        if name == "TRAILER!!!":
            continue
        if name.startswith(".backup") or name.startswith("overlay.d"):
            continue
        if name == "init":
            data = orig_init
        ref_hdr = ref_by_name[name][1] if name in ref_by_name else hdr
        rebuilt += cpio_record(ref_hdr, name, data)
    rebuilt += cpio_record(ref_by_name["TRAILER!!!"][1], "TRAILER!!!", b"")

    page = ref["page_size"]
    hdr = bytearray(ref["header"])
    struct.pack_into("<I", hdr, 16, len(rebuilt))
    hdr[576:608] = b"\x00" * 32

    kernel = ref["kernel"]
    image = pad(bytes(hdr), page) + pad(kernel, page) + pad(rebuilt, page)

    new_id = hashlib.sha256(kernel + rebuilt).hexdigest()
    image = bytearray(image)
    image[576:608] = bytes.fromhex(new_id)

    with open(out_path, "wb") as fh:
        fh.write(bytes(image))

    print(f"ramdisk: {len(rebuilt)} bytes (was {patched['ramdisk_size']})")
    print(f"id:      {new_id}")
    print(f"wrote:   {out_path} ({len(image)} bytes)")
    return bytes(image)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    build(sys.argv[1], sys.argv[2], sys.argv[3])
