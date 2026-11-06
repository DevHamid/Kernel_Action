---
name: kernel-porting
description: "Use when porting kernel features or fixing DT bindings."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [kernel, arm64, device-tree, mglru, pstore, ramoops, android, caf]
    related_skills: []
---

# Kernel Porting & Troubleshooting

For custom Android/ARM vendor kernels (CAF/QCOM trees, 4.x-era). Covers backporting
subsystem features, verifying what actually runs at runtime, and fixing device-tree
driven drivers that silently fail to probe.

## When to Use

- Backporting a subsystem feature (MGLRU, scheduler, filesystem) into a vendor kernel
  and needing an honest answer on whether it is actually active on the SoC.
- A kernel feature is `CONFIG_*=y` but has no visible effect at runtime.
- pstore / ramoops / last_kmsg produces nothing despite the config being enabled.
- A device-tree node exists in the tree but its driver never probes.
- Importing a feature (ntsync, a misc driver) from another dev's kernel tree.
- A vendor external-module Makefile pins a config to a literal (`=m`) instead of the
  defconfig value.

## Delivery: push to the remote branch, do not build locally

This user's standing instruction for kernel work is: commit on the existing working branch
and push to GitHub; do not run local builds as the verification step. So the deliverable
of a porting task is a pushed commit on the agreed branch, and correctness is argued from
the source (config present, symbols guarded, Kconfig/Makefile wired) rather than from a
build log. Confirm the branch before pushing (`git status -sb`, `git log --oneline -1`) and
push explicitly by name (`git push -4 origin <branch>`) so a detached HEAD or a stale
remote-tracking ref cannot send the work somewhere unintended. Force IPv4 on every GitHub
call, not just push: NAT64/IPv6 resets connections on this host, so `git push -4` and
`curl -4 https://api.github.com/...`. A plain `curl` returning `http=000` with
`Send failure: Connection reset by peer` while `getent hosts api.github.com` shows a
`64:ff9b::` address is this exact fault — retry with `-4`, do not chase the token or the
network.

## Backporting a kernel feature (e.g. MGLRU)

0. **Confirm absence first.** Before porting, check whether the feature already exists in-tree at an older revision: diff the in-tree file against the upstream reference branch — function-by-function symbol set, struct-field surface (`tp->` fields), and used headers (`linux/btf.h`, `linux/win_minmax.h`, etc.). Matching structure means no backport is needed; shipping what is already there is churn. Only when the symbol surface differs (missing fields, functions, or guards) does actual backport work begin.

1. **Separate "compiled in" from "fully functional" before reporting status.** Three
   independent layers, and the user cares about the last one:
   - Config: `CONFIG_FOO=y` + `CONFIG_FOO_ENABLED=y` present in the right defconfig
     (`arch/arm64/configs/vendor/<device>-perf_defconfig`, check `.bak` too).
   - Code: the port compiles, init hooks exist, sysfs/debugfs nodes appear.
   - Runtime capability: the fast path is actually taken on this SoC.
   Never say "fully integrated" when only the first two are true. Say "integrated and
   booting, running the fallback path" and name the missing capability.
2. **Grep the capability gate, not the feature name.** Features gate their fast paths
   on capability bits (`get_cap(LRU_GEN_MM_WALK)`, `arch_has_hw_pte_young()`, etc.).
   Find the `#ifndef arch_has_hw_pte_young` generic fallback in `include/linux/mm.h`;
   if the arch does not override it and the defconfig lacks the companion
   `CONFIG_ARCH_HAS_*` symbol, the fast path is dead code on that device no matter how
   clean the port looks.
3. **Compare against the reference implementation by diffing branches, not by memory.**
   `git log --all --oneline | grep -i <feature>` then `git diff <ref-branch> <yours>`.
   If another dev's port is cited as "fully integrated", check whether their tree sets the
   same capability bits — often both run the same fallback and the claim is wrong.
