# Vendored submodule dependencies in kernel trees

A vendored dependency (KernelSU/BakaSU, SUSFS, NoMount, Baseband-guard) is tracked
as a git SUBMODULE, so the parent repo stores a `gitlink` — one pinned SHA — plus a
URL in `.gitmodules`. Four independent things get conflated constantly, and a swap
of one is never a swap of the others.

## Resolve all four states before agreeing or disagreeing about a swap

When the user says a dependency was changed, or that it never was, check all four
before answering:

1. **`.gitmodules` URL** — which repo the submodule is fetched from.
2. **The pinned SHA** — `git submodule status` or `git ls-tree <ref> KernelSU`.
   This is the commit the parent tree actually contains.
3. **The checked-out dir** — `git -C <submodule> log --oneline -1`. Can differ from
   the pin if the working tree is dirty.
4. **What the build compiles** — the kit workflow may overwrite the submodule
   outright (below).

A rename of an upstream project typically lands as a URL change in `.gitmodules`
plus a symlink retarget, with the pin left exactly where it was. The tree then
carries the NEW project's OLD code, and every fix that landed upstream after the
pin is absent. Report the pin delta as the real gap —
`compare/<pin>...<upstream-main>` gives `ahead_by`, and the changed-file list
names which subsystems moved — not the URL.

## Diagnose a broken vendored feature by the pin delta, not by reading our copy

When a submodule-provided feature fails at runtime (root grant denied, a mount
hidden, a policy not applied), the fastest path is not to read our vendored copy
line by line. Diff the pin against upstream and read the changed-file list:

```sh
gh api repos/<owner>/<repo>/compare/<pin>...<main> \
  --jq '.files[] | .status + " +" + (.additions|tostring) + " -" + (.deletions|tostring) + " " + .filename'
```

Then list the commits touching the failing subsystem's file:

```sh
gh api repos/<owner>/<repo>/commits?path=<kernel/feature/x.c> --jq '.[] | .sha[0:10] + " " + .commit.message'
```

Two root-cause shapes to look for, both of which read as "the feature is broken"
with no error anywhere:

- **A read that lost its credentials.** A loader that opens a privileged path
  without holding an elevated cred across the open fails on newer SELinux, returns
  early, and leaves its table empty — so every consumer of that table fails
  uniformly. The tell is an early `return` between `filp_open` and the parse loop,
  with no `override_creds`/`revert_creds` pair around it.
- **A fallback that substitutes a non-privileged equivalent.** A code path that
  "falls back" to a shell or a default when its privileged helper is missing runs
  successfully and hands back an unprivileged result. Grep the failing feature for
  `goto out` / fallback branches and ask what the substituted value actually is.

Both are invisible to a build gate: the code compiles, the config is `=y`, and the
feature is nominally present.

Both shapes are DIAGNOSTIC PATTERNS, not current defects — at a current upstream pin both are already fixed natively, so re-check the pin before treating either as the cause. The allowlist loader's missing cred across the privileged open (blanket root denial, no error anywhere) was fixed upstream; confirm with `git merge-base --is-ancestor <fix-sha> <pin>`. The su execve path is the subtler one, and getting it backwards has cost a build cycle: `ksud` is the su front-end, NOT a debug artifact — it claims the inherited su-session fd, sets uid/gid, SELinux context and cgroups, wraps the tty, and execs `/system/bin/sh` itself, so the correct chain is `su → ksud → /system/bin/sh` with the kernel having already applied the root profile. A `/system/bin/sh` in the exec path is therefore only a defect when it REPLACED `ksud` on the success branch; when `ksud` execs it, that is the intended chain. A patch that makes `su` exec `sh` directly bypasses every step above and hangs with no error. When a vendored feature fails uniformly with no error, check these two shapes against the pin's NATIVE code before reading our vendored copy line by line.

## The kit workflow may overwrite the submodule entirely

Before assuming `.gitmodules` controls what builds, read the workflow for a step
that re-runs an installer against the kernel-side integration. A KernelSU setup
step gated on an `ENABLE_KERNELSU` flag pipes an upstream `setup.sh` into the tree
and rewrites `drivers/kernelsu` regardless of the pin. With the flag false, the
submodule content comes from the pin; with it true, the pin is irrelevant.

Also grep the parent's `drivers/Makefile` for `$(shell ...)` lines that mutate the
submodule at build time (a `git fetch --tags` so a version string resolves). A
build-time mutation is invisible in git status and easy to mistake for a stale pin.

## Editing a submodule: commit inside it, bump the pointer in the parent

`git add <submodule>/<file>` in the parent fails with `fatal: Pathspec ... is in
submodule`. The edit belongs to the submodule's own history:

```sh
cd <submodule> && git checkout -b <fix-branch>
git add <file> && git commit
git push https://x-access-token:$TOKEN@github.com/<owner>/<repo>.git <fix-branch>
cd .. && git add <submodule> && git commit   # records the new gitlink
```

Commit the submodule FIRST — the parent's gitlink must point at a SHA that exists
on a remote, or CI's `--recursive` clone cannot fetch it.

## Pushing a backport branch to a fork of an upstream project

No write access to the upstream repo is normal. Fork it, then expect the fork push
to be REJECTED when the OAuth token lacks the `workflow` scope and the branch
history touches `.github/workflows/` — the error names the workflow file and
reads like a permission failure on your own code.

Fix: base the push branch on the fork's current default branch and carry only the
substantive diff, so no workflow file is added or deleted by the push:

```sh
git fetch <fork-url> main && git checkout -b fix FETCH_HEAD
git checkout <fix-branch> -- <file1> <file2>   # cherry-pick content, not history
git commit
git push <fork-url> fix
```

A squashed single commit also sidesteps this, because the push adds one commit
rather than replaying a history that modifies workflow files.

## A pin bump is not free: diff the hook-critical files first

Bumping a pinned dependency to pick up two fixes can drag in dozens of commits.
Before bumping, check whether the delta touches the mechanism the tree depends on:

```sh
gh api repos/<owner>/<repo>/compare/<pin>...<target> --jq '.files[] | select(.filename | test("hook|syscall|selinux")) | .filename + " +" + (.additions|tostring)'
```

A large rewrite of the architecture's syscall-hook file, or a refactor that renames
the register-access macros the tree's own hooks use, can break an integration that
was working. When the delta is too wide to review, the safe order is: cherry-pick
just the needed fixes onto the current pin first, prove the feature works on
  device, then evaluate the pin bump as its own change.

## When a full bump is blocked, pick the commit BEFORE the blocker and re-check each fix

An unconditional `$(error ...)` in a version-gated `.mk` blocks a bump to `main`
outright (see the wayne skill's gate check). The fallback is the last commit
before that blocker, chosen by position in the range rather than by date:

```sh
git -C <submodule> fetch --depth=200 <upstream-url> main
git -C <submodule> log --oneline <pin>..FETCH_HEAD --reverse | nl   # find the blocker's index
git -C <submodule> rev-parse <index-minus-one-sha>
```

Then verify EACH wanted fix at that candidate before writing any patch — a
pre-blocker commit typically carries some fixes natively and not others, because
upstream lands them interleaved with unrelated work:

```sh
git -C <submodule> merge-base --is-ancestor <fix-sha> <candidate> && echo NATIVE || echo MISSING
```

Trim the patch to ONLY the missing fixes. A hunk whose change is already native at
the new pin fails on a context mismatch, and a half-applied one double-applies the
native half. State which fixes rode the bump and which still ride the patch — the
pin and the patch now carry different halves of the same fix, and the user needs
to know that when reasoning about what is in the artifact.

## Shipping a submodule fix when the pin cannot move and the remote cannot be written

When the pin bump is too wide to review AND the submodule's remote is unwritable,
the fix still has to reach the build. Kernel trees that already vendor patches
carry a build-time hook for exactly this — grep the parent's `drivers/Makefile`
for a `$(shell ...)` line that runs `patch -p1 -N` against the submodule, and add
a sibling line for the new patch:

```make
$(shell [ -f $(srctree)/patch_<name>.patch ] && cd $(srctree)/KernelSU && patch -p1 -N --fuzz=0 < $(srctree)/patch_<name>.patch >/dev/null 2>&1 || true)
```

`patch -N` is idempotent, so a second make pass is a no-op. Anchor the patch on
the PINNED commit's context so it fails loudly rather than silently mis-applying
if the pin ever moves.

Three traps on this path:

- **The patch file is gitignored.** Kernel repos commonly carry a blanket
  `*.patch` rule, so `git add patch_x.patch` is refused and the commit lands
  WITHOUT it. CI then clones, the Makefile's `[ -f ... ]` test fails, and the fix
  silently never applies — a shipped "fix" that is a no-op. Use `git add -f`, and
  confirm with `git diff --cached --stat` that the patch is actually staged before
  committing.
- **Generate the patch from the PINNED state, not the checked-out state.** A
  stray `git fetch` inside the submodule moves its HEAD off the pin, and
  `git diff` then captures the ENTIRE upstream delta as if it were your change.
  Before generating, `git -C <submodule> checkout <pin>` and assert
  `git rev-parse HEAD` equals the pin.
- **Verify against a fresh shallow clone forced to the pin** — the exact state CI
  produces. Clone the submodule `--depth 1`, `git fetch --depth 1 origin <pin>`,
  `git checkout <pin>`, then `git apply --check -p1 <patch>`. Where the `patch`
  binary is unavailable locally, `git apply --check` is the stricter substitute
  and the CI runner has `patch`.

## A missing tree is a mount problem before it is a data-loss problem

When a durable path outside the write-safe root (`/srv/ssd/ksrc/...`) stops
resolving, check the mount before concluding the work is gone:

```sh
ls -ld /srv/ssd && mount | grep -i <mountpoint> && ls -la /srv/ssd/
```

A remount can present an EMPTY filesystem at the same path — `ls` succeeds, the
directory exists, and every file is absent — which reads exactly like a wiped
disk. Confirm against the remote before reporting data loss: `git ls-remote` and
`git log --oneline -1` on the branch prove the commits survived, and the local
tree is re-derivable from them. Report "the mount is presenting an empty
filesystem, the commits are safe on the remote" rather than "the tree is gone",
and re-check the path after the user remounts — the data is usually still there.

Permissions can also change with the remount: a path that was writable can come
back `root:root drwxr-xr-x` and refuse writes as a different uid. Check `ls -ld`
and a `touch` before concluding a clone cannot be placed there, and before
starting a redundant re-clone somewhere else.

## Verify the vendored fix the same way as any other patch

Before committing a submodule edit, grep for every symbol the new code references
and confirm it is *defined* (not merely declared) in the submodule — a helper that
exists on `main` may postdate the pin. Then confirm the edit left no orphaned
locals behind: a replaced block that declared a variable the new block no longer
uses must have that declaration removed, or `-Werror` fails on the unused variable.

