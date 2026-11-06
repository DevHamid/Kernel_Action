# Ramoops / pstore empty-dmesg debugging (sdm660 / Android 4.19)

## Root cause: zero-sized dump zone in the DTS

`fs/pstore/ram.c` splits the reserved region into zones from the DTS
properties. The dump (dmesg) zone gets whatever is left after console and
pmsg:

- `console-size` + `pmsg-size` + inter-zone metadata (`struct persistent_ram_buffer`
  header + `prz->size` rounding) take space out of `mem_size`.
- If the two fixed zones already swallow the whole reserved region, `dump_mem_sz`
  becomes 0 and `ramoops_init_przs("dump", ...)` allocates a ZERO-size zone —
  so `dmesg-ramoops-0` never appears in `/sys/fs/pstore`, even though the
  pstore backend registers fine and `max-reason` is high enough to capture
  everything.

The math is the diagnostic: `dump_size = mem_size - console_size - pmsg_size`
(metadata aside). If that is 0 or negative, the dump zone does not exist.

## Check sequence

1. Find the node: grep the tree for `ramoops` under `arch/arm64/boot/dts/`
   (vendor tree). Usually a dedicated `*-ramoops.dtsi` included by a base
   dtsi.
2. Read the reserved region and sizes:
   - `reg = <0x0 0xA0000000 0x0 0x00400000>` → 4 MiB @ 0xA0000000.
   - `console-size = <0x200000>`, `pmsg-size = <0x200000>` → 2 MiB each.
   - Sum = 4 MiB → `dump_mem_sz = 0`.
3. Confirm the fixed zones are what the tree actually uses: grep
   `record_size` (default dump record), `console_size`, `pmsg_size` in
   `fs/pstore/ram.c`. A 4 MiB region with 2 MiB console + 2 MiB pmsg is the
   classic zero-dump layout.
4. Verify the reserved region does not coincide with a DMA/IOMMU pool hint.
   `qcom,iommu-dma-addr-pool` is a HINT (address the IOMMU may use), not a
   reservation — overlap there is harmless; overlap with an actual
   `reserved-memory` child region is not.

## Fix

Make the dump zone positive: either enlarge the reserved region, or shrink
console/pmsg. For a 4 MiB region, `console-size = <0x100000>` (1 MiB) and
`pmsg-size = <0x100000>` (1 MiB) leaves a 2 MiB dump zone. Change only the
DTS node; no C code changes.

## Verify the fix reaches the board (include chain, and the wrong grep)

A dtsi edit is dead until something includes it. Trace the chain from the
board's `.dts` down to the edited dtsi before claiming the fix ships:

```bash
git grep -n '#include' -- arch/arm64/boot/dts/vendor/qcom/xiaomi/wayne.dtsi
# repeat for each dtsi named, until the ramoops dtsi is the last hop
```

On wayne the chain is four includes deep — `wayne.dtsi` →
`longcheer/common/longcheer-sdm660.dtsi` →
`longcheer/common/longcheer-sdm660-base.dtsi` →
`longcheer/common/longcheer-sdm660-ramoops.dtsi`. `git grep ramoops -- '*.dts'
'*.dtsi'` finding the file is NOT proof the board pulls it in; only the last
hop is.

**Never verify the dump-zone fix by grepping for a `dump` property.** The fix
adds no `dump-size`/`dump` property at all — it shrinks `console-size` and
`pmsg-size` so the leftover region becomes the dump zone. `grep -n dump
<dtsi>` returning nothing reads as "fix absent" when the fix is present and
live. The correct check is the arithmetic on the values actually committed:

```bash
git show <ref>:<path>/longcheer-sdm660-ramoops.dtsi   # committed values, not the dirty tree
# reg 0x400000 - console 0x100000 - pmsg 0x100000 = 0x200000 dump zone
```

A dirty working tree can differ from the branch that was built and shipped, so
read the committed blob, not the file on disk.

## Why vayu (sm8150) style pstore commits usually do NOT fix empty dmesg

Backported 4.19 trees usually already have several of the "pstore fix" commits
from newer trees. Before treating a proposed set as the fix, check each against
the actual tree:

- `max_reason` member / `pstore_dumper.max_reason = psinfo->max_reason` —
  already present in most backports; not the empty-dmesg cause.
