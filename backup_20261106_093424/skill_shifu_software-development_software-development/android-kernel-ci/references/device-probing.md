# Live-device sysfs probing (USB role, power, gadget) over SSH/serial

Class: probing a running Android/OpenWrt phone over dropbear SSH or tty console
(USB role switches, regulators, power_supply, gadget configfs). Rules here were
earned on-device; they apply to any single-UDC gadget device.

## Probe delivery: files, never pasted blocks

- Build every probe as a FILE on the PC, then pipe it over:
  `curl -4 -s <raw-url> -o /tmp/p.sh && cat /tmp/p.sh | ssh root@<ip> "cat > /root/p.sh && chmod +x /root/p.sh && echo LANDED"`.
  dropbear has no sftp-server, so scp fails; `cat | ssh "cat > dest"` is the pipe.
- NEVER give the user a multi-line `( ... ) &` block to paste — the ash shell
  submits it line-by-line and it breaks. Multi-line = file. Short and long
  SINGLE lines are safe to paste.
- Keep probes in the project repo `scripts/` so each new revision is one raw-URL
  curl away; commit+push before asking the user to fetch.

## Host-mode (role-switch) probes: design for the connection to die

- Flipping a single-UDC device to host tears down the configfs gadget — SSH AND
  the ttyGS0 serial console are the same gadget, so both die. There is no live
  window: the ONLY observation channel is a detached background process writing
  to a log file (`trap '' HUP INT TERM`, `... >> $LOG 2>&1`, `sync`).
- ALWAYS pair the main body with an INDEPENDENT watchdog subshell that
  unconditionally restores peripheral + rebinds the UDC after HOLD+20s. A main
  body that hangs on a sysfs read never reaches its own rollback line and
  strands the phone until reboot.
- NEVER touch the USB cable during a host-mode test — the cable is irrelevant;
  the phone's own CPU runs the probe. Unplugging mid-probe is the #1 way a
  survivable test becomes a reboot.
- Bound every sysfs read (`timeout 3 cat ...` when busybox has timeout) and
  never run `find /sys` inside a host-mode probe — deep sysfs walks hang while
  dwc3 is mid-transition, and the hang is what defeats the built-in rollback.
- Detached daemons that `trap '' HUP INT TERM` (to survive a closed session)
  also IGNORE a plain `kill` from their own control script — SIGTERM is trapped.
  Use `kill -9` gated on a `/proc/<pid>/cmdline` check (guards against pid
  reuse), or the "stop/on" command silently fails and the daemon keeps
  undoing the user's manual action.
