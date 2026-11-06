---
name: android-kernel-ci
description: "Use when building Android kernels in CI workflow kits."
version: 0.5.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [android, kernel, ci, github-actions, boot-image, termux]
    related_skills: [github, systematic-debugging]
---

# Android Kernel CI Builds (kit-based)

Build Android device kernels and boot images through GitHub Actions workflows
("kits") that the user clones and pushes from Termux; iterate from CI logs.
All compilation happens on CI runners — never on the user's device, never in
the agent sandbox. Generic CI mechanics live in the `github` skill; the root-
cause method is `systematic-debugging`. Depth lives in three references:
`references/toolchain-notes.md` (toolchains, boot.img payloads, initramfs),
`references/termux-delivery.md` (the user-push delivery loop), and
`references/boot-failure-debugging.md` (CI-green images that fail on device), and
`references/repurpose-target-os.md` (choosing the userspace when the device is
being repurposed into a Linux server/router — includes decoding a container-
feasibility probe and bringing up the USB-gadget LAN), and
`references/device-probing.md` (probing the LIVE device over SSH/serial:
USB role flips, VBUS/power chain, gadget teardown, watchdog rollback probes,
on-device init automation like screen-blanking guards), and
`references/multi-agent-repo-collab.md` (two agents on one shared kernel
repo: Kanban card ownership, commit/push handshake, the bar for what may be
relayed to the other agent, and reporting style), and
`references/github-actions-monitoring.md` (carrying workflows past a blanket
`.*` gitignore — un-ignore each parent dir; monitoring runs via the public
API; concurrency cancel-in-progress semantics), and
`references/kernel-action-build-dispatch.md` (driving a separate "Build
Kernels" kit repo: read the workflow, dispatch with an explicit source-branch
input, poll the run, verify the resolved-config artifact against claimed
tree symbols, and check out a named branch in a shallow clone via FETCH_HEAD),
and
`references/control-build-base-vs-backports.md` (isolating a device bug between
the user's backports and the stock base: pure-stock control branch, and
pushing it as a self-contained orphan commit when the base's history is
shallow-grafted), and
`references/fresh-restart-backport-chain.md` (re-anchoring a backport chain on
a known-good clean base: confirm the real working branch, create the fresh
feature branch, verify origin reachability before deleting, enumerate the full
patch delta, and replay build-infra first then feature backports last), and
`references/wayne-backport-verification.md` (per-task verification commands and
expected evidence for the A1–A7/B1–B7 backport map, including each feature's
real tree location and the dangling-config/absent-code fail states), and
`references/suspend-freeze-isolation.md` (isolating a suspend/wake freeze
between scheduler backports by single-variable Kconfig flips, including the
2×2 matrix, cross-lineage bisect-branch drift, and default-governor
fallback), and
`references/ramoops-pstore-debugging.md` (diagnosing empty pstore /
console-ramoops from the DTS reserved-region/zone sizing math, the
per-commit disposition when a proposed set of upstream pstore fixes is
offered, the missing-`RESERVEDMEM_OF_DECLARE` driver-side cause and its
compatible-collision trap — including the reversed-order and
missing-`record-size` variants — the reserved-region-above-the-RAM-ceiling
cause and its silent-revert history trap, and verifying the fix in the built
DTB via `scripts/inspect-dtb-ramoops.py`), and
`references/kernel-backporting.md` (porting a feature across kernel versions —
including sourcing the patch from the FULL compare when the user names one
commit, since a named commit is usually half a change — and auditing a partial
backport for functional liveness: a backport that compiles is not a backport
that works), and
`references/bootloop-feature-attribution.md` (attributing a bootloop among a
stacked bundle of backports: parallel one-feature-per-branch dispatch instead of
a sequential bisect, the `default y` Kconfig trap, dangling defconfig symbols,
no-op attribution branches, voiding an attribution when the base tree is
structurally incomplete, and verifying the enclosing `#ifdef`/`#else` before
claiming a duplicate definition), and
`references/vendored-submodule-dependencies.md` (a submodule rename is a URL
change and NOT a content update: resolve `.gitmodules` URL vs pinned SHA vs
checked-out dir vs what-the-build-uses, diagnose a broken vendored feature from
the pin-to-upstream delta, edit inside the submodule and bump the pointer in the
parent, and the fork-push `workflow`-scope rejection), and
`references/missing-device-probe.md` (a driver confirmed compiled in but whose
interface never appears: `Kbuild` vs `Makefile` in the same directory, the
Qualcomm driver → platform-glue → subsystem-controller chain, the
`ICNSS_FW_READY` gate that silently skips the driver probe, the
firmware-asymmetry rule (WLAN icnss loads no firmware from disk, but the peer
modem loads `<name>.mdt` + `.bNN` and powerup failure PANICS), DT facts that do
and do not explain a missing node, the QMI service-locator timeout that fails
upstream of the glue, the absence of ANY userspace boot interface
(`subsys_device_fops` has no ioctl, the attrs are read-only, so a missing
userspace trigger means a kernel source patch and a rebuild — not a script),
compiled-out debug prints that make silence look like health, a
`compatible`-mismatched node that makes a config change inert, and the dmesg
table plus the one-paste evidence bundle that separates the causes), and
`references/q6-subsystem-bringup.md` (the full contract for booting the modem
MSS on a non-Android userspace: who calls `modem_powerup()` and why nothing
in-tree does, the four cheap DT checks that can each invalidate a plan, the
TWO mandatory firmware loads in order — `mba.mbn` first via
`pil_mss_reset_load_mba()`, then `modem.mdt` + the full `.bNN` segment set —
the `qcom,pil-self-auth` ops-table swap and the TrustZone question it raises,
and the rule that firmware must be on disk before any trigger patch because
powerup failure panics), and
`references/ota-payload-extraction.md` (turning what the user actually uploads
— an AOSP OTA payload of `*.new.dat.br` + `*.patch.dat` + `*.transfer.list` —
into a raw partition image: the `transfer.list` range-pair grammar where
`nvals` counts VALUES not ranges and the pairs are end-exclusive
DESTINATIONS read sequentially from the source, the two gates that prove the
parse (range sum equals the source file, and a located ext4 superblock maps to
block 0), why the header's block count is not the image size, the filename
byte-scan that answers "is the firmware even in here" before any filesystem
parser is written, and the correction that on sdm660/wayne the modem firmware
lives in the VFAT `modem` partition at `/vendor/firmware_mnt`, NOT in
`vendor.img`).

Supporting scripts: `scripts/simg2img.py` converts an Android **sparse** image
to raw in pure stdlib Python (no `simg2img`, no root) for extracting that
firmware from a vendor image; its CRC32 chunk trap is in §6 of that
reference. `scripts/ota_transfer_list_to_raw.py` converts an **OTA payload**
(`.new.dat.br` + `.transfer.list`) to raw, runs both verification gates
itself, and refuses to guess on an odd-arity line.

