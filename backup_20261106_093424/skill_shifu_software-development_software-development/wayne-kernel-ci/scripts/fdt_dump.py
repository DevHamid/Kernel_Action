#!/usr/bin/env python3
"""Dump a device tree from a wayne `Image.gz-dtb` artifact.

Usage:
    fdt_dump.py <Image.gz-dtb> [node-substring ...]

The dtb is appended AFTER the gzip stream in `Image.gz-dtb`, so plain
`gzip.decompress()` on the whole file raises BadGzipFile even though the
gzip header is valid. This scans for the FDT magic after the stream instead.

With no node filter it prints every /reserved-memory child with its reg range,
which is the overlap check the ramoops fix needs.
"""
import struct
import sys


def cstr(b, o):
    return b[o:b.index(b"\0", o)].decode("utf-8", "replace")


def parse(b):
    """Return {node_path: [(prop_name, value_bytes)]} for a whole FDT blob."""
    magic, totalsize = struct.unpack(">II", b[:8])
    assert magic == 0xD00DFEED, "not an FDT (magic %#x)" % magic
    off_struct, off_str = struct.unpack(">II", b[8:16])
    props = {}

    def rec(o, path):
        while True:
            tok = struct.unpack(">I", b[o:o + 4])[0]
            if tok == 1:  # BEGIN_NODE
                o += 4
                name = cstr(b, o)
                o += len(name) + 1
                o = (o + 3) & ~3
                o = rec(o, path + "/" + name if name else path)
            elif tok == 2:  # END_NODE
                return o + 4
            elif tok == 3:  # PROP
                o += 4
                ln, nameoff = struct.unpack(">II", b[o:o + 8])
                o += 8
                val = b[o:o + ln]
                o += ln
                o = (o + 3) & ~3
                props.setdefault(path, []).append((cstr(b, off_str + nameoff), val))
            elif tok == 4:  # NOP
                o += 4
            elif tok == 9:  # END
                return o
            else:
                raise ValueError("bad token %d at %d" % (tok, o))

    rec(off_struct, "")
    return props


def extract_dtb(blob):
    """Find the appended dtb inside an Image.gz-dtb."""
    offs = [i for i in range(0, min(len(blob), 1 << 24), 1)
            if blob[i:i + 4] == b"\xd0\x0d\xfe\xed"]
    # magic bytes can also appear inside compressed data; walk backwards for
    # the last one whose declared totalsize fits inside the file.
    for o in reversed(offs):
        if o % 4:
            continue
        ts = struct.unpack(">I", blob[o + 4:o + 8])[0]
        if 0x10000 < ts < 0x200000 and o + ts <= len(blob):
            return blob[o:o + ts]
    raise SystemExit("no valid FDT found after the gzip stream")


def fmt_reg(val):
    if len(val) == 16:
        a, l = struct.unpack(">QQ", val)
    elif len(val) == 8:
        a, l = struct.unpack(">II", val)
    else:
        return "reg(len=%d)" % len(val)
    return "0x%X-0x%X" % (a, a + l)


def main():
    path = sys.argv[1]
    filters = sys.argv[2:]
    blob = open(path, "rb").read()

    if blob[:2] == b"\x1f\x8b":
        dtb = extract_dtb(blob)
    elif blob[:4] == b"\xd0\x0d\xfe\xed":
        dtb = blob  # already a raw dtb
    else:
        raise SystemExit("unrecognised file (head %s)" % blob[:4].hex(" "))

    props = parse(dtb)
    print("FDT parsed: %d nodes, dtb %d B" % (len(props), len(dtb)))

    for p in sorted(props):
        if filters and not any(f in p for f in filters):
            continue
        print("\n%s" % p)
        for name, val in props[p]:
            if name == "reg":
                print("    %-14s %s" % ("reg", fmt_reg(val)))
            elif name == "compatible":
                print("    %-14s %s" % ("compatible", cstr(val, 0)))
            elif name in ("console-size", "pmsg-size", "record-size",
                          "ftrace-size", "max-reason", "dump-oops"):
                print("    %-14s 0x%X" % (name, struct.unpack(">I", val[:4])[0]))
            elif val == b"":
                print("    %-14s (present)" % name)
            else:
                print("    %-14s %s" % (name, val.hex()))


if __name__ == "__main__":
    main()
