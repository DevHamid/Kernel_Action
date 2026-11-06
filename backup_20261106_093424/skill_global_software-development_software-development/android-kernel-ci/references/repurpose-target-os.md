# Repurposing a phone into a Linux server/router: choosing the userspace

Use when the device is being repurposed (router, pocket modem, container host)
rather than run as Android. The kernel/CI mechanics stay in the parent skill;
this file is the userspace and roadmap decisions.

## Pick the target to match what the user already runs

Match the distro **and version line** the user has already proven on their own
hardware. If they run OpenWrt 24.10 on another aarch64 board, the phone should
run the same line, not a newer or older one — that deletes compatibility doubt
and lets their existing workflow (LuCI, dockerman) carry over 1:1. Do not pick a
rootfs from memory of "latest"; verify the current release and its package feed.

## Match the userspace generation to the kernel generation

A rootfs line carries kernel modules (`kmod-*`) built for one kernel ABI. Every
module embeds a `vermagic` string (kernel version + config hash) and refuses to
load into a mismatched kernel. So a userspace whose kmods target 5.15/6.6 will
not load its WiFi/storage modules into a 4.19 vendor kernel. Either keep the
generations aligned (an 18.06/19.07-era userspace with a 4.x kernel; 23.05/24.10
with a 5.15/6.6 kernel) or build the needed drivers into the kernel (`=y`, not
`=m`). This is the real reason a Docker-capable userspace (23.05+) cannot sit on
an old vendor kernel: Docker needs a modern rootfs, and a modern rootfs needs a
modern kernel. Pick the kernel to match the userspace generation you need — not
the other way around.

### The version coupling is the KMODS, not the userspace — so a newer rootfs CAN ride an older kernel

Do not read the paragraph above as a hard "userspace version must equal kernel
version" wall. In a **hybrid** build (vendor kernel + borrowed generic rootfs,
where OpenWrt never builds the kernel — see the parent skill's boot-image path)
the ONLY kernel-version-bound part is `kmod-*`/vermagic: pure-userspace packages
(musl, busybox, `uci`, dnsmasq, hostapd, the web UI) are engine-agnostic and run
fine on an older kernel. That is why a 21.02 rootfs demonstrably runs on a 4.19
vendor kernel with zero kmod conflicts, and why going NEWER is a ladder of small
asks rather than one wall: each step mostly asks for a newer nftables/netlink
capability, and if you use no kmods (drivers built into the vendor kernel) the
version gap is largely in userspace, shimmable there. Newer userspace buys newer
APPS, not newer drivers — the vendor kernel already carries the drivers.

- Release-number tables (19.07->4.14, 21.02->5.4, 23.05->5.15, 24.10->6.6) are
  the release's DEFAULT/tested kernel, not a hard requirement. State them as a
  default, not a law, when answering "can I use kernel X with OpenWrt Y?".
- `ImageBuilder` reuses the release's PREBUILT kernel — you cannot change the
  kernel version with it at all. Only the full buildroot can, and there you own
  every patch and driver. Neither is how a hybrid (borrowed kernel + borrowed
  rootfs) works; that path packs them yourself.

## Rootfs target: generic real-hardware armv8, not the QEMU virt target

The community recipe for a custom-kernel phone is a **device-specific kernel**
plus a **generic real-hardware armv8 rootfs** — commonly the ImmortalWrt/OpenWrt
`rockchip/armv8` target. The "rockchip" string is only *which generic rootfs was
borrowed*; it is not the SoC, and it appears verbatim on Qualcomm MSM phones
paired with a postmarketOS Qualcomm kernel. That target is built for real block
devices, real network drivers, and real serial, so it does not hunt for virtio
hardware a phone lacks.

QEMU target rootfs (e.g. `armvirt/64`, now `armsr`) is built for `-M virt` and
expects virtio devices. A **RAM-only initramfs** of any arm64 rootfs still boots
on real hardware, because the kernel you supply provides the real drivers — the
virtio gap only bites once the rootfs mounts a disk or brings up its own network.
So armvirt can reach a booting userspace for a quick test, but switch to a
generic real-hardware armv8 rootfs before any hardware-dependent work (real eMMC
rootfs, USB gadget networking, modem).

