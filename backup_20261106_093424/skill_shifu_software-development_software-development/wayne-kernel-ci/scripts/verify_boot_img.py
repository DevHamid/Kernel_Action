#!/usr/bin/env python3
"""Verify a kbuilds boot.img really carries the kernel from the build you think it does.

`ANDROID!` at offset 0 only proves the file is a boot image. This proves the
kernel payload inside it is byte-identical to the Image.gz-dtb the run produced,
which is the check that separates "a boot image" from "THIS build's boot image".

Usage:
    verify_boot_img.py <boot.img> [Image.gz-dtb]

Exit 0 = verified (or verified-as-far-as-possible without the image), 1 = failed.
Stdlib only.
"""
import argparse
import hashlib
import struct
import sys

BOOT_MAGIC = b"ANDROID!"
GZIP_MAGIC = b"\x1f\x8b"


def parse_header(d):
    """Android boot image header v0/v1. Returns None if not a boot image."""
    if len(d) < 48:
        return None
    magic, kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, \
        second_size, second_addr, tags_addr, page_size, header_version, \
        recovery_dtbo_size = struct.unpack("<8s10I", d[:48])
    if magic != BOOT_MAGIC:
        return None
    return {
        "kernel_size": kernel_size,
        "kernel_addr": kernel_addr,
        "ramdisk_size": ramdisk_size,
        "ramdisk_addr": ramdisk_addr,
        "second_size": second_size,
        "tags_addr": tags_addr,
        "page_size": page_size,
        "header_version": header_version,
        "recovery_dtbo_size": recovery_dtbo_size,
    }


def locate_kernel(d, kernel_size, image=None):
    """Find the kernel payload offset.

    Do NOT trust the header's page_size to find the payload -- it can carry a
    bogus value (256) while the real flash page size is 4096. Prefer an exact
    match against the known Image.gz-dtb, then fall back to gzip magic at
    4096-aligned offsets.
    """
    if image is not None:
        needle = image[:64]
        off = d.find(needle)
        if off >= 0:
            return off, "matched Image.gz-dtb prefix"
    for off in range(0, min(len(d), 1 << 20), 4096):
        if d[off:off + 2] == GZIP_MAGIC:
            return off, "gzip magic at 4096-aligned offset"
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("boot_img")
    ap.add_argument("image", nargs="?", help="optional standalone Image.gz-dtb")
    args = ap.parse_args()

    d = open(args.boot_img, "rb").read()
    print("boot.img size: %d bytes" % len(d))

    h = parse_header(d)
    if h is None:
        print("FAIL: no ANDROID! magic -- not a flashable boot image")
        return 1
    print("ANDROID! magic OK -> flashable")
    for k in ("kernel_size", "ramdisk_size", "page_size", "header_version"):
        print("  %-16s %d" % (k + ":", h[k]))
    if h["page_size"] not in (2048, 4096):
        print("  NOTE: page_size=%d is not a real flash page size; ignoring it"
              % h["page_size"])

    image = None
    if args.image:
        image = open(args.image, "rb").read()
        print("Image.gz-dtb size: %d bytes" % len(image))
        if len(image) != h["kernel_size"]:
            print("WARN: kernel_size (%d) != Image.gz-dtb size (%d)"
                  % (h["kernel_size"], len(image)))

    off, how = locate_kernel(d, h["kernel_size"], image)
    if off is None:
        print("FAIL: could not locate the kernel payload")
        return 1
    print("kernel payload at offset %d (%s)" % (off, how))

    payload = d[off:off + h["kernel_size"]]
    if len(payload) != h["kernel_size"]:
        print("FAIL: truncated payload (%d of %d bytes)"
              % (len(payload), h["kernel_size"]))
        return 1

    sha = hashlib.sha256(payload).hexdigest()
    print("payload sha256: %s" % sha)

    if image is not None:
        isha = hashlib.sha256(image).hexdigest()
        print("image   sha256: %s" % isha)
        if sha == isha:
            print("VERIFIED: boot.img contains exactly the Image.gz-dtb from this build")
            return 0
        print("FAIL: payload differs from Image.gz-dtb -- this is a different build")
        return 1

    print("OK: payload extracted cleanly (no Image.gz-dtb given, so not "
          "cross-checked against a specific build)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
