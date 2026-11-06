# Device boot failure: controls before theories

Use for CI-green Android boot images that reboot or remain on the vendor logo.
Compilation, image-structure validation, device boot, and usable networking are
separate milestones. Report only the milestone actually observed.

## Interpret symptoms without overclaiming

- Repeated reboot is evidence of a reset, not proof of a kernel panic. Possible
  causes include watchdog timeout, bootloader rejection, userspace reboot,
  kernel panic, or power trouble. Configured panic behavior alone does not
  establish that a panic happened.
- A persistent logo cannot prove kernel startup, PID 1 survival, or OpenWrt
  success. Bootloader display contents can persist while a kernel runs or hangs.
- CONFIG_VT=n disables virtual terminals; it does not establish that all console
  drivers are absent or that opening /dev/console fails. Hardware serial consoles
  can exist without VT. Verify the actual configuration and boot arguments.
- No USB enumeration establishes that the host sees no USB device. It does not
  distinguish bootloader, kernel, gadget-driver, role-switch, or userspace faults.
  Do not repeatedly request adb or a USB serial session after the user reports
  that the device never enumerates.
- Empty pstore does not locate the failure. Before reading it as evidence, run
  the ramoops triage in order:
  1. `CONFIG_PSTORE_RAM=y` in the *resolved* config (kconfig silently drops
     options; check `out/.config`, not the fragment) AND the `ramoops` DT node
     present in the *baked* DTB — verify the node directly, never assume the
     source `.dtsi` inclusion chain survived the build. Confirm the node with a
     raw FDT token walk: the struct block holds `BEGIN_NODE(0x1)` + name bytes,
     `END_NODE(0x2)`, `PROP(0x3)` with prop length/offset/value, so find the
     `ramoops` BEGIN_NODE offset and read its `reg` (compare against the source
     `.dtsi`'s `<0x88F... 0x400000>`-style values), `compatible`
     (`"ramoops","removed-dma-pool"`), `console-size`/`record-size`/
     `pmsg-size`/`max-reason`. The DT node's `status` must be `okay`. This
     distinguishes 'region never reserved' from 'kernel registered but
     nothing written'.
  2. The recovery kernel's own ramoops reservation must match the payload's:
     `ramoops` lives at a fixed physical address, and the *recovery* kernel
     (OrangeFox/TWRP) also has to reserve that same address to expose the
     crashed kernel's records. If Fox's `reg` differs, `/sys/fs/pstore` in
     recovery is empty while the data is still physically in RAM — a "region
     mismatch", not proof nothing was logged.
  3. Warm-reboot only: pstore survives a *software* reboot (`reboot recovery`),
     never a power-cycle or battery pull — holding power clears RAM and the
     records are gone permanently. Establish how the device got to recovery
     before concluding 'no crash was recorded'.
  4. An early hang (stuck at logo, nothing logged) often means the kernel died
     before the ramoops platform driver probed, so nothing was ever written;
     empty pstore is then expected, not a pstore bug.
  Recovery may clear or consume records. Kconfig alone does not guarantee logs.

## A freeze is a hang, not a crash — userspace logs won't show it

- logcat carries no kernel state. A kernel deadlock/hard-lockup prints nothing to
  logcat; the stream simply stops mid-line when the device freezes (adb drops).
  Absence of a panic/FATAL in logcat is therefore NOT evidence the kernel was
  fine during a freeze.
- Tell hang from crash by the SHAPE of the tail: a crash ends with a FATAL /
  panic / watchdog-kill line; a hang ends cleanly mid-operation (a UI
  transition, a fork) with no terminating error. A clean cutoff at a specific
  transition = hang, and the only useful follow-up is kernel-side evidence
  (pstore console-ramoops, or live `cat /proc/kmsg` as root at the moment of
  the freeze) — logcat alone cannot advance the diagnosis.
- Reboot-reason lines (bootstat "Canonical boot reason: kernel_panic") carry a
  DATE. Verify it matches the current boot before treating it as evidence — a
  stale reason from an earlier crash cycle is a red herring.
- Userspace crash-loops (e.g. a service dying repeatedly on a SecurityException)
  are noise unless timed exactly to the freeze; correlate their last occurrence
  with the freeze moment before chasing them.

## Verify log provenance

Identify each file by its content, not by the export location. Recovery dmesg
normally describes recovery; pstore and last_kmsg may describe earlier boots.
Check Linux version, command line, init markers, and timing. Generic initramfs,
USB, or device-tree messages are not unique identifiers for the test image.
A recovery gadget error alone does not prove a physical USB fault or a fault in
the experimental image.

## Establish test identity and safety

Record exact image filename, SHA256, CI run/head SHA, kernel source commit,
final .config, donor SHA256, packing tool revision, boot arguments, and method
(fastboot boot versus writing boot through recovery). Compare images using the
same method; a successful RAM boot is not a control for a different install path.
Do not ask for more partition writes without a known-good boot backup, recovery
access, and a clear reason. RAM loading avoids replacing boot but does not prevent
Android userspace from writing storage. Never label an Android-ramdisk boot test
as zero-storage-write.

## First control: original versus repacked donor

Before cross-payload images, compare:

1. Original known-good donor, tested through the chosen boot method.
2. Same donor kernel and ramdisk, repacked through the experimental packer.

Preserve header fields, command line, payload bytes, alignment, and required
trailers/signatures. Host unpack-and-compare checks validate structure and
payload preservation; they do not prove device acceptance or boot.
If only the repacked control fails, inspect packing and image metadata before
changing either kernel or initramfs. Input filenames such as out/kernel are
host packer paths, not boot paths embedded in the image.

Pin the donor URL to a full commit SHA, not a branch: the "known-good"
property belongs to the exact bytes that were booted, and a branch head
drifts under the control. Verify the downloaded donor's SHA256 against the
copy already proven on device before trusting the control. When the control
is produced in CI, embed the host compare (prefix equality, zero tail,
header-field equality) as a hard gate in the same step that builds the
image — a drifted donor or a changed packer then fails the build instead of
shipping a silently unfaithful control artifact.

Donor files pulled from a boot partition (dd images, partition-sized repo
artifacts) usually carry trailing zero padding out to the partition size; a
whole-file diff then reports a spurious size mismatch. Compare the real
prefix instead: with L the repack's length, assert donor[:L] == repacked and
donor[L:] is all zero bytes, and struct-unpack every header field (sizes,
load addresses, page size, os version, cmdline) on both sides. Run this
host compare BEFORE scheduling the on-device control: a non-faithful repack
is a found packing bug that costs no device test; a faithful one leaves
bootloader acceptance of the assembled image as the only open variable.

A donor-payload repack control needs no kernel build — produce it from the
donor image alone (host script or a short CI step in minutes). Reserve full
kernel CI runs for rounds that actually test the kernel.

### The control's usefulness is bounded by its ramdisk

A control built from the donor's **Android** ramdisk and booted RAM-only
(`fastboot boot`) normally stalls at the vendor logo: Android's init expects the
real `/system`, `/vendor`, `/data` partitions and cannot start from a RAM-only
image. A logo-hang from such a control is therefore expected and does NOT
implicate the packer, the kernel, or the DTB — do not treat it as a packing
failure or reopen the packer because of it. Only a control whose ramdisk
actually runs on the tested boot path can fail in a way that carries signal.

## Getting a console at all

Any serial/USB-console observation requires a ramdisk that brings the gadget up
(e.g. a debug initramfs that binds g_serial or configfs-ACM). An Android ramdisk
exposes no such console, so a missing COM port after booting a donor-control
image is not evidence about the kernel — test the gadget-bearing image instead.
On the host: Windows 10/11 enumerates the CDC-ACM gadget natively (usbser.sys);
open it with PuTTY in Serial mode (line `COM<n>`, speed 115200, 8N1) or
`mode COM<n> baud=115200` from cmd. The absence of any port after booting the
gadget image is itself the diagnostic — it means the kernel never reached USB
controller/gadget init, so the fault is at or before USB bring-up, not in
userspace.

## Then compare one payload at a time

- New kernel + donor Android ramdisk: success proves that combination boots.
  Failure implicates that pairing, not necessarily a defective kernel; Android
  can depend on matching modules, policies, firmware, and vendor interfaces.
- Donor kernel + new initramfs: success proves that combination reaches the
  observed milestone. Failure implicates that pairing, not specifically /init;
  check initramfs format/compression, executable/interpreter support, command
  line, bootloader-added skip_initramfs, configuration, and watchdog handling.
- New kernel + new initramfs: compare against the above controls, keeping all
  other verified fields identical.

Both cross-combinations failing does not establish two independent faults.
They share packing and boot metadata, and each has compatibility requirements.
Multiple appended Qualcomm DTBs may be valid; order alone is not proof of
wrong board selection. Verify actual selection behavior and identifiers.

Keep init scripts byte-identical when introducing comparison images. Pin all
inputs; rebuilding an unchanged script does not ensure identical image bytes.
For a no-console custom initramfs, define an observable success signal supported
by verified hardware/drivers before asking for device tests. Do not count the
unchanged vendor logo as that signal.

## Investigate PID 1 carefully

- A failed exec redirection in a non-interactive shell can terminate PID 1, but
  test the actual BusyBox ash behavior and console-open failure before claiming
  root cause. Removing a redirect is a hypothesis test, not a confirmed fix.
- Verify /init mode, shebang interpreter, ELF architecture, and loader/library
  availability. A static interpreter removes dynamic-loader dependencies but
  cannot remove every possible execution failure.
- A failed exec /sbin/init can terminate a non-interactive shell; do not assume
  code after exec is always a reachable fallback. Verify shell semantics.
- Keep PID 1 alive deliberately; avoid an EOF-driven shell respawn busy loop.
- Treat watchdog servicing requirements as kernel/platform-specific; never
  disable safety mechanisms or add random delays without evidence.

## A non-panic freeze leaves pstore empty — read last_kmsg instead

- `kmsg_dump` fires only on a panic/crash or a reboot that goes through the
  dump callback. A pure userspace deadlock (system_server hung at unlock) fires
  nothing, so the ramoops region stays clean even when the driver probed
  correctly — EMPTY PSTORE ON A HANG IS EXPECTED, not a pstore bug.
- Capture the previous boot's kernel log via `/proc/last_kmsg` (needs
  `CONFIG_PSTORE_LAST_KMSG=y`): it survives a plain reboot and holds
  hung-task / soft-lockup / blocked-stack traces from the frozen boot. This is
  the cheapest kernel evidence for a hang and should be the first ask after a
  freeze, before re-verifying ramoops.

