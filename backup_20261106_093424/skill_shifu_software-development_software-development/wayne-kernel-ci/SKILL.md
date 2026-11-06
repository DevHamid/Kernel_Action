---
name: wayne-kernel-ci
description: Build wayne (sdm660) kernels via Kernel_Action CI.
---

# wayne kernel CI & debugging

## Dispatch a build
- Workflow: `DevHamid/Kernel_Action`, `workflow_dispatch`, ref `Kernel_Action`.
- Input: `KERNEL_SOURCE_BRANCH` = the `LKGeek_sdm660` branch to build.
- A push to the source branch also auto-triggers a build (event `push`).
- Publish step (34) pushes `boot.img`, `Image.gz-dtb`, `config.txt` to the `kbuilds` branch:
  `https://raw.githubusercontent.com/DevHamid/Kernel_Action/kbuilds/<file>`
- The AnyKernel3 zip stays behind the authenticated artifacts API unless pushed manually.
- The deliverable is a direct flashable link: hand over the `kbuilds` raw URL for `boot.img`, not a run ID, an artifact path, or a branch name.
- Dispatch input for a KSU/SusFS build: `CONFIG_KSU=y`, `CONFIG_KSU_SUSFS=y`, `CONFIG_KSU_SUSFS_SUS_MOUNT=y` (the workflow defaults are all `n`).
- The run's `head_sha` is the KIT's SHA, not the kernel source's — it does not tell you which kernel branch was built. Read the `git clone --recursive ... -b <branch>` line out of the log to confirm what CI actually compiled.

## A committed fix is not a built fix — verify push state before dispatching
A commit on a local branch is invisible to CI. Before dispatching a build for a
fix, prove the branch CI clones actually contains it:

```sh
git branch -r --contains <fix-sha>            # empty output = NOT pushed
git rev-list --count origin/<branch>..HEAD    # unpushed commit count
```

Dispatch a build for a branch whose tip does not contain the fix and you ship the
broken artifact through a green-looking pipeline — the most expensive failure mode
here, because the build succeeds and the defect only surfaces on device.

When the push is rejected as non-fast-forward, the remote has moved
independently. Do NOT force-push a shared branch to make your commit the tip —
that discards commits you did not author. Push your line to a new branch, build
that, and tell the user the two lines diverged so they can merge deliberately.

Do not trust the compare API's `ahead_by`/`behind_by` on a shallow clone — it
reports the whole upstream history as divergence. The local
`git branch -r --contains` and `rev-list --count` checks above are the reliable
signal.

## Amending a config fragment: prove the delta is surgical

`git commit --amend` is the right way to retract a symbol from a committed config
fragment, but only if you check the result is exactly what you intended. Diff the
`CONFIG_` lines alone — a large comment diff is invisible next to a real config
change:

```sh
git diff -U0 <fragment> | grep -E '^[+-]CONFIG_'   # must show ONLY the lines you mean to change
wc -c <fragment>                                   # comment growth is fine, config drift is not
```

Two rules follow:

- **Write the retraction into the fragment's own comments, not just the commit message.** A later session re-reads the fragment when the symptom returns; the commit message is read once. Record what was retracted, what killed it, and the file:line that killed it, so the same wrong lead cannot be re-derived from the same evidence.
- **Drop a symbol that is already on rather than keeping it "for safety".** A redundant `CONFIG_X=y` line implies the earlier claim it fixes was checked, and it launders an unverified claim into a build artifact. If the running kernel already has the symbol, the honest commit removes it and says why.

## Verify a change actually shipped
Compile success does NOT mean the change is in the artifact. Decode the dtb before claiming a fix is in:
1. Download `Image.gz-dtb` from `kbuilds`.
2. The dtb is appended after the gzip stream — find magic `d00dfeed`.
3. Walk the FDT (BEGIN_NODE / END_NODE / PROP tokens) and dump the target node's properties.

Run `scripts/fdt_dump.py <Image.gz-dtb> [node-substring ...]` for this — it locates the
appended dtb, walks the blob, and with no filter prints every `/reserved-memory`
child's `reg` range, which is the overlap check the ramoops fix needs.

Also confirm `boot.img` starts with `ANDROID!`. A size delta across builds is a cheap
sanity signal: `Image.gz-dtb` growing slightly means new code actually linked in, and a
shrinking `boot` image is worth a second look before flashing.

**`ANDROID!` proves the file is a boot image, not that it is THIS build's boot
image.** Cross-check the payload before handing over a link:

```sh
python3 scripts/verify_boot_img.py boot.img Image.gz-dtb
```

It parses the header, locates the kernel payload, and compares its sha256 against
the standalone `Image.gz-dtb` from the same run. Two traps it works around:
- **The header's `page_size` can be bogus** (e.g. 256) while the real flash page
  size is 4096. Do not compute the payload offset from it — find the gzip magic
  at 4096-aligned offsets, or match the `Image.gz-dtb` prefix directly.
- **`kernel_size` matching the image size is necessary but not sufficient** —
  only the sha256 comparison proves the payload is the build you just ran.

Run this before reporting a flashable link, and report the verification state
plainly: "compiled and linked, not verified running" is the truth for a kernel
that has not been flashed.

## Regression hunt: "this used to work"
When a value or feature regressed with no obvious culprit, `git log -S '<exact old value>' -- <file>` names the commit that changed it. This pinned a silently-reverted address that a plain `git log` on the file never surfaced, because the offending commit was about something else entirely. Diff the *value*, not the file.

## What POC means on this tree
`sdm660` has no `poc_selector.c` work to do: `poc_selector.c` is present (v2.6.3 by Masahito Suzuki, backported via `8fbe0fc96`), but `# CONFIG_SCHED_POC_SELECTOR is not set` in the built config — it is compiled out by design after the October wake-freeze. The upstream v3.0.0 fixes (`035d864ad9` sentinel / `065f533830` `__maybe_unused` / C89 decl fixes) are all already in this file, so there is nothing to port.

## Local tree
- No local kernel tree on this host — `/srv/ssd` is a fresh cloud disk and the old checkouts are gone. Read branches straight from `raw.githubusercontent.com`, or `git fetch origin <branch> --depth=1` + worktree into `/opt/data`. Write-safe root is `/opt/data`, so edit via `execute_code`/`terminal` — the `patch` tool refuses paths outside it.
- Branch state: `fix-ksu-sugrant` is live (BakaSU work, head 2026-11-02); `build-all-rekernel` is stale (head 2026-09-25); `devhamid-remastered` still on the remote but abandoned. **Verify a build's branch pin against the live branch before trusting its output** — `wayne-openwrt`'s `build.yml` kept cloning the stale `build-all-rekernel` after the switch, and a stale local checkout once showed an `msm_sharedmem.c` that rejected `reg=0` while the live branch had long since moved to dynamic allocation.
- `fix-ksu-sugrant`'s `wayne-oss-perf_defconfig` runs MGLRU OFF (`# CONFIG_LRU_GEN is not set`), `MQ_IOSCHED_ADIOS=y`, `MQ_IOSCHED_DEADLINE` unset. The MGLRU-on freeze config existed only on `devhamid-remastered`.
- **Read another branch with a worktree, not a re-clone.** `git fetch origin <branch> --depth=1` then `git worktree add <path> FETCH_HEAD` yields the full tree at that branch in seconds and respects the standing no-full-clone rule. Assert the tip before reading any file out of it as evidence: `git -C <path> rev-parse HEAD` against the SHA you fetched, and `git -C <path> status --short` empty.
- **A mount that comes back empty is a mount that lost its data, not one that was restored.** `/srv/ssd` returning 4.0K with zero files after a remount means the filesystem came back blank — do not treat "the mount is back" as "the tree is back". Confirm with `du -sh` and a real `ls` of the tree root before resuming analysis, and when the tree is genuinely gone re-clone from source (`git clone --filter=blob:none --no-checkout --depth 1` + `git sparse-checkout` on only the subsystems you need) rather than reasoning from remembered line numbers. `git checkout -b` from the re-clone keeps branch work intact. When the mount DOES come back with data, verify the restore rather than trusting it: `git log -1 --format=%H` against the expected tip, `git submodule status` against the expected pin, and `ls` every patch file the build applies. A partial restore leaves the tree at an older commit with the patches intact, which reads as *nothing was lost* while the fix commit is gone.
- When a durable path is outside the write-safe root, write the file to the write-safe root with the file tool and `cp` it in with a shell command — a large `cat > file <<EOF` heredoc in the repo can trip the command-approval gate and stall.
- `KernelSU` and `drivers/kernelsu` are submodules; only submodules auto-pull in CI.
  **A URL swap is not a content update:** `.gitmodules` pointing at BakaSU says
  nothing about which BakaSU commit is pinned — check `git submodule status` and
  diff the pin against upstream `main` before concluding an integration is current.
  Editing a submodule file requires committing inside `KernelSU/` first, then
  bumping the pointer in the parent. See `android-kernel-ci`'s
  `references/vendored-submodule-dependencies.md`.
  **The pin's identity is decided by `kernel/Kbuild`'s `REPO_NAME :=` line, not by
  the URL and not by the tag.** A fork tags commits it inherited from its parent,
  so a pin can carry the fork's own version tag while its source still says the
  parent's name. Read that one line at the pin and at upstream `main`:
  `git show <pin>:kernel/Kbuild | grep 'REPO_NAME :='` vs the same on `main`.
  When they differ, the tree is running the parent's code under the fork's tag.
