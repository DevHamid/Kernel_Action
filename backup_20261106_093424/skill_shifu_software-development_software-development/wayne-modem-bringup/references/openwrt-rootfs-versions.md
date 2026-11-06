# ImmortalWrt rootfs versions for wayne (sdm660) — compatibility matrix

The wayne-openwrt CI does NOT use a buildroot/SDK. It downloads a prebuilt
rootfs tarball, overlays repo files into it, and packs it with the vendor
kernel into a boot.img. A rootfs tarball is userland-only (no kernel), so it
ASSEMBLES with any kernel — but whether it RUNS on a given kernel is a separate
question: userland expects newer kernel features, and any kmods shipped in a
rootfs image only match that release's own kernel.

## Version -> target -> kernel mapping (verified)
| Release | Target | Kernel in that release | Packages arch |
|---|---|---|---|---|
| 21.02.7 | armvirt/64 | 5.4 (contemporary with our 4.19 vendor kernel) | aarch64_cortex-a53 |
| 23.05.4 | armsr/armv8 | 5.15 | aarch64_generic |
| 24.10.1 | armsr/armv8 | 6.6 | aarch64_generic |

- The `armvirt` target was RENAMED `armsr` around 23.05 (openwrt commit
  `7198185`). A 23.05+ armvirt URL 404s — use `targets/armsr/armv8/`. Rootfs
  file: `immortalwrt-<ver>-armsr-armv8-rootfs.tar.gz`.
- 21.02/armvirt uses `aarch64_cortex-a53` packages; 23.05/armsr uses
  `aarch64_generic`. Feed base:
  `https://downloads.immortalwrt.org/releases/<ver>/packages/<arch>/packages/`.
- 24.10 is kernel 6.6 — the far side of the compatibility gap. Bumping the
  vendor kernel is the real prerequisite for 24/25, not the packaging format
  (apk vs opkg). apk migration is irrelevant here because we extract a rootfs
  and never run opkg on-device against a repo.

## Testing a different rootfs version against the same vendor kernel
GitHub Actions cannot boot sdm660 (no QEMU target), so a boot test = produce
a flashable image + assert faithful assembly; the real boot gate happens
on-device. To make the test honest (only variable = rootfs):
1. Ship the compiled kernel in the main build's artifact
   (`kernel/out/arch/arm64/boot/Image.gz-dtb`, add to upload-artifact path).
2. A dependent job (`needs: build`) downloads the artifact, pulls the target
   release's rootfs tarball, and assembles the initramfs with the IDENTICAL
   overlay + packer steps as the 21.02 build (same overlay-openwrt/init,
   usb-gadget, uci-defaults, burnin-guard, screen/m6/m7 scripts).
3. Pack with the same donor boot header + run the same `check-pack.py`
   faithfulness gate, upload as a separate artifact.

## Cross-version overlay pitfalls (learned flashing 23.05 — apply to any bump)
- Serial console: the configfs acm gadget creates `/dev/ttyGS0`, but login is
  only spawned if an inittab line references it. Stock rootfs inittab files
  (21.02 AND 23.05) ship no `ttyGS0` line. The main build appends
  `echo 'ttyGS0::askfirst:/usr/libexec/login.sh' >> etc/inittab`; a test/other
  build that omits this yields a boot that works (screen sleeps, userland
  alive) but picocom opens the port and gets no prompt. Always replicate the
  inittab append.
- UCI network model changed at 23.05: `network.lan.ifname` (list) is
  deprecated/removed in favor of the device model (`network.lan.device` +
  `network.device`, or `ports=` on a bridge). On 23.05+ an `add_list
  network.lan.ifname=usb0` is SILENTLY ignored — usb0 never joins br-lan, so
  no DHCP and no dropbear listener ("no ssh"). Detect the release
  (`grep "release='23\.05" /etc/openwrt_release`) and branch: 23.05+/24.10
  use `network.lan.device=br-lan` + `add_list network.lan.ports=usb0`;
  21.02 keeps `ifname`. A version-aware uci-defaults script handles both.

## Serving a boot image as a public download
GitHub Actions artifacts require auth (curl -H "Authorization: token ...").
To hand the user a token-free link, push the boot image (and initramfs) to a
`downloads` branch of the repo — `raw.githubusercontent.com` serves them with no
auth. Verify with a `curl -sSI` returning 200 and compare the sha256 to the
artifact before publishing the link.

Decision (user, 2026-11): stay on the prebuilt-extract approach; do NOT adopt
buildroot. It does not solve the real constraint (old vendor kernel) and adds
2-6h builds. Revisit buildroot only to ship a flashable image for others or
when a kmod cannot be packaged otherwise.
