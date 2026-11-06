# Ramoops carveout audit (boot.img)

Compare the ramoops DT node between two boot images (e.g. a booting reference
and a bootlooping experimental build). The node's `reg` and zone sizes can
change between builds even when the in-tree DTS file is unchanged — always
extract from the actual images.

## Method

1. Parse the boot.img header: ksz = first u32 of `struct.unpack('<10I', data[8:48])`.
2. Slice the kernel payload at page offset 4096; gunzip (zlib.decompressobj(16+MAX_WBITS)).
3. Walk every appended FDT in the decompressed kernel: find each `0xd00dfeed`
   magic, read totalsize/off_dt_struct/off_mem_rsvmap/off_dt_strings, then walk
   the struct block tokens (BEGIN_NODE=1, END_NODE=2, PROP=3, NOP=4, END=9)
   to collect `nodes{path:{prop:[cells]}}`.
4. Print the ramoops node props + every reserved-memory child for BOTH images.
5. Diff: `reg` base, `console-size`, `pmsg-size`, `record-size` presence, `max-reason`.

Reference script: `/opt/data/rm_props.py` (writes `/tmp/rmprops.txt`).

## Reading the diff

- A changed `reg` base is the ramoops carveout moving. Check the new base
  against every sibling reserved region for overlap: e.g. `ramoops_NEW range
  88f00000-89300000` sitting right after `removed_regions@86200000`
  (end 0x88f00000) is clean.
- `record-size` ABSENT means no dumps zone — panics are dropped; only console
  and pmsg exist. That is expected when `record-size` was never in the DTS.

## Cross-checks

- The driver side (`fs/pstore/ram.c`) parses zone sizes with
  `of_property_read_u32`, so single-cell `<0x200000>` values parse fine.
  Older `drivers/char/ramoops.c` used `of_property_read_u64` and FAILED on
  single-cell props (-EOVERFLOW). Match the parser to the tree before
  concluding a size property is broken.
- `console-ramoops` only fills from the normal printk console flow; a hang
  (no panic) leaves it empty even when the region is fine. Distinguish
  hang-vs-panic, not config-vs-working.