4. **Init-order freezes come from uninitialized per-node state.** When a feature freezes
   the device the moment it is enabled, look for a struct init that runs per `lruvec` /
   per-node / per-cpu: it must be called from the generic constructor
   (`lru_gen_init_lruvec()` from `lruvec_init()`), not only from the feature's own setup.

## Device-tree drivers that never probe

When a driver's config is `=y` but nothing shows up at runtime, check these in order
before touching code:

1. **Compatible string order.** `of_match_node()` matches on the FIRST string in the
   `compatible` property. A node written `compatible = "removed-dma-pool", "ramoops"`
   never binds the ramoops driver. Fix: put the driver-specific string first,
   `compatible = "ramoops", "removed-dma-pool"`.
2. **Is the node actually in the compiled DTB?** Trace `#include` chains from the
   board `.dts` to the `.dtsi` holding the node. A dtsi that exists in the tree but is
   not reachable from the board file contributes nothing.
3. **Address collisions with reserved pools.** Grep the whole dts tree for the base
   address — vendor iommu pools (`qcom,iommu-dma-addr-pool`) and other
   `reserved-memory` regions silently overlap. Pick an unused gap; verify the size fits.
4. **Only then** look at the driver's probe validation (size/power-of-2 checks,
   "already initialized", parse failures).

## pstore / ramoops checklist

`CONFIG_PSTORE=y`, `CONFIG_PSTORE_RAM=y`, `CONFIG_PSTORE_CONSOLE=y`,
`CONFIG_PSTORE_LAST_KMSG=y` (gives `/proc/last_kmsg`) are all required and all easy to
confirm at once with one grep of the defconfig.

**Empty pstore is usually a capture problem, not a config or DT problem.** pstore only
writes through `kmsg_dump()`, which fires on panic/oops — never on a deadlock or a
watchdog-reset hang. A device that freezes at the logo produces nothing in
`/sys/fs/pstore/` and `/proc/last_kmsg` while config and DT are both perfectly correct.
So before touching the DT, check the trigger path, in this order:

