#!/usr/bin/env python3
"""Android sparse image -> raw image converter (pure stdlib, no simg2img).

For hosts with no root and no access to AOSP's simg2img/unzip/file binaries.
Usage: python3 simg2img.py <in.sparse> <out.raw>

Handles all four chunk types. The CRC32 branch is the subtle one: per
sparse_format.h, chunk_header.total_sz counts the 12-byte header AND the
trailing 4-byte CRC word, so the image payload is total_sz - 12 - 4. Deriving
it from nblks*blk_sz overruns when the encoder padded the chunk, which yields
a short output image that still passes every per-block content check.
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
            sys.exit("file too small to be a sparse image")
        (magic, major, minor, fhdr_sz, chdr_sz,
         blk_sz, total_blks, total_chunks, _crc) = struct.unpack("<IHHHHIIII", hdr)
        if magic != SPARSE_MAGIC:
            sys.exit("not a sparse image (magic=0x%08X)" % magic)
        if major != 1:
            sys.exit("unsupported sparse major version %d" % major)
        if chdr_sz != 12:
            sys.exit("unexpected chunk header size %d" % chdr_sz)
        print("sparse: blk_sz=%d total_blks=%d chunks=%d img_size=%.1f MiB"
              % (blk_sz, total_blks, total_chunks,
                 total_blks * blk_sz / 1048576.0))
        for i in range(total_chunks):
            ch = f.read(12)
            if len(ch) < 12:
                sys.exit("truncated chunk header at chunk %d" % i)
            ctype, _rsvd, nblks, total_sz = struct.unpack("<HHII", ch)
            if ctype == CHUNK_RAW:
                data = f.read(nblks * blk_sz)
                if len(data) != nblks * blk_sz:
                    sys.exit("truncated RAW payload at chunk %d" % i)
                o.write(data)
            elif ctype == CHUNK_FILL:
                fill = f.read(4)
                o.write(fill * (nblks * blk_sz // 4))
            elif ctype == CHUNK_DONTCARE:
                o.write(b"\x00" * (nblks * blk_sz))
            elif ctype == CHUNK_CRC32:
                # total_sz = 12 (header) + payload + 4 (crc word).
                payload_len = total_sz - 12 - 4
                payload = f.read(payload_len)
                if len(payload) != payload_len:
                    sys.exit("truncated CRC32 payload at chunk %d" % i)
                o.write(payload)
                f.read(4)  # the CRC itself is not image data
                consumed = 12 + payload_len + 4
                if total_sz > consumed:
                    f.read(total_sz - consumed)  # encoder padding
            else:
                sys.exit("unknown chunk type 0x%04X at chunk %d" % (ctype, i))
        print("wrote %s (%d bytes)" % (dst, o.tell()))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: simg2img.py <in.sparse> <out.raw>")
    convert(sys.argv[1], sys.argv[2])
