#!/usr/bin/env python3
"""AOSP OTA payload -> raw partition image (pure stdlib, no root, no AOSP tools).

Handles the `*.new.dat.br` + `*.patch.dat` + `*.transfer.list` shape, which is
NOT an Android sparse image -- use scripts/simg2img.py for that.

Usage:
    python3 ota_transfer_list_to_raw.py <dir> <name>

Reads   <dir>/<name>.new.dat.br   <dir>/<name>.patch.dat   <dir>/<name>.transfer.list
Writes  <dir>/<name>.new.dat      <dir>/<name>.raw

Requires `pip install brotli` for the .br decompression step.

Two self-checks run before the image is declared good:
  (a) sum of every 'new' range size must equal len(new.dat)/blk_sz exactly;
  (b) an ext4 superblock located in the stream must map to destination block 0.
Both must pass -- a parse that only looks plausible produces a wrong image
with the right size.
"""
import os
import struct
import sys

BLK = 4096
EXT4_MAGIC = 0xEF53


def decompress(src, dst):
    try:
        import brotli
    except ImportError:
        sys.exit("brotli module missing -- run: python3 -m pip install brotli")
    total_in = total_out = 0
    with open(src, "rb") as f, open(dst, "wb") as o:
        d = brotli.Decompressor()
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            total_in += len(chunk)
            out = d.process(chunk)
            o.write(out)
            total_out += len(out)
    print("decompressed %d -> %d bytes" % (total_in, total_out))
    return total_out


def parse_transfer(path):
    """Return (header_lines, [(verb, [values...]), ...]).

    Grammar: '<verb> <nvals>,<v1>,...,<vN>' where nvals is EVEN and counts the
    values that follow; values pair as (start, end-exclusive).
    """
    lines = open(path).read().splitlines()
    cmds = []
    for ln in lines[3:]:
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(" ", 1)
        verb = parts[0]
        if verb not in ("new", "zero", "erase"):
            continue
        vals = [int(x) for x in parts[1].split(",")]
        if len(vals) % 2 != 0:
            sys.exit("ODD ARITY, refusing to guess: %s" % ln[:120])
        for i in range(1, len(vals), 2):
            if vals[i + 1] <= vals[i]:
                sys.exit("non-increasing range in: %s" % ln[:120])
        cmds.append((verb, vals))
    return lines, cmds


def ranges(vals):
    return [(vals[i], vals[i + 1]) for i in range(0, len(vals), 2)]


def check_range_sum(cmds, dat_blocks):
    total = sum(e - s for verb, vals in cmds if verb == "new" for s, e in ranges(vals))
    if total != dat_blocks:
        sys.exit("GATE (a) FAILED: new ranges sum to %d blocks, new.dat has %d"
                 % (total, dat_blocks))
    print("gate (a) OK: new ranges sum to %d blocks == new.dat" % total)


def check_superblock_lands_at_zero(cmds, dat_path):
    """Locate an ext4 superblock in the stream and prove it maps to block 0."""
    data = open(dat_path, "rb")
    cursor = 0
    sbs = list(_find_superblocks(data))
    for verb, vals in cmds:
        if verb != "new":
            continue
        rs = ranges(vals)
        total = sum(e - s for s, e in rs)
        for sb_src in sbs:
            if cursor <= sb_src < cursor + total:
                off = sb_src - cursor
                acc = 0
                dest = None
                for s, e in rs:
                    nb = e - s
                    if acc <= off < acc + nb:
                        dest = s + (off - acc)
                        break
                    acc += nb
                if dest != 0:
                    sys.exit("GATE (b) FAILED: superblock maps to block %s, expected 0"
                              % dest)
                print("gate (b) OK: ext4 superblock at source block %d -> destination block 0"
                      % sb_src)
                data.close()
                return
        cursor += total
    data.close()
    print("gate (b) SKIPPED: no ext4 superblock found in stream "
          "(not an ext4 payload, or firmware-only)")


