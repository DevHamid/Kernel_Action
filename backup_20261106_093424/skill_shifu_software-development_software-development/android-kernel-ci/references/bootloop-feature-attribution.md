# Attributing a bootloop across a stacked backport bundle

Use when a tree carrying several backports (e.g. MGLRU + a scheduler feature +
I/O scheduler + root/hiding patchset) bootloops and you must name which one is
guilty. The user's constraint on this project is usually "don't waste time" —
so the goal is the smallest number of CI rounds that yields an attribution,
not the tidiest textbook bisect.

## One feature per branch, built and tested one at a time

The attribution unit is always ONE feature against the known-good base:

- arm per feature: base + feature X only (one cherry-pick set per branch)
- mirror arm from the failing tip: failing tip + feature X disabled/defaulted off
- the clean rollback: the known-good base, unmodified — always build this too,
  it is the artifact that gets the user booting again while attribution runs

All arms off the same base is what makes them comparable; an arm off the
failing tip carries the whole stack and answers nothing on its own. Cherry-pick
with `-x`.

SEQUENCING: prepare every arm as a branch, but build and boot-test them ONE AT
A TIME unless the user explicitly says otherwise. This user's standing
directive on device boot-tests is one feature at a time — "we patch one by one
instead of three at the same time" — because each flash overwrites the previous
and a phone that bootloops three times teaches nothing. Before dispatching arm
N+1, either get the boot verdict for arm N or get the user's go-ahead to run
several in CI; never silently convert the prepared arms into a parallel batch.

Three builds fired at once also cannot be told apart afterwards: each run's
`head_sha` reports the KIT branch, so several arms dispatched in the same minute
look identical in the run list. Record run id → arm branch in the message the
moment each dispatch returns.

Why one at a time beats a sequential bisect is unaffected — a bisect costs a CI
cycle per commit, an arm costs one cycle per feature. Build success is also NOT
a verdict: the answer comes from the user flashing the artifact and reporting
boot, so quote a red run as "no verdict yet" and a green run as "ready to
test", never as cleared or convicted.

## Verify each arm is actually single-variable before dispatching

An arm that silently contains nothing is wasted CI, and reads as a false
negative. Check BOTH directions on the branch's own tree:

- **The feature's config symbol exists and is enabled in that branch.** A pure
  feature branch cut from the base has the base's defconfig, which does not
  contain the new subsystem's symbols at all — cherry-picking the code without
  adding `CONFIG_<SUBSYS>=y` (+ its `_DEFAULT` override) builds the feature
  dead. Add the defconfig lines on the arm branch and commit them as part of
  the arm.
- **Nothing else changed.** `git diff <base> <arm> --stat` should list only the
  feature's files plus the defconfig hunk.

## A compile failure in an arm is NOT a verdict on the feature

An arm that dies in the compiler answered nothing about the bootloop. Report it
as "no verdict yet", fix the compile error, re-dispatch, and keep the feature
under suspicion — never let a red build read as "feature cleared". The user's
intuition ("feature X can't cause a bootloop") plus a build failure is not
confirmation, and saying so spends trust the correct answer later has to buy
back.

## Cherry-picking a series onto a vendor tree duplicates definitions

A vendor 4.19 tree often already carries part of an upstream series, so
`git cherry-pick -x <c1> <c2> <c3>` applies a hunk that inserts a static helper
the tree already declares. Cherry-pick exits 0 (the context matched), then CI
dies at the exact line the series added:

```
kernel/sysctl.c:180:27: error: redefinition of 'three'
```

After every multi-commit cherry-pick, before pushing, run a duplicate-definition
sweep over the files the series touched:

```bash
for f in $(git diff --name-only <base> <arm> -- '*.c' '*.h'); do
  git diff <base> <arm> -- "$f" | grep '^+' | grep -oE 'static .*\b([a-z_][a-z0-9_]*)\s*(=|\[|;)' \
    | sed -E 's/.*\b([a-z_][a-z0-9_]*)\s*(=|\[|;).*/\1/' | sort | uniq -d \
    | sed "s|^|$f: dup |"
done
grep -c 'static int __maybe_unused three' kernel/sysctl.c   # any name you expect once
```

Cheaper check when the error is already known: grep the branch for the symbol
that collided and confirm exactly one definition remains (`grep -n`). The
failing branch is otherwise sound — fix the duplicate, force-push, re-dispatch;
do not rebuild the arm from scratch.

### Before claiming a duplicate definition, verify the enclosing conditional

