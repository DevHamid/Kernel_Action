#!/usr/bin/env python3
"""Pure-Python Android sparse image -> raw image converter.

Usage: python3 sparse_to_raw.py <in.sparse> <out.raw>

Reads the sparse header magic 0xED26FF3A and walks the chunk stream:
    RAW      (0xCAC1) - literal payload
    FILL     (0xCAC2) - one 4-byte value repeated
    DONTCARE (0xCAC3) - zeros
    CRC32    (0xCAC4) - payload plus a trailing 4-byte CRC word

Chunk header is 12 bytes: u16 type, u16 reserved, u32 chunk_sz (in blocks),
u32 total_sz (bytes of the whole chunk INCLUDING the header). total_sz is the
authority for CRC32 payload length, not chunk_sz -- some encoders pad the
chunk, and trusting chunk_sz overruns or truncates.
"""
import struct
import sys

SPARSE_MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONTCARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4


def convert(src, dst):
    with open(src, "rb") as f, open(dst, "wb") as o:
        hdr = f.read(28)
        if len(hdr) < 28:
            sys.exit("file too small")
        magic, major, minor, fhdr_sz, chdr_sz, blk_sz, total_blks, \
            total_chunks, crc = struct.unpack("<IHHHHIIII", hdr)
        if magic != SPARSE_MAGIC:
            sys.exit("not a sparse image (magic=0x%08X)" % magic)
        if major != 1:
            sys.exit("unsupported sparse major version %d" % major)
        if chdr_sz != 12:
            sys.exit("unexpected chunk header size %d" % chdr_sz)
        print("sparse: blk_sz=%d total_blks=%d chunks=%d image=%.1f MiB"
              % (blk_sz, total_blks, total_chunks,
                 total_blks * blk_sz / 1048576.0))
        for i in range(total_chunks):
            ch = f.read(12)
            if len(ch) < 12:
                sys.exit("truncated chunk header at %d" % i)
            ctype, _rsvd, nblks, total_sz = struct.unpack("<HHII", ch)
            if ctype == CHUNK_RAW:
                want = nblks * blk_sz
                payload = f.read(want)
                if len(payload) != want:
                    sys.exit("truncated RAW payload at chunk %d" % i)
                o.write(payload)
            elif ctype == CHUNK_FILL:
                fill = f.read(4)
                if len(fill) != 4:
                    sys.exit("truncated FILL value at chunk %d" % i)
                o.write(fill * (nblks * blk_sz // 4))
            elif ctype == CHUNK_DONTCARE:
                o.write(b"\x00" * (nblks * blk_sz))
            elif ctype == CHUNK_CRC32:
                # total_sz covers header + payload + trailing CRC word.
                payload_len = total_sz - 12 - 4
                payload = f.read(payload_len)
                if len(payload) != payload_len:
                    sys.exit("truncated CRC32 payload at chunk %d" % i)
                o.write(payload)
                f.read(4)  # the CRC itself, not part of the image
                consumed = 12 + payload_len + 4
                if total_sz > consumed:
                    f.read(total_sz - consumed)  # encoder padding
            else:
                sys.exit("unknown chunk type 0x%04X at chunk %d" % (ctype, i))
        print("wrote %s (%d bytes)" % (dst, o.tell()))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: sparse_to_raw.py <in.sparse> <out.raw>")
    convert(sys.argv[1], sys.argv[2])
