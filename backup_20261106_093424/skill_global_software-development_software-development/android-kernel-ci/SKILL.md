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
repo: Kanban card ownership, commit/push handshake, reporting style), and
`references/github-actions-monitoring.md` (carrying workflows past a blanket
`.*` gitignore — un-ignore each parent dir; monitoring runs via the public
API; concurrency cancel-in-progress semantics), and
`references/kernel-action-build-dispatch.md` (driving a separate "Build
Kernels" kit repo: read the workflow, dispatch with an explicit source-branch
input, poll the run, and verify the resolved-config artifact against claimed
tree symbols), and
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
real tree location and the dangling-config/absent-code fail states).

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
- Diagnose the failing run's actual commit: fetch its head SHA and read the
  workflow AT that SHA before theorizing — an older run's failure is not the
  current kit's bug.
- **The local kernel tree is NOT the tree CI builds — never treat a local
  compile result as evidence about CI.** CI clones `KERNEL_SOURCE_BRANCH` from
  the remote (`devhamid-remastered`), where `config LITTLE_CPU_MASK` is deleted
  from every Kconfig; the local clone `/srv/ssd/ksrc/lkdev-devhamid-remastered`
  (HEAD `2f2d5552c`, dozens of commits behind) still carries the symbol at
  `arch/arm64/Kconfig` with `CONFIG_LITTLE_CPU_MASK=15` in its defconfig. A
  local build therefore exercises a different source tree: it can hit config
  behaviour CI structurally cannot, and host gaps (no bison/flex/clang/libssl-dev)
  add failures that say nothing about the runner. Before attributing any failure
  to the workflow, confirm the branch CI actually built:
  `git show origin/<branch>:arch/arm64/Kconfig | grep -c 'config LITTLE_CPU_MASK'`
  plus that branch's defconfig CPU_MASK lines — and check whether the feature
  base is even an ancestor (`git merge-base --is-ancestor base work`), because
  feature branches here are separate lines, not extensions of the CI branch.
  Local CI-equivalent checks are useful only for CONFIG-ONLY regressions; a
  host-side compile error is never evidence about the runner.
