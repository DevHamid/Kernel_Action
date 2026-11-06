# Control Build: isolating a device bug between backports and the base

Use when a device hangs/freezes and you must determine whether the user's kernel
backports are the cause, or the stock base/ROM/userspace is. Applies to any
kernel where the user's tree = an unmodified upstream base + a set of backports.

## Why a full pure-stock control, not one-revert-per-branch bisects

A bisect branch that reverts a single backport only proves that one revert does
not fix the bug. If the symptom is caused by multiple backports interacting, or
by the base/ROM/userspace itself, those all stay red and tell you nothing. The
clean discriminator is a full A/B:

- Branch A = user's kernel (base + backports)
- Branch B = control: the UNMODIFIED upstream base, zero backports

If B also freezes → bug is in base/ROM/userspace; backports exonerated.
If B does not freeze → backports are the culprit; bisect them.

## Procedure

1. Identify the true stock base: the unmodified lineage the ROM ships (e.g.
   San-Kernel `stable-release` for DroidSpaces 4.19 sdm660).
2. Create the control as a SEPARATE isolated branch off that base.
3. Use the stock defconfig (e.g. `vendor/wayne-oss-perf_defconfig`), not the
   user's modified one.
4. Verify the tree actually carries stock markers before calling it a control:
   - `CONFIG_SCHED_CASS=y` (stock scheduler) instead of WALT
   - no LTO
   - defaultconfig path present, device DTS present
5. Add a dedicated CI workflow on that branch (`workflow_dispatch` + push
   trigger) that builds the stock defconfig and uploads the artifact.
6. Communicate plainly: the control is a separate, isolated branch; the user's
   main branches are untouched. A user who hears a stock base was used will
   reasonably fear their work was merged or overwritten — state explicitly that
   nothing was merged, and that the control answers only base-vs-backports.

## Pitfall: pushing a control branch whose history is shallow-grafted

If you cloned/fetched the upstream base shallow (`--depth=1`) and then branched
off it, the push may fail with `remote unpack failed: index-pack failed` — the
branch references parent objects the remote does not have. Unshallowing
(`git fetch --unshallow <remote> <branch>`) can hang many minutes on a large
kernel history. Instead, collapse to a single self-contained ORPHAN commit:

```bash
git checkout --orphan <newbranch>
git add -A
git commit -m "<msg>"
git push origin <newbranch>:<targetbranch>
```

An orphan commit carries the full tree with no parent chain, so the push ships
as one object set and cannot fail on missing ancestry. Before pushing, verify
the tree actually contains what the build needs:

```bash
git ls-tree -r --name-only <ref> -- .github/workflows/...   # workflow present
git ls-tree -r --name-only <ref> -- arch/arm64/configs/vendor/...  # defconfig present
```

A self-contained commit is worthless if the workflow is absent from it.

## Pitfall: "the artifact only has a zip, no kernel file"

GitHub Actions ALWAYS wraps an uploaded artifact in a `.zip` wrapper, regardless
of how many files the workflow uploads. If the user unzips and reports "only
control-kernel.zip, no kernel file", the kernel files are INSIDE that zip —
unzip again. To confirm what a build actually packed, read the upload step's
`path:` and the copy steps feeding it. If the workflow asserts the kernel before
uploading (e.g. `test -s out/arch/arm64/boot/Image || exit 1`), then a green
build guarantees `Image` is in the artifact — the zip is just the wrapper.
A `cp ... || true` on a device-tree path is harmless for a full boot.img test:
if the dtb path is wrong it silently skips, but you flash a complete boot.img
anyway.

## Pitfall: the user wants a flashable AnyKernel zip, not a raw Image to pack

The user will push back on being handed a raw `Image` and told to pack it into
a boot.img manually — they already have a working flashable-zip pipeline
(Dev's `Kernel_Action` repo). Mirror that proven pipeline instead of asking them
to re-pack. The canonical AK3 recipe already established in the user's builds:

1. Build the combined `Image.gz-dtb` target after the normal kernel build:
   `make ... Image.gz-dtb` (an arm64 appended-dtb image — kernel gzip member
   plus the device DTB per appended-dtb config).
2. Clone the AK3 packaging source shallow: `git clone --depth=1
   https://github.com/LKDenchin/KernelSU_Action -b prebuilt_ak3
   $RUNNER_TEMP/AnyKernel3`.
3. Copy the built `Image.gz-dtb` into the AK3 tree, remove `$RUNNER_TEMP/AnyKernel3/.git`
   and README, and upload the whole AK3 dir as a zip artifact.

This yields a zip the user flashes directly in recovery with no mid-steps, and
it is byte-for-byte the packaging their other builds already use.

## Pitfall: the workflow lives under `.github`, which the repo gitignores

The kernel repo's `.gitignore` typically ignores `.github/`, so a plain
`git add .github/workflows/control-build.yml` stages nothing and the commit is
empty — the workflow never reaches the branch. Use `git add -f
.github/workflows/control-build.yml` to force it in. Confirm the file is staged
(`git status`) before committing; an empty commit silently ships no workflow.

## Pitfall: artifact download needs auth

Listing artifacts (`/actions/runs/<id>/artifacts`) works unauthenticated, but
DOWNLOADING (`/actions/artifacts/<id>/zip`) returns 401 without a token. If the
agent has no PAT, it cannot byte-verify the zip contents from the API — rely on
the workflow's own `exit 1` asserts (e.g. the AK3 step hard-fails if
`Image.gz-dtb` is missing) plus the artifact size/name to infer the kernel is
inside, and say plainly that the zip bytes were not independently verified.
