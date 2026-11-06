# Backport Techniques

## Version fingerprinting (body-level, not symbol-level)

To decide whether two patchsets are the same revision:

1. Build each side as a real tree: vanilla sources at the exact tag + `git apply` of its patch. Compare against **patched** content, never the unpatched base.
2. Extract top-level function bodies by brace matching (definitions start at column 0, gather to the first `{`, match braces, index by the first identifier before `(`). Normalize: strip comments/blank lines, collapse whitespace.
3. Pairwise `difflib.SequenceMatcher` on normalized bodies. Buckets: IDENTICAL (1.00), near (>=0.90), drift (0.6-0.9, API adaptation), DIVERGENT (<0.6, structural).
4. **Fingerprint the data model, not the API.** The revision marker lives in structure shapes: list dimensions (`lists[gen][type][zone]` vs `lists[gen][type]`), whether an abstraction exists (`mm_walk_args`), whether a function drains zone lists or just bumps a counter. Two revisions can share every function name.
5. Report to the user as a table with verdicts and the *reason* each divergent function differs (which revision introduced what), never as a bare "same/different".

Worked example (MGLRU): the v4->v5 delta is entirely in `inc_min_seq`/`get_nr_to_scan`/`inc_max_seq` (flat per-type lists -> per-zone lists, need_aging flag -> memcg min/low guards + force_deactivate) and the `mm_walk_args` walker abstraction. A 4.19 tree carrying all v5 function names with v4 bodies is v4, not v5.

Corollary learned the hard way: a tree that *advertises* v5 in its commit subject can still lack v5 markers. Run the fingerprint before believing the label — the presence of `struct lrugen` (not `struct lru_gen_struct`), `mm_walk_args`, `lru_gen_init_state`, and `lru_gen_free_memcg` is what distinguishes a real v5 port from a v4 one wearing a v5 commit message.

## GitHub fetch recipes

- Single commit patch: `https://github.com/<owner>/<repo>/commit/<sha>.patch`; fallback `.diff` when `.patch` returns 0 bytes.
- Commits touching a file: `https://api.github.com/repos/<owner>/<repo>/commits?path=<file>&per_page=40` — filter messages for FROMLIST/BACKPORT to find port series.
- Compare branches: `.../compare/base...owner:repo:branch` gives commits + files + additions/deletions (caps at 250 commits).
- Files at a historical ref: `https://raw.githubusercontent.com/<owner>/<repo>/<sha-or-tag>/<path>` — use the pre-feature merge commit to get a clean port without unrelated tree contamination.
- Version check: fetch `Makefile` head; `VERSION`/`PATCHLEVEL`/`SUBLEVEL` are the first lines.

## Finding cross-SoC donor ports

Don't restrict the donor search to the target's own SoC. Porters reuse their own work across every tree they maintain, so the best donor for an sdm660 tree may sit in an sdm845 or other adjacent tree by the same author.