**Recognise which of the two shapes you were given before reaching for a
script.** A `.dat.br` + `.transfer.list` + `.patch.dat` triple is an OTA
payload and `simg2img.py` will reject it on the magic check; a bare `.img`
with the `ed26ff3a` magic is a sparse image and the OTA script does not
apply. The extensions both say "image", so the discriminator is the file
list, not the name — and a 0-byte `patch.dat` means a FULL image with
nothing to apply, which is the cheap case.

## When to Use

- User asks to build/flash a kernel or boot image for an Android device via CI.
- A CI kernel build failed and the log must be turned into a fix.
- Don't use for: generic GitHub Actions failures outside kernel builds (github
  skill), or generic debugging discipline (systematic-debugging skill).

## Procedure

1. **Find the device's proven recipe first.** Locate the user's earlier working
   kernel CI repo (Kernel_Action-style) and read every make invocation and
   toolchain step. Mirror it exactly. Completion criterion: every make command
   in the new workflow matches the proven pattern (compiler/linker args,
   CROSS_COMPILE paths, defconfig target, PATH setup).
2. **Verify the kernel tree on the exact branch** before writing anything:
   defconfig path exists, device DTS exists, submodule/symlink deps resolved
   (KernelSU: `drivers/kernelsu` is a symlink into a submodule — check
   `.gitmodules`). Use the git trees API; verify from source, never memory.
3. **Write the kit:** workflow YAML, config fragment, init scripts, pack script,
   README, push commands. Validate locally: PyYAML parse of the workflow,
   `bash -n` on every shell script. When updating an existing kit, patch the
   on-disk files — never regenerate a workflow from remembered content (a
   remembered 180-line YAML drops steps silently, and remembered paths point
   at directories the current repo layout no longer has). Before zipping,
   diff against the previously shipped ZIP: every pre-existing workflow step
   name must survive, and every file you did not intend to touch must hash
   byte-identical. When adapting an existing kit to a new
   device, re-derive the pack script's device-specific asserts (expected
   cmdline prefix, header version, offset sanity) from the NEW donor's
   unpack_bootimg output — never copy them from the old device.
4. **Verify risky steps with real artifacts:** byte-inspect a donor boot.img
   (`unpack_bootimg.py`; confirm gzip magic + trailing DTB magic -> payload is
   Image.gz-dtb, note header version and ramdisk compression), repack round-trip
   until kernel and ramdisk are byte-identical, exec-test static binaries on a
   matching-arch host only.
5. **Deliver by the cheapest push path available.** First check whether the
   agent itself can push: `git remote -v` shows an SSH remote and
   `git ls-remote origin` authenticates → the agent commits, tags, and pushes
   itself, and only the flash/test block goes to the user. The ZIP plus one
   copy-paste Termux push block (see `references/termux-delivery.md`) is the
   fallback for when the agent has no push access. Gate before sending INSIDE
   the built ZIP (or the committed tree, on the agent-push path),
   not the workspace: assert each fix's marker string is present, and hash
   every file you changed OR restored against its expected bytes — a revert
   ships no new marker, so only a byte-hash catches a ZIP built from a stale
   workspace. Zip with each file's real relative path as arcname — flattened
   names (`overlay-debug-init` instead of `overlay-debug/init`) break the
   user's `cp -r tmp/. repo/` overlay: files land outside their directories
   and the user pushes a partial repo. Bump the kit version.
6. **On CI failure:** get the full log, diagnose from the kernel source (fetch
   the exact Makefile/Kconfig lines the error names), fix ONE thing, bump
   version, re-deliver. Completion criterion: the new commit message names the
   single fix.
7. **On device-boot failure (CI green but the phone bootloops or sticks on
   logo):** check log provenance first (recovery-exported logs are the
   recovery kernel's, not the payload's), then run the bisect-image protocol
   in `references/boot-failure-debugging.md`. Completion criterion: the next
   on-device round tests exactly one payload variable against a known-good
   donor control. If the device BOOTS then freezes (system hangs at lock-screen
   unlock, no crash line), that is a hang, not a reboot — logcat will not show
   kernel state; collect pstore/live `/proc/kmsg` instead (see the reference's
   "freeze vs crash" section).
8. **On device-boot SUCCESS (a serial shell appears):** harvest the hardware
   inventory IMMEDIATELY — a RAM-only boot is ephemeral and rebooting loses it.
   Over the live console run `uname -a`, `cat /proc/device-tree/model`,
   `cat /proc/partitions`, `ls -l /dev/block/bootdevice/by-name/`,
   `ls /sys/class/udc/`, `ip link`, `free -m`, and `dmesg`. The partition list
   proves whether eMMC is visible (Milestone 3 / Docker gate); `/sys/class/udc`
   and `ip link` prove the USB-gadget and network bring-up path; dmesg shows the
   rest. Read the NEXT wall off this output instead of guessing it.
   Note: a donor-control image hanging on the vendor logo does NOT contradict
   this — an Android ramdisk cannot boot RAM-only, so the real image booting is
   the signal, and the control was simply a weak control.
   When the user says they will paste console results one batch at a time, stay
   silent between batches — acknowledge once, then answer only when they signal
   they are done. Don't pre-empt, re-explain, or comment on each paste; they are
   driving the console and mid-batch commentary just gets in the way.
9. **After shipping a release, byte-verify the ARTIFACT contains what the
   workflow was supposed to install** — a green CI run proves the workflow ran,
   not that a copy step targeted the right tree. Download the published boot
   image, parse the `ANDROID!` header (page size at offset 36; kernel/ramdisk
   sizes at 8/16, each section page-aligned), gunzip the ramdisk, and walk the
   newc cpio in pure Python (the `cpio` binary may not exist), asserting each
   new file is present with its expected marker string and that untouched files
   (e.g. the gadget init) are still there. For kernel-side patches, also verify
   the KERNEL payload: an `Image.gz-dtb` is a gzip member plus appended DTB, so
   `zlib.decompressobj(31)` over the kernel bytes yields the plain Image and
   each patch's marker string should be countable in it — the ramdisk check
   alone cannot see a C patch.

## Always-on rules

