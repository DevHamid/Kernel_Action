# Auditing build-time patches applied to a vendored submodule

A tree that patches a pinned submodule at build time accumulates patch files that
no session has re-read against the current symptom. Each one is a hunk set that
rewrites upstream code, applied in a fixed order by `drivers/Makefile`, with its
failures swallowed. This is the procedure for auditing that set before trusting
any conclusion drawn from the built binary.

## Read the apply order, then read every hunk

The order is decided by the `$(shell ...)` lines in `drivers/Makefile`, top to
bottom — not by filename, not by commit date.

```sh
grep -n 'patch -p1' drivers/Makefile          # apply order, with line numbers
cat <each patch file named there>             # read EVERY hunk, not just yours
```

A patch inherited from an earlier session is not automatically one you endorse.
It is a file in the repo that has never been audited against the symptom you are
currently chasing.

## What to look for in each hunk

For every hunk, answer: **what does this change on the SUCCESS path?**

- A hunk that rewrites the privileged exec target (`ksud_path` → `sh_path`) on
  the success branch makes the feature *always* return an unprivileged result.
  It never falls back, because there is no privileged path left to fall back
  from. The symptom is a hang with no error — the privileged helper never runs,
  so the handshake that produces the user-visible prompt never happens.
- A hunk that adds an early `return` between a privileged open and its parse
  loop leaves the feature's table empty, so every consumer fails uniformly.
- A hunk that adds a `goto`/fallback branch to a non-privileged equivalent runs
  *successfully* and hands back an unprivileged result — the worst shape, because
  nothing errors.

Classify each hunk as **load-bearing** (keep), **harmful** (drop), or
**superseded** (the upstream pin now carries it natively — drop, it will fail on
a context mismatch or double-apply).

## Splitting a partly-harmful patch

Keep the legitimate hunks, drop the harmful one, then regenerate any successor
patch against the corrected state:

```python
import re
src = open('<patch>').read()
head, *hunks = re.split(r'(?=^@@ )', src, flags=re.M)
keep = [h for h in hunks if h.startswith('@@ -<line-you-want>')]
open('<fixed>.patch', 'w').write(head + ''.join(keep))
```

Then re-verify the whole ordered sequence from a pristine clone (see the SKILL.md
ordered-sequence rule). A successor patch anchored on the harmful state applies
cleanly and preserves the defect — fixing only the successor's context is not
enough.

## Why a harmful hunk can survive a green build

The apply hook is `$(shell ... patch -p1 -N --fuzz=0 < ... >/dev/null 2>&1 || true)`.
That discards the error text and the exit code, so:

- A patch that fails to apply leaves the file in its pre-patch state, silently.
- A patch that partly applies leaves a broken intermediate state, silently.
- A patch that applies cleanly but is harmful produces a **green build with a
  broken runtime**.

Only the last case is invisible to CI. It is caught by reading the hunk, never by
reading the build result — which is why the audit above happens before trusting
any runtime conclusion drawn from the artifact.

## When the symptom is a hang, start here

A hang with no error and no crash means a code path never completed. Before
auditing versions or submodule history:

```sh
grep -n 'memcpy.*filename\|exec\|return -EINVAL' <submodule>/kernel/feature/<f>.c
```

Read what the feature execs and what it returns on each branch. The version
question and the behaviour question are settled by different evidence: the
`version code`/`version name` line in the build log settles the first, the
function body settles the second.

## Two silent causes wear the same symptom — separate them before patching

A patched feature that hangs can be broken by the patch OR by its own guard
firing, and neither prints anything. Both are silent, so "the patch is wrong" and
"the helper is absent" look identical from the shell. Do not pick one and patch
against it — enumerate both and name the evidence that discriminates:

- **The patch rewrote the success path** — found by reading the hunk (above).
- **The feature's own guard bailed** — an early `return -EINVAL` when a helper
  binary or an allowlist entry is absent. Found by grepping the feature's
  `pr_info`/`pr_err` strings and asking for the device's `dmesg` filtered to
  them: each guard prints a distinct line (`no ksud found, don't process execve`
  vs `do_execveat_common su found`), so one grep names which branch ran.

When the patch audit comes back clean and the guard is the remaining candidate,
say so and ask for that grep rather than editing the patch again. A patch
revision made on a new theory, with the old theory unrefuted, is how a
legitimate hunk gets dropped for the second time in one investigation.
