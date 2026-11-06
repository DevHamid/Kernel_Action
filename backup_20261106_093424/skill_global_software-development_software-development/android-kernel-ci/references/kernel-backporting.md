# Kernel Feature Backporting (cross-version)

Port a feature from a reference kernel (an older CAF / newer-upstream tree) into the working tree. When `git apply --check` fails on context, the reference patch is a different kernel version — do not fight the patch; adapt to the target tree's actual code.

## Procedure

1. Fetch the reference commit via the GitHub API, not a web scrape: `gh api repos/<owner>/<repo>/commits/<sha> --jq '.files[] | .filename + "\n" + (.patch // "NO_PATCH")'`. Split per file; skip CI/workflow hunks — they are not source.
2. Try `git apply --check` on each file patch. If it fails, reconstruct proper unified-diff headers (`diff --git`, `---`, `+++`) in case the API returned bare hunks. If it still fails, the context differs structurally — move to a manual port.
3. Read the target tree's ACTUAL implementation at the anchors the patch touches (never the reference's). Map each hunk to its equivalent location in the target version — line numbers and surrounding code drift between minor versions.
4. Check every constant the patch introduces against the target tree: grep for the same numeric value in the same flags word. Flag bits are shared namespace — a bit free in 4.9 may be taken in 4.19 (e.g. `LBF_MOVED 0x20` collides with `LBF_NOHZ_AGAIN 0x20`; use the free `0x40`).
5. Judge whether the target algorithm already provides the behavior the patch adds. If the target loop's structure (walk direction, per-item repositioning) yields the same result natively, omit that hunk and mark it with a `ponytail:` comment naming the ceiling and the upgrade path.
6. Verify before committing: grep the whole tree for the new identifier (it should appear only where intended); confirm helper call signatures match the target tree (`detach_task(p, env)`, `list_add`, `can_migrate_task(p, env)`); for compile-time feature macros, confirm the `#define SCHED_FEAT_*` constant exists so `sched_feat(...)` expands to `if (1)/if (0)`.

## Pitfalls

- **Do not force a patch that will not apply.** A cross-version patch applies only if its hunk context matches. If it does not, the reusable artifact is the reference's INTENT (what behavior it changes), not its text.
- **Flag-bit collisions are silent.** Reusing a taken bit produces no error; it silently ORs two meanings into one flag. Always grep the target tree for the exact value in that word before assigning.
- **Features may be compile-time constants, not runtime sysctls.** In these kernels `sched_feat(x)` expands to `SCHED_FEAT_##x` (a macro constant, e.g. at `kernel/sched/sched.h`). Adding the `#define` enables the branch at compile time; there is no runtime toggle to set.
- **Match the target loop, not the reference loop.** Upstream rotation/block logic can be redundant on a target walk that already relocates entries — judge by the target's control flow, and say so rather than cargo-culting dead code.
- **When the `patch` tool is denied (source outside write-safe root) and edits are written via a Python triple-quoted heredoc, `\n` inside a C string literal becomes a real newline** — a `printk(KERN_INFO "%s by %s\n", ...)` lands split across two source lines and the compiler stops at "missing terminating quote". After any heredoc write, scan the inserted region for string literals that span a real newline (count unescaped quotes per line in `printk`/`KERN_` lines — an odd count means one is broken) and verify the `\n` stayed escaped. This catches the failure locally instead of on a ~12-minute CI round-trip.