## "Factory reset" after a hang is FBE, not a wipe

- When a device hangs at the lockscreen and afterwards apps look freshly reset
  but media (DCIM) still shows and files survive in recovery, it is FBE, not a
  wipe: DE-storage (media) is unencrypted, while CE-storage
  (`/data/user/0/<pkg>`, app data) stays encrypted until the lockscreen
  credential unwraps it. An interrupted unlock handshake leaves CE wrapped →
  apps appear reset though the bytes remain.
- A boot.img is RAM-loaded and physically cannot erase `/data` — never reformat
  or reflash the ROM over this symptom; the hang is the cause, and reformatting
  is the only thing that actually costs the data. Steer the user away from the
  reflex of a full-ROM reflash, and state that the flash of boot.img cannot
  have wiped userdata.

## Boots-then-freezes-at-a-transition on a backported kernel

- When a device boots then freezes at a specific transition (e.g. lockscreen
  unlock) on a heavily-backported kernel, suspect the recently-added CPU-
  scheduler and vm-reclaim layers first (CFS/load-balancer changes, MGLRU /
  lruvec locking): the freeze hits exactly when a burst of app forks collides
  with reclaim, which is where a load-balancer or lruvec lock bug wedges.
- Bisect stacked backports by REMOVING THEM ONE AT A TIME, keeping the known-
  good fixes (e.g. the sysctl-array sentinel) in EVERY test build, and pushing
  each removal branch to CI. A branch is a "removed-X" build (work = base minus
  backport X). If removing backport X still freezes → X is not the culprit. If
  the unlock stops hanging → X isolates it. Once a backport is exonerated, fold
  it back in and never rebuild it. After ruling out all the recent backports,
  the freeze lives in the common core (base + sentinel) or in userspace — stop
  bisecting kernel deltas there.
- Verify the removal branch is actually clean of the backport's symbols before
  dispatching: grep the defconfig and the touched driver dirs for the backport's
  feature names (and the reverted commits' message strings) — a revert that left
  a dangling Kconfig/defconfig reference will mislead the result.

## Stop condition

When repeated tests produce no new evidence, stop speculative flashing. Inspect
actual artifacts or add a verified observable checkpoint. No new CI run unless
it tests a named hypothesis. Do not compile locally or on the user's device.