- Push: `git push https://x-access-token:$TOKEN@github.com/DevHamid/LKGeek_sdm660.git HEAD:refs/heads/<branch>`, token from `grep -m1 oauth_token ~/.config/gh/hosts.yml | awk '{print $2}'` (use `-m1` — a duplicate newline causes HTTP 400).
- **A submodule's real gitdir is `.git/modules/<name>`, not `.git/`.** Inside a submodule, `.git` is a *file* containing `gitdir: ../.git/modules/<name>`, so `rm -f .git/*.lock` there removes nothing and a stale `shallow.lock`/`FETCH_HEAD.lock` keeps every fetch failing with "a git process may have crashed in this repository earlier". Clear them at the real path: `rm -f .git/modules/<name>/{shallow,FETCH_HEAD,index,config}.lock`.

## Pitfalls found the hard way
- **`Kbuild` and `Makefile` in the same driver directory are NOT interchangeable.** qcacld-3.0 ships both. The in-tree build (`make O=out ... Image.gz-dtb`) reads `Kbuild` — that is where `obj-$(CONFIG_QCA_CLD_WLAN) += wlan.o` lives, so `CONFIG_QCA_CLD_WLAN=y` already builds the driver into `Image.gz-dtb`. The `Makefile` (with `WLAN_SELECT := CONFIG_QCA_CLD_WLAN=m` and its `KBUILD_OPTIONS`) is the external-module wrapper, reached only via `make -C $(KERNEL_SRC) M=<dir> modules`. An edit to that `Makefile` line is a no-op for this build, however convincing the mechanism story. Before editing any build file, grep the kit workflow for the make invocation that actually runs.
- **A whole-tree `grep -rn` on a kernel source tree blows the tool timeout and exits 124 with truncated output — which reads exactly like "no matches".** A full tree is ~70k files, so the search does not finish inside a normal call, and the killed run returns either nothing or a partial list. Scope the search to the subsystem's own directory with an explicit `timeout`, and treat exit 124 as "unknown", never as a negative result. `git ls-tree -r --name-only <ref> | grep <feature>` is the path-free alternative that finishes in seconds and is the right default when the feature's location is a guess.
- **Do not offer a build-file edit as the fix without naming which build path it rides.** If the path was not checked, label the change unverified rather than wrapping it in a confident mechanism — and when asked "is this harmless?", a no-op edit is trivially harmless but answering "yes, ship it" without checking whether it does anything implies it does. See `android-kernel-ci`'s `references/missing-device-probe.md`.
- **Revert a change you cannot verify locally rather than shipping it on a plausible mechanism.** A config-type or Kconfig edit whose effect depends on a tool the sandbox lacks (no `bison`/`flex`, no root to install them) cannot be tested before it costs a CI cycle. Make the edit, try to verify it, and when verification is impossible `git checkout --` the file and say so — then fix the defect where it CAN be verified. Shipping an untestable change because the mechanism story is tidy is the same error as shipping an unchecked build-file edit, one level deeper: the story explains why it *should* work, which is exactly what makes it convincing and exactly what makes it unverified.
- **When the fix belongs in the kit, do not contort the kernel tree to reach it.** If the defect is in the kit workflow (a missing `olddefconfig`, a step that overwrites a submodule), the correct fix is an edit to the kit repo — even though the kernel tree is the repo you have open and can push. Name the kit file and line, state that the fix lives there, and ask before editing a repo you have not been working in. A kernel-tree workaround for a kit defect fixes the symptom on this tree and leaves the next tree exposed.
- **WLAN bring-up chain: qcacld → pld_snoc.c → icnss.c.** The interface cannot appear until `icnss_wlan_enable()` succeeds, because icnss raises the regulators, enables the CXO clock, and boots the Q6 WLAN subsystem. `wayne-oss-perf_defconfig` has `CONFIG_QCA_CLD_WLAN=y`, `CONFIG_ICNSS=y`, `CONFIG_ICNSS_QMI=y`, `CONFIG_CNSS_GENL=y` — the driver side is correct, so a missing `wlan0` is an icnss probe problem, not a compile problem. The single most useful line is the ABSENCE of `icnss: WLAN FW is ready` while `Platform driver probed successfully` and `wlan: Loading driver` are both present — that combination means the Q6 never reported ready over QMI, so the driver's probe was silently never called and the interface can never appear. **Grep the QMI service locator FIRST, before `icnss_qmi`** — it sits upstream of icnss, fails independently, and its timeout produces the same silent symptom with no icnss output at all. The full decision table, the modem firmware contract, the `icnss`/`icnss2` dual-`compatible` switch, the no-userspace-boot-interface finding, and the quirk-settability check are in `android-kernel-ci`'s `references/missing-device-probe.md`.
- **Prove "this is not a kernel config problem" by diffing the two builds' configs, not by asserting it.** When the same source builds a working feature on one userspace and not another, filter both defconfigs to the feature's symbols and diff them — an empty result plus a full diff that is all LTO/zram/compression tuning closes the config hypothesis with evidence rather than argument.
- **Do not publish a conclusion while the check that would refute it is still running.** A background grep that looks irrelevant to the current hypothesis can be exactly what disproves it; poll it before answering. Concluding from the evidence already in hand is how two wrong root causes ship in one session.
- **A DT node with no `status` property defaults to `"ok"`.** `sdm660.dtsi`'s `qcom,icnss@18800000` node has no `status` line while sibling subsystem nodes do — that is a style inconsistency, not the disabling reason. Check `compatible` against the driver's `of_device_id` table (`icnss.c` registers `"qcom,icnss"`) and confirm the node instantiated from the `iommu: Adding device 18800000.qcom,icnss to group N` dmesg line before blaming the DTS. **Never confirm node existence with `cat /proc/device-tree/<node>/status`** — that file exists only when the node carries a `status` property, so it prints "node absent" for a node that bound fine, and that false negative has already been reported upward as a root cause once.
- **Split the firmware question by subsystem: WLAN firmware is remote, MODEM firmware is on disk.** The two are loaded by completely different paths and conflating them has produced a wrong "firmware is a dead end" conclusion on this project.
  - **WLAN (icnss v1, the bound driver):** `icnss.c` and `icnss_qmi.c` contain zero `request_firmware` calls. The Q6 fetches WLAN firmware itself over QMI once the WLFW server comes up. Copying `wlanmdsp.mbn`/`bdwlan.*` to `/lib/firmware/` is NOT the gate on this path — do not spend the session there before the probe log has ruled out power, clock, and QMI.
  - **Modem (pil-q6v5-mss):** absolutely loads from disk. `pil-q6v5-mss.c:160` sets `desc->fw_name = subsys->fw_name` (from `qcom,firmware-name` in the DT), then `peripheral-loader.c:1252` does `request_firmware("<fw_name>.mdt")`, and `pil-msa.c:651` separately loads `mba.mbn` BEFORE that. An empty `/lib/firmware/` is a hard blocker here — `pil_boot()` fails at `request_firmware()`, and `subsystem_powerup()` (`subsystem_restart.c:773`) then **panics** unless `ignore_ssr_failure` is set.  Grep the driver that actually owns the path before making any claim about firmware. Exact file list, the `qcom,pil-self-auth` ops swap, the `qcom,sequential-fw-load` ordering, the rmtfs daemon contract, and the QMI-over-QRTR data plane are in `android-kernel-ci`'s `references/q6-subsystem-bringup.md`.
