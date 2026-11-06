# Diagnosing a missing device when the driver is already compiled in

Scope: an interface or block device that never appears (`wlan0` missing, no
`/dev/block/...`, no `sda`), where the driver is confirmed built into the image
and the config resolves correctly. The compile is NOT the suspect. This is a
probe problem, walked in order, cheapest evidence first.

## 0. Separate the two claims before anything else

State each from its own evidence:

- "the driver is in the image" — proven from the build file
  (`obj-$(CONFIG_X) += ...`), not from the defconfig fragment
- "the device did not appear" — proven from on-device output (`ip link`,
  `/sys/class/...`)

Never let one stand in for the other. The most expensive mistake in this class
is treating a build-file edit as the fix for a probe failure.

## 1. Read the build invocation to learn which file the build actually reads

A driver directory can carry BOTH `Kbuild` and `Makefile` (qcacld-3.0 does).
They are not equal:

- `make O=out ... Image.gz-dtb` → kbuild reads `Kbuild`. `obj-$(CONFIG_X)` in
  `Kbuild` decides `obj-y` vs `obj-m`.
- `make -C $(KERNEL_SRC) M=<dir> modules` → reads the directory's `Makefile`,
  the external-module wrapper. Its `KBUILD_OPTIONS` / `WLAN_SELECT` overrides
  apply only on this path.

Grep the kit workflow for its make lines before editing either file. An edit to
`Makefile` in a tree that only ever runs the `Kbuild` path is a no-op, however
plausible its mechanism.

## 2. Confirm the config symbol resolves as you believe

Defconfig fragment is not the resolved config. kconfig silently drops a symbol
whose dependencies are unmet. Grep the resolved `out/.config` (or the
CI-uploaded config artifact) for the symbol, not the fragment.

## 3. Walk the driver's own platform chain

For Qualcomm WLAN the stack is:

```
qcacld-3.0       the WLAN driver (Kbuild: obj-$(CONFIG_QCA_CLD_WLAN) += wlan.o)
  |-- pld_snoc.c platform glue — icnss_register_driver(), icnss_wlan_enable()
        |-- icnss.c the Q6 WLAN subsystem controller — power, clocks, QMI, PIL
```

The interface cannot come up until `icnss_wlan_enable()` succeeds, because that
is what raises the regulators, enables the CXO clock, and boots the WLAN
subsystem. A perfectly built driver plus an icnss that never probes gives
exactly the symptom in scope.

### The FW_READY gate — the stage most often skipped

`icnss_wlan_enable()` refuses to run unless `ICNSS_FW_READY` is set:

```c
if (test_bit(ICNSS_FW_DOWN, &penv->state) ||
    !test_bit(ICNSS_FW_READY, &penv->state)) {
        icnss_pr_err("FW down, ignoring wlan_enable state: 0x%lx\n", ...);
        return -EINVAL;
}
```