The inverse error is just as costly: reporting a duplicate symbol that is not
one. A subsystem backport routinely defines a real implementation under
`#ifdef CONFIG_<SUBSYS>` and an empty stub under the matching `#else` —
`lru_gen_age_node()` implemented at one line and `static void
lru_gen_age_node(...) { }` a thousand lines later is NORMAL upstream structure,
not a merge artifact. Two `grep -n` hits for a function name prove nothing on
their own.

Walk the preprocessor structure before asserting a duplicate: from the second
definition, scan backwards for the nearest unmatched `#if`/`#ifdef` and confirm
whether an `#else` sits between the two definitions.

```bash
awk '/^[[:space:]]*#(if|ifdef|ifndef)/{push[++d]=NR; s=$0}
     /^[[:space:]]*#else/{if(d) print "else at " NR " closes if at " push[d] ": " s}
     /^[[:space:]]*#endif/{if(d) d--}' mm/vmscan.c
```

If an `#else` separates them, the two definitions are mutually exclusive and
there is no duplicate. Say so and retract the claim in the same turn — a
confident wrong "root cause" costs more trust than an honest "not found", and
the user will remember the retraction longer than the correction.

## The `default y` trap, and the dangling-symbol trap

Two config facts decide whether a feature was in a given build, and they fail in
opposite directions:

- A `config <SYM>` declared `default y` is ENABLED in every build that does not
  explicitly unset it. Scheduler backports commonly do this. So a bootlooping
  build "whose defconfig never mentioned the feature" still ran it, and the
  feature cannot be cleared by pointing at the defconfig. To disable it on an
  arm you must flip the Kconfig default (`default y` → `default n`) or add the
  explicit `# CONFIG_<SYM> is not set` line — and confirm it in the resolved
  config artifact.
- A defconfig line whose symbol matches NO `config` block in the tree is a
  silent orphan: kconfig drops it and nothing is built. A known-good base can
  carry `CONFIG_LRU_GEN=y` while the tree contains zero `lru_gen_` code — the
  line is inherited residue, not a feature. Proving absence requires the CODE
  grep, not the config grep.

Ground truth is always the resolved config artifact plus a code grep at the
exact SHA:

```bash
git grep -l 'lru_gen_' <ref> -- '*.c' '*.h'        # empty = feature absent from tree
git grep -n 'config SCHED_BORE' <ref> -- '*Kconfig*' # absent = symbol is not real
git show <ref>:init/Kconfig | grep -A4 'config SCHED_BORE'  # read default y/n
```

## A defconfig conflict-marker commit is not necessarily the bug

A stacked backport series can commit unresolved `<<<<<<<`/`=======`/`>>>>>>>`
markers into the vendor defconfig at an intermediate commit and clean them in a
later one. Audit markers across the whole chain
(`git show <c>:<defconfig> | grep -c '^<<<<<<<'`) before blaming the tip — if
the tip is marker-free the bootloop has another cause and the intermediate
commit is history, not evidence.

## Prefer the cheapest discriminating variable

Rank candidate causes by how early they execute and how cheaply they flip:

1. A feature enabled by Kconfig `default y` that runs from the first context
   switch (scheduler) — top suspect, and unsetting it is a one-line change.
2. A feature that registers at subsystem init and takes over a default
   (`CONFIG_MQ_<IOSCHED>_DEFAULT=y` displacing BFQ) — a broken registration
   fails during boot; flipping the default back is one line.
3. A feature compiled out entirely (`# CONFIG_<SYM> is not set`) — it cannot be
   the cause of a bootloop, but the backport may still have rewritten
   unconditionally-compiled core files (see below).

## `CONFIG_<FEATURE>=n` does not un-do a refactor

A large backport (MGLRU-style) rewrites core files unconditionally — page LRU
list helpers, `mm/memcontrol.c`, `mm/swap.c`, `include/linux/mm_types.h` — not
just code inside `#ifdef CONFIG_<FEATURE>`. Turning the symbol off leaves those
call-signature rewrites compiled in (e.g. 3-arg `add_page_to_lru_list` becoming
2-arg with the lru derived internally). Therefore "feature off" and "feature
absent" are DIFFERENT trees, and a bootloop of the feature-off tree does not
clear the backport. To actually clear it you need an arm where the backport
commits were never applied — the known-good base.

## Rollback branch: keep it byte-clean and prove what it carries

When the user's fallback directive is "go back to <known-good> and reverse
everything", build that branch from the exact base SHA, verify zero feature
code (`git grep <feature>_` empty for each), then prove the shipped artifact's
resolved config has the feature symbols ABSENT (not merely off) plus the
root/hiding stack and other keepers still on. Hand over that flashable artifact
first — it restores a booting phone while the attribution arms are still in CI.