- removal of the reason filter in `ramoops_pstore_write` (always write) —
  usually already present.
- DTS sizing commit from another SoC — SoC-specific; the binding is the same
  but the reserved-memory layout differs.
- cosmetic filename rename (dmesg→console) — does not create data.

If the reserved-region/zone math is sound, the backend is registered, and the
DTS is the only sizing input, a zero dump zone is the first thing to check —
not the C code.

## Second root cause: silent HANG (deadlock) never fires panic — pstore stays empty

Even with correct zone sizing (dump zone positive, backend registered), a real
freeze can still leave `/sys/fs/pstore` empty. A silent deadlock raises NO
exception, so no `panic()`/oops runs, so `kmsg_dump` never writes — ramoops
only captures dumps that a panic/oops triggers. This is distinct from
the zero-dump-zone cause above: check the kernel log / hang semantics before
assuming sizing is wrong.

### Machine-hang detectors reset BEFORE any panic can dump

Vendor WDT drivers (e.g. qcom `core_hang_detect`/`gladiator_hang_detect`) arm
the PMU; on a hit they raise a hardware WDT bite → hard reset. The bite is a
silent reboot, not a panic — no pstore dump. `PANIC_TIMEOUT=-1` (disable
auto-reboot-on-panic) makes this worse: even if a panic DID run, it would hang
instead of rebooting.

### Fix: convert the bark into a panic so the dump fires before the bite

Standard watchdog practice — catch the bark (soft timer firing before the
hardware bite), panic, dump, then reboot:

- In the WDT driver's bark handler, call `panic("Watchdog bark: system hung")`
  instead of the hardware bite, and register a `panic_notifier` that extends the
  WDT by `panic_timeout+10`s so the reset happens AFTER the dump flushes.
- Set `CONFIG_PANIC_TIMEOUT` to a small POSITIVE value (e.g. 3) so the kernel
  actually reboots after the dump instead of hanging on the panic.

On sdm660/Android 4.19 the binding is `qcom,msm-watchdog` →
`drivers/soc/qcom/watchdog_v2.c` (NOT `qcom-wdt.c`/`kpss-wdt`). The bark
handler is `wdog_bark_handler` (≈line 771); the fix is to replace its
`msm_trigger_wdog_bite()` call with `panic("Watchdog bark: system hung")`.
The existing `panic_wdog_handler` notifier already extends the WDT by
`panic_timeout+10`s, so the reset lands AFTER the dump flushes — no new
notifier is needed. Grep for OTHER callers of `msm_trigger_wdog_bite()`
(e.g. in `msm-poweroff`) and leave them untouched — only the bark path should
panic. `panic()` needs `#include <linux/kernel.h>`.

Verify `pstore_dumper` is registered (`kmsg_dump_register()`) — panic invokes
it, which is what lands the dump.

## Third root cause: no `RESERVEDMEM_OF_DECLARE` — the node matches nothing, so `ramoops_probe()` never runs (CONFIRMED on wayne 4.19, empty `/sys/fs/pstore` despite correct DTS sizing and a positive dump zone)

Correct DTS zone math and a registered pstore backend are NOT sufficient. The
DTS node still has to become a platform device, and on 4.19 that happens only
through `drivers/of/of_reserved_mem.c`:

`fdt_init_reserved_mem()` → `__reserved_mem_init_node(rmem)` walks
`__reservedmem_of_table` (built from every `RESERVEDMEM_OF_DECLARE` in the
kernel) and calls the FIRST `initfn` whose compatible matches, then returns.
If no entry matches the node's compatible, no device is created,
`ramoops_probe()` never runs, and `/sys/fs/pstore` stays empty — the DTS is
simply never consumed.

Diagnostic: `grep -rn RESERVEDMEM_OF_DECLARE --include=*.c` in the tree. If
there is no `RESERVEDMEM_OF_DECLARE(ramoops, "ramoops", ...)` in
`fs/pstore/ram.c`, this is the cause. Check the tree, not upstream — mainline
has it, vendor backports frequently dropped it.

### The compatible-collision trap

