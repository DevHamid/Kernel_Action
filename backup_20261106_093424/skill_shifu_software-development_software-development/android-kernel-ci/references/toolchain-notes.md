# Toolchain, boot.img and initramfs notes

Domain facts for Android kernel CI builds. Each item was verified against a
real tree or artifact; re-verify per device before trusting.

## AOSP prebuilt toolchains (android.googlesource.com)

- Clang: `platform/prebuilts/clang/host/linux-x86/+archive/refs/heads/master/clang-r<REV>.tar.gz`
  (r547379 suits 4.19-era kernels). Extracts flat: `bin/clang`, `bin/ld.lld`.
- GCC 4.9 (tag android-12.1.0_r27):
  `platform/prebuilts/gcc/linux-x86/{aarch64,arm}/...-4.9/+archive/refs/tags/android-12.1.0_r27.tar.gz`.
  Contains binutils (as/ld/ar/nm/objcopy), cpp, and `*-androidkernel-*`
  variants — but NO plain `gcc`. Point CROSS_COMPILE/CROSS_COMPILE_ARM32 at the
  `bin/` prefixes for binutils only.

## Kernel Makefile override semantics

- `CC = clang` (recursive `=`) is overridable ONLY by command-line args;
  `export CC=...` is silently ignored by the kernel build.
- Kconfig runs `$(CC)` during defconfig (CC_VERSION_TEXT; GCC_VERSION /
  CLANG_VERSION via scripts/*-version.sh). A compiler-detection failure here
  presents as Kconfig parse errors (`init/Kconfig:NN: syntax error` / `invalid
  option`) plus `<path>/bin/...-gcc: not found` — treat as "wrong compiler
  selection", not as a Kconfig bug.

## Vendor-tree divergence

- Before adding CONFIG_X, find where X's objects are built in the vendor
  Makefiles. Example shape of the trap: upstream builds `nf_log.o` unconditionally
  in netfilter-objs; a vendor tree may gate it behind CONFIG_DEBUG_KERNEL.
  Enabling `CONFIG_NETFILTER_XT_TARGET_LOG` then compiles nf_log_ipv4/ipv6 and
  xt_LOG (the consumers) without the core -> `ld.lld: error: undefined symbol:
  nf_log_*` at final vmlinux link. Fix by dropping the consumer option (or
  enabling the gate too, if safe on a perf defconfig).
- Expect benign defconfig warnings when appending a fragment: `override:
  reassigning to symbol X` just means the vendor defconfig already set X.

## Boot image payloads (Qualcomm-style, header v0/v1)

- Phone kernels ship as `Image.gz-dtb`: gzip Image with the DTB APPENDED.
  Confirm by byte-inspection: gzip magic `1f8b` at kernel start, `d00dfeed`
  (DTB) at its tail. A plain Image silently breaks repack and boot.
- A Magisk-patched donor ramdisk is fine as a header/cmdline donor — reuse
  header fields only, never its ramdisk contents.
- Repack gate: pack -> unpack -> kernel and ramdisk must be SHA-identical.
- Multi-word cmdline strings fragment under shell `$(...)` expansion; drive
  mkbootimg from Python with an argv list (shlex.split the donor's format
  output), never eval.

## Initramfs rules

- CONFIG_DEVTMPFS_MOUNT does NOT apply to initramfs boots (drivers/base/Kconfig
  help says so) — mount devtmpfs explicitly in /init.
- PID 1 must never exit: exiting the last shell panics the kernel ("Attempted
  to kill init!"). Wrap the final shell in `while true; do /bin/sh; done`.
- USB serial console: CONFIG_USB_G_SERIAL=y auto-creates /dev/ttyGS0. Do NOT
  also set CONFIG_USB_ETH — legacy precomposed gadgets form a single-select
  Kconfig choice and kconfig silently drops one. configfs functions (ACM/NCM/
  RNDIS) sit outside that choice and compose freely.
- Alpine `busybox-static` .apk is a plain tar.gz: `tar -xzf` yields
  `bin/busybox.static`; verify arch with readelf on x86 runners, never exec it.
- A rootfs whose own busybox is dynamic (musl) needs the init shebang to point
  at the injected STATIC binary (`#!/bin/busybox-static sh`) so early boot
  never depends on loader paths.