## Qualcomm sdm660 mainline path (wayne-class devices)

For a Snapdragon 660 device, a close-to-mainline kernel is the better base than
an Android vendor kernel for a non-Android userspace:
`linux-postmarketos-qcom-sdm660` (postmarketOS, versioned by pmOS release), the
`sdm660-mainline` GitHub org (`sdm660-mainline/linux`, `u-boot`, `lk2nd`), and
the pmOS wiki status page. Reported working on SDM660/630/636: storage, WiFi,
USB (partial), display, pinctrl, I2C, SPI, thermal. The pmOS kernel is built to
run real distros; the vendor kernel is built to run Android. Use `lk2nd` (their
Qualcomm secondary bootloader) if the stock bootloader needs help.

## OpenWrt + Docker is real (do not claim otherwise)

Docker works on OpenWrt **aarch64 from ~23.05 / 24.10**: the feed carries
`dockerd`, `containerd`, `runc`, and `luci-app-dockerman`. dockerd is a Go
binary and runs on musl; the old "musl can't run Docker" objection is wrong for
modern OpenWrt. Older rootfs lines (e.g. 21.02) predate solid Docker support —
that is a version gap, not an architectural wall.

Container requirements, in dependency order:

1. cgroups + namespaces (kernel config) — the `NAMESPACES`/`CGROUP*` fragment.
2. overlayfs (kernel config) — `CONFIG_OVERLAY_FS`.
3. **writable persistent storage** — a RAM-only rootfs cannot hold an image
   store; this forces a real rootfs on eMMC/USB. Usually the true blocker.
4. the runtime packages — from the matching feed.

### Decoding a container-feasibility probe

Report the REAL blocker count, not the probe's `fatal=N`. Group the failures by
root cause first; a multi-fatal probe typically counts one cause twice and one
userspace gap as kernel evidence.

| Signal | Meaning | Verdict weight |
|---|---|---|
| memory controller absent from `/proc/cgroups` | `CONFIG_MEMCG` off — dockerd refuses to start ("kernel does not support memory limit capabilities") | **hard blocker** |
| `cgroup memory mount failed` | same root cause as above, not a second blocker | duplicate |
| `CONFIG_SECCOMP` off (`Seccomp: 0`) | dockerd only runs with `--security-opt seccomp=unconfined`; no syscall sandbox | DEGRADED |
| `br_netfilter` absent | published-port DNAT across docker0 depends on the userland proxy (`--userland-proxy=true`, the default) | DEGRADED |
| `unshare -n` → `not found`, `rc=127` | missing busybox applet, NOT a kernel gap — confirm with the matching `CONFIG_NET_NS=y` and a passing net-namespace test | false negative |
| overlayfs mount + copy-up write, veth pair, bridge, MASQUERADE, freezer/pids/devices controllers | PASS means the config fragment actually landed and works | positive proof |

Ceiling rule: MEMCG, seccomp and br_netfilter are three separate symbols. A
vendor kernel that withholds all three caps out at DEGRADED — never sell a
MEMCG-only fix as "Docker support". For a vendor-kernel v1, recommend the native
path (procd/init services, no container runtime) and put real Docker on the
mainline track where these symbols are clean. Also note a vendor `mm/` that will
not compile with `CONFIG_MEMCG` is a known failure mode: bisect the build to
prove which change kept it green before proposing to fight it.

## USB gadget network: the link is Layer 2, not a service

Creating a configfs gadget (`rndis.usb0`, `ecm.usb0`) makes the interface appear
and the host show a connected adapter. That is ALL it does. Nothing assigns an
address, runs DHCP, or puts the interface in a firewall zone.

- OpenWrt's stock `/etc/config/network` bridges only the board ethernet
  (`eth0`); an orphaned `usb0` gets no IP, no dnsmasq, no zone — so the host
  pings nothing and the web UI (LuCI) is unreachable while the link looks fine.
- Fix it in the IMAGE, not by hand at runtime: ship
  `/etc/uci-defaults/90-usb0-lan` doing
  `uci add_list network.lan.ifname='usb0'` then `uci commit network`.
  uci-defaults runs once on first boot, before services need the interface.
  Prefer it over overwriting `/etc/config/network`, which discards the distro's
  own defaults and silently drops the board's ethernet definition.