A node with `compatible = "ramoops", "removed-dma-pool"` matches BOTH entries,
and `of_flat_dt_is_compatible()` returns true for any string in the list — so
`kernel/dma/removed.c`'s `RESERVEDMEM_OF_DECLARE(dma,
"removed-dma-pool", ...)` can claim the node first in link order, register a
DMA pool, and return. Adding a ramoops entry alone does NOT fix it; the
collision must be removed. Since the region is `no-map` and used purely as
ramoops storage, drop the second compatible: `compatible = "ramoops";`.

Check the ORDER the dtsi actually declares, not the order you expect. A branch
can ship `compatible = "removed-dma-pool", "ramoops"` with the DMA pool FIRST —
same collision, opposite order, and it reads as "ramoops is there" to a
substring grep. Grep the committed blob for the full compatible line and assert
the ramoops string is the ONLY one before calling the collision resolved.

### `record-size` absent vs. sized to zero — two different checks

The zero-dump-zone cause above is arithmetic (console+pmsg consume the region).
A separate failure is the dump record property simply MISSING from the dtsi:
`ramoops_parse_dt()` defaults `record-size` to 0 when the property is absent,
and `ramoops_probe()` rejects a context whose record/console/ftrace/pmsg sizes
are all zero. So a dtsi carrying `console-size` + `pmsg-size` but no
`record-size` gets console+pmsg only and never a dmesg dump zone. Grep the
committed dtsi for `record-size` explicitly — do not infer the dump zone from
the region math alone, because the property may not be there to size it.

### The fix must defer device creation to an initcall

The `RESERVEDMEM_OF_DECLARE` callback runs from
`early_init_dt_scan_nodes()` — long before the platform bus exists, so
`platform_device_register_simple()` there faults. The callback only stashes
`rmem->base`/`rmem->size`; the device is created in `ramoops_init()` (a
`postcore_initcall`, which runs after `of_platform_default_populate()`).

Use `of_platform_device_create(node, NULL, NULL)` — NOT
`platform_device_register_simple()`. `ramoops_probe()` only calls
`ramoops_parse_dt()` when `dev_of_node(dev)` is set; a plain platform device
has no OF node, so `console-size`/`pmsg-size`/`record-size` are silently
dropped and the probe fails on NULL platform data. `of_device_alloc()`
populates `dev->resource` from the node's `reg` via `of_address_to_resource()`
and sets `dev->dev.of_node`, so both the resource and the DT properties land.
Verify the parent `reserved-memory` node declares `#address-cells = <2>` /
`#size-cells = <2>` / `ranges`, or the `reg` will not translate.

### Include `of_platform.h` — `of_reserved_mem.h` does not declare the creator

`of_platform_device_create()` is prototyped in `include/linux/of_platform.h`,
NOT in `of_reserved_mem.h`. Including only the reserved-mem header compiles
under a permissive build but fails under `-Werror` with
`implicit declaration of function 'of_platform_device_create'` plus an
int-to-pointer conversion error — and the failure surfaces ~12 minutes into
CI, after the dependency install. Add both headers together:

```c
#include <linux/of_reserved_mem.h>   /* RESERVEDMEM_OF_DECLARE, struct reserved_mem */
#include <linux/of_platform.h>       /* of_platform_device_create */
```

Grep the tree's headers for every NEW symbol the patch introduces before
committing — `grep -rn '<symbol>' include/linux/` — rather than assuming the
header that names the subsystem also declares its helpers. The same check
covers `for_each_compatible_node` (`of.h`) and `platform_device_register_simple`
(`platform_device.h`).

Also confirm the region does not overlap an existing `reserved-memory` child
(`__rmem_check_for_overlap()` only warns, it does not fail) — walk the base
dtsi's `reg` entries and diff the ranges before shipping.

## Fourth root cause: reserved region OUTSIDE physical RAM — silently inert (CONFIRMED on wayne: empty `/sys/fs/pstore` with correct sizing, correct compatible, positive dump zone, node present in the shipped DTB)

Every check above can pass and pstore still stays empty if the region itself
sits at or above the device's RAM ceiling. `memblock` owns no memory there, so
the reservation is inert and `ramoops_probe()` gets nothing usable — the node
is in the DTB, the driver is correct, and `/sys/fs/pstore` is empty anyway.

On a 4 GB device RAM ends at `0xA0000000`. A region
`reg = <0x0 0xA0000000 0x0 0x00400000>` therefore starts AT the ceiling and
lies entirely outside RAM. This is easy to miss because the address looks
plausible next to the other reservations and the node compiles cleanly.