`ICNSS_FW_READY` is set in exactly ONE place —
`icnss_driver_event_fw_ready_ind()` — which also prints
`icnss: WLAN FW is ready: 0x...` and calls `icnss_call_driver_probe()`. That
function invokes `priv->ops->probe()` → `pld_snoc_probe()` → `pld_add_dev()` →
the HDD probe that creates the wiphy (`wlan_hdd_cfg80211.c`'s `wiphy_new()`).

So if the firmware never reports ready over QMI, the whole downstream chain is
skipped quietly: `icnss_driver_event_register_driver()` takes its `goto out`
branch (printing only the debug-level `FW is not ready yet`), and
`pld_snoc_probe()` is never called. No probe → no wiphy → no interface, with the
driver and the DT both fully correct.

The decisive read is therefore the ABSENCE of `icnss: WLAN FW is ready` from
dmesg while `icnss: Platform driver probed successfully` and
`wlan: Loading driver vX` are both present.

Read the platform-glue source for what it requires, then check each requirement
in the DT and the resolved config:

- the subsystem node's `compatible` against the driver's `of_device_id` table
- `reg`, `interrupts`, `iommus` present and matching what the driver's
  resource-parse actually reads
- the `*-supply` regulators exist and are enabled in the board dtsi
- `clocks` / `clock-names` resolvable to a real clock provider

## 4. Device-tree facts worth knowing before blaming the DT

- A node with no `status` property defaults to `"ok"` — a missing `status` is
  NOT evidence the node is disabled. Check `compatible` against the
  `of_device_id` table first.
- Sibling nodes in the same dtsi often DO carry `status = "ok"`, so an absent
  one on a specific node is a style inconsistency, not a disabling signal.
- An absent node and a present-but-unbound node are different faults with
  different evidence: `/proc/device-tree/...` on the live device distinguishes
  them in one command.
- A dtsi nothing includes is dead code regardless of how correct its content
  is — trace the `#include` chain from the board `.dts` before trusting it.

## 5. Firmware: NOT the gate for WLAN, but ALWAYS check it for the peer

Two different firmware paths, and conflating them has already produced a wrong
conclusion here.

**WLAN (icnss v1) does NOT request firmware from disk.** Grepping the subsystem
driver for `request_firmware` and finding zero hits is the expected result on
this path. Do not spend the session copying WLAN firmware before the probe log
has ruled out power, clock, and QMI.

**But the peer subsystem DOES — and its firmware is a hard prerequisite.**
`pil-q6v5-mss.c` sets `desc->fw_name = subsys->fw_name`, which the DT supplies
via `qcom,firmware-name` (`sdm660.dtsi`, `"modem"`), and
`peripheral-loader.c` then does `request_firmware("%s.mdt", desc->fw_name)`
plus `"%s.b%02d"` segments. So the modem loads `/lib/firmware/modem.mdt` and
its `.bNN` files from disk. **`ls /lib/firmware/` is a mandatory line in every
one-paste bundle, and an empty `/lib/firmware/` is a hard blocker, not a
cosmetic one** — even with a boot trigger the peer fails at
`request_firmware()`.

Read the failure severity too: `subsystem_powerup()` PANICS on powerup failure
unless the subsystem sets `ignore_ssr_failure`. So a boot-trigger patch that
runs before the firmware is in place risks a panic, not a clean error. Order
firmware before any trigger patch.

Firmware that was staged earlier may simply not be there: a rootfs reflash
wipes `/lib/firmware/`, so re-check it in every bundle rather than trusting a
previous session's staging note. `icnss2/qmi.c` (v2, a different driver) wants
`bdwlan.elf`/`bdwlan.bin`/`bdwlan.dmy` on disk — do not carry that requirement
over to the v1 path, and do not carry the v1 "no request_firmware" result over
to the peer.

## 6. The evidence that settles it

One on-device grep separates the three causes:

```
dmesg | grep -i -E 'icnss|cnss|wlan|pld|qmi'
```

Read it against this table:

| Log line | Cause | Next move |
|---|---|---|
| `fw service registration failed` | a QMI / subsystem-notif / service-locator symbol did not resolve | grep the resolved config for those symbols |
| **icnss probed OK + driver loaded, but NO `WLAN FW is ready` line** | the Q6 WLAN subsystem never reported ready over QMI, so `ICNSS_FW_READY` was never set and the driver's probe was never called | `dmesg \| grep -i icnss_qmi` for the failed transaction (`Fail to send MSA Mem info req`, `Ind Register resp wait failed`); then grep the resolved config for `CONFIG_QCOM_RMTFS_MEM` and the QMI service symbols |
| `Memory base not found in DT`, `Fail to get IRQ` | node not binding | check `compatible` vs `of_device_id`, and `reg`/`interrupts` |
| nothing mentioning icnss at all | node never instantiated | `dmesg \| grep -i 'Adding device.*icnss'` — no line means no node matched a driver; then check the include chain |
| `wlan enable failed` / QMI timeout | subsystem-side: regulators, clock, `hyp_enabled`, or iommu bypass | check the supplies and the `qcom,iommu-dma` property |

Two cheap supporting reads:

```
zcat /proc/config.gz | grep -E 'ICNSS|CNSS|QMI|SUBSYSTEM|SERVICE_LOCATOR|RMTFS|PIL'
ls /lib/firmware/ | grep -iE 'modem|mss|wlan|wcn'
dmesg | grep -i 'Adding device.*icnss'
```

The `ls /lib/firmware/` line is not optional decoration — the peer subsystem
loads its own `.mdt` from disk (§5), and a reflash silently empties that
directory. Bundle it every time.

**An empty grep is the most valuable result, not a failed one.**
`dmesg | grep -i icnss_qmi` returning NOTHING eliminates every
QMI-transaction hypothesis at once: `icnss_qmi.c` uses a fatal-level error
macro on every failed MSA / Ind-Register / Capability / BDF transaction, so a
transaction that ran and failed would have printed. Zero output means
`wlfw_new_server()` was never called — the WLFW QMI service never advertised
itself. Chase the advertisement, not the transaction.

**The QMI service locator sits UPSTREAM of icnss and fails independently.**
`service-locator.c`'s `init_service_locator()` runs its own
`qmi_add_lookup(SERVREG_LOC_SERVICE_ID_V01, ...)` and waits on a completion for
`LOCATOR_SERVICE_TIMEOUT`. When it times out:

```
servloc: init_service_locator: wait for locator service timed out
servloc: pd_locator_work: Unable to connect to service locator!, rc = -62
```

`rc=-62` is that driver's own `-ETIME` from the timeout, NOT `ETIMEDOUT` (110).
With the locator dead, `icnss_pd_restart_enable()`'s
`get_service_location("wlan","wlan/fw",...)` fails, the PDR notifier is never
registered, the WLFW service is never observed, and `wlfw_new_server()` never
fires — producing exactly the "no WLAN FW is ready" row above with no
`icnss_qmi` output at all. **Grep `servreg|pdr|service.loc` BEFORE
`icnss_qmi`**: a locator timeout explains the empty icnss_qmi grep, and the same
locator failing for a different consumer (`adsprpc: PDR notifier locator for
adsp is down`) proves it is a transport problem, not a WLAN bug.

## 6a. Silence in dmesg is not health — check whether the print was compiled out

A subsystem that prints nothing may be a subsystem whose diagnostics were never
built. Vendor drivers gate their debug prints behind a CONFIG that is usually
off. `icnss_pr_dbg()` marks exactly where the bring-up chain stops
("Get service notify opcode", "WLFW server arrive", "FW is not ready yet",
"PD notification registration happened") and every one of those is invisible
without `DYNAMIC_DEBUG`. Confirm before believing the log:

```
echo 'file <driver>.c +p' > /sys/kernel/debug/dynamic_debug/control
```

**Read the RUNNING kernel's config for the symbol before proposing to add it.**
A defconfig grep is not evidence: `DEBUG_FS` is `select`ed transitively by
`mm/Kconfig`, `kernel/trace/Kconfig`, `net/sunrpc/Kconfig`,
`drivers/md/bcache/Kconfig` and `drivers/edac/Kconfig`, so a kernel can be
built with `CONFIG_DEBUG_FS=y` from a defconfig that never mentions it and from
neither of the vendor defconfigs. `zcat /proc/config.gz | grep DEBUG_FS` on the
device settles it in one command; the defconfig cannot.

A `nonexistent directory` failure is therefore AMBIGUOUS, not proof of
`CONFIG_DEBUG_FS=n` — the same failure appears when the shell is a different
(older) build than the one under test, and when debugfs is simply not mounted.
Match the failure to the build you are actually testing (`uname -a` +
`/proc/config.gz` from that same session) before concluding anything.

`DYNAMIC_DEBUG` (`lib/Kconfig.debug`, `default n`) is the symbol that is
genuinely usually missing and the only one worth adding — it makes the chain
runtime-switchable with no rebuild. Prefer it over the driver's own debug
symbol (e.g. `CONFIG_ICNSS_DEBUG`) when that symbol's help text says it enables
`BUG_ON` — a hang risk on a device whose registers may already be wedged, for
no gain over `DYNAMIC_DEBUG`.

**Do not ship `CONFIG_DEBUG_FS=y` as an instrumentation fix.** Adding a symbol
that is already on is a redundant line that costs a build cycle and implies the
earlier "we are debugging blind" claim was checked, when it was not.

## 6b. A node named for a driver is not necessarily bound to that driver

`compatible` decides binding; the node's name is a comment. sdm660 carries
`qcom,rmtfs_sharedmem@0` with `compatible = "qcom,sharedmem-uio"` — it binds
the UIO sharedmem driver, not `rmtfs_mem.c`. Enabling `CONFIG_QCOM_RMTFS_MEM=y`
therefore compiles a driver with nothing to bind to, and the fix appears to
"do nothing" for a reason that looks like a mystery.

Before enabling any driver's CONFIG, grep the tree for a node whose
`compatible` the driver actually matches:

```
grep -rn 'compatible = "<driver-compatible>"' arch/ -A6
grep -rn '.compatible = "' drivers/<path>/*.c | head
```

Also check the node is in the right block (`reserved-memory` vs `soc`) and that
its `reg` carries a real base+size — `reg = <0x0 0x200000>` with no base is
not a valid region. If no reference for the correct node exists in any local
tree, leave the DTS alone rather than inventing a reserved region: a wrong
reserved-memory range can brick a boot, and a config-only change that turns
out inert costs one cycle.

## 6c. Collect the whole subsystem in ONE paste, not one grep per turn

The build-flash-boot-dmesg cycle is the expensive part; each turn spent
requesting a single grep spends a full round-trip to learn one bit. Ask for the
entire relevant surface at once, writing to a path that exists on the device
(`/sdcard` is often absent in an OpenWrt shell — use `/tmp`):

```sh
{
  echo "=== <subsystem> ===";    dmesg | grep -i <subsystem>
  echo "=== <glue> ===";         dmesg | grep -i <glue>
  echo "=== transport ===";     dmesg | grep -iE 'qmi|servreg|pdr|rmtfs'
  echo "=== class ===";         ls /sys/class/<class>/ 2>&1
  echo "=== config ===";        zcat /proc/config.gz | grep -iE '<SYMS>'
} > /tmp/debug.txt 2>&1; cat /tmp/debug.txt
```

Pre-commit to a decision rule before the log arrives, so each outcome maps to
a patch instead of a re-derivation:

| Observation | Meaning | Patch |
|---|---|---|
| glue's debug line present, no server-advertise line | service discovery broken | the transport is a symptom, not necessarily the cause — walk §6d before patching a region |
| server arrives, then a fatal error from the glue | transport works, transaction fails | MSA/SMMU/capability mismatch in the DT |
| ready + driver loaded, interface still absent | driver-side (wiphy creation) | different investigation entirely |

**Never read `cat /proc/device-tree/soc/<node>/status` as a node-existence
test.** That file exists only when the node carries a `status` property; a node
without one still defaults to `"ok"` and binds, so the read prints "node absent"
for a node that is demonstrably present — a false negative that has already been
reported upward as a root cause once. Prove the node instantiated from the
`iommu: Adding device <addr>.<compatible> to group N` dmesg line instead: it is
emitted only for a node that matched a driver, so its presence settles the DT
question in one command and cannot mislead.

## 6d. When the transport is the suspect, time it and find its remote peer

A service-locator / QMI timeout names WHERE the chain stopped, not WHY. Two
reads turn it into a root cause, and both are free.

**Do the timestamp arithmetic before theorising.** A timeout constant printed at
a timestamp that matches it means the wait ran to completion:

```
service-locator.c:28   #define LOCATOR_SERVICE_TIMEOUT   300000   (300 s)
[313.653351] servloc: init_service_locator: wait for locator service timed out
```

300 s plus the ~13 s of boot before the work was scheduled lands exactly on the
print. `init_service_locator()` runs in a scheduled workqueue
(`service-locator.c:330-331`), not an initcall, so it is not racing boot — it
waited the full window and the remote never answered once. That rules out
ordering, missing config, and "too early" as causes, and localises the fault to
the remote peer.

**Find out whether the remote peer ever booted.** The transport's peer is a
remote subsystem; a subsystem that never booted cannot answer any QMI lookup,
and every consumer of that transport fails together. On SDM660 the peer is the
modem MSS:

```
dmesg | grep -iE 'pil-q6v5-mss|qcom,mss|modem|subsys'
```

Read it in this order:

- `pil-q6v5-mss <addr>.qcom,mss: No pas_id found.` — `dev_info`, NON-FATAL
  (`pil-q6v5-mss.c` falls back to the non-PAS boot path), and mainline sdm660
  has no `qcom,pas-id` either. Not the blocker. Same for `minidump-id not
  found for modem`.
- `platform <addr>.qcom,mss:qcom,mba-mem@0: assigned reserved memory node` —
  proves `pil_mss_driver_probe()` ran and called `of_platform_populate()`, so
  the MSS driver bound. It does NOT prove the Q6 booted.
- **A `subsys-pil-tz <node>` line proves that node's DRIVER registered a
  subsystem — it does NOT prove the subsystem booted, and its absence proves
  nothing at all unless you know which driver that node uses.**
  `subsys-pil-tz.c` names itself from `qcom,firmware-name`
  (`subsys-pil-tz.c:1090`, the only string it reads for the name), so ONLY
  TZ-based nodes — venus, adsp/lpass, cdsp/turing, kgsl-hyp — ever print one.
  The sdm660 modem is `pil_modem: qcom,mss@4080000` with
  `compatible = "qcom,pil-q6v55-mss"`, which binds `pil-q6v5-mss.c`, a
  DIFFERENT driver that never registers with `subsys-pil-tz` at all. So the
  modem's absence from that list is expected and carries ZERO information —
  treating it as an asymmetry, or as evidence the modem never booted, is a
  misattribution that has already been reported upward once. Before reading
  anything into which subsystems print the line, resolve each node's
  `compatible` to its driver:

```
cat /proc/device-tree/soc/<node>/compatible   # on device
grep -rn '"<compatible>"' drivers/soc/qcom/*.c | head   # in tree
```

  **Registering is not booting, and nothing in the kernel tree boots a
  subsystem for you.** `subsys_register()` (what both drivers call) only
  advertises a subsystem under `/sys/class/subsys/`. The real boot entry point
  is `__subsystem_get()` (`subsystem_restart.c:945`) → `subsys_start()`
  (`:836`) → `desc->powerup()`, and for the modem that powerup is
  `modem_powerup()` (`pil-q6v5-mss.c:146`) → `pil_boot()`. Grep the whole tree
  for `subsys_boot(` / `rproc_boot(` / callers of `subsystem_get(` and you find
  only unrelated drivers. **A peer that is registered but never booted is the
  expected state on a non-Android userspace.**

  **Do NOT conclude "so write a userspace program to boot it" — check whether
  the kernel even exposes a userspace boot interface first.** On this tree it
  does not: `subsys_device_fops` (`subsystem_restart.c:1411`) has only
  `.open`/`.release` — no `.read`, `.write`, or `.unlocked_ioctl` — so the
  `/dev/subsys_<name>` node is open/close only, and the `subsys_attrs[]`
  (`:382`: `name`, `state`, `crash_count`, `restart_level`, `firmware_name`,
  `system_debug`) are all read-only. `subsystem_get()` is `EXPORT_SYMBOL`
  kernel-only with no sysfs or chardev wrapper anywhere in the tree.
  Read `subsys_device_fops` and the attr list BEFORE promising a userspace
  fix; when there is no wrapper, the trigger needs a kernel source patch (a
  writable attr or an ioctl), and that is a rebuild, not a script. Verify the
  firmware is in place before that patch ships, or the powerup failure panics.
- Nothing at all from the MSS node means the driver never bound — back to the
  DT and `compatible` (section 4).

When the peer is missing, the correct conclusion is that the fault is
UPSTREAM of every subsystem on that transport: the config, the fragment, and
the driver-side debug build are all instrumentation, not fixes. Stop patching
kernel config for it and name what would make the peer boot.

**Check that the substrate itself is healthy before blaming the peer.** The
same bundle distinguishes "transport dead because its substrate is missing"
from "transport dead because its peer never booted", and the two have opposite
fixes:

```
dmesg | grep -iE 'smem|smp2p|scm|hyp|pil-tz'
```

`OF: reserved mem: initialized node smem-mem@...` plus
`platform soc:smem: assigned reserved memory node` proves SMEM came up and
bound; several live `subsys-pil-tz` lines prove PIL-TZ and the TrustZone path
work. With those present and only the one peer missing, the substrate is fine
and the peer is the fault — which is the case that makes a kernel-side fix the
wrong tool.

## 6e. What makes the remote subsystem boot on one userspace and not another

When the peer is missing on the non-Android userspace but the same kernel boots
Wi-Fi fine under Android, the difference is not the kernel. On SDM660 the WLAN
Q6 shares the modem's servreg/QMI transport, so one dead peer takes the whole
transport with it.

**"It's a userspace problem" is not the end of the investigation — verify what
userspace can actually DO before naming that the fix.** Android's vendor
userspace triggers the Q6 bring-up through an interface that may not exist on
the target kernel at all. Settle two questions, in this order, before writing
any plan:

1. **Does the kernel expose a userspace boot interface?** Read
   `subsys_device_fops` for ioctl/read/write and the `subsys_attrs[]` list for
   a writable attr. On the sdm660 tree the answer is no (see §6d), which makes
   the fix a kernel source patch plus a rebuild — a very different amount of
   work from "write an init script", and the user deserves to hear the real
   cost up front.
2. **Is the peer's firmware present?** See §5 — the peer loads
   `/lib/firmware/<name>.mdt` + `.bNN` from disk, and powerup failure panics
   unless `ignore_ssr_failure` is set.

Only after both are answered can the remaining work be sized honestly. A
config change shipped as the fix in that situation costs a build-flash-boot
cycle to learn nothing, and a "userspace fix" promised without checking the
interface can turn out to need a kernel patch — which is the difference
between a script and a rebuild.

## 6f. Two drivers, one `compatible`: check quirk settability AND availability before switching

A DT node's `compatible` can be claimed by more than one platform driver, and
the two drivers are not interchangeable. On sdm660 both `icnss.c` (v1) and
`icnss2/main.c` register `"qcom,icnss"` in their `of_device_id` tables, so the
same node matches either — enabling both is a probe race, so a switch is a
replacement, never an addition.

**Check that the candidate driver is actually BUILT before planning the
switch.** A `compatible` match in the source proves nothing about the running
kernel: `drivers/soc/qcom/Makefile` gates each driver on its own
`obj-$(CONFIG_ICNSS)` / `obj-$(CONFIG_ICNSS2)` line, and a driver whose CONFIG
is unset is absent from the image and from the running kernel entirely. The
one-paste bundle answers it on device:

```
ls /sys/bus/platform/drivers/ | grep -E 'icnss|cnss'
zcat /proc/config.gz | grep ICNSS
```

`icnss2` present in `/sys/bus/platform/drivers/` means it is built AND bound
something; absent from that listing means the switch requires enabling
`CONFIG_ICNSS2` first — a config change you did not propose, on a driver that
has never run on this hardware.

They differ in the one property that matters when a QMI handshake is failing:

- `icnss2` has an `icnss_init_control_params()` that reads a DT property, and
  its `SKIP_QMI` quirk sets `ICNSS_FW_READY` **unconditionally**
  (`icnss2/main.c`), which bypasses the servreg/QMI handshake entirely and lets
  the platform glue probe normally.
- The v1 driver's `quirks` global is initialised once (`icnss.c:74`) and never
  written again — no `module_param`, no DT read, no setter. Its `SKIP_QMI` is
  unreachable dead code, so it can never be used to work around a dead
  transport no matter how tempting the bit name looks.

**Never assume a quirk is settable because the bit exists.** Grep for writes
before building a plan around it:

```
grep -rn 'quirks\s*=\|set_bit.*quirks\|clear_bit.*quirks' --include='*.c' drivers/soc/qcom/<driver>.c
```

Only the initialisation line means the quirk cannot be set from DT, module
params, or sysfs.

Check API compatibility the same way before switching drivers: list the glue's
calls and confirm each exists in the candidate driver's header.

```
grep -oE 'icnss_[a-z_]+' drivers/staging/qcacld-3.0/core/pld/src/pld_snoc.c | sort -u
grep -oE 'icnss_[a-z_]+\(' include/soc/qcom/icnss2.h | tr -d '(' | sort -u
```

A clean API match does NOT prove the candidate driver drives the hardware
correctly — it only proves it will link and probe. State that limit when
proposing the switch.

## 7. Reporting discipline for this class

- "The driver is compiled in" and "the interface appears" are separate claims.
  Keep them separate in the write-up.
- Static analysis that does not converge is a "not yet found", not a root
  cause. Name the hypotheses eliminated, with the file:line that eliminated
  each, and name the one artifact that would resolve the rest.
- A retracted wrong root cause costs more trust than an honest pending one.
- When device evidence kills your ranked hypotheses, restate the ranking from
  the new evidence in the same turn. Say plainly which causes the log
  eliminated (with the line that eliminated them) before naming the surviving
  one — do not defend the earlier analysis, and do not quietly re-rank without
  acknowledging the ones that died.