def _find_superblocks(f):
    """Yield source block indices holding a block-aligned ext4 superblock."""
    sz = os.path.getsize(f.name)
    f.seek(0)
    pos = 0
    while pos < sz:
        buf = f.read(min(1 << 24, sz - pos))
        if not buf:
            break
        i = 0
        while True:
            j = buf.find(b"\x53\xef", i)
            if j < 0:
                break
            blk = pos + j - 1080
            if blk >= 0 and blk % BLK == 0 and j + 1080 + 64 <= len(buf):
                inodes, blocks = struct.unpack("<II", buf[j + 1080:j + 1116])
                lbs = struct.unpack("<I", buf[j + 1080 + 24:j + 1080 + 28])[0]
                if 0 < lbs <= 6 and blocks > 0 and inodes > 0:
                    yield blk
            i = j + 1
        pos += len(buf)
    f.seek(0)


def build(cmds, dat_path, out_path):
    """Sequential read from new.dat, scattered writes to destination ranges."""
    max_end = max(vals[i + 1] for _, vals in cmds for i in range(1, len(vals), 2))
    # NOTE: do not size from the header's block count -- it is not reliable.
    size = max_end * BLK
    print("image size from max range end: %d blocks = %.3f GiB" % (max_end, size / 2 ** 30))
    data = open(dat_path, "rb")
    out = open(out_path, "wb")
    out.truncate(size)
    src_off = 0
    n = {"new": 0, "zero": 0, "erase": 0}
    for verb, vals in cmds:
        rs = ranges(vals)
        if verb == "new":
            total = sum(e - s for s, e in rs)
            buf = data.read(total * BLK)
            if len(buf) != total * BLK:
                sys.exit("short read: wanted %d got %d" % (total * BLK, len(buf)))
            p = 0
            for s, e in rs:
                nb = e - s
                out.seek(s * BLK)
                out.write(buf[p * BLK:(p + nb) * BLK])
                p += nb
            src_off += total * BLK
        else:
            for s, e in rs:
                out.seek(s * BLK)
                out.write(b"\x00" * ((e - s) * BLK))
        n[verb] += 1
    out.close()
    data.close()
    print("applied new=%d zero=%d erase=%d; consumed %d/%d bytes of new.dat"
          % (n["new"], n["zero"], n["erase"], src_off, os.path.getsize(dat_path)))
    print("wrote %s (%d bytes)" % (out_path, os.path.getsize(out_path)))


def verify_ext4(path):
    with open(path, "rb") as f:
        f.seek(1024)
        sb = f.read(64)
    magic = struct.unpack("<H", sb[56:58])[0]
    if magic != EXT4_MAGIC:
        print("ext4 superblock: INVALID (magic=0x%04X) -- not an ext4 image" % magic)
        return
    inodes, blocks = struct.unpack("<II", sb[0:8])
    lbs = struct.unpack("<I", sb[24:28])[0]
    print("ext4 superblock: VALID  inodes=%d blocks=%d bs=%d fs=%.2f GiB"
          % (inodes, blocks, 1024 << lbs, blocks * (1024 << lbs) / 2 ** 30))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit("usage: ota_transfer_list_to_raw.py <dir> <name>")
    d, name = args
    br = os.path.join(d, name + ".new.dat.br")
    dat = os.path.join(d, name + ".new.dat")
    tl = os.path.join(d, name + ".transfer.list")
    raw = os.path.join(d, name + ".raw")

    if os.path.getsize(os.path.join(d, name + ".patch.dat")) == 0:
        print("patch.dat is empty -> FULL image, no patch to apply")
    else:
        print("WARNING: patch.dat is non-empty -> incremental OTA, NOT handled")

    decompress(br, dat)
    _, cmds = parse_transfer(tl)
    dat_blocks = os.path.getsize(dat) // BLK
    check_range_sum(cmds, dat_blocks)
    check_superblock_lands_at_zero(cmds, dat)
    build(cmds, dat, raw)
    verify_ext4(raw)
    print("DONE")


if __name__ == "__main__":
    main()