- Pass `CC=clang LD=ld.lld CLANG_TRIPLE=...` as COMMAND-LINE make args on every
  make invocation, including the defconfig step — the kernel Makefile assigns CC
  with recursive `=` that environment exports never override, and Kconfig shells
  out to `$(CC)` via scripts/*-version.sh during defconfig, so a missing
  compiler surfaces as `init/Kconfig: syntax error`, not a compiler error.
- Clone kernel trees with `--recurse-submodules` and hard-fail right after
  (`test -f kernel/drivers/kernelsu/Kconfig || exit 1`) — a dangling KernelSU
  symlink breaks `drivers/Kconfig` with "can't open file"; never mask with
  `|| true`.
- Grep the vendor tree's Makefiles for object gating before enabling any Kconfig
  option — vendor trees diverge from upstream (e.g. `nf_log.o` gated behind
  DEBUG_KERNEL where upstream builds it unconditionally), and enabling the
  and enabling the consumers without the core dies at final link with `undefined symbol:`.
  - Choose the NARROWEST correct Kconfig gate for an object, not a broad umbrella. When an object is gated behind a coarse switch, re-gate it on the subsystem's own symbol rather than enabling the umbrella in the defconfig (e.g. `nf_log.o`: `netfilter-$(CONFIG_DEBUG_KERNEL) += nf_log.o` → `netfilter-$(CONFIG_NF_LOG_COMMON) += nf_log.o`, and drop `CONFIG_DEBUG_KERNEL=y` from the defconfig). `CONFIG_DEBUG_KERNEL` is the whole kernel-debug parent — it drags in DEBUG_OBJECTS and the entire `mm/Kconfig.debug` memory-debugging menu; enabling it just to build one `.o` pollutes a production kernel and a sharp reviewer will reject it. And tristate symbols (`config NF_LOG_COMMON` is `tristate`, not `bool`) are NOT auto-enabled: they only build if the defconfig sets them `=y` or some other config `select`s them — grep `select <sym>` before assuming it comes free.
- **In a directory holding BOTH `Kbuild` and `Makefile`, kbuild reads `Kbuild` and ignores `Makefile`.** The `Makefile` there is the external-module entry point (`$(MAKE) -C $(KERNEL_SRC) M=$(dir) modules` with its `KBUILD_OPTIONS` overrides), so an edit to it never reaches an in-tree build. Read the kit workflow's actual make invocation first — `make O=out ... Image.gz-dtb` takes `Kbuild`; `M=` plus the `modules` target takes `Makefile` — and name which path your proposed edit rides. Vendor trees that ship both files for one driver (qcacld does) make this trap easy to fall into.
- **Never hand the user a build-file edit as "the fix" on the strength of a plausible mechanism story.** A tidy why-it-works explanation, and especially a folksy analogy, is not evidence that the build path was checked. Confirm the symbol already resolves the way you claim in the build system's own terms — which file the build reads, which target it invokes — and if you could not confirm it, label the change unverified instead of wrapping it in a confident mechanism. An unverified change presented as a fix costs a build cycle and the user's trust; presenting it honestly costs nothing. The same discipline covers the follow-up question "is this harmless?": a no-op edit is trivially harmless, but answering "yes, ship it" without checking whether it does anything at all implies it does.
- **A device-tree node with no `status` property defaults to `"ok"`** — do not treat a missing `status` as the reason a subsystem does not probe. Check the node's `compatible` against the driver's `of_device_id` table, and its `reg`/`interrupts`/supplies against what `probe` actually reads, before naming the DT. An absent node and a present-but-unbound node are different faults with different evidence.
- **"The driver is compiled in" and "the device appeared" are different claims — keep them separate when a net or block device is missing.** Prove the compile state from the build file (`obj-$(CONFIG_X) += ...`) and the resolved config, then treat the missing interface as a PROBE problem: missing platform or power-domain layer, regulator or clock not claimed, remote firmware not loaded. On Qualcomm WLAN the chain is driver → platform glue (`pld_*`) → subsystem controller (`icnss`/`cnss`), and the controller's probe is the usual failure point, not the driver's.
- **A subsystem that prints nothing may be a subsystem whose diagnostics were
  never built — never read silence as health.** Vendor drivers gate their debug
  prints behind a CONFIG that is normally off, and those prints are exactly the
  ones marking where a bring-up chain stops (`icnss_pr_dbg()` names the
  server-advertise, the FW-ready gate, and the PD-registration step, and every
  one is invisible without `DYNAMIC_DEBUG`). Before believing an empty log, try
  `echo 'file <driver>.c +p' > /sys/kernel/debug/dynamic_debug/control`.
  **But read the RUNNING kernel's config before proposing any symbol:**
  `zcat /proc/config.gz | grep DEBUG_FS` on the device settles in one command
  what a defconfig grep cannot. `DEBUG_FS` is `select`ed transitively by
  `mm/Kconfig`, `kernel/trace/Kconfig`, `net/sunrpc/Kconfig`,
  `drivers/md/bcache/Kconfig` and `drivers/edac/Kconfig`, so a kernel can carry
  `CONFIG_DEBUG_FS=y` while NEITHER vendor defconfig mentions it — and a
  `nonexistent directory` failure is then ambiguous between "debugfs not
  compiled in" and "this shell is a different/older build than the one under
  test" (match it with `uname -a` + `/proc/config.gz` from the same session).
  `DYNAMIC_DEBUG` (`lib/Kconfig.debug`, `default n`) is the symbol that is
  genuinely usually missing and the only one worth adding — it makes the chain
  runtime-switchable with no rebuild. Prefer it over a driver's own debug symbol
  when that symbol's help text says it enables `BUG_ON` — a hang risk on a
  device whose registers may already be wedged, for no gain over
  `DYNAMIC_DEBUG`. **Never ship `CONFIG_DEBUG_FS=y` as an instrumentation fix:**
  adding a symbol that is already on is a redundant line that costs a build
  cycle and implies the earlier "we are debugging blind" claim was checked,
  when it was not.
- **Grep a dmesg line's literal text to its source file before ranking it as evidence.** A line's prefix names the DRIVER that printed it, not the subsystem the line is about, and a distinctive-looking string is easy to chase to the wrong file — which is how a whole theory gets built on a misattributed line. One command resolves it:

```sh
grep -rn '<literal substring of the message>' drivers/ --include=*.c
```

  Do this BEFORE treating any dmesg line as decisive. A line read as "subsystem X booted / didn't boot" can turn out to be printed by a driver that has nothing to do with X, in which case the entire asymmetry it appeared to show is an artifact of the misattribution.
- **Verify first, then rank hypotheses — the reverse order is what produces wrong leads.** The costly pattern is: form a mechanism story from static analysis, rank it, and only then look for the check that would refute it. The cheap check is almost always the one that kills the story, so run it before ranking anything. A `compatible` match in the source proves the code exists, not that it is compiled in (`obj-$(CONFIG_...)` gates it) or bound on the device (`/sys/bus/platform/drivers/` settles that) — so an API-compatibility check is not evidence a candidate driver runs on this hardware. **If you have not run the check, do not rank the hypothesis it would kill:** label it unverified and run the check.
- **"Native" means native — never lead with the workaround.** When the native path is still open and unsolved, a dongle / different-chip / alternate-transport route is a fallback, not the plan, and it must not be listed first. A user who states "make it as native as possible, whatever it takes" is setting scope, not asking for options; offering a workaround anyway spends a turn and reads as giving up on their hardware. State the native path, its cost, and its blocker, and let them ask for the fallback.
- **An empty grep is the highest-value result, not a failed one.** When a
  driver's error macros are fatal-level, a failed call would have printed, so
  zero output eliminates every transaction-level hypothesis at once and points
  upstream to service discovery. `dmesg | grep -i icnss_qmi` returning nothing
  means the QMI service never advertised itself — chase the advertisement, not
  the transaction. Grep the transport layer (`servreg|pdr|service.loc`) BEFORE
  the consumer: a service-locator timeout explains the consumer's silence, and
  the same locator failing for a different consumer proves a transport bug
  rather than a subsystem bug.
- **Collect the whole subsystem's state in ONE paste, and answer a roadmap request with the whole map, breadth first.** The build-flash-boot-dmesg cycle is the expensive part, so a turn that learns one bit is a turn mostly wasted. Two applications of the same rule: (a) bundle the subsystem, its glue, the transport, the relevant `/sys/class` listing, and the resolved-config grep into ONE redirect, writing to a path that exists on the device (`/sdcard` is often absent in an OpenWrt shell — use `/tmp`), and pre-commit to a decision rule before the log arrives so each outcome maps to a patch instead of a re-derivation (full recipe in `references/missing-device-probe.md`); (b) when the user asks for the overall roadmap/blueprint, answer with the FULL map — every milestone, its real state, and the one thing blocking each — plus the single consolidated probe that would resolve the open ones, rather than drilling one link at a time. This user has twice pushed back on one-by-one debugging as a time sink and asked for the whole picture at once; treat a roadmap request as breadth first, depth second. Two things make breadth cheap: the notes index already records each milestone's verdict (read it before asking anything), and a single dmesg bundle can carry every subsystem's state. Serial debugging is right only when one variable genuinely cannot be separated — say so when that is the case.
- **A node named for a driver is not necessarily bound to that driver.**
  `compatible` decides binding; the node name is a comment. sdm660's
  `qcom,rmtfs_sharedmem@0` is `compatible = "qcom,sharedmem-uio"` and binds the
  UIO driver, so enabling `CONFIG_QCOM_RMTFS_MEM=y` compiles a driver with
  nothing to bind to and the change looks inert for a non-obvious reason. Grep
  for a node whose `compatible` the driver actually matches before enabling any
  CONFIG, and check the node sits in the right block with a real base+size
  `reg`. When no correct reference node exists in any local tree, leave the DTS
  alone rather than inventing a reserved region — a wrong reserved-memory range
  can brick a boot, while an inert config change costs one cycle.
- **Before adding any CONFIG symbol, check whether the RUNNING kernel already has it.**
  A defconfig grep is not evidence of absence: `select` pulls symbols in
  transitively, so a kernel routinely carries symbols neither vendor defconfig
  names. `zcat /proc/config.gz | grep <SYM>` on the device is the only ground
  truth, and it is one command. Shipping a symbol that is already enabled costs
  a build cycle and implies the gap was verified when it was not.
- **Before adding any CONFIG symbol to a defconfig or fragment, resolve its whole dependency chain from the tree's own Kconfig at the exact branch.** kconfig silently drops a symbol whose dependencies are unmet, so a fragment line can look correct and do nothing. For each symbol: (a) find its `config <SYM>` stanza and read every `depends on` and `select`; (b) confirm each dependency is satisfied in the resolved config — including `default y` symbols that never appear in the defconfig because they are hidden behind `if EXPERT` (e.g. `PRINTK`, which `DYNAMIC_DEBUG` needs and which is always on); (c) for a `tristate` that something else `select`s, confirm the selecting symbol is actually enabled. Record the chain in the commit message so the next session does not re-derive it. This is the same discipline as the nf_log trap, applied to the symbols being ADDED rather than the ones being enabled.
- **Grade a candidate fix as a candidate, not a fix, and say so in the commit body.** When a change is the leading hypothesis rather than a verified one — because its effect is remote-side, or because the DT node it needs does not exist yet — write that into the commit message and the fragment comment, name what evidence would confirm it, and state plainly which parts are instrumentation (they pay off on any outcome) versus speculative (they may do nothing). A fragment comment that says "expect this to be insufficient on its own, here is why" stops the next session re-deriving the same dead end, and stops a user flashing it as a certain fix.
- **Walk back a committed patch when later evidence contradicts its premise, in the same turn.** A commit that was reasonable when written is not owed defense once a timestamp arithmetic or a missing-peer line kills the mechanism it rested on. Amend or supersede it, say plainly which part was wrong and what evidence killed it, and keep only what still earns its place (instrumentation earns its place; a speculative fix that cannot work does not). Shipping the cycle on a dead mechanism because it is already committed is the same error as shipping it the first time, one round-trip later.
- **When one root cause explains several symptoms, stop treating them as separate bugs.** A dead transport kills every consumer on it, and the consumers' symptoms look independent (WLAN missing, a locator down, an adsprpc PDR failure). Confirm the shared cause from source — one peer, one transport, several consumers — then fix once at the shared cause instead of per-symptom. The signal is two or more unrelated-looking failures that share a transport or a peer in the log.
- **When a user reports a pasted command "is broken", stop repairing the text and change the delivery channel.** A multi-line shell block pasted through a chat client gets mangled by line wrapping and quoting, and no amount of rewording makes it survive. The durable fix is to commit the script to the repo's `scripts/` and give ONE paste-safe line that fetches it: `wget -qO /tmp/p.sh <raw-url> && sh /tmp/p.sh`. That byte-exact fetch replaces scp (which fails — dropbear has no sftp-server) AND pasted blocks. Same rule for diagnostic bundles: put the script in `scripts/`, push, then hand over the one-liner.
- **Enumerate credential files instead of remembering one path.** Several same-length token files can sit side by side and only one is valid, so a remembered path is a coin flip that looks fine until the first 401. Test each candidate against the API in one command and use the one that returns 200:
```
for f in /opt/data/.gh_token /opt/data/github_token; do
  TOK=$(head -1 "$f"); CODE=$(timeout 60 curl -s -o /dev/null -w '%{http_code}' -H "Authorization: token $TOK" https://api.github.com/repos/<owner>/<repo>); echo "$f -> $CODE"
done
```
  A stale token is indistinguishable from a permissions problem until you test it, so test before concluding you cannot push and before asking the user for new credentials. Redact the token from any output you echo back.
- Reply in the language the user wrote in; never switch languages mid-thread unless asked. A language switch that was never requested is an error, not a style choice — the user has caught this twice on one thread and asked "why did you change language?". Correct it in the same turn, restate the substance, and do not explain at length.
- Diagnose the failing run's actual commit: fetch its head SHA and read the
  workflow AT that SHA before theorizing — an older run's failure is not the
  current kit's bug.
- Push with the credentials you already hold: if `~/.ssh` authenticates to
  the repo's remote (`git ls-remote origin` succeeds), do the commit/tag/push
  YOURSELF, tags included — the user installed the publish key precisely to
  delegate pushing, and being handed `git push` commands anyway reads as
  ignoring what they gave you. The copy-paste Termux push block is only for
  when the agent has no push access. Confirm arrival with `git ls-remote
  origin` (SSH — no PAT needed); when no `gh`/PAT exists, watch a
  tag-triggered release by polling the release-by-tag endpoint with `curl -4`
  (see the github skill's repo-management reference) instead of declaring CI
  status invisible.
- When a GitHub `git push` fails asking for a Username (e.g. "could not read
  Username for 'https://github.com'"), or an SSH remote fails with "Permission
  denied (publickey)" while `git@github.com:<owner>/<repo>` authenticates fine,
  the remote URL is wrong — plain HTTPS has no stored credentials, and
  `ssh.github.com:443` vs `git@github.com` are distinct endpoints whose
  `~/.ssh/config` Host blocks do not carry over. Reset the remote to the
  verified-working SSH host (`git remote set-url origin
  git@github.com:<owner>/<repo>`) rather than wiring up HTTPS credentials or
  re-checking the key; confirm with `git ls-remote origin`.
- Make a separate `--depth=1` clone for the new feature project (the user's
  standing rule: never a full kernel clone), verify the target branch exists via
  `git ls-remote --heads` before cloning, and fix the remote to the working SSH
  host before the first push.
- Before the first commit in any clone, set git identity and match it to the
  repo's existing commit author (`git log -1 --format='%an <%ae>'`) — a
  `git commit` fails outright (exit 128) when `user.name`/`user.email` are
  unset, and committing under a different author than the tree's history (e.g.
  the user's personal name when the repo commits as the agent) makes the new
  commits read as a foreign author.
- Feature work does NOT pile onto the user's accumulating branch. He treats
  `devhamid-remastered` as a kitchen-sink branch and is unhappy when new work
  lands there — he expects a FEATURE BRANCH per piece of work. The current
  feature base is `project-hail-mary` (created fresh off `build-all-rekernel`,
  `a1e6b3a97`); the old `mglru-v5` base was deleted by user directive and is
  recoverable from origin. Don't assume the current branch is where work
  belongs; state the target branch and get the name confirmed.
  Before committing/pushing anything that constitutes its own feature, state the
  target branch and get the name confirmed; never assume the current branch is
  where the work belongs. When diagnosing remote branch state, check BOTH local
  clones (`/srv/ssd/devhamid-remastered-prjk/repo` and `/srv/ssd/kernel-work`)
  — they track different branch sets and one may show a branch (e.g. `mglru-v5`)
  the other hasn't fetched, so `git branch -a` in one clone alone is not ground
  truth. Confirm the base branch is an ancestor of the work before claiming the
  work is built on it (`git merge-base --is-ancestor base work`).
- When the USER pushed (Termux fallback loop), have them run
  `git log --oneline -1` and confirm the new commit message BEFORE opening
  Actions — "Everything up-to-date" after a failed unzip/copy means nothing
  reached the remote.
- AOSP gcc-4.9 prebuilt tarballs contain NO gcc binary (binutils only); never
  let the build fall back to `$(CROSS_COMPILE)gcc`.
- Deliver the flashable **AnyKernel3 zip**, not the raw `boot.img` — the AK3 zip is what gets flashed in recovery (it installs `boot.img` plus modules via `anykernel.sh`). A bare `boot.img` is only for `fastboot flash boot`. Attach the file itself as media; never hand the user a GitHub artifact API URL — artifact links return HTTP 401 anonymously even on public repos (auth-gated by design), so the user sees a broken link.
- **Check the skill's own `scripts/` and `references/` before writing a helper
  for a subsystem this project has already worked in.** A helper that already
  exists — with its traps documented — gets rewritten from scratch, and the
  rewrite is the inferior copy because it has not been debugged yet. The
  sparse-image converter was re-derived this way while the verified one sat in
  `scripts/simg2img.py` with its CRC32 trap already written down; the same
  check would have saved the first half of an extraction session. Grep
  `linked_files` from `skill_view` and read what is there first. This is the
  "a pitfall already written down that you hit anyway is the most expensive
  kind of repeat" rule applied to tooling rather than to patches.
- **Before writing a C patch you cannot compile locally, LOAD the reference
  that covers its subsystem and run the header/symbol audit it names — do not
  write the patch from memory and let CI proofread it.** The no-local-build
  constraint makes CI the first compiler, so every avoidable include/symbol
  mistake costs a full ~12-minute cycle plus a re-dispatch. The references
  already carry the exact failure signatures for their subsystems; a patch
  written without them re-discovers known pitfalls at build cost. Concretely,
  for every NEW symbol the patch introduces, `grep -rn '<symbol>'
  include/linux/` and confirm the header declaring it is in the include list —
  the header that names the subsystem does NOT necessarily declare its helpers
  (`of_platform_device_create` is in `of_platform.h`, not
  `of_reserved_mem.h`; `for_each_compatible_node` in `of.h`). Then re-read the
  matching reference for the subsystem's other traps before committing. This is
  a pre-commit gate, not a post-failure cleanup: a pitfall already written down
  that you hit anyway is the most expensive kind of repeat.
- **Before committing a C patch you cannot compile locally (no-local-build
  constraint), verify every NEW symbol reference exists in the translation
  unit's ACTUAL include chain.** `poc_selector.c` is `#included` from `fair.c`,
  which includes `sched.h`, which pulls `include/linux/sched.h` — that is where
  `idle_cpu` lives (line 1859), not in `kernel/sched/sched.h`. Search the
  header the file really pulls in, not just nearby headers, or you ship a
  compile failure proofread from the wrong file.
- **Before merging onto a branch someone calls "the full stack", prove each
  feature is STRUCTURALLY complete there — not merely that a commit bearing its
  name is an ancestor.** A backport series splits into a type/field commit and
  the call-site commits that dereference those fields; a branch can carry the
  consumers and lack the definition, so the tree looks feature-complete by
  `git log --grep` and dies only at compile. Check the definition site, not the
  log: `git show <ref>:include/linux/sched.h | grep -c 'burst_time\|burst_score'`
  for scheduler features, and the subsystem's own header for anything else.
  When a merge base fails to build that way, the base is the defect — re-anchor
  on the branch that carries both halves instead of patching the missing fields
  into a half-backport.
- **A bootloop verdict on a structurally incoherent base is void.** If the base
  the bootloop was attributed on cannot reconstruct the feature that is present,
  the named culprit was never isolated — the tree was malformed in more than one
  way. Say so plainly and re-attribute on the clean per-feature arms. Do not
  quietly keep the old attribution because it is already in the chat history.
- **A backport that compiles is not a backport that works.** Once the build is
  green, audit the call graph before reporting the feature as functional: grep
  every new function for callers outside its own definition and every new field
  for writes outside init. A definition with no caller makes the whole feature
  inert, and the surviving call sites can turn the dead value into a constant
  scale factor that still degrades the kernel. Procedure in
  `references/kernel-backporting.md`.
- **Decide whether a feature was IN a bootlooping build from its Kconfig, not
  from the defconfig.** A `config <SYM>` with `default y` compiles the feature
  into every build whether or not the defconfig names it (scheduler backports
  fold into `fair.c` and run from the first context switch), so "the defconfig
  did not mention it" does NOT clear it. Conversely a defconfig line matching no
  `config` symbol in the tree is a dangling orphan that enables nothing — grep
  the feature's CODE symbols (`git grep -l '<feature>_' <ref> -- '*.c' '*.h'`,
  expects hits) to prove presence, and `git grep -n 'config <SYM>' -- '*Kconfig*'`
  to prove the symbol is real. Both directions have produced a wrong attribution.
- **Trace the ACTUAL build source before touching any tree the user points at.**
  A kit repo's `config.env` names the source repo and branch the workflow
  clones (`git clone --recursive $KERNEL_SOURCE -b $KERNEL_SOURCE_BRANCH`);
  the repo in the user's message is often a REFERENCE tree, not the one that
  built the failing image. Resolve the run's `head_sha`, read `config.env` at
  that SHA, and confirm the source repo/branch before cloning or patching
  anything. Diagnosing and "fixing" the wrong tree burns a whole session and
  ships a fix the build never compiles.
- **Only git SUBMODULES auto-pull at build time; everything else is frozen at
  the commit you push.** A `git clone --recursive` at a pinned branch fetches
  nothing "latest" and merges nothing. Check `.gitmodules` to enumerate what
  refreshes each run (e.g. KernelSU via `drivers/kernelsu` →
  `../KernelSU/kernel`); a tree with no `.gitmodules` has its vendored copy
  pinned forever. When a user asks "shouldn't it auto-pull?", answer with this
  mechanism and the concrete list, not a guess.
  **A submodule URL swap is not a content update.** Renaming an upstream project
  changes `.gitmodules` and a symlink and leaves the gitlink pin exactly where it
  was, so the tree carries the NEW project's OLD code with every post-pin fix
  absent. When a dependency is blamed for a failure, report the pin delta
  (`compare/<pin>...<main>` → `ahead_by` plus the changed-file list), not the URL,
  and resolve all four states before agreeing or disagreeing that a swap happened.
  Detail and the diagnosis procedure in
  `references/vendored-submodule-dependencies.md`.
- **Read the kit workflow for a step that overwrites a submodule before trusting
  `.gitmodules`.** A KernelSU setup step gated on an `ENABLE_KERNELSU` flag pipes
  an upstream installer into the tree and rewrites `drivers/kernelsu` regardless of
  the pin; with the flag false the submodule content comes from the pin instead.
  Also grep the parent's `drivers/Makefile` for `$(shell ...)` lines that mutate
  the submodule at build time (a `git fetch --tags` so a version string resolves) —
  a build-time mutation is invisible in `git status` and reads as a stale pin.
- **Edits to a vendored submodule go INSIDE it; the parent only records the new
  pointer.** `git add <submodule>/<file>` in the parent fails with `fatal: Pathspec
  ... is in submodule`. Commit and push the submodule branch FIRST, then
  `git add <submodule>` in the parent so the gitlink points at a SHA that exists on
  a remote — CI's `--recursive` clone cannot fetch an unpushed one.
- **Verify a claimed hook-method / integration path against the build system's
  own selector before declaring it the root cause.** Read the Kbuild/Kconfig
  conditional chain that chooses the path and confirm which branch the tree's
  config actually takes, then check the checker script's requirements against
  the tree. A `choice ... default X` in a submodule is NOT proof the build took
  X — an unrelated symbol can route the build elsewhere, and the branch that
  runs may be fully valid. Both directions have produced a wrong attribution
  here: a defaulted-away path blamed for a failure, and a valid path
  "corrected" into a broken one on the user's say-so that it already worked.
- **Before calling a duplicate definition or dead code a root cause, verify the
  enclosing `#ifdef`/`#else`/`#endif` nesting.** A function that appears twice in
  one file is usually the normal config-gated pair — the real implementation
  under `#ifdef CONFIG_X` and an empty stub under `#else`. Walk the conditional
  stack from the definition back to its opener and confirm both copies sit in
  the same conditional before claiming a bad merge; a substring grep over the
  file cannot see the gate and produces a confident, wrong "smoking gun" that
  costs a retraction. Same discipline for "this code never runs": confirm the
  call site is not inside a branch that is compiled out.
- **When the user corrects a technical claim, revert the change in the same
  turn and re-derive from source.** Do not defend a wrong diagnosis or leave
  the edit in place "just in case" — `git checkout --` the touched files,
  confirm the working tree is clean, and state plainly which claim was wrong.
  A reverted bad patch costs one command; a shipped one costs a build cycle
  and the user's trust.
- **When static analysis does not converge, say so and ask for the evidence
  that would settle it — do not keep drilling or present a guess as a finding.**
  Deep-reading a subsystem without a confirmed root cause burns the session and
  invites a confident wrong answer. State plainly which hypotheses were checked
  and eliminated (with the file:line that eliminated them), name the one
  artifact that would resolve it (a ramoops dump, a manager error string, a
  resolved-config grep), and ask for it. A retracted wrong "root cause" costs
  more trust than an honest "not yet found".
- One fix per CI iteration; bundling changes makes the next log unreadable.
- **When a subsystem is the suspected bootloop/flash culprit, disable it in the defconfig AND keep its lifecycle fixes in-tree (belt-and-braces).** Two independent changes ship together: (a) the real fixes — port the upstream defect fixes (struct-layout aliasing, missing mm-lifecycle hooks) so the code is sound; (b) the config off-switch — set the subsystem's `CONFIG_*=n` (e.g. `CONFIG_LRU_GEN=n`) and drop its default-scheduler takeover (`CONFIG_MQ_ADIOS_DEFAULT=y` over BFQ). This restores a known-good classic path (page reclaim falls back to classic LRU) while the fixed code stays ready to re-enable. Verify the off-switch actually took by grepping the resolved-config artifact (`# CONFIG_LRU_GEN is not set`), never the fragment. Then offer a deliberate second test flash with the subsystem re-enabled to prove the fixes cured it rather than merely hid it behind the off-switch.
- One variable per on-device boot-test round: bisect images prove nothing if
  the init scripts changed in the same iteration.
- A "no-feature" bisect branch is NOT the feature branch minus the feature —
  verify the full compare delta before using it as a single-variable control.
  A bisect branch may be a different lineage with base drift (e.g. `compare
  fix-poc-idle...bisect-no-poc` showed 42 ahead / 15 behind, a newer base with
  MGLRU fully implemented, not just POC removed). Check `ahead_by`/`behind_by`
  and the changed-file list before attributing a boot/freeze difference to the
  named feature. See `references/suspend-freeze-isolation.md`.
- Treat the boot logo and USB enumeration as separate observations: a headless
  system may retain the logo while running, and lack of enumeration does not
  locate the failure. If the user observes no USB device, plan diagnostics that
  do not depend on adb or a live USB console.
- Recovery-exported logs (TWRP/OrangeFox) belong to the recovery kernel, not
  the `fastboot boot` payload — verify the `Linux version` line before using
  them as evidence about a payload boot.
- Lead a feasibility answer with the plain verdict the user asked for ("is it
  possible: yes/no") plus rough odds, THEN the mechanism and risks. Do not bury
  the answer under a wall of caveats — the user will ask "simplified, is it
  possible or not" if you do. Check the actual current state (distro version,
  package feed, in-tree drivers, on-device firmware) before writing any
  component off; absolute negatives have been wrong on this project. "musl can't
  run Docker" (Docker runs fine on OpenWrt aarch64 from 23.05/24.10) and "the
  modem will never work" (the vendor kernel already carries the modem drivers)
  both had to be retracted — a dismissive verdict costs trust and is usually
  just an unverified assumption.
- **Decode a multi-failure probe before quoting its score.** A probe that prints
  `fatal=N` usually double-counts one root cause and counts at least one
  userspace gap as a kernel gap. Group the FAILs by cause, classify each as
  kernel / userspace / duplicate, and report the real blocker count — not the
  probe's. A tool reporting `not found` with `rc=127` says nothing about the
  kernel; check the applet and the matching `CONFIG_*` separately before writing
  a symbol off.
- **A gadget link is Layer 2, not a service.** Creating a USB-ethernet function
  (RNDIS/ECM/NCM) only makes an interface appear. If the distro's network config
  does not bridge or address that interface, the host sees "connected" with no
  route and every service on the device times out — SSH and the web UI alike.
  Never conclude "the service is broken" before an IP/DHCP check from the host.
- **An unexercised feature is unverified, not working.** When the roadmap claims
  a service (web UI, DHCP, SSH, USB ethernet), the milestone is not done until a
  host-side check actually reached it. Grep the build for the copy step AND
  reach it over the wire; presence in the rootfs proves only that it was unpacked.
- **Close a milestone as ONE commit carrying evidence and decision.** When a
  probe answers a milestone, land the README row, the roadmap box, the progress
  figure, and a dated note in the same commit as the verdict — including the
  discounted false negatives and the stated ceiling, so a later session cannot
  re-litigate a settled question from a stale box.
- Explain mechanism in PLAIN LANGUAGE with a concrete everyday analogy FIRST,
  then the technical detail — this user explicitly asks to be taught "like a
  12-year-old / someone with zero knowledge" and values the explainers as part
  of the project journey, not filler. Analogy first, then the exact paths,
  commits, and register names; never drop the technical layer, and never lead
  with it. Same two-layer shape for chat answers and for written notes (see the
  knowledge-notes skill).
  **An analogy is a teaching device, never evidence.** A tidy why-it-works
  story plus a coffee-shop analogy is exactly what an UNVERIFIED claim looks
  like — the shape of a finding without its substance. Never let the analogy
  carry the confidence; state what was actually checked (which file, which
  command, which output) and label the rest as inference. If the analogy is
  the only support, the finding is not ready.
- Target the userspace the user already runs and has proven on their own
  hardware (match their existing board's distro/version line), not the newest
  release or an arbitrary pick — a proven-environment target deletes whole
  classes of compatibility doubt.
- Match the userspace generation to the kernel generation *where kmods are
  involved*: `kmod-*` carry a `vermagic` ABI tag and refuse to load into a
  mismatched kernel, so a 23.05+ rootfs that needs its feed's kmods cannot use
  them on an old 4.x vendor kernel — pick the kernel to fit the userspace you
  need, or build those drivers in (`=y`). This is NOT a blanket "userspace
  version must equal kernel version" wall: a hybrid build (vendor kernel +
  borrowed generic rootfs) runs pure-userspace packages of any modern line on an
  older kernel fine (a 21.02 rootfs rides a 4.19 kernel with zero kmod
  conflicts); only the kmods are version-bound. See
  `references/repurpose-target-os.md`.
- Prefer a generic real-hardware armv8 rootfs (e.g. `rockchip/armv8`) over the
  QEMU virt target (`armvirt`/`armsr`) for any hardware-dependent milestone; the
  virt target expects virtio devices a phone lacks. A RAM-only initramfs of any
  arm64 rootfs still boots on real hardware under your own kernel.
  - Never treat "I added the config line" as proof the option took: kconfig
  **silently drops** an option whose dependencies are unmet (the nf_log case
  above is one instance). Add a CI step that greps the RESOLVED `out/.config`
  for each required symbol and hard-fails the run on a miss, and upload that
  dump as an artifact — the resolved config, not the fragment, is ground truth.
  Before writing any symbol, fetch the tree's Kconfig at the exact branch
  (`raw.githubusercontent.com/<repo>/<branch>/drivers/.../Kconfig`) and read its
  `depends on`/`select` lines; a symbol's real name and its dependencies are
  never safe to recall from memory.
  - Keep the project root (repo, kit, notes, build artifacts) OUTSIDE any
  prune-managed scratch directory — a scratch copy of the kit was silently
  pruned and had to be re-cloned from the remote. Persist under a durable path
  and treat the git remote as the source of truth. To prove a path really lives
  on the intended filesystem, compare device ids (`stat -c %d <path>`) against
  the mount — symlinks and bind mounts both hide a relocation. A durable root
 outside the agent's write-safe root makes the file/patch tools refuse writes.
 For that case write the file to the write-safe root with the file tool, then
 `cp` it into the repo with a shell command — a large `cat > file <<EOF`
 heredoc in the repo can trip the command-approval gate and stall, whereas the
 file-tool + `cp` path is not gated.
 - Files that live in the kit but are never wired into the build (a build step
 that copies only a whitelist) ship nothing: a helper committed to the repo is
 NOT in the image until a build step AND the installer both copy it. Before
 telling the user a shipped helper exists on-device, grep the workflow and the
 installer for the copy step — or unpack the artifact (step 9).
 - Dry-run every idempotent source-patch script against a freshly downloaded
 copy of the real file BEFORE pushing, and diff brace balance (`s.count('{') -
 s.count('}')` must match the original) — an insertion placed AFTER a closed
 `if` block (e.g. appending a log line past the block's `return`) emits a
 duplicate return + stray brace, a C syntax error CI only catches ~12 minutes
 later. When CI job logs are inaccessible (403 without admin), reproduce the
 patch locally against the fetched source and inspect the generated block —
 deterministic compile failures are reproducible offline.
 - Before relying on dmesg to explain a driver failure, grep the driver's
 source for how its error macros are defined — vendor drivers commonly gate
 ALL error logging behind `#ifdef DEBUG` which the Makefile never defines, so
 a failing call prints NOTHING.
 - **Preserve a git bundle BEFORE deleting a remote branch, its working clone,
 or any partition of a verified backport chain.** Deleting a branch the user
 declared broken is irreversible; a restart directive never means throw the
 verified work away. Save `git bundle create <path>.bundle --all` (carries
 every commit) plus a plaintext reference map of the chain — base branch/commit,
 per-card resolution commit SHAs, and compile-gate facts — and persist both on
 a durable path outside the prune-managed scratch dir. The rebuild then resumes
 from disk alone.
 - **A green compile gate does NOT prove a card's work is in the tree.** A backport card can pass compile-check while its content never landed — the kconfig/commit that should carry the feature may have been lost in a rebase, reverted, or never pushed. When auditing claimed completion: (a) for each SHA a card cites, `git cat-file -t <sha>` must succeed — a `fatal: Not a valid object name` means the commit does not exist in the clone; (b) grep the ENTIRE repo (`git log --all --oneline --grep="<feature>" -i`, and `grep -rn` the working tree) for the feature's symbols — zero hits across all refs means the work is absent regardless of what the card or compile run says. Verify from source and git objects, never from the card's narrative or a remembered SHA.
- **A DTS fix is not shipped until the include chain reaches the board.** Trace
  `#include` from the device `.dts` down to the edited dtsi and confirm the last
  hop — a dtsi nothing includes is dead code, and `git grep` finding the file
  proves nothing about the board. Read the COMMITTED values with
  `git show <ref>:<dtsi>` (a dirty working tree can differ from what shipped).
  For ramoops specifically, verify the zone arithmetic
  (`mem_size - console-size - pmsg-size > 0`), never a `dump-size` property: the
  dump-zone fix adds no such property, so grepping for one reports a present fix
  as absent. For ANY reserved-memory region also assert the region is inside the
  device's RAM ceiling — a region above it is silently inert and leaves pstore
  empty no matter how correct everything else is. Detail in `references/ramoops-pstore-debugging.md`.
- **When a chain-walk or dependency script reports a file MISSING, cross-check
  with a direct path lookup before treating it as a root cause.** A resolver
  that anchors relative `#include`s to the wrong base directory reports
  existing files as absent, and that false "missing file" reads exactly like a
  real broken include chain. Confirm with `find`/`ls` on the reported path
  before building a diagnosis on it.
- **Never record a fix as working on the user's say-so when you could not see
  the evidence yourself.** When the artifact that would prove it (a screenshot,
  a console paste) is unreadable or absent, ask for the specific command output
  before writing the verdict down — a user's "it works" can describe a
  different screen than the one you asked them to check, and a retracted
  success costs more trust than a pending one. This is the "compiled is not
  running" boundary one level up: a green build plus a clean DTB parse plus
  a user's summary is still not a populated `/sys/fs/pstore`.
  When you cannot read the user's evidence at all (an image the vision backend
  refuses, a paste that never arrives), say that plainly and name the one
  command that would settle it — never fill the gap with the user's summary and
  never report a milestone as verified on that basis. A pending verdict is
  recoverable; a retracted one is not.
- **Before proposing next steps on a settled investigation, re-read the
  confirmed verdict from memory.** A root cause that was confirmed and
  user-verified stays settled — do not propose re-enabling the convicted
  feature, or backporting further fixes inside it, as the "next step". Check
  MEMORY.md for the known-good branch/config and build the next step on that; a
  status answer that contradicts the recorded verdict costs the user a whole
  re-verification round.
- When the user proposes a set of upstream commits as the fix for a bug, determine which are ALREADY in the tree before applying or dismissing any — heavily-backported vendor trees routinely already carry most of a suggested set. For each commit fetch its `.patch` and grep the tree for its substantive change (e.g. the reason-filter removal, the `max_reason` member); mark each already-applied / relevant-missing / wrong-SoC / cosmetic-only. Only the genuinely absent and applicable ones need work. See `references/ramoops-pstore-debugging.md` for the concrete case.
- **Never probe a guessed file path when checking feature presence — grep for the SYMBOL across the whole tree.** Kernel subsystems live at non-obvious locations: BBR is `net/ipv4/tcp_bbr.c` (not `drivers/net/`), scheduler backports like Cambyses/POC/BORE fold into `kernel/sched/fair.c` (not a per-feature file), and Kconfig options can be present with zero code (a dangling `CONFIG_*`). A `0` count on a guessed path is meaningless and can wrongly conclude yesterday's work failed. Check presence with `git ls-tree -r --name-only origin/<branch> | grep -i <feature>` (path-free) or `git show origin/<branch>:kernel/sched/fair.c | grep -c <symbol>`, and for version-sensitive features (BBR v3) grep a real marker (`#define BBR_VERSION 3`) rather than file existence.
- **Never cip-upstream the base of a device-kernel backport chain.** Mixing a
 cip upstream line under 12 mechanical backports produced a tree that built but
 never booted on the device; the user abandoned it and declared the boot
 undebuggable (no device, no serial, no logs). When a user closes the boot-debug
 path and chooses a clean restart, accept it — do not re-ask for logs or try to
 debug the boot — and re-anchor the chain on the known-bootable base (mglru-v5).
 On restart, re-verify every card against the new clean base in order from the
 first task; do not assume prior verification carries over to the new tree. Diagnostic patches must use unconditional
 `pr_err()` with the rc in the format string, at every branch of the failing
 path, not a re-run of the compiled-out logging. Structure it so ONE grep
 names the answer: an ENTER line printing the branch-selecting state (the
 driver's flags word, key pointers, counters) and a single EXIT line printing
 the final rc, plus one line at each intermediate failure. Print the flags
 word verbatim — on a driver with multiple code paths gated by a flags word,
 the branch taken is otherwise invisible and you re-flash to find it.
- **To isolate a device bug between the user's backports and the stock base,
  build a FULL pure-stock control branch, not one-revert-per-branch bisects, and
  push it as a self-contained ORPHAN commit when the base's history is
  shallow-grafted.** Full procedure, verification, and the `remote unpack failed:
  index-pack failed` pitfall live in `references/control-build-base-vs-backports.md`.
  Key rules: the control is an ISOLATED branch off the unmodified upstream base
  using the STOCK defconfig (verify stock markers like `CONFIG_SCHED_CASS`,
  no LTO, before calling it a control); an orphan commit (`git checkout
  --orphan`, `git add -A`, commit, push) carries the full tree with no parent
  chain so it cannot fail on missing ancestry; and state plainly that the
  control is separate and the user's main branches are untouched — a user who
  hears a stock base was used will reasonably fear their work was
  overwritten. Deliver the control as a flashable AnyKernel zip mirroring the
  user's existing packaging (combined `Image.gz-dtb` + the
  `LKDenchin/KernelSU_Action -b prebuilt_ak3` AK3 source), never a raw Image
  the user must pack by hand — and force-add the workflow with `git add -f`
  because `.github/` is gitignored in the repo.
