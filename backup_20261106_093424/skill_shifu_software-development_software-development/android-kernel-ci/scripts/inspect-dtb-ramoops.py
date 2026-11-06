#!/usr/bin/env python3
"""Inspect ramoops node props in an Image.gz-dtb or raw .dtb.

Confirms a DTS sizing fix actually landed in the built/flashable artifact
(console-size / pmsg-size / reg / max-reason). Pass either the combined
Image.gz-dtb (gzip member + appended DTB) or a bare .dtb.

Also asserts the reserved region is inside the device's RAM ceiling. A region
at or above the ceiling is silently inert -- memblock owns no memory there, so
ramoops_probe() gets nothing usable and /sys/fs/pstore stays empty even though
the node is present in the DTB and every other check passes. Pass the ceiling
with --ram-ceiling (e.g. 0xA0000000 for a 4 GB device); omit to skip the
assertion.

usage: inspect-dtb-ramoops.py <Image.gz-dtb|.dtb> [--ram-ceiling 0xA0000000]
"""
import sys, zlib, struct

def load_dtb(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] == b'\xd0\x0d\xfe\xed':
        return data  # already a DTB
    # assume Image.gz-dtb: gzip member then appended DTB
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    d.decompress(data)
    tail = d.unused_data
    i = tail.find(b'\xd0\x0d\xfe\xed')
    if i < 0:
        sys.exit('no DTB found in payload')
    return tail[i:]

def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    opts = [a for a in argv[1:] if a.startswith('--')]
    ram_ceiling = None
    if '--ram-ceiling' in opts:
        ram_ceiling = int(opts[opts.index('--ram-ceiling') + 1], 0)

    dtb = load_dtb(args[0])
    (magic, totalsize, off_struct, off_strings, _rsv, _ver, _lc,
     _cid, sz_strings, _sz_struct) = struct.unpack('>10I', dtb[:40])
    assert magic == 0xd00dfeed, 'not a DTB'
    strings = dtb[off_strings:off_strings + sz_strings]
    blob = dtb[off_struct:]

    def s(off):
        end = strings.find(b'\x00', off)
        return strings[off:end if end != -1 else len(strings)].decode('ascii', 'replace')

    pos, found, depth = 0, False, 0
    reg = None
    while pos < len(blob):
        tok = struct.unpack('>I', blob[pos:pos+4])[0]; pos += 4
        if tok == 1:  # BEGIN_NODE
            end = blob.find(b'\x00', pos)
            name = blob[pos:end].decode('ascii', 'replace')
            pos = (end + 1 + 3) & ~3
            if name.split('@')[0] == 'ramoops':
                found, depth = True, 0
                print('ramoops node')
            elif found:
                depth += 1
        elif tok == 2:  # END_NODE
            if found and depth == 0:
                break
            if found:
                depth -= 1
        elif tok == 3:  # PROP
            l, noff = struct.unpack('>II', blob[pos:pos+8]); pos += 8
            val = blob[pos:pos+l]; pos = (pos + l + 3) & ~3
            if found:
                if l == 4:
                    print('  %-14s = 0x%08x (0x%x = %d MiB)' % (
                        s(noff), struct.unpack('>I', val)[0],
                        struct.unpack('>I', val)[0] >> 20,
                        struct.unpack('>I', val)[0] >> 20))
                else:
                    print('  %-14s = %s' % (s(noff), val.hex()))
                if s(noff) == 'reg' and l == 16:
                    # #address-cells=2 / #size-cells=2 -> two 64-bit big-endian words
                    reg = struct.unpack('>QQ', val)

    if not found:
        sys.exit('ramoops node NOT FOUND in this DTB')

    if reg and ram_ceiling:
        base, size = reg
        top = base + size
        print()
        print('region 0x%x - 0x%x (%d MiB) vs RAM ceiling 0x%x' % (
            base, top, size >> 20, ram_ceiling))
        if top > ram_ceiling:
            print('FAIL: region is AT/ABOVE the RAM ceiling -- memblock owns no '
                  'memory there, so the reservation is inert and /sys/fs/pstore '
                  'will stay empty. Move the region below the ceiling.')
            sys.exit(1)
        print('OK: region is inside RAM (%d MiB of headroom)' % (
            (ram_ceiling - top) >> 20))

if __name__ == '__main__':
    main(sys.argv)