1. Collect candidate repos (search results, org repos, the porter's other trees).
2. For each, list branches then query commits on the touched file:
   `https://api.github.com/repos/<owner>/<repo>/commits?sha=<branch>&path=mm/vmscan.c&per_page=40`
3. Filter commit subjects for the feature name and for `v<N>` markers; read the parent chain to get both the pre-feature and post-feature commits.
4. Score each candidate: **revision fidelity first** (does it carry the target revision's data-model fingerprint?), **kernel distance second**. A true-revision port two versions away outranks an older-revision port on the exact version.
5. Prefer a donor whose own history contains the debug/fix commits after the port (`early-boot NULL deref`, `reset_batch_size`, `inc_max_seq`) — those fixes are exactly the landmines you would otherwise rediscover at runtime on a phone.

Fetch the donor's pre- and post-feature file sets at those two SHAs via `raw.githubusercontent.com/<owner>/<repo>/<sha>/<path>` and use them as base/theirs for the 3-way merge below.

### Abort a bad donor before spending a resolution pass on it

Revision fidelity can win the ranking and still lose the merge. A donor on a kernel two versions away can carry the exact target revision and still produce hunks whose context lands inside a *different function* in the target, because the surrounding code was reorganised between versions. That is unrecoverable per-hunk: you cannot paste a function's body into another function and have it mean anything.

Cheap early-exit test, run **immediately after `git apply --3way`, before resolving a single marker** — for each conflicted file, compare the enclosing function name on both sides:

```bash
for f in $(git diff --name-only --diff-filter=U); do
  echo "== $f"
  awk '/^<<<<<<</{p=1;n++} p{print} /^>>>>>>>/{p=0;print "  --"}' "$f" | head -40
done
```

Signals that the donor is structurally wrong and should be abandoned (reset to the base sha and pick the exact-version donor instead, accepting the older revision as the base for a later surgical upgrade):

- the ours-side of a hunk is a fragment of function A while the theirs-side is a fragment of function B
- a theirs-side block replaces a newer target construct with an older equivalent (`vm_fault_t` -> `int`, `activate_mm` with `ARCH_WANT_IRQS_OFF_ACTIVATE_MM` -> a plain call)
- the same file yields conflicts in unrelated areas that only make sense if the two files had different section ordering

Also count the damage before deciding: total conflicted files and total hunks is the real cost estimate. A donor that needs 28 hunks resolved across 13 files is worse than one needing 9 files, even when the first is a revision closer.

## 3-way merge onto a diverged tree

When the target tree carries vendor work (KernelSU/SUSFS, extra mm patches, custom reclaim), the port cannot be applied line by line. Build the merge inputs and let git do it:

1. Synthetic branch off the real base: copy the **donor's pre-feature** files in, commit (`base`). Then copy the **donor's post-feature** files in, commit (`theirs`).
2. `git diff base theirs > feature.patch` — this is the port, natively expressed against the donor's own base.
3. Return to the real branch and `git apply --3way feature.patch`. Because both blobs now exist in the repo, the 3-way merge absorbs context drift and conflicts only where the two sides genuinely disagree.

### Filter the patch before applying — `--3way` is atomic

A single path in the patch that does not exist in the target tree aborts the **entire** apply, exits 1, and leaves the tree completely untouched. The output still lists "Applied patch to ... cleanly" for other files, so it reads like a partial success while nothing changed. Always filter first:

```python
import re, os
parts = re.split(r'(?m)^(?=diff --git )', open(src).read())
kept = [p for p in parts
        if (m := re.match(r'diff --git a/(\S+)', p))
        and os.path.exists(os.path.join(TREE, m.group(1)))]
open(dst,'w').write(''.join(kept))
```

Files that legitimately vanish across versions (`kernel/cgroup.c` -> `kernel/cgroup/*.c`), donor-only files (`mglru_block.c`), and the donor's own defconfigs are all expected drops — log them, don't chase them.

### Verify the merge actually landed

Never trust the apply log. After applying, confirm the tree changed: symbol count in the main touched file and its line count should both jump (e.g. `grep -c lru_gen mm/vmscan.c` 0 -> 108, 4471 -> 6790 lines). An unchanged count means the apply aborted and you are looking at the pre-merge tree.

### Post-merge contamination audit (mandatory, before committing)

Resolving every conflict marker does **not** mean the merge is clean. `git apply --3way` silently merges hunks that do not conflict, and those clean hunks carry the donor's unrelated vendor work with them. A file can end at zero markers and still absorb hundreds of foreign lines.

Run this on the staged diff, per file:

```bash
cd "$TREE" && git add -A
git diff --cached --stat            # a file with a large delta you did not intend is the smell
for f in $(git diff --cached --name-only); do
  total=$(git diff --cached "$f" | grep -cE '^\+' | grep -v '^\+\+\+')
  feat=$(git diff --cached "$f" | grep -E '^\+' | grep -cE 'lru_gen|LRU_GEN')   # feature symbols
  echo "$f  added=$total  relevant=$feat"
done
```

Decision rule: if `relevant` is a tiny fraction of `added` (e.g. 1 of 814), the file's merge is contaminated — `git checkout -- <file>`, then hand-add only the lines the feature actually needs, verified against the donor's post-feature file with `grep -n '<symbol>' <donor>/<file>`. Files with a high relevant ratio are fine as merged.

Worked example: the donor's `kernel/sched/core.c` contributed 814 added lines to a file the feature touches in exactly one place (`lru_gen_use_mm(mm)` inside `finish_task_switch`). The 30 conflicted hunks were all donor UCLAMP code and resolved to "ours" correctly, yet the *clean* hunks still carried the rest. Correct action was to revert the file and confirm the single needed line was already present.

### Post-merge completeness audit (the inverse failure)

Contamination is lines you did not want; **omission is files you never merged**, and it is worse because it is invisible: no conflict, no marker, no warning, and the build often still passes. The feature is then half-wired and dies the instant it is exercised.

The file set for a 3-way merge is usually derived, and a derived list can silently lose a file whose whole delta is one line. Do not build it from a `commits?path=<one-file>` query — that returns only files touched by commits that happened to modify that path, so a one-liner in a *different* file is missed:

```bash
# WRONG: only files changed in commits that touched mm/vmscan.c
commits?path=mm/vmscan.c   ->  collect .files[]

# RIGHT: parse the port's own patch
for f in $(grep -h '^diff --git' feature.patch | sed 's|diff --git a/||; s| b/.*||'); do
  [ -f "$TREE/$f" ] || echo "ABSENT IN TREE: $f"
done
```

Then reconcile against what you actually changed:

```bash
git diff --name-only <base> HEAD > /tmp/touched
# every file the donor's port names must appear in /tmp/touched, or be a known version drop
```

Expected legitimate drops, log them and move on: files that moved between versions (`kernel/cgroup.c` -> `kernel/cgroup/*.c`), donor-only scratch files the patch deletes (`mglru_block.c`), and the donor's own defconfigs.

Worked example: `mm/mmzone.c` was absent from a merge file set because it was derived from a `path=mm/vmscan.c` commit query. Its entire delta was one line — `lru_gen_init_lruvec(lruvec);` appended to `lruvec_init()`. Everything else merged, the tree compiled, and the kernel booted with the feature off. Enabling the feature froze the device instantly, because `lruvec_init()` starts with `memset(lruvec, 0, sizeof(struct lruvec))` — so every generation list head was NULL and the enable path's `fill_evictable()` did `list_add()` straight into them.

## Conflict mapping recipe

```python
import re, subprocess, os
parts = re.split(r'(?m)^diff --git ', open(patch).read())[1:]
for f in parts:
    name = re.match(r'a/(\S+)', f).group(1)
    open('one.patch','w').write('diff --git a/' + f)
    r = subprocess.run(['git','apply','--check','one.patch'], capture_output=True, text=True)
    # CLEAN if rc==0, CONFLICT otherwise, ABSENT if not os.path.exists(name)
```

Run cumulatively for a patch *series*: apply in order for real, re-check each subsequent piece, so downstream conflicts reflect earlier patches. Note that a series from a rebased tree will conflict 0/N even though the final tree is fine — fall back to fetching the final tree state at the merge commit instead.

## CI-error fix loop

User dispatches CI, sends back the zipped step logs (`20_Compile kernel.txt` holds the build). Loop:

1. Extract the zip (`zipfile.ZipFile(...).extractall()`), grep only that file for `error:|fatal error` — the log interleaves successful `CC` lines, so filter to the error lines plus a few lines of context each.
2. Classify each error: missing struct member / missing helper declaration / wrong arg count. The first two mean a dependency the donor tree had and the target lacks; the third means a stale call site surviving a signature change.
3. Before pushing the fix, sweep every identifier *called* in the branch's added lines (`git diff <base>..HEAD` `+` lines, regex `(\w+)\s*\(`) against the tree (bulk `grep -rhoE` index over include/mm/kernel/fs/arch headers, minus C keywords). Push only when the suspect list is empty — CI runs are the expensive resource, local greps are free.
4. One fix commit per CI round, message naming the errors and the root cause; push and confirm with `git ls-remote` (network resets mid-push are common; retry until the remote sha matches HEAD).

## Runtime failure after a green build (device boot test)

A green CI build says the port is *coherent*, not that it is *correct*. The phone boot test is the next gate, and it fails in its own ways:

1. **Get the donor's post-port fix commits first, before the user ever flashes.** Port series are followed by debug commits on the donor tree (`early-boot NULL deref`, `lru_zone_size underflow`, `zero-init reclaim_state`). Each one is a known landmine. Grep the donor's commit history for them and apply the equivalents as part of the port, not as post-mortems.
2. **Ask for `dmesg`/`last_kmsg`/ramoops from the failed boot before guessing.** One log line replaces a whole bisect round. If the user cannot get one, fall back to the bisect in step 5.
3. **Counter ownership is the #1 runtime killer in mm ports.** LRU-style code has two counter layers: node/zone counters and per-memcg counters (`lru_zone_size`). Some ported paths (`inc_max_seq`, `reset_batch_size`) must touch **only** node/zone — calling the full `update_lru_size()` there double-counts against `lru_gen_update_size()`, the per-memcg counter underflows (negative lru_size), and the device glitches, hangs, then bootloops. Rule: when a donor fix commit switches `update_lru_size` -> `__update_lru_size` in a ported aging path, that is not a style change — it is counter-ownership repair. Carry it.
4. **Verify the page->flags bit budget from generated artifacts, not source.** The feature's widths (`LRU_GEN_WIDTH`, `LRU_REFS_WIDTH`) come from `kernel/bounds.c` into `include/generated/bounds.h`; read the generated values and compute `SECTIONS+ZONES+NODES+LAST_CPUPID+KASAN+<feature widths>` against `BITS_PER_LONG - NR_PAGEFLAGS`. Add the feature's widths to the arithmetic checks in `page-flags-layout.h` so an overflow becomes a compile error instead of silent aliasing. Then widen every flag validator that whitelists individual bits (`PAGE_FLAGS_CHECK_AT_FREE`, `fuse_check_page()`) to tolerate the feature's `*_MASK` bits, or freeing a feature-tagged page trips `bad_page()`.
5. **Bisect with a safe-boot build, not by reverting code.** Most runtime-enablement features have a boot-time switch (e.g. `CONFIG_LRU_GEN_ENABLED`). Build with the code compiled in but boot-time enablement off: a clean boot isolates the crash to runtime logic (then enable via sysfs and watch debugfs/dmesg); a bootloop anyway means the damage is at init/link time. Keep that off-switch commit separate so it is one `# CONFIG_X is not set` line, not a revert.

   **A clean boot with the switch off does not mean the disabled path is free.** Treat compiled-in-but-disabled as its own state to verify, not as "feature off". Audit every hook that reaches feature code from a hot path — `grep -rn '<feature>_' --include=*.c mm/ include/ kernel/ fs/` — and confirm each is either an `if (feature_enabled())` call site or early-returns on the switch. Unguarded hooks cost full price while the switch reads zero: an unguarded mm-list `add_mm` on every fork takes an RCU read lock, bumps a memcg refcount, grabs the **global** spinlock (the no-memcg path) and queues the mm on a FIFO that only the aging path drains — so with aging off nothing ever dequeues, the list grows for the kernel's lifetime, and the device lags with SystemUI crashes while the feature reports itself disabled. Add `if (!feature_enabled()) return;` to those entry points before drawing any conclusion from a "disabled" build. Expect the unguarded-hook symptom to be *slowness and app/UI crashes*, not a clean bootloop — do not dismiss it as the tree being generally heavy.

   **Placement of that guard is a compile problem in its own right.** `feature_enabled()` normally lives in an inline header (`mm_inline.h`) that the struct header holding the object (`mm_types.h`) cannot include without a cycle, so guarding the helper itself fails with an implicit-declaration error; guarding at the call site with `#ifdef CONFIG_X_ENABLED` compiles but pins the decision at build time, which is exactly wrong for the bisect flow above — flip the feature on via sysfs and the hot path stays disabled. Guard on the state the enable path establishes instead:

   ```c
   /* an object is only queued by add_mm(), which early-returns when off */
   if (list_empty(&mm->feature.list))
           return;          /* never queued -> feature was off */
   ```

   This needs no header, is exact (only the enable path sets it), and tracks runtime toggle correctly. It replaces the spurious `VM_WARN_ON(list_empty(...))` a ported helper often carries, which otherwise fires for every untracked object on every context switch. Check the init path runs before first use (the alloc-time `feature_init_mm()` does `INIT_LIST_HEAD()` ahead of `add_mm()`), otherwise the test reads uninitialised memory.
   **Read back the capability mask after enabling — do not assume every requested bit was granted.** Features of this shape advertise sub-capabilities as a bitmask in a sysfs node, and the kernel silently drops the ones the hardware or config cannot support. Writing the maximum value and reading back a smaller one is the *expected* result, not a failure: a CPU without a hardware accessed-bit capability cannot support the page-table-walk bit, and a kernel without `CONFIG_ARCH_HAS_NONLEAF_PMD_YOUNG` cannot support the non-leaf bit. Predict the expected mask *before* telling the user what to look for, and treat the discrepancy as a real bug only if a bit you expect to be set is missing. State which bits are off and why at the moment of the result — otherwise the user reads a partial mask as a broken port.

   **A missing debugfs node usually means a config switch, not a broken feature.** If `debugfs_create_file()` appears to run but the node is absent, grep the defconfig for `CONFIG_DEBUG_FS` before debugging the feature: with it unset the call compiles to a no-op stub and the file is never created. Confirm enabled state via sysfs and `dmesg` first, then add the debugfs config (see the one-switch-at-a-time rule in SKILL.md) only if the counters are actually needed.

6. **One commit per boot-test round**, message naming the *symptom* ("boot-loop fixes") plus root causes — the user reads these on the phone later and needs the symptom in the subject to know which build it was.
7. **Recovery is the user's first need, not the diagnosis.** A bootlooped daily driver needs a working boot image before any more testing: point him at the stock/known-good `boot.img` the CI pipeline patches, and do not ask for another flash of untested code.
8. **Read the shape of the failure before theorising.** Two runtime signatures carry opposite diagnoses, and telling them apart costs one look at the console:

   | Signature | Means |
   |---|---|
   | Slow degradation — lag, UI/SystemUI crashes, then hang | unguarded hot-path hook running while the feature reports itself off (see the disabled-path audit above) |
   | **Instant** freeze/reboot on enable, **silent** — no `BUG:`, no stack trace | uninitialised or NULL state being written to; the enable path itself is broken |

   Silence is the discriminator. With assertions active, a genuine invariant violation prints a function name and line. No output at all means the assertion never ran — usually because `CONFIG_DEBUG_VM` is unset, which compiles every `VM_BUG_ON` in the enable path to nothing. Confirm with `grep -E 'CONFIG_DEBUG_VM' <defconfig>`; absent means the corruption was never reportable. Build one diagnostic kernel with `CONFIG_DEBUG_VM=y` appended to the defconfig so the next failure names the invariant, and expect slower boot plus more dmesg noise as the stated trade.

   For this signature, check the init path first: a `memset(struct, 0, sizeof(struct))` in the alloc path zeroes the feature's sub-struct, so the feature's own init must run *after* it. Zeroes that look like valid state are NULL list heads.
9. **Prove the branch is even implicated before debugging.** When the user reports a symptom, diff your branch against the base for the subsystem the symptom names:

   ```bash
   git diff --stat <base> HEAD -- block/ drivers/block/ mm/readahead.c fs/
   ```

   An empty (or trivially small) diff means the symptom is pre-existing or environmental. Worked example: a console flooded with `attempt to access beyond end of device` / `loop8: rw=0, want=21304, limit=21296` from Android APEX loop mounts — `block/`, `drivers/block/` and `mm/readahead.c` were byte-identical to the base, and `sizelimit / 512` matched the kernel's `limit` exactly, so the kernel had the size right and a userspace reader was walking past EOF. Nothing to fix in the port. Say that plainly instead of theorising about mechanisms in untouched code, and check whether the same message predates your branch in the user's own earlier logs.

   Related trap: that message is `KERN_INFO`, so a `grep -icE 'BUG|WARNING'` count returns 0 and reads as "kernel clean". A zero warning count is not evidence — read the console text itself.

## Old-kernel porting traps (from the MGLRU/4.4+4.19 work)

- New-version patches routinely assume 5.x-only files (`include/linux/pgtable.h`, `arch/arm64/tools/cpucaps`): these need real backport work or an arch-gated fallback, they cannot be created by copy.
- Device trees accumulate unrelated mm patches (le9, custom reclaim tunables) that shift every context line — a series that applies to vanilla will not apply to them, and a diff-based port must first subtract those.
- Device-kernel ports often add `arch/` changes (PTE young-bit helpers) that vendor ports deliberately omit via software fallbacks; count the arch delta when estimating port size. When merged code still *calls* such a helper (`arch_has_hw_pte_young()`), do not backport arm64 pgtable code — supply a local fallback returning the software-walk answer (`false`) and let the existing page-table walk carry the behaviour.
- Donor-internal identifiers arrive in code whose declaration the donor defined elsewhere: a donor's flag (`force_reclaim`) or a donor's function-local (`memcg`, from a declaration line a resolution pass dropped) both surface as `use of undeclared identifier`. Treat these as resolution damage, not missing features — diff the enclosing function against the donor's post-feature version and restore the parameter or declaration, rather than inventing a new global or deleting the guard.
- Changelogs mislabel versions: a tree advertising "v5" may carry v4 bodies. Only the structural fingerprint settles it — see above.
- Kconfig `$(shell,...)`/`$(success,...)` expansions inline the command's *output* into the line being parsed. If the command returns nothing, the line collapses (`default  if CC_IS_GCC`) and the parser reports a syntax error on the config entry — not on the script that produced the empty string. Reproduce the expansion by hand (`sh scripts/<helper>.sh ...`) before editing any Kconfig; the bug is almost always in the helper.
- A `VAR=$(...)` assignment wrapped in extra parentheses is subshell-local: later uses see an empty `VAR` and emit placeholder output (e.g. `000000`) that parses as garbage downstream. When a script's output looks like zeros or blanks, check for stray parens before assuming a locale or compiler-version problem.
- Helper functions a port *deletes* are as dangerous as ones it adds: a donor may drop a vanilla helper its own other files still call, because the donor never compiled that file with the feature enabled. Diff the donor's touched headers against vanilla for vanished (`page_lru_base_type`, `page_off_lru`) as well as changed symbols, and restore vanishing helpers verbatim from vanilla.
- API-shape changes ripple beyond the patch's file list: when a helper's arity changes (e.g. LRU list helpers dropping the explicit `lru` argument), `grep -rn '<helper>(' --include=*.c mm/` over the WHOLE target tree — callers in files the patch never touched (compaction.c, mlock.c, tracepoint macros) are the ones CI reports, one run per file.