- **A symbol in the running kernel but in neither defconfig was pulled in by a transitive `select`.** When `zcat /proc/config.gz` shows a symbol your defconfig grep says is absent, do not conclude the device is on a different build — grep the tree for `select <SYMBOL>` and find the dependency that enabled it. Adding that symbol to the fragment is then redundant, and the honest commit removes it and says why. This has already produced one wasted `CONFIG_DEBUG_FS=y` recommendation; the real gap was a different symbol (`CONFIG_DYNAMIC_DEBUG`, `default n`) that the defconfig also did not name.
- **`subsys_register()` advertises a subsystem; it does not boot it, and there is no userspace way to boot one.** `subsys_device_fops` (`subsystem_restart.c:1411`) has only `.open`/`.release` — no `.ioctl`, no `.read`, no `.write` — and the sysfs attrs (`:382`: `name`, `state`, `crash_count`, `restart_level`, `firmware_name`, `system_debug`) are all read-only. `subsystem_get()` is `EXPORT_SYMBOL` with no wrapper. So "write a userspace trigger" is NOT an available fix — and neither is `subsystem_restart()`: `__subsystem_restart_dev()` requires `state == SUBSYS_ONLINE` and only WARNs otherwise, so it cannot cold-boot a subsystem that has never been up. The trigger has to be `subsystem_get()` reached from kernel code: an out-of-tree module calling the exported `subsystem_get()` is one shape, a writable sysfs attr or an `.unlocked_ioctl` on `subsys_device_fops` is another, and both need a build. Build a module trigger in (`=y`) rather than shipping a `.ko` — kmods carry a vermagic tag and refuse to load into a mismatched kernel. Do not promise the userspace program — check the fops table first. Full chain in `android-kernel-ci`'s `references/q6-subsystem-bringup.md`.
- **Enumerate and test every credential file before concluding access is broken.** Two same-length token files sitting side by side, one expired and one valid, is indistinguishable from a permissions problem until you call the API with each. `for f in <candidates>; do curl -s -o /dev/null -w '%{http_code}' -H "Authorization: token $(head -1 $f)" .../repos/<repo>; done` settles it in one command. An SSH permission error and an expired token look like the same wall from outside, and the fix for one is not the fix for the other.
- **ramoops region must be inside physical RAM.** wayne is 4 GB → ceiling `0xA0000000`. A region at/above it gives memblock nothing and `/sys/fs/pstore` stays empty no matter how correct the driver code is. Use `0x88F00000` (adjacent to `removed_regions1`, which ends exactly there).
- **`fs/pstore/ram.c` needs `RESERVEDMEM_OF_DECLARE(ramoops, "ramoops", ...)`** or the DTS node never becomes a platform device. Create the device in `ramoops_init()` (`postcore_initcall`) via `of_platform_device_create()` — the reserved-mem callback runs from `early_init_dt_scan_nodes()`, before the platform bus exists. Needs BOTH `of_reserved_mem.h` and `of_platform.h` (the latter for `of_platform_device_create`; missing it fails under `-Werror`).
- **DTS `compatible` order matters.** `compatible = "removed-dma-pool", "ramoops"` lets `kernel/dma/removed.c` claim the node in link order. Use `"ramoops"` alone.
- **SuSFS v2.3.0 is a two-file patch.** The `fs/namespace.c` hunks alone are incomplete — `fs/super.c` needs the `get_anon_bdev()` `SUS_MOUNT` branch, and `susfs_def.h` needs `DEFAULT_KSU_MNT_MINOR_DEV (1 << 12)`. Reference commits `cbae0965f3` + `c8cfa0a3e7` in `AstideLabs/android_kernel_xiaomi_sm8250`.
- **A single linked reference commit may be incomplete.** Pull the full compare, not just the linked commit — the follow-up commit often carries the missing half.
- **Read the whole compare, don't scan it.** When handed a compare URL, open every commit's patch and read the diff body. A title-only inventory lists the work without doing it, and it is the difference between "there are POC fixes in there" and knowing which ones this tree already has.
- **Verify a port is complete by CONTENT, not by SHA.** Upstream SHAs never match this tree's history (it backports through its own commits). Check the fix's substance is present instead: the terminating `{ }` ctl_table sentinel, `__maybe_unused` on SMT-only vars, zero `for (int ...)` declarations in the file. `git merge-base --is-ancestor` returning false means nothing here.
- **Check the built config before chasing a feature as a root cause.** Grep `resolved-config` for the feature's `CONFIG_` symbol first. A compiled-out feature (`# CONFIG_SCHED_POC_SELECTOR is not set`) cannot cause a runtime bug, no matter how suspect its code looks.
- **A `subsys-pil-tz` line proves a driver registered a subsystem, not that it booted — and its absence is meaningless unless you resolve which driver the node uses.** `subsys-pil-tz.c:1090` takes its name from `qcom,firmware-name`, so only the TZ-based nodes (venus, adsp/lpass, cdsp/turing, kgsl-hyp) ever print one. The modem binds `pil-q6v5-mss.c` via `compatible = "qcom,pil-q6v55-mss"`, a different driver that never registers with `subsys-pil-tz`. Calling the modem's absence from that list an "asymmetry" or boot evidence is a misattribution — resolve each node's `compatible` to its driver before reading anything into the list.
- **Registering a subsystem is not booting it, and nothing in the tree boots one for you.** `subsys_register()` only advertises an entry under `/sys/class/subsys/`; `subsys_boot()`/`rproc_boot()` have no in-tree callers outside unrelated drivers. A peer that is registered but never started is the EXPECTED state on a non-Android userspace, where no vendor component triggers the Q6 bring-up. Do not hunt for a kernel config that would boot it — name the missing userspace trigger instead. **But check whether a userspace trigger is even possible before promising one** — on this kernel it is not (see the `subsys_device_fops` rule above), so the fix is a source patch, and saying "write an init script" sends the next session down a dead end.
- **Retract a wrong lead in the same turn you discover it, before acting on it.** When a verification run kills a hypothesis you just offered, say which claim was wrong and what killed it BEFORE proposing the next step, and write the retraction into the fragment/commit comment so a later session cannot re-derive it. Three wrong leads were caught by device evidence this way (a no-op Makefile edit, "kernel can't fix it", a driver swap) — each one would have cost a build cycle if it had been shipped on its mechanism story.
- **A rule you already know is not a rule you applied.** The expensive misses on this project were not unknown unknowns — each one contradicted a pitfall already written in this skill, and the session passed the check that would have caught it because it stopped one step early: the URL was verified but the pin was never diffed; the patch applied cleanly but the ordered sequence was never replayed; the commit existed but its push state was never checked. Before reporting a submodule, patch, or fix as landed, re-read the governing pitfall above and name the specific command whose output proves it. "I checked the thing that was easy to check" is how a known rule gets skipped.
- **Verify first, then rank hypotheses — the reverse order is what produced every wrong lead here.** The pattern that cost the most: form a mechanism story from static analysis, rank it, and only then go looking for the check that would refute it. The correct order is cheap-check-first, because the cheap check is usually the one that kills the story. Three wrong leads in one session (a no-op Makefile edit, "kernel can't fix it", a driver swap) each had a one-command refutation available before they were proposed — `ls /sys/bus/platform/drivers/` on the device kills the driver swap; the resolved config kills the no-op. **If you have not run the check, do not rank the hypothesis it would kill.** Say "unverified" and run it.
- **Read a submodule file at the revision CI builds, not at whatever the working copy is checked out to.** A stray fetch or an earlier checkout leaves the submodule off the pin, and a file read from it then describes a different commit than the one CI clones — a gate that is unguarded at the pin can be guarded at the working copy's HEAD, or the reverse, and the diagnosis inherits the error. Assert the SHA before reading anything as evidence: `git -C <submodule> rev-parse HEAD` against `git ls-tree HEAD <submodule>` in the parent. This is the submodule form of "generate the patch from the PIN, not the checked-out HEAD", and it bites diagnosis exactly as it bites patch generation. **An uncommitted edit in the submodule is the same error with a quieter signature:** `rev-parse HEAD` still matches the pin, so the SHA check passes, while the bytes on disk are yours rather than upstream's. A gate you version-gated in a session that was later reverted is still sitting in the working tree, and reading it produces a diagnosis of a file CI never sees. Run `git -C <submodule> status --short` and require it empty before reading any submodule file as evidence — or diff the working tree against the pin (`git diff <pin> -- <path>`) and read THAT output. Restoring with `git checkout -- <paths>` is also the cleanup step that makes a later `git status` meaningful again.
- **A backup copied mid-edit is not a baseline.** Saving a file to `/tmp` "before" changing it, after already changing it once, produces a contaminated reference that makes `diff` report "no change" on a file you did change — and the confusion compounds when line numbers in your own excerpts match neither copy. Restore the baseline from git (`git checkout -- <path>` or `git show <rev>:<path>`), assert that revision is the one CI builds, and diff against that. This is the off-pin-read failure one level closer to home, and it is what an `anchor not found` on a file you believe you already read is telling you.
- **When a patch's anchor fails to match, suspect the file's revision before suspecting the patch.** An `anchor not found` on a file you believe you already read means the bytes on disk are not the bytes you inspected — most often because the working copy sits on a different revision than the one you read. Re-assert `git rev-parse HEAD` against the expected revision, restore from git, and re-extract the target region before concluding anything about the patch. Confirm a landed patch by re-reading the target region of the file, not by trusting a line-numbered excerpt whose offsets you have already been confused by.
- **Distinguish "the mechanism exists in the source" from "the mechanism is available on the device".** A header exposing every function a plan needs proves the code will link, not that the driver is compiled in. `drivers/soc/qcom/Makefile` gates each driver on its own `obj-$(CONFIG_...)`, and a driver whose CONFIG is unset is absent from the image entirely — so an API-compatibility check is not evidence the candidate driver runs on this hardware. When a plan depends on a driver being present, prove presence from `/sys/bus/platform/drivers/` or the running config, not from the source tree.
- **When the user states a goal, do not quietly narrow it.** "Make it as native as possible, whatever it takes" is a scope statement, not a request for options. Substituting a workaround because the native path is harder is a scope change the user did not authorize — state the native path and its cost, and let them choose to downgrade. Conversely, when they do choose a route, execute that route without re-litigating it each turn.
- **An approved option is the next action, not one of several.** When the user answers a menu you offered with "do option 1", that edit is the work of this turn — other pending items (a failed build to re-dispatch, a verification to run) do not displace it. If both must happen, do the approved one and name the other as queued; silently substituting adjacent work leaves the user's decision unimplemented while the turn looks productive.
- **Before proposing a patch, read the target function's real success path — and when the user challenges your reading of it, re-read the source instead of defending the story.** A mechanism story built from a neighbouring function or a remembered shape is not evidence about the function under discussion. The user often knows the subsystem's contract better than the code reading suggests, and "you're right, and I had the mechanism backwards" costs one turn while shipping an inverted fix costs a build cycle and the user's trust. Confirm the chain from the source the feature actually runs, then answer. **When the challenge carries two claims, verify both from source and answer each separately** — a challenge can be half right ("sh is the correct exec target" true, "ksud is debug mode" false), and agreeing with the whole of it or rejecting the whole of it leaves one half wrong in the record and one wrong patch in the tree.
- **When static analysis has produced two wrong leads in one investigation, stop deriving a third and ask for the device evidence that separates the candidates.** Each code-derived guess costs a build cycle and more trust than an honest "not yet found". Name the specific candidates, name the one command that discriminates them, and say plainly that the next step is evidence rather than another patch. This is the general form of the rule above it — a third guess is not diligence, it is the reflex that produced the first two.
- **Grade every fix by how far it was actually verified.** Applied, compiled, verified-in-dtb, and flashed-and-observed are four different states. Collapsing them is what produces the over-claim the user has to correct — say "verified compiled and linked, not verified running" when that is the truth.
- **Do not report a swap as done because the URL changed.** A `.gitmodules` retarget to the new project is not a content update: the gitlink pin stays where it was, so the tree carries the new project's OLD code. When the user says "you still haven't switched to X", check `git submodule status` and diff the pin against upstream `main` before agreeing or disagreeing — and report the pin delta (`ahead_by` + changed files), not the URL. Detail in `android-kernel-ci`'s `references/vendored-submodule-dependencies.md`.
- **When the user reports "still not on the new version", read the version line out of the build log before touching anything.** BakaSU prints its own identity at config time — `-- <REPO_NAME> version code: N` / `-- <REPO_NAME> version name: <tag>-<sha>[-dirty]@<repo>`. That line is ground truth for what CI actually compiled, and it settles the question in one grep instead of a submodule archaeology session. `grep -n 'version code\|version name' <build-log>`. A `-dirty` suffix there also means uncommitted changes were in the build, so the artifact does not correspond to any commit.
- **Read that version line BEFORE agreeing that a submodule swap landed, not after the user reports it twice.** The line is printed by every build, so it is available at the moment the swap is claimed — the first "the URL now points at the fork" claim is exactly when to grep it. Verifying the URL and the patch's apply-clean and stopping there is how a known rule gets skipped: the URL is the easy check, the version line is the one that answers the question. When the line names the parent project, the tree is running the parent's code under the fork's tag no matter what `.gitmodules` says.
- **A vendored project's version CODE is not an ordering signal — do not compare two pins by it.** `KSU_VERSION := $(shell expr 30000 + $(KSU_LOCAL_VERSION) + 700)` where `KSU_LOCAL_VERSION` is `git rev-list --count HEAD`, so the number is a function of how much history the clone happened to fetch, not of how new the code is. A `--depth 1` clone and an unshallowed clone of the same commit report different codes. Compare pins by commit position (`git merge-base --is-ancestor`, `git log <a>..<b>`) and by content, never by the printed version code. It bites hardest when comparing the CI build's printed code against a locally-fetched clone's code — those two histories differ, so the comparison is meaningless in both directions.
- **The manager's "kernel update required" gate lives in the manager APK, not in the kernel tree.** Nothing under `kernel/` or `userspace/ksud` in the submodule decides the minimum the manager accepts, so the required minimum cannot be read from this repo. When the user reports that prompt, say the gate is in the APK and ask for the exact version string it demands rather than guessing a target — and do not describe a kernel-side version bump as satisfying a check you cannot see.
- **A `-dirty` suffix in the version line is EXPECTED on this tree, not a defect.** `KSU_COMMIT_SHA` appends `-dirty` when `git diff-index --quiet HEAD` fails, and the build-time patches make the submodule dirty by design. Report it as cosmetic; the artifact corresponds to the pin plus the patches, not to a clean commit.** (1) A loader that opens a privileged path without holding an elevated cred across the open — on newer SELinux the open is denied, the function returns early, and its table stays empty, so every consumer fails. (2) A path that "falls back" to a non-privileged equivalent when its privileged helper is missing — it runs successfully and hands back an unprivileged result. Grep the feature for an early `return` between `filp_open` and its parse loop, and for `goto out`/fallback branches, before reading the code line by line. **Check whether a patch rewrote the SUCCESS branch, not just the fallback branch.** A hunk that changes the privileged exec target on the success path makes the feature *always* hand back an unprivileged result — it never falls back, because there is no privileged path left to fall back from. The symptom is a hang with no error: the privileged helper never runs, so the handshake that would produce the user-visible prompt never happens. Read every `memcpy`/assignment to the exec target in the function and confirm the success path still names the privileged binary.
- **A component's name is not its build profile — verify a "debug mode" claim from the cfg gate before agreeing with it.** Log-level macros in vendored userspace routinely resolve to a verbose level only under a debug-assertions cfg; release builds log at `Info`. Answer the fear with the gate, not with reassurance. On this tree: `ksud` is the su front-end, not a debug artifact — it claims the inherited su-session fd, sets uid/gid, SELinux context and cgroups, and wraps the tty before exec'ing `/system/bin/sh` itself, so the correct chain is `su → ksud → /system/bin/sh` with the kernel having already applied the root profile. A patch that makes `su` exec `sh` directly bypasses every one of those steps and hangs with no error. **The user does not want KSU in debug mode** — a standing constraint when bumping pins or patching, satisfied by keeping the build a release build, never by removing ksud.
- **A patched early-return bail kills its caller silently, so its symptom is indistinguishable from a hang.** An execve-hook patch that returns `-EINVAL` when its privileged helper is absent produces no message and no prompt — the shell just stops. When a patched feature goes quiet, put the bail in the candidate list beside the feature's own logic, and **after two wrong leads derived from reading code, stop proposing patches and ask for the device evidence that separates the candidates** (`dmesg | grep -iE "ksu|ksud|sucompat|allow_list"` separates a missing-ksud bail from an allowlist that never loaded). Static analysis wrong twice in one investigation is not converging; a third code-derived guess costs another build cycle and more trust than an honest "not yet found".
- **State what a fix does NOT cover before listing what is still open.** An MGLRU-off build cannot test the MGLRU freeze; say so at the handoff, not after the user asks why the freeze is still happening.
- **Unblock what you can instead of reporting a blanket blocked.** When one bug blocks a runtime check, look for a path around it (`/sys/fs/pstore` is world-readable) rather than listing both faults as stuck.
- **Porting across kernel versions: check the target tree's real signature before applying an upstream change.** A backport of a newer feature often carries newer-tree API assumptions. Example: upstream const-qualified `ctl_table` `proc_handler` args in 5.4+ (`typedef int proc_handler (struct ctl_table *ctl, ...)` became `const`), but 4.19's typedef is non-const — so 4.19 handlers MUST stay non-const or they won't match the typedef. Read `include/linux/sysctl.h` before "fixing" this.
- **Audit every symbol a ported hunk references before committing.** Grep each one against the tree's headers and confirm it is *defined* (not merely declared) somewhere that links into vmlinux. A patch that compiles upstream can reference a constant that exists nowhere in this tree (`DEFAULT_KSU_MNT_MINOR_DEV`).
- **4.19 has no `fs_context.h`** — adapt includes when porting from newer trees.
- **BakaSU uses the SuSFS inline hook on 4.19.** Do not switch to `CONFIG_KSU_MANUAL_HOOK`; the `inline_hook_check.mk` requirements are satisfied. (User-confirmed.)
- **Grep for the tree's OWN Qualcomm symbol names, never mainline's — this is a 4.19 QC tree and the names differ completely.** The modem PIL stack here is `CONFIG_MSM_PIL_MSS_QDSP6V5=y`, `CONFIG_MSM_PIL=y`, `CONFIG_MSM_SUBSYSTEM_RESTART=y`, `CONFIG_MSM_PIL_SSR_GENERIC=y`. Grepping the mainline names (`QCOM_Q6V5_MSS`, `QCOM_Q6V5_PAS`, `QCOM_MDT_LOADER`, `REMOTEPROC`, `QCOM_Q6V5_COMMON`) returns nothing and reads as "the modem plumbing is entirely absent" — the opposite of the truth, and a conclusion that would send a session off to port drivers that are already built in. Cross-check against a sibling defconfig in the same directory (`arch/arm64/configs/vendor/`) when a grep comes back empty: an empty result on one symbol is a naming question, not a finding. **Then resolve the DT node's `compatible` to the driver's `of_device_id` table** — `pil_modem: qcom,mss@4080000` is `qcom,pil-q6v55-mss`, served by `pil-q6v5-mss.c` under `CONFIG_MSM_PIL_MSS_QDSP6V5`, and the `qcom,pil-tz-generic` siblings (venus/adsp/cdsp) are a different driver entirely.
- **`CONFIG_QCOM_SCM` absent from every sdm660 defconfig is not a blocker — check what actually links before reporting a missing dependency.** `pil-msa.c` calls `scm_call2()`, and `drivers/firmware/Kconfig` gates the provider on `QCOM_SCM`, so a defconfig grep suggests a link failure. It is not one: the sibling defconfigs that demonstrably build and boot carry the same absence, and the provider is pulled in by another path. Report an unset symbol as a question with the check that settles it (`obj-$(CONFIG_...)` in the Makefile plus the Kconfig `depends`/`select` chain), not as a defect.
- **On 4.19 the rmtfs path is the UIO driver, not `rmtfs_mem`.** `CONFIG_UIO_MSM_SHAREDMEM=y` binds the `qcom,rmtfs_sharedmem@0` node (`compatible = "qcom,sharedmem-uio"`, `qcom,client-id = <1>`) in `sdm660.dtsi`. `CONFIG_QCOM_RMTFS_MEM` compiles `rmtfs_mem.c`, which needs a `qcom,rmtfs-mem` node with a real base+size `reg` and `no-map` that does not exist in any local sdm660 tree — enabling it produces a driver with nothing to bind. Do not "fix" rmtfs by switching symbols; the gap is the missing userspace daemon over `/dev/uio*`.
- **A reserved-memory node with a zero base `reg` is rejected by its driver, not defaulted — so a node that looks present binds nothing.** `qcom,rmtfs_sharedmem@0` carries `reg = <0x0 0x200000>` (base 0), and `msm_sharedmem.c:153` returns `-EINVAL` on `shared_mem_pyhsical == 0`, so the UIO device never appears and the daemon has no device to open. Grep the probe for an explicit `== 0` / `< 0` guard on the base before believing any node carrying a `reg` is live. Repair it by deriving a real region from the reserved-memory map — enumerate every sibling region's `reg`, find a provably free gap, align it for `qcom,guard-memory` — never by inventing an address. `git apply --check` proves the patch applies; only a boot proves the region is usable, and `scripts/fdt_dump.py` prints every `/reserved-memory` child's `reg` so the overlap check is one command.
- **A subsystem node being `status = "ok"` in the SoC dtsi is not the same as it being enabled for THIS device.** Check the device's own overlay for an override before concluding the node is live. wayne's `xiaomi/wayne.dtsi` and `longcheer/wayne/wayne-common-base.dtsi` carry none for `pil_modem` — that is the answer, and it is worth grepping for `&pil_modem` across the device dtsi tree rather than assuming.
- **Do not conclude "a config change, not a porting project" from the defconfig alone — grade it from the resolved config plus the userspace gap.** `CONFIG_KALLSYMS_ALL=y` sitting in the defconfig while `CONFIG_DEBUG_KERNEL` is unset is silently dropped by Kconfig (`depends on DEBUG_KERNEL && KALLSYMS`), which is exactly why the symbol-export fix is the correct integration. The kernel side can be complete and the feature still dead: the modem firmware, drivers, DT nodes, and reserved memory can all be present and correct while nothing boots the subsystem and no userspace daemon serves its shared-memory requests. Name the userspace gap explicitly rather than implying the kernel side settles it.
- **`sdm660-mtp-wayne.dts` reaches ramoops via** `xiaomi/wayne.dtsi` → `longcheer-sdm660.dtsi` → `longcheer-sdm660-base.dtsi` → `longcheer-sdm660-ramoops.dtsi`. Resolve `#include` relative to the *including* file's directory, not a single base dir.