- Write the pidfile with `$!` (the backgrounded subshell's pid), NEVER `$$` —
  inside a `( ... ) &` subshell `$$` is still the PARENT shell's pid, which
  exits immediately, so the pidfile points at a dead process and every
  kill/status check is wrong. Both bugs (trapped SIGTERM + dead pid) look
  identical from the user's side: "my `on`/`stop` does nothing".
- Recovery when both links are dead: force reboot (long-press power ~12s),
  replug, wait — the boot init service (rc.d S*-usb-gadget) rebinds the gadget
  automatically. SSH comes back on its own; no reflashing needed.

## Reading the power/role chain (Qualcomm phones)

- `/sys/class/regulator/regulator.*/state` files are 0444 — NOT writable from
  userspace even as root. A userspace force-enable of a VBUS/OTG regulator is a
  dead end; fix must be in-kernel (driver/DT) or via a writable gate.
- Writable gates live elsewhere: check `/sys/module/<driver>/parameters/` for
  rw module params (e.g. the PD policy engine's software-VBUS control) before
  concluding a kernel patch is needed — and TEST the gate: a param that accepts
  a write but changes nothing in extcon/regulator state is not a lever.
- Role evidence hierarchy: `extcon*/state` (USB vs USB-HOST per named extcon),
  the role regulator's `state`, `/sys/class/power_supply/*/uevent`
  (TYPEC_POWER_ROLE, TYPEC_MODE, BOOST_CURRENT), and dmesg for actual device
  enumeration. A device seated but never enumerated with zero `new USB device`
  dmesg lines = the port is not sourcing VBUS, not a driver problem.
- xHCI root hubs enumerating (`1-0:1.0`, `usb1/usb2`) while a seated device
  never shows up as `1-1` means the controller switched to host but nobody
  raised the 5V. On Qualcomm dwc3 the OTG 5V boost is enabled ONLY by the
  kernel through the `vbus_dwc3` regulator in `dwc3_otg_start_host()`
  (`devm_regulator_get_optional(dev, "vbus_dwc3")` — NULL silently skips the
  enable). Android masks a missing supply because its userspace USB HAL enables
  the charger's VBUS regulator itself; a non-Android userspace has no such HAL.
  Fix = add the DT phandle the driver looks up (e.g.
  `vbus_dwc3-supply = <&smb2_vbus>;` on the USB node), verified against the
  driver source on the exact branch, not from memory of upstream DTS.
- WIRING A PREVIOUSLY-ABSENT SUPPLY CAN REGRESS HOST MODE, not just fail to
  fix it: with the phandle missing, `regulator_enable()` is skipped (ret=0) and
  the host still comes up; once the supply resolves, the enable actually runs,
  and if the charger refuses it a `if (ret) { ...; return ret; }` placed BEFORE
  `dwc3_host_init()` aborts the whole host bring-up — the xHCI root hubs that
  appeared before now vanish entirely. So read the driver's error handling
  around the enable call before shipping the DT fix: a correct phandle plus a
  fatal-on-error path is a net regression. Make the supply failure NON-FATAL
  (log rc, continue) so host mode always comes up AND you finally see the real
  charger rc; do the same on the disable path (a failed disable that returns
  early skips all host teardown and wedges the next host start).
- A host role that lights xHCI buses but leaves the charger extcon at
  `USB-HOST=0` means the role swap never reached the PMIC/charger — on Android
  a userspace daemon does that notification; on OpenWrt nobody does, so that is
  the gap to bridge in-kernel.
- Read a driver rc as a SENTINEL, not always an errno. A workaround routine that
  loops over a table of settings and gives up returns a fixed `-EINVAL` when it
  exhausts the table — that rc means "every step timed out", NOT "a bad
  argument" and NOT a failed register write. Confirm by reading the routine's
  tail (the `if (i == ARRAY_SIZE(tbl)) { rc = -EINVAL; goto out; }` shape)
  before theorizing about the rc value. The register writes succeeded; the
  analog block never signalled completion.
- When a PMIC VBUS/OTG boost refuses to soft-start — the enable writes
  succeed, but the boost never reports done and the routine exhausts its
  current table — the failure is BELOW the register layer, so stop reading
  rcs and go look at the state machine that gates the boost. On Qualcomm SMB2
  the prime suspect is the Type-C FSM: if the charger believes a SOURCE is
  already attached to us (it reports itself as sink, e.g. `TYPEC_MODE=Source
  attached`), it will not raise its own 5V. Cheap no-rebuild experiments to
  discriminate, in order: read the Type-C class state
  (`ls /sys/class/typec/`; `cat port0/power_role port0/data_role`), and if a
  role-forcing write exists there, force source while a host-mode test runs
  and see whether the seated device finally enumerates. Only a confirmed
  enumeration turns this from hypothesis into a fix ("force PR_SOURCE on
  host-mode entry"); until then it is the next thing to TEST, not a shipped
  answer.

## On-device init automation (screen blanking, guards, watchdogs)

- A one-shot action scheduled for N seconds after boot (`offdelay`-style sysfs
  write) can be silently UNDONE by the relevant driver finishing its late
  bring-up — the write lands first, the driver then re-enables its default.
  Ship a retry/guard loop instead: perform the action, sleep, re-assert,
  forever; the manual override command kills the loop first (see the SIGKILL
  rule above) so the override stays instant.
- Ship such helpers as an rc.d START=99 init script plus the helper file, and
  make the INSTALLER re-copy them on every boot OUTSIDE any install-once
  marker — a marker-gated persistent-rootfs install runs once, so files added
  to the tree AFTER the user first provisioned the partition never reach the
  already-installed device.
- On a procd system (OpenWrt/ImmortalWrt) do NOT background the daemon from an
  init script's `start()` (`/root/helper.sh guard 90 &`): procd reaps the rc
  script's process group the moment `start()` returns, so the guard is killed
  almost immediately and the scheduled action never fires. Use `USE_PROCD=1`
  with `procd_open_instance` / `procd_set_param command <helper> <fg-mode>` /
  `procd_set_param respawn 3600 5 5` — procd supervises AND restarts it. Give
  the helper a FOREGROUND mode (`guardfg`) as well as the detached one.
- A guard that re-asserts an action every R seconds will fight a manual
  override that only acts once: the override is undone on the next tick. Add a
  VETO flag the loop checks each tick (e.g. `/tmp/.screen.on`, on tmpfs so a
  reboot clears it) — the override command drops the flag, the guard keeps the
  overridden state while it exists, and `off`/`stop` clear it. Without this the
  user's manual `on` appears not to work at all.
