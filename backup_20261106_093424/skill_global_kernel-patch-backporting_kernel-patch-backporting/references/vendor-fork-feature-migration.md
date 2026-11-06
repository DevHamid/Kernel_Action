# Vendor-Fork Bundled-Feature Migration

Device-kernel forks bundle features (root solution, file-hiding shims, IO schedulers, container bits) copied from third-party repos. "Upstream our X to the latest version" means: find the right patch for the target kernel version, decide whether code work is needed at all, then apply.

## Decide by SHA before porting anything

When the upstream project was **renamed** (root solution, renamed fork), the rename is often metadata only. Compare heads before planning work:

```bash
cd <old-repo> && old=$(git rev-parse HEAD)
cd <new-repo> && new=$(git rev-parse HEAD)
# identical SHA -> rename only; no code work, just repoint and note the new canonical URL
```

Do this first: it can collapse a "migration" task into a one-line change, and it prevents a wasteful re-port of identical code.

## Pick the patch by kernel version, from the directory listing

Third-party patch bundles are organised per kernel version and the newest set is not your set:

- schedulers: `patches/legacy/linux-<ver>-<feature>/` for old trees (4.19), `patches/stable/<ver>-...` for current ones.
- vendor patch bundles: `Patches/<Feature>/<file>_to_<ver>.patch` — take the file whose name matches the target version exactly.

Verify the file exists by listing the directory. Names visible in a repo URL or README (a `-5.1.5` variant while the tree ships a `-5.1.0r2`) are commonly wrong; a probe that exits 2 is a missing file, not an error to debug. Confirm EVERY file of a multi-part series before applying the first one — a series whose second patch does not exist for your version means from-source work, and you want to know that before applying patch one.

## No 4.19 patch = real backport, and it is its own task

Some of these projects only publish patches for current kernels (6.x). That is a from-source backport against the target subsystem (`block/`, `fs/`), sized like any other backport in this skill — not an "apply the patch" step. Say so plainly in the plan and schedule it after the whole-tree sync, so it lands on the final tree shape instead of being rebased over it.

## Userspace halves are not kernel work

Some requested items are userspace (Android's `lmkd` is a userspace daemon). The kernel's only obligation is the mechanism it needs (PSI: `CONFIG_PSI=y`); check the defconfig for that symbol and report the split rather than hunting for kernel code to change.

## Order within a multi-feature pass

1. Whole-tree upstream sync first — it rewrites the files every later patch touches, so patches applied before it get rebased for nothing.
2. Then the version-appropriate feature patches (scheduler, file-hiding shims, rekernel/Droidspaces-style extras).
3. Then renames/no-op migrations and userspace config, which are cheap.
4. One commit per feature, each naming the upstream repo and the exact patch file used — the user audits these later and cannot recover provenance otherwise.
