# Kernel Feature Backporting (cross-version)

Port a feature from a reference kernel (an older CAF / newer-upstream tree) into the working tree. When `git apply --check` fails on context, the reference patch is a different kernel version — do not fight the patch; adapt to the target tree's actual code.

## Sourcing the patch: one named commit is usually half a change

When the user names a single upstream commit as "the fix", that commit is often
the FIRST half of a two-commit change, and the second half — carrying a missing
`#define`, a missing include, or a corrected call site — lands minutes-to-hours
later in the same branch. Porting only the named commit ships a patch that cannot
compile, or compiles inert.

Before porting anything the user points at, enumerate the FULL compare and read
every commit in it:

```sh
gh api repos/<owner>/<repo>/compare/<base>...<branch>?per_page=250 \
  --jq '.commits[] | .sha[0:10] + " " + (.commit.message | split("\n")[0])'
```

Then, for the commit the user named, grep the target tree for EVERY symbol and
constant its hunks reference. A constant that exists nowhere in the target tree
is the tell that the series is incomplete — the definition was dropped when only
half of it landed. Trace it back through the compare to the commit that adds it
and port both together.

Read the named commit's own message for the words "complete" / "missing" /
"apply missing … hunk": that phrasing is the author admitting the feature was
partial before this commit, which means the target tree is missing the OTHER
half too.

Read the whole compare, do not just enumerate it. Printing a commit-title list
and replying "yes, I see those" is not reading the diff: open every commit's
patch body and determine which of the named fixes the target tree already
carries. A title-only inventory lists the work without doing it.

Enumerate ALL files the feature touches from the compare's changed-file list, not
from the one file the user named. A subsystem's integration is routinely split
across several files (`fs/namespace.c` carrying the mount hooks while
`fs/super.c` carries the anon-bdev hunk is the canonical shape), and the tree can
carry one file's half and lack the other's — so the feature looks integrated by
grep and is functionally incomplete.

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
- **A trailing zero-length array member aliases whatever is placed after it.** A struct that ends in `member[0]` contributes nothing to `sizeof()`, so a member appended AFTER it occupies the same address. When a backport extends such a struct (e.g. grows `struct mem_cgroup` while it still ends in `nodeinfo[0]`), a member added past the `[0]` flexible member silently aliases the preceding field — it compiles clean and only surfaces at runtime as memory corruption (here: the per-memcg mm-list fifo, a bootloop on the manufacturing screen). Inspect the target struct's tail before extending it: new members go BEFORE the `[0]` flexible member, never after.
- **Match the target loop, not the reference loop.** Upstream rotation/block logic can be redundant on a target walk that already relocates entries — judge by the target's control flow, and say so rather than cargo-culting dead code.
- **A donor's FIX commit may already be satisfied by the target.** When studying a successful backport series (a feature that landed cleanly on another kernel), check the exact bug condition each FIX commit addresses, not just that its symbols exist. The three classic 4.14/4.19 POC selector fixes are: `idle.c` (`set_cpu_idle_state_poc(cpu, ...)` → `smp_processor_id()`), `topology.c` (`sd_span` → `sched_domain_span(sd)` + manual `max_cpu`), and `fair.c` (`p->cpus_ptr` → `&p->cpus_allowed`). Verify each against the target before porting: if `do_idle` already sets `int cpu = smp_processor_id();` at entry, the idle fix is void (`cpu` cannot diverge from the running CPU); if the topology code already uses `sched_domain_span`/`cpumask_last`, that fix is void; if `fair.c` already passes `&p->cpus_allowed`, that fix is void. Porting a fix whose bug condition does not exist in the target is a dangerous no-op — it edits code for a failure the tree never had. Distinguish "fix applies" from "bug already absent" before touching the tree.
- **When the user's own fix-history is available, check it before re-porting.** A fix the user (or a prior session) already landed and pushed stays landed; a later commit that "reverts" it is a regression in that branch, not evidence the fix was never needed. Run `git log --oneline --all -S '<old-value>' -- <path>` and print the value per commit before concluding the current tree needs the fix. Record in the commit message which halves were ported and which were deliberately NOT ported because the target already satisfies them, so the next session does not re-litigate it.
- **Verify a port's completeness by CONTENT, not by SHA.** A tree that backports through its own commits never shares upstream SHAs, so `git merge-base --is-ancestor` returning false says nothing. Check the fix's substance instead — the terminating `{ }` ctl_table sentinel, `__maybe_unused` on SMT-only vars, zero `for (int ...)` declarations in the file, `if (likely(sched_info_on()))` intact.
- **Grep the built/resolved config for the feature's CONFIG_ symbol before chasing it as a root cause.** A compiled-out feature (`# CONFIG_SCHED_POC_SELECTOR is not set`) cannot cause a runtime bug however suspect its code reads, and hours of static reading of dead code is pure waste.
- **Porting across kernel versions: check the target tree's real signature before applying an upstream change.** A backport of a newer feature often carries newer-tree API assumptions. Example: upstream const-qualified `ctl_table` `proc_handler` args in 5.4+ (`typedef int proc_handler (struct ctl_table *ctl, ...)` became `const`), but 4.19's typedef is non-const — so 4.19 handlers MUST stay non-const or they won't match the typedef. Read `include/linux/sysctl.h` before "fixing" this.
- **Audit every symbol a ported hunk references before committing.** Grep each one against the tree's headers and confirm it is *defined* (not merely declared) somewhere that links into vmlinux. A patch that compiles upstream can reference a constant that exists nowhere in this tree (`DEFAULT_KSU_MNT_MINOR_DEV`).
- **A partial-integration feature is only detectable by grepping for the OTHER half.** A subsystem whose integration was split across files shows one file's hunks present and the other's absent; grepping for the feature name finds hits and reads as "integrated". Enumerate every file the full compare touches, then grep the target tree for each one's marker. A `CONFIG_*=y` gate with zero hits in the expected file is the signature of the missing half.
- **When the `patch` tool is denied (source outside write-safe root) and edits are written via a Python triple-quoted heredoc, `\n` inside a C string literal becomes a real newline** — a `printk(KERN_INFO "%s by %s\n", ...)` lands split across two source lines and the compiler stops at "missing terminating quote". After any heredoc write, scan the inserted region for string literals that span a real newline (count unescaped quotes per line in `printk`/`KERN_` lines — an odd count means one is broken) and verify the `\n` stayed escaped. This catches the failure locally instead of on a ~12-minute CI round-trip.