### Determine the ceiling from the device, not the DTS

Qualcomm Android DTS trees usually carry NO `memory@` node — RAM size comes
from the bootloader. Get it from the device model (wayne = Mi 6X, 4 GB →
ceiling `0xA0000000`; a 6 GB variant ends at `0xC0000000`). Then assert:

```
region_top = reg_base + reg_size
region_top < ram_ceiling        # else the region is outside RAM
```

### The highest existing reservation is a red flag, not a reassurance

Walk every fixed `reg` in the base dtsi's `reserved-memory` node and sort by
top address. If the new region sits ABOVE all of them, treat that as a signal
to check the ceiling — vendor trees cluster reservations just under the RAM
top, and a region floating above the pack is usually outside it. On wayne the
next-highest reservation topped out at `0x9F7FF000`, 8 KB below the ramoops
base.

### Trace the address history — a sizing commit can silently revert an address

A commit that only means to change zone sizes can carry an address revert in
the same diff, and its message will not mention it. Before trusting any
address in the tree, trace it:

```bash
git log --oneline --all -S '0xA0000000' -- <path>/<board>-ramoops.dtsi
# then per commit: git show <sha>:<path> | grep -o 'reg = <...>'
```

Print the `reg` line for every commit that touched the file and read the
sequence. An address that was correct, regressed, and was inherited by later
work shows up as a flip in that column — the regression commit is the one that
changed it without saying so.

### Overlap check is necessary but not sufficient

Zero overlap with the other reservations proves the region is *free*, not that
it is *addressable*. Run both: the overlap diff against every fixed `reg` in
the base dtsi, AND the ceiling assertion above.

## Verify the fix in the built artifact

A DTS change only matters if it lands in the DTB that ships in the flashable
payload. Parse the DTB directly — do not trust the source tree or a green CI
run. `scripts/inspect-dtb-ramoops.py <Image.gz-dtb>` decodes the DTB (handling
the gzip member + appended-DTB layout of `Image.gz-dtb`) and prints the
ramoops node's `reg`/`console-size`/`pmsg-size`/`max-reason` from the actual
built image. Expected after the fix: `console-size = 0x100000`,
`pmsg-size = 0x100000`, `reg` still 4 MiB — dump zone 2 MiB. `gzip.decompress`
(and `zcat`) FAIL on `Image.gz-dtb` because a trailing DTB is appended after
the gzip member; use `zlib.decompressobj(31/16+MAX_WBITS)` and read
`d.unused_data` for the DTB.

## State the verification boundary: compiled is not running

Every check above proves the fix COMPILED, LINKED, and LANDED IN THE DTB. None
of them proves `ramoops_probe()` actually bound and populated `/sys/fs/pstore`
— that only the device can show. When handing the artifact over, say which
side of the line you are on in plain words: "verified compiled and present in
the built DTB, not verified running." Do not let a green CI run plus a clean
DTB parse read as "pstore now works".

The on-device confirmation is a single command, and it is the ONLY proof:

```bash
ls -la /sys/fs/pstore/          # populated = probe bound and zones registered
```

### When root is broken, the pstore check is NOT blocked — use the unprivileged path

`/sys/fs/pstore` is mode 0444 (world-readable), so `adb shell ls /sys/fs/pstore/`
works with SU completely broken. Do not report the pstore verification as blocked
by a root failure — that conflates two independent faults and stalls the one check
that is already unblocked. Run the unprivileged `ls` and pair it with
`adb shell su -c id` so the two problems stay separate.

The SU failure is still the higher-priority defect (it blocks every other
on-device verification), but it does not block THIS one. Ask for the SU evidence
— the manager app's error text and `su -c id` output — as its own item, and take
the pstore answer from the `ls` you can already get.

If it is still empty after flashing the fixed build, the driver-side fix did
not take effect and the next evidence needed is
`dmesg | grep -i -E 'ramoops|pstore|reserved'` — do not re-derive the cause
from static reading, ask for that output. A populated pstore is also the
precondition for the whole point of the exercise: pulling `dmesg-ramoops-0`
after a freeze to name the freezing code path, which no amount of source
reading substitutes for.
