#!/usr/bin/env python3
"""Extract every file from a FAT12/16 filesystem image (pure stdlib, no root).

Use for Qualcomm firmware blobs shipped as raw VFAT images -- e.g. the
`NON-HLOS.bin` member of a fastboot `firmware-update.zip`, which IS the
`modem` partition image (VFAT, mounted at /vendor/firmware_mnt on device).

    python3 fat16_extract.py <image.bin> <outdir>

Prints a manifest of path / size / sha256-prefix. Directory structure,
including LFN long names, is preserved. Read-only: the input is never
modified. Handles FAT12 and FAT16 (distinguishes by cluster count); FAT32
is detected and refused because its root dir is a cluster chain, not a
fixed region.
"""
import os
import struct
import sys
import hashlib

FAT12_MAX_CLUST = 4085
FAT16_MAX_CLUST = 65525


def parse_bpb(data):
    """Read the BIOS Parameter Block. Raises on a non-FAT boot sector."""
    if data[3:11] != b'MSDOS5.0' and data[3:11] != b'MSWIN4.1':
        raise SystemExit('not a FAT boot sector (OEM name is %r)' % data[3:11])
    bps = struct.unpack_from('<H', data, 11)[0]
    spc = data[13]
    rsvd = struct.unpack_from('<H', data, 14)[0]
    nfat = data[16]
    rootent = struct.unpack_from('<H', data, 17)[0]
    tot16 = struct.unpack_from('<H', data, 19)[0]
    spf16 = struct.unpack_from('<H', data, 22)[0]
    tot32 = struct.unpack_from('<I', data, 32)[0]
    spf32 = struct.unpack_from('<I', data, 36)[0]
    if bps not in (512, 1024, 2048, 4096) or spc == 0 or nfat == 0:
        raise SystemExit('implausible BPB: bps=%d spc=%d nfat=%d' % (bps, spc, nfat))
    tot = tot16 or tot32
    spf = spf16 or spf32
    root_secs = (rootent * 32 + bps - 1) // bps
    data_start = rsvd + nfat * spf + root_secs
    nclus = (tot - data_start) // spc
    if nclus < FAT12_MAX_CLUST:
        fat_type = 12
    elif nclus < FAT16_MAX_CLUST:
        fat_type = 16
    else:
        raise SystemExit('FAT32 detected (%d clusters) -- this script does not '
                         'handle a chained root directory' % nclus)
    return dict(bps=bps, spc=spc, rsvd=rsvd, nfat=nfat, rootent=rootent,
                spf=spf, root_start=rsvd + nfat * spf, root_secs=root_secs,
                data_start=data_start, fat_type=fat_type, total_sectors=tot)


def dir_entries(blob):
    """Yield (long_name, short_name, cluster, size, is_dir) from a dir blob."""
    lfn = []
    for i in range(0, len(blob), 32):
        e = blob[i:i + 32]
        if len(e) < 32 or e[0] == 0x00:
            break
        if e[0] == 0xE5:            # deleted
            lfn = []
            continue
        attr = e[11]
        if attr == 0x0F:            # LFN component
            lfn.append(e)
            continue
        nm = e[0:8].decode('ascii', 'replace').strip()
        ex = e[8:11].decode('ascii', 'replace').strip()
        short = nm + ('.' + ex if ex else '')
        long_name = short
        if lfn:
            parts = []
            for le in lfn:
                chars = le[1:11] + le[14:26] + le[28:32]
                parts.append(chars.decode('utf-16-le', 'ignore').split('\x00')[0])
            long_name = ''.join(parts)
        lfn = []
        yield (long_name, short, struct.unpack_from('<H', e, 26)[0],
               struct.unpack_from('<I', e, 28)[0], bool(attr & 0x10))


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    src, outdir = sys.argv[1], sys.argv[2]
    data = open(src, 'rb').read()
    bp = parse_bpb(data)
    bps, spc, rsvd, spf = bp['bps'], bp['spc'], bp['rsvd'], bp['spf']
    data_start = bp['data_start']
    fat = data[rsvd * bps: rsvd * bps + spf * bps]
    print('FAT%d  bps=%d spc=%d rsvd=%d nfat=%d rootent=%d spf=%d '
          'data_start_sector=%d total=%d'
          % (bp['fat_type'], bps, spc, rsvd, bp['nfat'], bp['rootent'], spf,
             data_start, bp['total_sectors']))

    def next_cluster(c):
        if bp['fat_type'] == 12:
            off = c + c // 2
            v = struct.unpack_from('<H', fat, off)[0]
            return v >> 4 if c & 1 else v & 0x0FFF
        return struct.unpack_from('<H', fat, c * 2)[0]

    eoc = 0xFF8 if bp['fat_type'] == 12 else 0xFFF8

    def read_chain(c, size):
        out = b''
        seen = set()
        while 2 <= c < eoc and c not in seen and len(out) < size:
            seen.add(c)
            off = (data_start + (c - 2) * spc) * bps
            out += data[off: off + spc * bps]
            c = next_cluster(c)
        return out[:size]

    manifest = []

    def walk(clus, relpath, depth=0):
        if depth > 8:
            return
        if clus:
            blob = read_chain(clus, 64 << 20)
        else:
            blob = data[bp['root_start'] * bps:
                        (bp['root_start'] + bp['root_secs']) * bps]
        for long_name, short, c, size, is_dir in dir_entries(blob):
            if short in ('.', '..'):
                continue
            dest = os.path.join(relpath, long_name)
            if is_dir:
                os.makedirs(dest, exist_ok=True)
                walk(c, dest, depth + 1)
            else:
                blob_f = read_chain(c, size)
                with open(dest, 'wb') as f:
                    f.write(blob_f)
                manifest.append((dest, size,
                                 hashlib.sha256(blob_f).hexdigest()[:16]))

    os.makedirs(outdir, exist_ok=True)
    walk(0, outdir)
    manifest.sort()
    total = 0
    for p, size, h in manifest:
        total += size
        print('  %12d  %s  %s' % (size, h, os.path.relpath(p, outdir)))
    print('extracted %d files, %d bytes (%.2f MB)'
          % (len(manifest), total, total / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