1. **Is the running kernel the one you built?** `cat /proc/version` against the tree's
   `Makefile` version + `CONFIG_LOCALVERSION`. A device booting `4.19.259-Miku` while your
   tree is `4.19.325-<tag>` is not running your build, and every missing feature is
   explained without a single code change. **The dmesg you are reading may be from a
   different kernel entirely — the recovery kernel.** Recovery (OrangeFox/TWRP) boots its
   own kernel from the recovery partition, often an old stock/vendor kernel with no pstore
   at all. Prove a dmesg is recovery's without asking anyone: SELinux AVC audit lines
   carrying `scontext=u:r:recovery:s0` (recovery's own domain) only appear in a recovery
   boot, and `ro.orangefox.kernel` / `ro.twrp.*` properties (visible in `/tmp/recovery.log`)
   name the recovery kernel version. If a captured dmesg shows no `ramoops` reservation but
   the author insists it is their fresh build, suspect recovery first — pull `dmesg` from a
   normal Android boot before touching config or DT.
2. **`CONFIG_PANIC_TIMEOUT` must be positive.** `-1` means "never reboot on panic", so
   even a watchdog panic writes no console-ramoops and the device just sits there. Set
   `10` so a panic reboots and the capture lands.
3. **Hangs need converting into panics.** Add `CONFIG_DEBUG_KERNEL=y`,
   `CONFIG_DETECT_HUNG_TASK=y`, `CONFIG_BOOTPARAM_HUNG_TASK_PANIC=y`,
   `CONFIG_SOFTLOCKUP_DETECTOR=y`. Without these a stuck task is never detected, never
   panics, and never dumps. Adding `DEBUG_KERNEL` pulls debug-only code into the build —
   expect a fresh compile failure on the first run and budget for it.

Expected artifacts after a real panic: `/sys/fs/pstore/console-ramoops`,
`/sys/fs/pstore/dmesg-ramoops-*`, `/proc/last_kmsg`. If `/sys/fs/pstore/` does not exist
at all, pstore is not compiled in and you are debugging a different kernel.

## Backporting a misc driver from another dev's tree (ntsync as the worked example)

When a feature exists only in someone else's kernel repo, take the commit patch, not the
repo: `curl -sL <github>/commit/<sha>.patch -o /tmp/x.patch`. `git apply --check
--verbose` first; hunks touching CI files (`anykernel/`, `.github/workflows/`) fail
harmlessly in a tree with different build plumbing — `git apply --reject` applies the
core files and leaves `.rej` only for the irrelevant ones. Never rewrite the whole
driver to "clean it up": the upstream author already put `#ifndef`-guarded shims
(`lockdep_assert`, `atomic_try_cmpxchg`, `compat_ptr_ioctl`) at the top, and those guards
make the shims no-op on a kernel that has the real thing. Verify each helper against the
TARGET tree before keeping its shim — check the header AND the `.c` that defines it
(`grep -rn '<helper>' include/ fs/`), because a shim guarded by
`#if LINUX_VERSION_CODE < KERNEL_VERSION(x,y,z)` instead of `#ifndef` redefines a symbol
the tree already provides and dies with `error: static declaration of '<helper>' follows
non-static declaration`. Decide per helper, never per file: this 4.19 backport tree
already ships `compat_ptr_ioctl()` (`fs/ioctl.c`, declared in `<linux/fs.h>` under
`CONFIG_COMPAT`), so that shim must be deleted, while a sibling helper can genuinely
still be missing.

Defconfig wiring: after adding the Kconfig symbol, add `CONFIG_<FEATURE>=y` explicitly to
the device defconfig even when the Kconfig says `default y`. A `default y` does not
survive a later fragment, and CI symbol-validation steps grep the defconfig, not the
built `.config`.

Pick the defconfig from the CI run, not from the device name. The build log's `env:` block
names it (`KERNEL_CONFIG=vendor/<device>-oss-perf_defconfig`) and that is frequently NOT
the plain `vendor/<device>-perf_defconfig` the naming implies — this user's wayne CI
builds `wayne-oss-perf_defconfig`. Editing the wrong one is invisible in the log: a
`default y` symbol compiles with no config line at all, so a driver can break the build
while its config entry is absent, and the user will ask why his defconfig went untouched.

## Applying a large upstream delta (CIP-style rebase): triage the apply log

When welding a big upstream series onto a vendor kernel (e.g. a linux-cip delta)
the applying tool writes an `apply.log`. Classify it, do not eyeball it:

- `error: repository lacks the necessary blob to perform 3-way merge.` is a
  PARTIAL-CLONE artifact (`git clone --filter=blob:none`), not a patch failure.
  `git am -3` / `git apply -3` needs the base blob for its 3-way fallback and dies for
  want of it; it repeats constantly and usually falls back to direct application. Ignore
  it for triage.
- The REAL failures are `error: patch failed: <path>:<line>` followed by
  `error: <path>: patch does not apply`. Isolate just those:
  ```
  grep -E 'error: patch failed: [^:]+' apply.log | sed 's/error: patch failed: //' | sort -u
  ```
  That is the true reject list.
- Bucket rejects by subsystem. On a QC/Android tree the arch fossils
  (mips/m68k/parisc/x86) mean nothing on arm64, but a reject in `block/`, `kernel/sched/`,
  `mm/`, `fs/<your-fs>/`, `drivers/mmc/`, `drivers/usb/dwc3/`, `include/linux/`, or the
  top-level `Makefile` is a genuine weld the compiler cannot paper over. Each such reject is
  either hand-resolved or silently dropped — the dropped ones are the prime suspects for
  the runtime incompatibility you are chasing.
- Report the reject count as the literal number (e.g. the count of unique files from the
  sort -u), not as "a few"; it sets how much confidence the rest of the port deserves.

## Aligning a defconfig against a reference requirements doc

When the user hands a config guide (DroidSpaces `Kernel-Configuration.md`, a distro's
required-options list) and asks whether his defconfig satisfies it, do a real diff, not a
grep of a few headline symbols:

1. **Extract the requirements from the doc's own code blocks, sectioned.** Parse the
   fenced `makefile` blocks; split required (Step 1) from optional (Step 2 / firewall) so
   you can report the two counts separately. `re.findall(r'^(CONFIG_[A-Z0-9_]+)\s*=\s*(\S+)',
   section, re.M)` gives `symbol -> value`; watch for explicit `=n` requirements
   (`ANDROID_PARANOID_NETWORK=n` is a real requirement on ≤4.19, not an omission).
2. **Index the tree's Kconfig symbols in Python, not grep.** `os.walk` every `Kconfig*`,
   `re.findall(r'^\s*(?:menu)?config\s+(\w+)\s*$', t, re.M)` — ~17k symbols in a second.
   Per-symbol `grep -rl` across the tree times out on a 4.19 CAF tree and its empty
   results read as "symbol absent" when grep simply ran out of time; the walk is both
   fast and authoritative. Build the index once, reuse it for every symbol in the list.
3. **Map renamed/legacy symbols before declaring anything missing.** A doc written for a
   newer kernel lists symbols that were renamed or dropped in the target version. Verify
   with one targeted grep of the tree's Kconfig, then record the alias in the commit
   message so the next session doesn't re-derive it. Known mappings for this 4.19
   backport tree: `NF_CONNTRACK_NETLINK`→`NF_CT_NETLINK`,
   `NETFILTER_XT_TARGET_MASQUERADE`→`IP_NF_TARGET_MASQUERADE`,
   `IP_NF_TARGET_ULOG`→`NETFILTER_XT_TARGET_LOG`, `NETFILTER_XT_TARGET_REJECT`→
   `IP_NF_TARGET_REJECT`. `NF_CONNTRACK_IPV4`/`NF_CONNTRACK_IPV6` and
   `FW_LOADER_COMPRESS` have no symbol at all here — skip them, do not add a dead line.
4. **Append as a labelled, greppable block.** One `# === <feature> alignment, per
   <doc> ===` marker then the lines, at the defconfig's tail. The marker makes the block
   findable, droppable as a unit, and diffable; state the skip-list and renames in the
   commit body. Report the verdict as counts ("44 of 47 added, 3 skipped — no such
   symbol in tree") plus the WLAN/feature symbols still confirmed present, so the user
   can see alignment without opening the file.
5. **The doc's patch steps are part of the same task, not a footnote.** A config guide that
   references `Documentation/resources/kernel-patches/...` ships the patches only in its
   source repo — copying the doc text copies the instructions, not the patches. Complete
   the phase in the same turn: fetch each patch from the source repo
   (`raw.githubusercontent.com/<owner>/<repo>/main/<path>`, URL-encode spaces in file
   names), `git apply --check` before applying (there is no `patch` binary on this host —
   use `git apply`; expect harmless `has type 100644, expected 100755` mode warnings and
   hunk offsets from tree drift), confirm every symbol a patch references exists in the
   tree, apply, commit the code changes, then store the patch files in-tree under
   `Documentation/resources/kernel-patches/<target>/` with `git add -f` — the repo's
   `.gitignore` excludes `*.patch`, so a plain `git add` stages nothing and the commit
   stat silently shows only the code files. The user asks "is it fully integrated?" and
   reads an empty patch directory as half-done work; do not hand back only config
   alignment when the guide's other steps are still outstanding.

## External module Makefiles: pass the config value, not a literal

Vendor module Makefiles (qcacld-3.0 and friends) often hardcode `WLAN_SELECT :=
CONFIG_QCA_CLD_WLAN=m`. That builds the module as `m` regardless of what the defconfig
chose, so a `=y` defconfig silently produces a module and the driver never links in. Fix:
`WLAN_SELECT := CONFIG_QCA_CLD_WLAN=$(CONFIG_QCA_CLD_WLAN)`. Prefer a targeted
find/replace edit for the line; if you do it with a shell one-liner, the `$(...)` is eaten
by the shell — single-quote the whole script and re-read the line to confirm it landed,
because a silently emptied value (`WLAN_SELECT := CONFIG_QCA_CLD_WLAN=`) looks like a
successful edit and only fails at build time.

## Diagnosing a build failure from CI logs (backported feature wiring)

When the user uploads a build log and the workflow died mid-compile, work the error
backwards to its gating chain before touching code:

1. **Find the first failure, not every error.** CI aborts at the first hard error, so
   everything after it is untested — do not promise the rest of the tree is clean. Read
   ~80 lines around the first `##[error]`/`error:` to get the full symbol set.
2. **Undefined function ⇒ its .c never got built.** Trace `obj-$(CONFIG_FOO)` in the
   Makefile for that directory back to the Kconfig symbol, then find who `select`s that
   symbol. A symbol that no config selects is `n` for everyone, and `select` symbols are
   invisible in defconfigs — so a missing `select` in `arch/<arch>/Kconfig` shows up as
   an undefined reference hundreds of lines from its cause. Fix goes in the Kconfig
   `select` list, never in the defconfig.
3. **Prove absence properly: fetch every Kconfig, grep the set.** List the tree
   (`GET /repos/<owner>/<repo>/git/trees/<branch>?recursive=1`, filtered on basename
   `Kconfig*`), then `curl` them in parallel with `xargs -P 16` into a flat directory
   (mangle `/` to `_` in filenames). A single-file grep on `arch/<arch>/Kconfig` is
   how you convince yourself a symbol is absent when it lives two Kconfigs away.
4. **Identify the reference version by file content, then diff the whole subtree.**
   Hash the suspect file against 2–3 upstream tags (raw URL per tag) to learn which
   era the backported subtree came from, and diff the ENTIRE subtree against that tag —
   the first reported error is usually one of several missing pieces. Report all gaps
   in one pass instead of letting CI find them one run at a time.
5. **Check the warning posture.** `DISABLE_CC_WERROR: false` in the log means `-Werror`
   is live, so format warnings will also kill the build.
6. **When the logs are auth-gated, make CI publish the error instead.** A deploy key buys
   push access only: `GET /actions/runs/<id>/logs` answers 401 and check-run annotations
   come back empty unauthenticated, so retrying the fetch never works and the run stays
   opaque. Patch the workflow to publish it. On the build step use `set -o pipefail` plus
   `make ... 2>&1 | tee build.log` — `tee` alone swallows make's exit status and the step
   goes green on a failed build. Then add an `if: failure()` step that appends the errors
   to the run summary:
   `{ echo '### build errors'; echo '```'; grep -nE "error:|fatal error|undefined reference|No rule to make" build.log | head -80; echo '```'; } >> $GITHUB_STEP_SUMMARY`.
   The step summary renders on the run page without auth, so one red run becomes
   diagnosable. Dump any `.config` you need to inspect into the summary the same way — the
   resolved config, not the defconfig, is what the compiler actually saw.

Verification for this class is the CI rerun (see push rule above): there is usually no
local toolchain (clang/lld/bc/flex), so argue correctness from the source diff and the
upstream reference, then push and watch the run.

## Reporting style for this user

Short, concrete, no hedging padding. Lead with the verdict, then a two-column
"what's live / what's dormant" split, then numbered next-step options. State
uncertainty by naming the exact missing mechanism, not with vague qualifiers.
Explain jargon in plain words for this user — he codes as a hobby and will ask
"what does that mean?" if a term is undefined. Never leave a vague hand-wave like
"grab the patches separately" in a report; name the concrete artifact (file path,
URL, command) so the next step is unambiguous and, when it is work you can do,
do it rather than assigning it to him.