- **When assigning a custom static LAN IP (e.g. `192.168.1.100`), check DHCP pool collisions.** Stock OpenWrt default DHCP start is `.100`, which collides with a static IP `.100`. Always shift the DHCP pool start (e.g. to `.110`) in `uci-defaults` alongside setting the static IP — the uci-defaults script must set both the static IP and the DHCP range in one pass.
- Decide the role before writing that script: `lan` when the host reaches the
  device's web UI/SSH; `wan` (or a separate interface with its own dnsmasq
  range) when the device is sharing an uplink to the host.
- Verify from the HOST side: address present, `ping` the gateway, then the port
  (LuCI 80, SSH 22). Interface-up is not the test — an interface can be up with
  no route and look perfectly healthy in `ip link`.

## Modem / mobile data: hard, not impossible

An **Android vendor kernel already carries the Qualcomm modem stack**
(`msm_ipc_router`, `qrtr`, PIL/`q6v5` firmware loader, `rmnet`, `qmi_wwan`), so
the kernel side is not the wall. The chain to make it work:

1. Modem firmware blobs (`NON-HLOS.bin`, `mba.mbn`, `modem.mbn`) — usually still
   present in the phone's `/firmware`/`modem` partition, reusable.
2. PIL firmware load at boot (push firmware to the modem DSP).
3. QMI transport up over IPC Router (`qrtr`) via GLINK/SMEM.
4. Userspace QMI stack: `libqmi`, `uqmi`, `ModemManager` (in the OpenWrt feed).
5. Data path via `rmnet` / QMI WWAN.

Real risks: vendor modem drivers may be gated behind Android-specific configs;
the loader may expect Android's partition/`by-name` layout; a QEMU-target rootfs
is modem-blind. Treat as research (~low odds), not fantasy. A phone battery is
an asset here — a pocket modem with a built-in UPS and no power cable.

## Persistent rootfs: pick the storage before designing M3

A phone's USB port is a **device** (peripheral) port by default; using a USB
stick as storage requires switching the DWC3 controller to **host/OTG** mode.
Rank the options by risk to the user's data:

| Option | Storage | Risk | Docker-capable |
|---|---|---|---|
| USB-OTG stick rootfs | external | none to the phone | yes (size of the stick) |
| spare eMMC partition | internal | destructive if it holds Android data | yes |
| internal rootfs + USB as data disk | mixed | low | yes (images on USB) |
| RAM-only overlay | RAM | none | no (lost on reboot) |

`/sys/class/udc/` non-empty proves device/gadget mode works. Reading a USB disk
requires ALL of: `CONFIG_EXTCON=y` (mandatory — `USB_DWC3_DUAL_ROLE` has
`depends on EXTCON=y`), a PMIC extcon driver (`EXTCON_QCOM_SPMI_MISC` for
Qualcomm PM660-class PMICs), `USB_DWC3_DUAL_ROLE=y`, `USB_OTG=y`,
`USB_XHCI_HCD=y`, `USB_STORAGE=y`, `SCSI=y`, `BLK_DEV_SD=y`. A USB-A port on
USB3 can bind a hub with no host-mode config — which is why "the port powers
USB sticks" proves nothing; the discriminator is whether `/dev/sda` appears
when a stick is inserted.

A deferred-probe failure on the PD/TypeC PHY (`usbpd_create failed: -517`) means
role switching may still not work even with EXTCON enabled — test read-only on a
RAM boot first, and fall back to the eMMC route or the pmOS mainline kernel
(which carries full TypeC/extcon support) if it fails.

## Milestone framing

The gate order is fixed and must be respected when answering "is X possible?":

```
M1  kernel boots, serial console reachable        <- the gate; nothing downstream counts
M2  userspace boots (the chosen target line)
M3  persistent rootfs on eMMC (flash, not RAM)
    A: network (USB ethernet / Wi-Fi) -> Docker + dockerman
    B: modem (firmware -> PIL -> QMI -> rmnet) -> mobile data
```

Both A and B need M1–M3. A question about Docker or the modem is downstream of
the boot test — answer the boot question first, then the feasibility question.
Do not let a roadmap discussion substitute for running the next on-device test.
