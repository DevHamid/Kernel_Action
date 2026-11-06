# Fresh restart: re-anchoring a backport chain on a clean base

Use when a device-boot debugging path is closed (user hits a wall, declares the
branch undebuggable, or wants a clean slate) and chooses to start over from a
known-good base. The goal is a single clean branch that replays the verified
patch set one patch at a time, each testable in isolation.

## The workflow

1. Confirm the known-good base. Ask the user which branch actually works day-
   to-day — it is often NOT the one you assumed. In this project the working
   branch was `build-all-rekernel` (head `a1e6b3a97`), not the experimental
   `mglru-v5`.
2. Create the fresh branch from that base: `git checkout -b <new>
   origin/<base>`. Verify the new branch's head with `git log --oneline -2`.
3. Verify the base is reachable on origin BEFORE deleting anything
   (`git ls-remote --heads origin | grep -i <branch>`). Delete local control /
   bisect / old-feature branches only after that check — origin is the safety
   net, so everything stays recoverable.
4. Enumerate the full patch delta on the OLD branch vs the NEW base — this is
   the definitive list of what must be replayed:

   ```bash
   git log --oneline origin/<base>..origin/<oldbranch>
   git rev-list --count origin/<base>..origin/<oldbranch>
   ```

5. Categorize the commits (awk/sed on the message) so the replay order is
   obvious: build/infra fixes (netfilter, ramoops/pstore, defconfig,
   droidspaces, ci/gitignore) first, so the tree builds; then the actual
   feature backports (e.g. POC/REFLEX, Cambyses, MGLRU) last, each as an
   isolated, testable unit.
6. Confirm the replay order with the user before applying; let them pick which
   patch starts. Feature backports that carry a "fixes freeze" commit (e.g.
   MGLRU's `lru_gen_init_lruvec`) are the highest-value first candidate for a
   freeze bug.

## Pitfall: a feature branch's "feature commit" may be missing from the delta

When diffing base-vs-old, a backport can appear only as a FIX commit without
its original addition (e.g. MGLRU showed only `lru_gen_init_lruvec` fix — the
feature itself was already in the base, or the delta's base is older than the
teature). Do NOT assume a feature is added by the old branch; check whether the
base already carries the config/code before treating the fix as the whole
feature.

## Pitfall: interrupted git ops leave a half-applied state

`git checkout -b` that gets interrupted (e.g. process killed) can leave the
index mid-merge or the branch not fully created. Before retrying, run
`git status --short` and `git cherry-pick --abort` if a cherry-pick is in
progress; verify with `git branch --show-current` that you are on the branch
you expect. Git operations report success via the command's exit code — a
non-zero exit means the state is NOT what the output's last line implies; check
`git status` before assuming a branch exists.