## Debug the whole subsystem set at once, against the roadmap

The build-flash-boot-dmesg cycle is the expensive part, so never spend a turn requesting one grep. When a subsystem blocks, ask for every related subsystem's state in ONE paste, and surface the milestone roadmap state in the same answer — blockers are usually shared. `scripts/wayne-diag.sh` collects build, config, dmesg, driver bindings, DT, firmware, and network state in a single busybox-safe pass; copy it to the device and run it.

**A snapshot earns its keep by killing bad patches, not by being fast.** Two driver-swap and instrumentation proposals that looked well-supported were refuted by the device report before either cost a build. Ask for the snapshot BEFORE writing a patch you cannot verify locally, and re-derive every ranked hypothesis from what it shows instead of defending the earlier analysis.

**Read the snapshot's driver-binding and config sections before trusting any source-tree conclusion about the running kernel.** `/sys/bus/platform/drivers/<name>/` present vs absent, and `zcat /proc/config.gz`, are the only ground truth for what is built and bound — a `compatible` match in the tree says nothing about which driver the image actually carries, and a defconfig grep says nothing about which symbols the kernel was built with (transitive `select` can add symbols neither defconfig names). Both directions have produced a wrong plan on this project.

**Transfer the script through git, not through chat.** A multi-line shell script pasted into a busybox `ash` prompt gets corrupted by line-wrapping — quotes and brackets mangle, and a single dropped character invalidates the whole thing. Commit the script to the CI repo and have the user `wget` it on the phone; base64 is the wrong escape hatch too (a 3 KB script is ~4 KB base64, one bad character and it is garbage).

