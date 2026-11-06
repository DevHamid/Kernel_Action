#!/usr/bin/env python3
"""Rebuild a raw partition image from an AOSP OTA payload.

Usage: python3 rebuild_ota_image.py <transfer.list> <new.dat> <out.raw>

transfer.list command format (verified against real payloads):
    new   <nvals>,<start1>,<end1>,<start2>,<end2>,...
    zero  <nvals>,<start1>,<end1>,...
    erase <nvals>,<start1>,<end1>,...

  - nvals is always EVEN; the values are (start, end-EXCLUSIVE) pairs.
  - 'new' payload is read SEQUENTIALLY from new.dat in the order the ranges
    appear, and written to the listed DESTINATION ranges.
  - 'zero'/'erase' write zeros to their destination ranges.
  - The header's block count is NOT trusted as the image bound; the bound is
    derived from the maximum end value across all commands.

Run verify_transfer_list() first: it proves the interpretation before you
spend minutes writing a multi-gigabyte image.
"""
import os
import struct
import sys

BLK = 4096
EXT4_MAGIC = 0xEF53
SUPERBLOCK_OFF = 1024
MAGIC_OFF = SUPERBLOCK_OFF + 56  # s_magic within the superblock


def parse(lines):
    """Yield (cmd, [(start, end), ...]) for every command in the transfer list."""
    for ln in lines[3:]:
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(" ", 1)
        cmd = parts[0]
        if cmd not in ("new", "zero", "erase"):
            continue
        nums = [int(x) for x in parts[1].split(",")]
        vals = nums[1:]
        if len(vals) % 2 != 0:
            raise SystemExit("odd arity, aborting: " + ln[:120])
        pairs = [(vals[i], vals[i + 1]) for i in range(0, len(vals), 2)]
        if any(e <= s for s, e in pairs):
            raise SystemExit("non-increasing range, aborting: " + ln[:120])
        yield cmd, pairs


def read_superblock(path):
    """Return (block_size, blocks, inodes) from a raw image, or None."""
    try:
        with open(path, "rb") as f:
            f.seek(SUPERBLOCK_OFF)
            sb = f.read(64)
    except OSError:
        return None
    if len(sb) < 64 or struct.unpack("<H", sb[56:58])[0] != EXT4_MAGIC:
        return None
    inodes = struct.unpack("<I", sb[0:4])[0]
    blocks = struct.unpack("<I", sb[4:8])[0]
    log_bs = struct.unpack("<I", sb[24:28])[0]
    if log_bs > 6:
        return None
    return 1024 << log_bs, blocks, inodes


def verify_transfer_list(list_path, dat_path):
    """Prove the (start, end-exclusive, sequential-source) interpretation.

    Checks that the sum of all 'new' range sizes equals the size of the data
    file, and that the ext4 superblock (if present) maps to destination
    block 0. Returns True when both hold.
    """
    lines = open(list_path).read().splitlines()
    total = sum(e - s for cmd, pairs in parse(lines) if cmd == "new"
                for s, e in pairs)
    dat_blocks = os.path.getsize(dat_path) // BLK
    if total != dat_blocks:
        print("FAIL: 'new' ranges total %d blocks, data file holds %d"
              % (total, dat_blocks))
        return False
    print("OK: 'new' ranges total %d blocks == data file (%d)"
          % (total, dat_blocks))

    # Find the superblock in the data stream, then map it to a destination.
    hit = None
    with open(dat_path, "rb") as f:
        pos = 0
        while True:
            f.seek(pos)
            buf = f.read(1 << 24)
            if not buf:
                break
            base = pos
            i = 0
            while True:
                j = buf.find(b"\x53\xef", i)
                if j < 0:
                    break
                blk = base + j - MAGIC_OFF
                if blk >= 0 and blk % BLK == 0:
                    sb = blk + SUPERBLOCK_OFF
                    if sb + 64 <= base + len(buf):
                        raw = buf[sb - base:sb - base + 64]
                        ino = struct.unpack("<I", raw[0:4])[0]
                        blks = struct.unpack("<I", raw[4:8])[0]
                        lbs = struct.unpack("<I", raw[24:28])[0]
                        if lbs <= 6 and blks > 0 and ino > 0:
                            hit = (blk // BLK, blks, 1024 << lbs)
                            break
                i = j + 1
            if hit:
                break
            pos += len(buf)

    if not hit:
        print("NOTE: no ext4 superblock found in the data stream; "
              "cannot confirm destination mapping.")
        return True

    src_blk, fs_blocks, fs_bs = hit
    print("OK: ext4 superblock at data block %d, fs=%d blocks x %d"
          % (src_blk, fs_blocks, fs_bs))

    cursor = 0
    for cmd, pairs in parse(lines):
        if cmd != "new":
            continue
        total = sum(e - s for s, e in pairs)
        if cursor <= src_blk < cursor + total:
            off = src_blk - cursor
            acc = 0
            for s, e in pairs:
                nb = e - s
                if acc <= off < acc + nb:
                    dest = s + (off - acc)
                    print("OK: superblock maps to destination block %d %s"
                          % (dest, "(CONFIRMED)" if dest == 0 else "(UNEXPECTED)"))
                    return dest == 0
                acc += nb
        cursor += total
    print("FAIL: superblock block %d not covered by any 'new' command" % src_blk)
    return False


def rebuild(list_path, dat_path, out_path):
    lines = open(list_path).read().splitlines()
    max_end = 0
    cmds = list(parse(lines))
    for cmd, pairs in cmds:
        for s, e in pairs:
            max_end = max(max_end, e)
    size = max_end * BLK
    print("image bound: %d blocks = %d bytes (%.3f GiB)"
          % (max_end, size, size / 2 ** 30))

    data = open(dat_path, "rb")
    out = open(out_path, "wb")
    out.truncate(size)
    n_new = n_zero = n_erase = 0
    for cmd, pairs in cmds:
        if cmd == "new":
            total = sum(e - s for s, e in pairs)
            buf = data.read(total * BLK)
            if len(buf) != total * BLK:
                raise SystemExit("short read: wanted %d got %d"
                                 % (total * BLK, len(buf)))
            pos = 0
            for s, e in pairs:
                nb = e - s
                out.seek(s * BLK)
                out.write(buf[pos * BLK:(pos + nb) * BLK])
                pos += nb
            n_new += 1
        else:
            for s, e in pairs:
                out.seek(s * BLK)
                out.write(b"\x00" * ((e - s) * BLK))
            if cmd == "zero":
                n_zero += 1
            else:
                n_erase += 1
    out.close()
    data.close()
    print("applied new=%d zero=%d erase=%d" % (n_new, n_zero, n_erase))
    sb = read_superblock(out_path)
    if sb:
        bs, blocks, inodes = sb
        print("ext4 superblock VALID: %d blocks x %d = %.2f GiB, %d inodes"
              % (blocks, bs, blocks * bs / 2 ** 30, inodes))
    else:
        print("WARNING: no valid ext4 superblock at offset 1024")
    print("wrote %s (%d bytes)" % (out_path, os.path.getsize(out_path)))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: rebuild_ota_image.py <transfer.list> <new.dat> <out.raw>")
    lst, dat, out = sys.argv[1:4]
    if not verify_transfer_list(lst, dat):
        sys.exit("verification failed -- fix the parser before building")
    rebuild(lst, dat, out)