## MGLRU backports: three hooks that must travel together

When porting MGLRU (or any mm-lifecycle feature with per-mm state) into a 4.x vendor tree, the backport is incomplete if the mm-lifecycle hooks are missing, and the missing-hook build compiles clean and is ONLY detectable by grepping for the call sites:

1. `mm_init()` (in `kernel/fork.c`) must call `lru_gen_init_mm(mm)` — otherwise the per-mm `lru_gen` list/memcg/nodes are never initialized.
2. `__mmput()` must call `lru_gen_del_mm(mm)` — without it the lru_gen mm-list fifo accumulates dead `mm_struct`s and `iterate_mm_list()` walks freed memory. The no-op stub exists in `include/linux/mm_types.h`, so the call site compiles and links even when the feature is off — grep for the CALL SITE, not the stub.
3. `_do_fork()` must call `lru_gen_add_mm(p->mm)` for children without `CLONE_VM` (guarded by `IS_ENABLED(CONFIG_LRU_GEN) && !(clone_flags & CLONE_VM)` under `task_lock`) — without it forked children are never on the list and their pages are never aged.

Because `lru_gen_init_mm`/`lru_gen_del_mm` have no-op stubs when `!CONFIG_LRU_GEN`, a compile gate proves nothing about whether the hooks call wired. Before shipping a build that claims MGLRU is fixed, grep the whole tree for the three call sites in `fork.c` (definition hits in `mm/vmscan.c` are not the call sites). The `lru_gen_del_mm` hit inside `lru_gen_migrate_mm()` is upstream-correct — it removes the mm from the old memcg's list. `lru_gen_use_mm` at `fs/exec.c` is the pre-existing exec path, not a backport requirement.

MGLRU also touches `mm/memcontrol.c` (`pn->lruvec.pgdat = NODE_DATA(node)` must be set at alloc time, before the first `mem_cgroup_lruvec()` call) and `mm/vmscan.c` (`inc_max_seq()`/`reset_batch_size()` must use `__update_lru_size()`, not `update_lru_size()`, because the per-memcg `lru_zone_size` is owned by `lru_gen_update_size()` and double-accounting underflows it).


A backport can compile cleanly and still do nothing. After the build errors
are fixed, audit the call graph before telling the user the feature works.

Procedure:

1. Count errors PER TRANSLATION UNIT, not per run. The first failing object
   aborts the build, so every later object was never compiled — an error count
   from `core.c` says nothing about `fair.c`. State which objects were reached.
2. For every function the backport introduces, grep for callers excluding its
   own definition (`grep -rn "<name>" kernel/ | grep -v "static .* <name>("`).
   Zero callers means the function is dead and everything downstream of it is
   dead with it.
3. For every field the backport introduces, grep for WRITES outside init and
   zeroing. A field that is only ever zeroed is dead input to every consumer.
4. Follow the dead function's output forward to the call sites that ARE live
   and compute the constant that actually flows. An inert feature is not
   automatically harmless: when a surviving call site multiplies by the
   feature's output, the dead value becomes a fixed scale factor (a penalty
   field stuck at 0 shrank every scheduler slice to ~1% of its computed
   length — the kernel still booted, but throughput collapsed).
5. Check the build's `KBUILD_CFLAGS` for `-Werror=` promotions before treating
   an unused-function warning as a blocker; without the promotion the dead
   function only warns.

Pitfalls:

- **Distinguish a backport defect from upstream design.** A truncation the
  upstream patch also performs (a u8 cache holding an average of a u64 field)
  is the reference's design, not a porting bug. Read the upstream source
  before "fixing" a truncation that was intentional.
- **Fork/parent-inheritance paths are a SEED, not the runtime source.** When
  the backport drops the runtime updater, the inheritance path still compiles
  and still runs, but the value it seeds never reaches the consumer — the
  feature looks wired and is inert.
- **A field that indexes a fixed-size array is safe only while it holds its
  init value.** Wiring the missing caller later activates a latent
  out-of-bounds read unless the upstream cap is verified to engage BEFORE the
  index is taken.
- **Byte-extraction helper types travel separately from their use sites.** A
  backport can copy `((x16 *)&field)->u8[1]` style accessors without the
  `union x16`/`union x32` definitions. Grep the whole tree for the type name
  before assuming it exists; if absent, define the unions in a header the
  consuming file already includes, guarded by the same feature macro.
- **Verify a new symbol's reachability by walking the include chain
  header-by-header**, not by assuming the obvious header provides it
  (`sched.h` -> `linux/sched/mm.h` -> `linux/kernel.h` -> `linux/bitops.h` is
  how `fls64` reaches `fair.c`). Name each hop in the report so the claim is
  checkable.