**Firmware staged to `/lib/firmware/` does not survive a rootfs reflash.** When the diag report's firmware section comes back empty, say so explicitly — it is a second independent fault sitting behind the first, and it will surface the moment the first is fixed.

Before proposing a fix for one subsystem, check which other milestones it touches. A dead QMI transport takes the modem, the WLAN, and every other subsystem on that transport with it, so a "Wi-Fi bug" can be a roadmap-wide blocker — and a milestone that looks blocked may have a route around it (the whole service stack runs over USB RNDIS with no Wi-Fi at all).

**"Full working" is the goal, not "as far as it goes."** Do not downgrade a milestone to a known limitation in order to close it out. State the blocker, name what would clear it, and offer the route around it as a choice with its cost stated — then let the user pick.

**"Native" means native: do not lead with the workaround.** When the native path is still open and unsolved, a dongle / USB-RNDIS / different-chip route is a fallback, never the primary recommendation — and it must not be listed first. The user's goal is a fully native firmware with the built-in hardware working, and they will reject a workaround offered as the plan; offering one anyway spends a turn and reads as giving up. State the native path, its cost, and its blocker, and let them ask for the fallback.

**Grep a print string to its source file before reading any meaning into a dmesg line.** A line's prefix names the DRIVER that printed it, not necessarily the subsystem the line is about — and chasing a distinctive string to the wrong file first is easy. `grep -rn '<literal substring of the message>' drivers/ --include=*.c` resolves it in one command and prevents a whole theory from being built on a misattributed line. Do this BEFORE ranking a dmesg line as evidence.

## Build watcher pattern
Poll `actions/runs/<id>` every 60s, append status to a scratch file, exit on `completed`. Run as a background terminal with `notify=true` so completion pings without holding the turn. Keep the artifact-printing snippet in a heredoc — backslash-escaped quotes inside an inline `python3 -c` break.

- **`workflow_dispatch` returns 204 with an empty body — the run ID is not in the response.** Poll `actions/runs?per_page=3` after the POST and match on `event: workflow_dispatch` with a `created_at` after your dispatch time. Never watch a run ID you did not read out of that poll: a guessed or stale ID watches the previous run and reports its status as your build's.
- **Launch the watcher with `background=true, notify=true`, not a trailing `&` inside a foreground call.** A `... &` inside a normal terminal call detaches the process from the tool's tracking, so it cannot be polled or waited on and the call itself can return a bogus exit code. Write the watcher to a scratch file first (a heredoc is fine there), then run it as its own background terminal call. **A watcher that exits 127 means the script file was never written** — the heredoc call was rejected, so the background process had nothing to execute. `ls` the script before believing the watcher ran, and re-issue the write as its own call.

## Read the published log before theorising about a slow or dead build
A step's `in_progress` state carries no information about whether work is
happening. Do not explain a long-running step from the step list — the log is
the only evidence, and it is published even when the run fails:

```sh
tail -20 <scratch>/build_result.txt          # watcher output
curl -sSL https://raw.githubusercontent.com/<kit>/build-logs/<log>.log
```

