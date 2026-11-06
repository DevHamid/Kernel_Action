---
name: wayne-modem-bringup
description: "Use for wayne sdm660 modem bring-up: rmtfs, PIL, QMI/QRTR."
version: 1.0.0
author: shifu
license: MIT
metadata:
  hermes:
    tags: [wayne, sdm660, modem, rmtfs, pil, qmi, qrtr, openwrt]
    related_skills: [wayne-kernel-ci, android-kernel-ci]
---

## When to Use
Task touches the modem on wayne: rmtfs/sharedmem bind failures, booting the modem (PIL), firmware file placement, QMI/QRTR control plane, or the kernel branch/pin behind the wayne-openwrt build.

# wayne modem bring-up (Mi 6X / sdm660 / OpenWrt)

## Branch and driver state (verified 2026-11-05)
- Live kernel branch: `DevHamid/LKGeek_sdm660@fix-ksu-sugrant`. `build-all-rekernel` is stale (head 2026-09-25); `devhamid-remastered` abandoned. Check `wayne-openwrt/.github/workflows/build.yml`'s clone pin against the live branch before trusting a CI build — the pin drifted once.
- `fix-ksu-sugrant` defconfig: MGLRU OFF (`CONFIG_LRU_GEN` not set), `MQ_IOSCHED_ADIOS=y`, `MQ_IOSCHED_DEADLINE` unset.

## rmtfs node: no DTS patch needed
Both branches' `drivers/uio/msm_sharedmem/msm_sharedmem.c` are byte-identical and take the dynamic-alloc path at line 153 (`reg = <0x0 0x200000>` -> `dma_alloc_coherent`, SZ_4K guards). The `qcom,rmtfs_sharedmem@0` node (sdm660.dtsi) binds as-is. A stale local checkout once showed the old driver rejecting `reg=0` with `-EINVAL` — read the remote HEAD, never a remembered checkout.

## The boot path is subsystem_get — nothing else
`pil-q6v5-mss.c`'s `pil_subsys_init()` registers subsys name `"modem"` with `.powerup = modem_powerup()`, which ends in `return pil_boot(&drv->q6->desc)`. `subsystem_get("modem")` therefore runs the entire MBA+modem boot. The whole PIL stack and subsystem_restart are built-in (=y).
- **Never build a boot module around `pil_mss_reset_load_mba()`** — it is unexported (pil-q6v5-mss.c has zero EXPORT_SYMBOL, so a .ko calling it dies at insmod with "Unknown symbol") and it is the RAMDUMP path only (line 198, inside `modem_ramdump`).
- Exported and module-safe: `subsystem_get`, `subsystem_get_with_fwname`, `subsystem_set_fwname`, `subsystem_put`, `subsystem_restart`, `pil_boot`, `pil_shutdown`, `pil_desc_init`.
- Inside `pil_boot()` the MBA image is loaded by `pil-msa.c:656-670` (`request_firmware("mba.mbn")`, or `"mba.b00"` for non-elf images); the modem image follows as `modem.mdt` + `modem.bNN` (peripheral-loader.c `"%s.mdt"` :1252 / `"%s.b%02d"` :1024).
- `subsystem_restart()` is NOT a cold-boot substitute: `__subsystem_restart_dev()` requires `SUBSYS_ONLINE` and WARNs otherwise. SSR recovery only.
- Firmware naming (verified): the loader requests lowercase `mba.mbn` (fixed name — `subsystem_set_fwname` does NOT affect it), `modem.mdt`, `modem.bNN` from `/lib/firmware`. Android ships `MBA.MBN`/`MODEM.MDT` uppercase. Symlink all three lowercase into the firmware path, or set fwname to `MODEM` (basename, no extension) before the first boot. The firmware loader only searches `/lib/firmware`, so a ro VFAT mount elsewhere is invisible to it without symlinks.
- sysfs: `device_create(NULL, ...)` puts attrs under `/sys/devices/virtual/`, NOT `/sys/class/` — create a class (`class_create` + `device_create(class, ...)`) if the docs promise `/sys/class/modem-boot/...`.
- `pil-q6v5-mss: No pas_id found.` is dev_info, non-fatal (non-PAS fallback). Don't chase it.

## Boot order — do not swap
kernel up -> mount modem VFAT (firmware visible) -> rmtfs daemon answering -> `subsystem_get("modem")`. Boot the modem before rmtfs answers and you get the MBA hand-off followed by a watchdog bite, which looks like a firmware fault and isn't one.

## Userspace: openwrt-packages/ (in-p repo, prebuilt .ipk set)
The wayne-openwrt CI extracts a prebuilt ImmortalWrt 21.02.7 armvirt-64 rootfs and overlays into it — there is NO OpenWrt buildroot/SDK in CI. So package builds happen outside CI; the repo ships recipes + the .ipk set.
- Cross-version rootfs compatibility (23.05 armsr, 24.10) and the CI pattern
  for testing a newer rootfs against the same vendor kernel: see
  `references/openwrt-rootfs-versions.md`.
- Feed base: `https://downloads.immortalwrt.org/releases/21.02.7/packages/aarch64_cortex-a53/` (target arch = aarch64_cortex-a53).
- 23.05+ renamed the target: `armvirt` is GONE; it is `armsr/armv8` (kernel 5.15), packages `aarch64_generic` (+ `aarch64_cortex-a53` feed still exists). 24.10 = kernel 6.6. Rootfs tar still ships: `immortalwrt-23.05.4-armsr-armv8-rootfs.tar.gz`. A rootfs tar is userland-only (no kernel), so it assembles with our 4.19 kernel exactly like 21.02.
- CI test: `test-rootfs-2305` job (needs: build) reuses the main build's compiled `Image.gz-dtb` (now in the artifact) and assembles the 23.05.4 armsr rootfs with the identical overlay+packer path; artifact `wayne-openwrt-2305` ships `openwrt-2305-boot.img` (+ `openwrt-initramfs.cpio.gz`). Real on-device boot gate cannot run in GitHub Actions (no sdm660 QEMU) — flash the 23.05 img and boot it.
- From feed: `libqmi` (1.30.8, has QRTR baked in — Depends libqrtr-glib), `qmi-utils`, `libqrtr-glib`, `libmbim`, `glib2`, `libudev-zero` (drop-in libudev).
- Custom: raw `libqrtr` (linux-msm/qrtr @ 29e36ae, meson) + `rmtfs` (linux-msm/rmtfs @ b30a3eb). rmtfs links `-lqrtr -ludev -lpthread` and uses raw libqrtr.h — the feed's libqrtr-glib does NOT satisfy it.
- rmtfs flags (`rmtfs.c` getopt `o:S:Prsv`): use `-r -o /var/lib/rmtfs`. Do NOT use `-s` (calls rproc_init, exits — this kernel boots via PIL/subsystem_get, not remoteproc). Do NOT pass the uio node as argv.
- rmtfs opens `/dev/qcom_rmtfs_uio1` HARDCODED (rmtfs_mem_open_uio) and reads udev sysattrs `maps/map0/{addr,size}`. Our msm_sharedmem makes `/dev/uioN` named `rmtfs` — the init script must create the symlink `/dev/qcom_rmtfs_uio1 -> /dev/uioN` before starting the daemon.