- When the user reports a build as "stuck", "not progressing", or asks you to
  cancel workflows, establish ground truth BEFORE touching anything:
  `gh run list --repo <owner>/<repo> --status in_progress` plus the newest
  `gh run list --limit 5`. Report the newest run's id, conclusion, duration and
  artifacts in ONE line first ("nothing in progress; newest run = success in
  3m52s, artifacts present"), then diagnose. Never cancel a finished run, and
  never "fix" a workflow whose latest run is green. **But treat a reported hang
  as REAL until step data disproves it** — this user reads the Actions UI and
  has been right about a genuine hang while the newest run sat green. A build
  ordinal the user quotes ("check build #376", "see build 41312878842") names a
  SPECIFIC run: resolve it by matching `run_number` and `head_sha`
  (`GET /repos/<owner>/<repo>/actions/runs/<id>`), never by taking the newest
  run from a short list — `gh run list --limit N` does not print run_number, so
  the short list silently omits the run the user means, and a run dispatched
  from an older commit is exactly the one that hangs. Ground truth for a hang
  is the job's STEP LIST with `started_at` timestamps, re-read immediately
  before you report: name the step whose `conclusion` is `None` and quote its
  start time, because one earlier read is a snapshot and the same endpoint has
  reported three different "stuck" steps across a single session. A run whose
  logs zip is ~22 bytes died before the publish-log step — that is evidence the
  run never finished, not a permissions problem. Never cancel without explicit
  user confirmation (cancelling is irreversible): `POST
  /repos/<kit>/actions/runs/<id>/cancel` returns HTTP 202, and the run can stay
  `in_progress` for 20–60s afterwards, so verify with a follow-up GET before
  declaring it dead. Commands and the log-retrieval fallback live in
  `references/github-actions-monitoring.md`.
  - **A `--limit` list hides runs; enumerate and match `run_number` explicitly.**
  A short `gh run list --limit 5` returned only 3 runs and made "build #376"
  look nonexistent — it was run id `41312878842`, visible only when listing
  further back. When the user quotes an ordinal, page the list
  (`--limit 50` / the REST `runs` endpoint) and match `run_number` to an id, and
  say the id you resolved so a mismatch is correctable in one line.
  - **Locate a hang by reading the JOB STEPS, not the run status.** Run-level
  `status: in_progress` tells you nothing about where it is stuck. GET
  `/repos/<o>/<r>/actions/runs/<id>/jobs` and read each step's
  `started_at`/`completed_at`: the hung step is the one with a `started_at`,
  `conclusion: null`, and every later step never started. This is what
  distinguishes "stuck in `git clone`" from "stuck in the kernel build" — two
  diagnoses with opposite fixes — and it costs one API call. Re-poll the jobs
  endpoint before theorising: a step can finish between your first read and
  your conclusion.
  - **A hung run has no logs to read.** Its log zip downloads as ~22 bytes
  (empty) because it never reached the publish-log step. Do not spend calls
  hunting for the runner log of a still-hung run — get the step timeline from
  the jobs endpoint instead, and state plainly that the log does not exist yet.
  - **A cancel is asynchronous — verify it, don't conclude from one poll.**
  `POST /repos/<o>/<r>/actions/runs/<id>/cancel` returns `202`; a GET within
  the next ~30s still reports `in_progress`. Poll until `completed / cancelled`
  before reporting, and never re-cancel on the strength of a single stale read.
  - **Correct your own wrong diagnosis out loud, with the evidence that
  overturned it.** Two retractions were owed here: "the SSD went away" (wrong —
  the run really was hung) and "stuck in the clang download / git clone"
  (wrong — the jobs endpoint showed the clone finished in 52s and the hang was
  in the build step). The user had said "not progressing" from the start; the
  failure was not pulling the job steps on the first ask.
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
- When the configured GitHub SSH remote fails with "Permission denied
  (publickey)" but `git@github.com:<owner>/<repo>` authenticates fine, the
  remote URL's host alias is wrong — `ssh.github.com:443` and `git@github.com`
  are distinct endpoints and `~/.ssh/config` Host blocks do not carry over.
  Reset the remote to the verified-working host (`git remote set-url origin
  git@github.com:<owner>/<repo>`) rather than re-checking the key or blaming
  credentials; confirm with `git ls-remote origin`.
- Make a separate `--depth=1` clone for the new feature project (the user's
  standing rule: never a full kernel clone), verify the target branch exists via
  `git ls-remote --heads` before cloning, and fix the remote to the working SSH
  host before the first push.
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
- One fix per CI iteration; bundling changes makes the next log unreadable.
- One variable per on-device boot-test round: bisect images prove nothing if
  the init scripts changed in the same iteration.
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
 the file-tool + `cp` path is not gated.
- **When a project path that worked yesterday reads EMPTY, check the mount
 before theorising about the repo.** `du -sh <path>` returning 4.0K, a missing
 `lost+found`, and `findmnt` still listing the mount means the filesystem's
 contents are gone while the mountpoint survives. Diagnose with `stat -c %d` /
 `findmnt` (is this path on the mount I think it is?), `df`, and a listing of
 the mount root — then STOP and tell the user not to write to that path. If the
 host rootfs is a Docker overlay whose `lowerdir`s live on the SAME partition as
 the data mount, that one partition takes the overlay, every local clone, the
 kit repo, the agent cache, AND the Docker daemon with it (`docker ps` failing
 with "Cannot connect to the Docker daemon" is the corroborating signal, not a
 separate problem). Recovery needs a host-level `e2fsck -n` (read-only) or a
 remount that the agent session cannot run — ask for `lsblk -f`, `mount | grep
 <dev>`, and `dmesg | grep -iE '<dev>|ext4|I/O'` from the host console BEFORE
 any destructive step. State plainly that the pushed remotes are the recovery
 source and that only unpushed work (stashes, local-only commits) is at risk;
 never re-clone over a possibly-recoverable mount. Also treat a dangling
 symlink as a symptom of the same event: if `$TMPDIR`/scratch points into the
 dead mount, verify a path is writable with a real `touch` before writing
 artifacts there.
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
- **Never probe a guessed file path when checking feature presence — grep for the SYMBOL across the whole tree.** Kernel subsystems live at non-obvious locations: BBR is `net/ipv4/tcp_bbr.c` (not `drivers/net/`), scheduler backports like Cambyses/POC/BORE fold into `kernel/sched/fair.c` (not a per-feature file), and Kconfig options can be present with zero code (a dangling `CONFIG_*`). A `0` count on a guessed path is meaningless and can wrongly conclude yesterday's work failed. Check presence with `git ls-tree -r --name-only origin/<branch> | grep -i <feature>` (path-free) or `git show origin/<branch>:kernel/sched/fair.c | grep -c <symbol>`, and for version-sensitive features (BBR v3) grep a real marker (`#define BBR_VERSION 3`) rather than file existence.
- **Never insert `yes '' | make olddefconfig` between the vendor defconfig step and the build on a 4.19 kernel.** On 4.19, `syncconfig` (run by the next plain `make`) calls `check_conf()` -> `conf_string()` -> `xfgets(stdin)` for any symbol whose `.config` value is EMPTY; CI stdin is EOF, so it prints `Bitmask of available LITTLE CPUs (LITTLE_CPU_MASK) [] (NEW)` + `Error in reading or end of file.` and the build dies. `make <vendor>_defconfig` writes `CONFIG_LITTLE_CPU_MASK=` (empty) when the symbol has no default and the defconfig omits it; `olddefconfig` does NOT fill it (it only calls `conf_read()`), so the following `make` is the one that prompts. **The symbol merely EXISTING in the tree is not the trigger — an EMPTY `.config` value is.** A branch that carries `config LITTLE_CPU_MASK` in its Kconfig AND sets `=15`/`=240` in its defconfig builds clean even with the `yes '' | olddefconfig` step present, because there is nothing left to prompt about. Do not predict a hang from symbol presence alone — check whether that branch's defconfig supplies a value before claiming it will prompt. The vendor `%_defconfig` rule (`conf --defconfig=<file>`) is non-interactive by itself because it calls `conf_set_all_new_symbols(def_default)`. Reproduce config-only regressions locally: `make O=<scratch> ARCH=arm64 CC=gcc vendor/<x>_defconfig`, then `yes '' | make O=<scratch> ... olddefconfig`, then `make O=<scratch> -j4 < /dev/null` — the prompt appears at the third step (prompt count 0 in the control with the symbol's value present in the defconfig). Host has no bison/flex: copy prebuilt `scripts/kconfig/conf`, `zconf.tab.c`, `zconf.lex.c` from `/srv/ssd/kernel-work` (same kconfig sha) into BOTH the srctree dir and `<O>/scripts/kconfig/`, then clean them out of the source tree afterwards (`git status --short` must be empty).
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