On hosts without the `gh` CLI, every `gh api` call in this skill works as
`curl -sS -H "Authorization: token $TOKEN" <same-url>` with
`TOKEN=$(grep -m1 oauth_token ~/.config/gh/hosts.yml | awk '{print $2}')`.

Traps that all cost a full turn each on this project:
- **A step's success says nothing about the step that fails.** "Steps 1-17
  passed, so config was clean" is wrong whenever the failing step performs its
  own config pass — the kit's build step runs `make $KERNEL_CONFIG` itself, so
  the workflow's separate config-injection step succeeding proves nothing about
  it. Attribute a failure to the step that FAILED, then read that step's log.
- **A `cancelled` conclusion is not a cancellation.** GitHub retries a job that
  dies on the runner and reports `run_attempt: 2` with `run_started_at` moved
  forward; the watcher catches the transient `cancelled` during the handoff and
  reports a dead build that is actually running. Re-read
  `run_attempt`/`run_started_at` before reporting a cancellation.
- **`run_attempt` and the step list cannot distinguish compiling from hung.**
  Both look identical from outside. Only the log can, and a log with zero
  compiler output and a trailing prompt means not one file was ever compiled.
  Never report a cold-cache or slow-runner theory without the log in hand.
- **A cancelled run's logs endpoint can return an empty archive.** The
  `actions/runs/<id>/logs` zip comes back ~22 bytes with no entries for a run
  killed mid-step. Do not read that as "no log exists" — the same output is on
  the `build-logs` branch (`build-<sha>.log`, `config-<sha>.txt`) and in the
  run's `build-log-failure` artifact, both of which survive the cancellation.
- **A `gzip: stdin: unexpected end of file` or `tar: Unexpected EOF in archive` inside a download step is a truncated CDN tarball, not a build failure.** The toolchain archives come from third-party release CDNs and truncate under load. The signature is decisive: the step dies during extraction with zero compiler output, so nothing reached the kernel and no source, config, or patch is implicated. Re-dispatch the same branch and inputs instead of opening a diagnosis, and report the failure as infrastructure — a run that died at step 9 of 30 invites the assumption that the code was at fault, and saying so plainly stops the next session from re-litigating a defect that never existed.

When a theory is formed before the log is read, say which evidence would
confirm it and go get that evidence — a plausible mechanism stated as a finding
is the failure mode this rule exists to prevent.

## Verify against the RUN, then decode the PUBLISHED file
- The run's `artifacts` list is the authoritative size for what CI produced. Compare it
  against the `kbuilds` file before calling a mismatch a problem — a `kbuilds` file whose
  size matches neither the current nor the previous run means a different step published
  it, not that the download is truncated.
- **Never call a `kbuilds` file corrupt from a decompression error alone.** `Image.gz-dtb`
  is a gzip stream with a raw dtb appended, so `gzip.decompress()` on the whole file
  raises `BadGzipFile` while the gzip header at offset 0 is perfectly valid (`1f 8b`).
  This reads as a corrupt download and sends you chasing a phantom. Locate the appended
  dtb first, then decode; `scripts/fdt_dump.py` does both.
- A few-KB size difference in the gzip payload with a correct decoded dtb does not
  change what you would flash. Say so plainly rather than implying the build is suspect.
- Download the file twice and compare sizes before concluding the remote is inconsistent —
  a transient partial read looks identical to a real mismatch.

## Before editing the kit workflow, check whether the fix already landed
A request to "fix the workflow in the kit" can arrive after the kit has already
been edited several times for the same defect. Read the kit's own commit history
and current run status BEFORE pushing anything:

```sh
TOKEN=$(grep -m1 oauth_token ~/.config/gh/hosts.yml | awk '{print $2}')
curl -sS -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/<kit>/commits?sha=<branch>&per_page=15"
curl -sS -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/<kit>/actions/runs?per_page=10"
```

On hosts without the `gh` CLI, every `gh api` call in this skill works as
`curl -sS -H "Authorization: token $TOKEN" <same-url>` with the token above.

Three things this catches that a fresh edit would undo:
- **The fix is already in HEAD.** Several commits may have attempted the same
  change and the current tip may already be green. Report the current state
  before proposing an edit, or you push a duplicate into a working pipeline.
- **The fix was tried and reverted for a reason.** A commit message that reverts
  a prior fix names why it failed — read it before re-attempting the same shape.
  Re-landing a reverted fix is the most expensive kind of duplicate work.
- **The failure you were asked to fix is not the failure that is happening.**
  Match the run's `head_sha` to the commit you think is deployed, and read the
  failing step's log, before attributing the failure to a mechanism.

## When the user's report and the repo disagree, re-verify before acting
A handoff message describing a live defect is a snapshot, not the current state.
The repo keeps moving while you verify, and a fix requested in that message may
already be shipped, reverted, or superseded. Re-read the kit's history and run
status (see "Before editing the kit workflow") and report what the evidence shows
BEFORE proposing or pushing an edit — including when the answer is "this is
already done and green".

The failure mode this prevents: the diagnosis in the handoff is correct, so it is
treated as current, and a duplicate fix is pushed into a pipeline that already
works. Correct diagnosis of a past state is still a wrong action on a present one.

**When the user reports a RUNTIME symptom, trace the symptom before auditing the
version.** "su freezes", "no Shell su prompt", and "still not the new version"
are different defects with different owners, and a version audit answers none of
the runtime ones. A hang with no error means a code path never completed, so grep
the feature's function for what it execs and what it returns before opening the
submodule history. The version question and the behaviour question are settled by
different evidence: the version line in the build log settles the first, the
function body settles the second.

When the user names BOTH in one message, treat them as two workstreams and say
which one the current build already answers. Reporting a successful version bump
as if it addressed a freeze is the over-claim the user has to correct.

When the current state is green but the defect class is still live (a fix that
works only because the tree happens to be complete today), say both: the build
works now, AND the next new symbol re-opens it. Offer the hardening edit as a
choice with its CI cost stated, and do not push it into a green pipeline without
the user's say-so.

## Device-check commands that need no root
`/sys/fs/pstore/` is mode 0444, so `adb shell ls /sys/fs/pstore/` works with su broken.
Use it to confirm pstore independently of the SU problem; pairing it with `adb shell su -c id`
separates the two faults instead of letting one mask the other.
When a runtime check is blocked by another bug, state which check is unblocked by
working around the blocker rather than reporting both as blocked.

## Bumping a vendored submodule pin: check the hard build gates FIRST
Bumping a pin to upstream `main` looks like the obvious way to get a vendored
project's fixes, and it can fail the build outright for reasons that have nothing
to do with the fixes. Decide bump-vs-patch HERE, before reaching for the
patch-based fallback below — a bump is the cleaner fix when it is possible.

- **Check whether the bump is already done before doing it.**
  `git ls-remote <upstream-url> main` against `git ls-tree HEAD <submodule>`
  settles "is the pin the tip?" in one command, and the answer is often yes — a
  stale reported version then comes from an older build's artifact or log, not
  from the pin. When the pin is already the tip, say there is nothing newer to
  bump to and show the version line from the build log as the proof, instead of
  opening a patch investigation for a bump that already landed.

```sh
git -C <submodule> fetch --depth=200 <upstream-url> main
git -C <submodule> diff --stat <pin> FETCH_HEAD -- kernel/   # kernel-side churn only
```

Two gates decide whether a bump is even possible:

- **A blocking commit is a snapshot, not a permanent state — re-check it against the current upstream tip before declaring a bump impossible.** Upstream suspends a feature by adding `$(error Please wait ...)` to a compat file its `Kbuild` includes, and later unsuspends it by deleting that line inside an unrelated commit. A blocker recorded in an earlier session — or in this skill — describes the repo as it was then; carrying that conclusion forward without re-reading the file at the current tip is how a bump stays "blocked" for weeks after it became possible. Re-run the check every time:
  ```sh
  git -C <submodule> show FETCH_HEAD:<path/to/compat.mk>
  git -C <submodule> log --oneline --all -S '<the error string>' -- <path>
  ```
  The `-S` pickaxe names BOTH the commit that added the gate and the one that removed it, so one command settles whether the blocker is still live.
- **An unconditional `$(error ...)` in a version-gated `.mk` is a hard blocker while it is present.** Upstream projects suspend a feature by adding `$(error Please wait ...)` to the compat file their `Kbuild` includes when the feature's config symbol is set. If this tree sets that symbol and ships the feature's source, the include fires and the build dies before compiling a file. Grep the upstream range for `$(error` and check whether the guarding symbol is enabled in this tree's defconfig BEFORE promising a bump — a suspended upstream feature is not a bumpable one. **Read the surrounding `ifeq`/`else` branches too:** a gate that only errors when the feature's source file is ABSENT does not fire on a tree that ships it, so "there is an `$(error)` in that file" is not the same finding as "that `$(error)` will fire here".
- **A gate that looks like a blocker can be a false positive on an older kernel — but ONE dead version guard is not proof the symbol is unused.** A vendored project's symbol-export check is written against the newest kernel it supports, so it can require a symbol to be non-`static` when every path resolving that symbol is compiled out on this tree. Before de-`static`-ing anything to satisfy the gate, grep the feature source for EVERY reference to the symbol and classify each by its own guard — one file can resolve the same symbol at several sites under DIFFERENT guards (`#if LINUX_VERSION_CODE >= 6.6` at one, `#ifdef CONFIG_KALLSYMS_ALL` at another), and the site this kernel takes may not be the one you read. **The link step is the arbiter:** if the symbol were genuinely unreferenced the linker would never name it, so `undefined symbol` is the refutation of a false-positive conclusion, not a new defect to diagnose. When the gate really is dead here, version-gate the check to match the code and ship it as a build-time patch — exporting a symbol for a caller that does not exist changes the kernel to satisfy a build system, not to fix a defect.
- **A symbol-export check is a textual grep that runs before the compiler, so a compile-side fix is unreachable while it fires.** `static_export_check.mk`'s `check_symbol_export` greps the kernel source for the literal string `static <type> <symbol>` and calls `$(error)` when the string is present; most of its entries carry no version guard at all. The consequence is an ordering trap: a `#else` branch that hard-links a `static` symbol gives `ld.lld: undefined symbol`, you fix the `#else` branch, and the build still dies at the same gate — your fix was never compiled. Read the gate before writing any compile-side fix, and note that the gate's own message names the file and the integration it wants.
- **Simulate the gate's greps locally instead of reasoning about them.** Each check reduces to one `grep -q -F '<literal string>' <file>`, so the whole gate is verifiable in the sandbox before pushing: run the same greps against the real kernel sources and confirm every string is absent. Do the same for the gate's own skip conditions — `grep -q "struct selinux_state " <header>` decides whether an entire block of five checks runs, so one grep can retire five blockers or activate them. A gate that is one grep per entry cannot be argued with; run it.
- **Anchor an insertion on unique preceding context, never on a function name alone.** A name that appears as a forward declaration AND as a definition has no braces at the first site, so brace-matching from it walks on into the next function's body and lands the insert in unrelated code — and the insert reports success. Match the definition's own doc comment (or another unique preceding span) and brace-match from there, then read the insert's neighbours before committing.
- **A defconfig line is intent, not fact — check the resolved config before trusting a guard that reads a symbol.** `CONFIG_X=y` in a defconfig is silently dropped when `X`'s Kconfig entry carries `depends on` something that is `n`, so a gate whose skip condition is `ifneq ($(CONFIG_X),y)` runs even though the defconfig says it should not. `KALLSYMS_ALL` depends on `DEBUG_KERNEL`, so a perf defconfig that sets it without `DEBUG_KERNEL` resolves to a config carrying neither. Grep the resolved config — `kbuilds/config.txt` from the last run, or `out/.config` — for the symbol before concluding a guard was honoured.
- **`CONFIG_DEBUG_KERNEL=y` is prohibited on this tree, unconditionally — "it is the declared dependency of the symbol I need" is NOT an exception.** The user's rule is absolute, and the argument "there is no other way to reach the symbol except through its own dependency" is precisely the rationalization it exists to block. A build that needs a debug umbrella to link is a build with a wrong integration, not a build that needs the umbrella. `KALLSYMS_ALL` carries `depends on DEBUG_KERNEL && KALLSYMS`, so a defconfig that sets it without `DEBUG_KERNEL` resolves to neither — and the pull toward enabling the umbrella at that moment is strong, because the dependency chain reads as a proof. It is not; it is a description of why the integration is wrong. Do not offer it as a narrow gate, do not offer it as a temporary probe, and do not commit it "while a better route is found" — commit it and the user has to reject it, which costs a build and their confidence. Verify any claim that a symbol "survived" by grepping the RESOLVED config for it, never the fragment.
- **A `#ifdef CONFIG_KALLSYMS_ALL` / `#else` split that hard-links a `static` symbol is fixed by moving the `#else` branch onto the runtime resolver, not by enabling `KALLSYMS_ALL`.** Base `CONFIG_KALLSYMS` already covers every function symbol, because functions live in `.text`; `KALLSYMS_ALL` only adds DATA symbols. So when the no-`KALLSYMS_ALL` branch takes the address of a `static` function and the linker names it `undefined symbol`, replace the address-of with the same `ksu_resolve_symbol_for_functable_hook("<name>")` call the `KALLSYMS_ALL` branch already uses — it walks `kallsyms_on_each_match_symbol`, which is exported under plain `CONFIG_KALLSYMS`. Two checks make it safe: (a) confirm the symbol is a FUNCTION by grepping its definition in the kernel tree, so base kallsyms covers it; (b) confirm the inserted call is byte-identical to one already compiling in the same function, which is your proof it links. State in the commit that this is the non-debug route, because the next reader reaches for the dependency first. **A resolver patch is not sufficient on its own when the project also ships a symbol-export check** — that check is a textual grep on the kernel sources that runs BEFORE any file compiles, so it aborts the build and the patched `#else` branch is never reached at all. When it is live, the documented integration is the fix: drop `static` from both the forward declaration and the definition and add `EXPORT_SYMBOL`. That makes the `#else` branch link natively, which retires the resolver patch entirely — one kernel-side change instead of a submodule edit plus a build-time patch.
- **Before patching a branch, prove which branch actually compiles — a `#else` block can carry externs its compat defines switch off.** The same region often references several symbols, and only one is the link error because the others sit behind a version or compat guard. Resolve the chain instead of patching whatever the linker happened to name first: a compat header defines its `KSU_COMPAT_USE_*` macro from a `KSU_COMPAT_HAS_*` macro that a compat `.mk` sets when a struct or symbol exists in this tree (`grep -c 'struct selinux_state ' <header>` → `kernel_compat.mk` → the compat header). An `extern` under a false guard is never compiled, so "fixing" it adds a hunk for a symbol that was never referenced. The linker naming one symbol is evidence about ONE site, not about the block.
- **Read the kernel-side churn, not the repo-wide stat.** A large
  `files changed / insertions` total is usually userspace (Rust `ksud`, manager,
  CI) that never links into vmlinux. Filter with `-- kernel/` and read that diff
  before judging risk. A scary-looking `+278` in one kernel file can be entirely
  `#ifdef CONFIG_COMPAT`-gated additive code for a platform this tree does not
  build, which makes the bump far safer than the raw number suggests.

When a bump is blocked, say so and offer the real alternatives with their cost
stated — pin to a commit BEFORE the blocking change, or keep the pin and patch
the specific fix (next section). Do not describe a cosmetic patch (a version
string, a `REPO_NAME`) as if it were the fix: it makes the log look right while
the device stays broken, which is the failure mode the user has to catch.

### Picking the pre-blocker commit, then trimming the patch to match

Enumerate the range in commit order and take the one immediately before the
blocker — the blocker's index minus one, not "somewhere earlier":

```sh
git -C <submodule> log --oneline <pin>..FETCH_HEAD --reverse | nl   # locate the blocker
git -C <submodule> rev-parse <candidate-sha>
```

Then check EACH wanted fix for native presence at that candidate before writing
any patch:

```sh
git -C <submodule> merge-base --is-ancestor <fix-sha> <candidate> && echo NATIVE || echo MISSING
```

A pre-blocker commit routinely carries some of the wanted fixes and not others,
because upstream lands them interleaved with unrelated work — the fix you need
most can sit just past the gate. **Trim the patch to only the fixes that are
MISSING at the new pin.** A hunk whose change is already native at the pin fails
on a context mismatch, and a half-applied one double-applies the native half.
Report which fixes rode the bump and which still ride the patch: the user needs
to know the pin and the patch now carry different halves of the same fix.

### When a bump makes the build-time patches obsolete

A pin bump that carries a fix natively turns its patch file into dead code, and deleting the file is only half the removal — the `$(shell ...)` hook that applied it may carry other work chained onto the same line:

```sh
$(shell [ -f patch.patch ] && cd $(srctree)/KernelSU && patch -p1 ... ; cd $(srctree)/KernelSU && git fetch --tags origin ...)
```

The `;` after the patch command means the tag fetch runs unconditionally *today*, but it sits inside a hook whose stated purpose is the patch. Delete the patch file and the next reader reasonably deletes the whole line — silently killing the fetch that `Kbuild`'s `git describe` depends on, which drops the printed version string to the hardcoded fallback. **Read the entire `$(shell ...)` line for chained side-effects before deleting any part of it, and re-anchor the surviving work as its own unconditional line with a comment saying why it is unconditional.**

## Shipping a submodule fix the pin cannot carry
When a pinned submodule is too far behind to bump safely and its remote is
unwritable, ship the fix as a patch applied at build time: add a
`patch -p1 -N --fuzz=0` sibling to the existing `$(shell ...)` line in
`drivers/Makefile`. Four traps, all hit here:
- **The patch file is gitignored** — a blanket `*.patch` rule refuses `git add`, so
  the commit lands without it and CI silently never applies the fix. Use
  `git add -f` and confirm with `git diff --cached --stat`.
- **Generate the patch from the PIN, not the checked-out HEAD.** A stray fetch
  inside the submodule moves it off the pin and `git diff` then captures the whole
  upstream delta. `git -C <submodule> checkout <pin>` and assert the SHA first.
- **Anchor every patch on the state the PREVIOUS patch produces, not on the pin.**
  When `drivers/Makefile` applies several patches in sequence, each one rewrites
  context the next one's hunks depend on. A patch generated against the pristine
  pin fails to apply once an earlier patch has touched the same function. Read the
  `$(shell ...)` lines in order, replay that exact sequence in a scratch clone, and
  generate the new patch from the resulting state — one context line differing is
  enough to reject a whole hunk.
- **Verify the WHOLE ORDERED SEQUENCE against a fresh `--depth 1` clone forced to
  the pin** — the exact state CI produces — applying each patch in the same order
  `drivers/Makefile` does. `git apply --check` on one patch in isolation proves
  nothing about the second. `git apply --check` is also the local verification path
  of choice: the `patch` binary the `$(shell ...)` hook invokes runs on the CI
  runner and may be absent in the dev sandbox, so a `patch --dry-run` that cannot
  run is not evidence the patch is bad.

**A `|| true` patch hook turns a failed apply into a silent half-patch, and a
half-patch is worse than no patch.** The
`$(shell ... patch -p1 -N --fuzz=0 < ... >/dev/null 2>&1 || true)` shape discards
both the error text and the exit code, so a context mismatch applies the hunks
that DO match and drops the ones that don't. The build then compiles a broken
intermediate state instead of failing at the apply.

The signature is a compile error naming a symbol the patch was supposed to delete:
`use of undeclared identifier 'X'` where the declaration-removing hunk applied and
the use-removing hunk did not. When that error appears on a patched submodule file,
suspect a swallowed apply before suspecting the patch's content, and confirm by
replaying the ordered sequence in a scratch clone.

**Fix a swallowed apply by regenerating the patch from the post-predecessor state,
not by loosening the apply.** Copy the scratch clone to the write-safe root, apply
the predecessor patches, hand-edit the target file there, then `git diff` the
result into the new patch — and drop any hunk that belongs to a predecessor
(`git diff` picks up their changes too, which silently re-applies them). Then
re-verify the whole ordered sequence from a pristine clone.

**When a regenerated patch still fails, diff the failing hunk's context lines
against the file instead of regenerating from another guess.** A second
regeneration from a slightly different base fails the same way and burns a cycle.
The mismatch is almost always ONE context line at the hunk's tail, where the
predecessor's edit landed. Print the hunk and the file's real lines side by side
and read them against each other:

```sh
sed -n '/^@@ -368/,/^diff --git/p' <patch> | head -30   # context the hunk expects
sed -n '366,392p' <submodule>/kernel/feature/x.c        # what the file actually has
```

Correct that one line in the patch, then re-verify the whole ordered sequence from
a pristine clone. The predecessor rewrites the tail of the same function the patch
rewrites, so the trailing context is the line that differs — a removed line the
predecessor already changed (`ksud_path` vs `sh_path`) rejects the entire hunk
while looking identical at a glance.

**Before regenerating a patch, decide whether the PREDECESSOR is itself correct.**
The ordered-sequence rule above assumes every predecessor is a patch you want to
keep. When a predecessor turns out to carry a harmful hunk, fixing only the new
patch's context anchors the fix on top of the harm — the new patch then applies
cleanly and the defect survives. Audit each predecessor's hunks for what they do
to the SUCCESS path, not just whether they apply:

```sh
cat <predecessor>.patch          # read EVERY hunk, including the ones you did not write
```

When a predecessor is partly harmful, split it: keep the legitimate hunks, drop
the harmful one, then regenerate the successor against the corrected state. A
predecessor inherited from an earlier session is not automatically a patch you
endorse — it is a file in the repo that has never been audited against the
current symptom.

**An unreachable `goto` label left behind is a warning, not a defect.** Removing
the `goto out` that used to jump to a label leaves `out:` unused and the compiler
emits `warning: unused label 'out' [-Wunused-label]`. The same warning fires on
`fs/open.c` and `fs/stat.c` from the SuSFS hook pattern, so it is ambient noise on
this tree. Leave the label rather than diverging further from upstream, and say
it is cosmetic when reporting the build.

**Audit the inherited patch set before trusting any runtime conclusion from the
artifact.** A build-time patch carried over from an earlier session has never
been read against the current symptom, and a harmful hunk in it produces a green
build with a broken runtime — the one failure CI cannot show you. Read the apply
order from `drivers/Makefile`, then read every hunk in every patch it names and
classify each by what it does to the SUCCESS path. Procedure, the
hunk-classification rules, and the split-a-partly-harmful-patch recipe are in
`references/build-time-patch-audit.md`.

**Do not modify a patch set in response to an undiagnosed runtime symptom.** A freeze, a hang, or a silent failure has several candidate owners, and an edit shaped to the first mechanism story can invert the defect — the hunk that "removes the wrong exec target" can be the hunk that installs it. Diagnose first (the function's real success path, the device's `dmesg`), and when that evidence is not in hand, say the symptom is undiagnosed rather than shipping a change that only looks considered. The patch set is not a place to experiment, and a green build proves nothing about which way the runtime now fails.

## Attribute a CI failure to the right commit before diagnosing it
A kit repo's `head_sha` is the kit's SHA, not the kernel source's. If
`gh api repos/<owner>/<source-repo>/commits/<sha>` returns 422, the failure is not
your build — a push to the kit's own branch fires runs that have nothing to do with
your branch. Check `event`/`head_sha`/`head_repository` before reading any log.

A build that dies with no compiler error and a log ending mid-prompt
(`* Restart config...` then `Symbol [Y/n/?] (NEW)`) is `make` waiting on stdin.
The full diagnosis procedure — reading the prompt's shape, which make modes
prompt, and the correct fix shapes — is in `references/kconfig-prompt-hang.md`.
Three rules from it are always-on:

- **A `(NEW)` tag on a symbol that IS in the committed defconfig means the symbol
  is unreferenced** — nothing `select`s it and nothing `depends on` it — so
  kconfig treats it as new regardless of the defconfig line. Confirm with
  `git show HEAD:<defconfig> | grep <SYM>` (rules out a missing line) AND
  `grep -rn 'select <SYM>\|depends on <SYM>' <tree>` (proves the real cause).
- **Never write `yes '' | make ... olddefconfig` in a step that sets
  `set -o pipefail`.** `olddefconfig` finishes without consuming stdin, `yes`
  takes SIGPIPE on its next write, and `pipefail` turns that 141 into a step
  failure. The log shows `# configuration written to .config` immediately
  followed by `yes: standard output: Broken pipe`, which reads as a build error
  but is a pipeline artifact — the config pass itself succeeded. Use
  `make ... olddefconfig < /dev/null` instead. Confirm the trap locally with
  `bash -c 'set -o pipefail; yes "" | true; echo $?'` → 141.
- **A single-step `make $KERNEL_CONFIG` + plain `make` flow is not prompt-proof,
  only prompt-free.** The plain `make` invokes `syncconfig`, and `syncconfig` is
  the mode that prompts. It stays quiet only because the defconfig step already
  left `.config` complete. The next new symbol `conf` cannot materialize puts the
  prompt straight back into the build step, so add an explicit
  `olddefconfig < /dev/null` after the defconfig step to kill the class rather
  than this instance.

A headless runner has no TTY, so this hang never errors and never times out on
its own; it burns the full job duration and surfaces as `cancelled`, which reads
as an infrastructure flake rather than a config bug.

**Suppressing a hard gate unmasks the layer behind it — do not read the newly-visible error as a regression your fix caused.** A `$(error ...)` in a `.mk` aborts the build before the compiler or linker ever runs, so everything behind it is invisible. Clear that gate and the next defect surfaces immediately, looking like the fix broke something: a gate that demanded a non-`static` export was version-gated away, and the very next run died at link with `undefined symbol` on the same symbol. The error was always there; the gate was hiding it. When you remove a gate, say in the handoff that the run now tests the layer behind it, and read the new failure as the next item in the chain rather than as damage — reverting a correct fix because its consequence surfaced is the expensive misreading.

**A `$(error ...)` gate that fires on a symbol this tree does not use is a symptom of a config that did not resolve, not necessarily a bad check.** Before concluding a vendored gate is wrong, check whether the config symbol that would have skipped it ever reached the resolved config at all — `Kbuild` guards these checks with `ifneq ($(CONFIG_X),y)` precisely so trees that do not need them are exempt, and an unmet `depends on` silently drops the exemption. Grep the resolved config for the guard symbol first; when it is absent, the fix is making the symbol stick, and the gate needs no edit at all.

