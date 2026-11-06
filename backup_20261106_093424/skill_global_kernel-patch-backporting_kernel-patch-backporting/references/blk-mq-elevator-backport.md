# Backporting a Modern blk-mq I/O Scheduler to 4.19

For schedulers published only for 6.x (ADIOS, newer kyber/bfq revisions) that must run on a 4.19 device tree. Upstream ships one self-contained file (`block/<sched>.c`) plus Kconfig/Makefile wiring — no per-hunk conflict work, but a systematic API rewrite.

## Procedure

1. **Extract the file, don't apply the patch.** Split the upstream patch on `^diff --git`; the scheduler source is one part. Save it as a scratch `.c` and treat every other part (Kconfig, Makefile, `elevator.c`, docs) as the to-do list for step 4.
2. **Probe the target's API before writing any transform.** For each symbol the source uses, `grep -rl '\b<sym>\b' block/*.c block/*.h include/linux/*.h`. A symbol that resolves only to the file you are porting is missing in 4.19 and needs a rewrite, not a copy.
3. **Transform with regex/line-level replacements, not exact whitespace.** Match on the call shape (`\binsert_flags\b` -> `at_head`) and assert on *counts*; exact tab-escaped `str.replace` of whole C signatures fails repeatedly because the file's real indentation never matches the literal. Make any "symbol X is gone" assert skip comment lines (`l.strip().startswith(('*','/*','//'))`), or a comment mentioning the old macro trips the guard.
4. **Wire the scheduler into four places** — see the checklist below. Missing any one yields a clean build of a scheduler that never runs.
5. **Sweep called identifiers again after the transform** (`grep -on '\b\(blk_mq\|elv\|__blk\)[a-z_0-9]*('`) and confirm each has a declaration reachable from `block/`. `elv_rqhash_del`, `elv_rqhash_add`, `elv_bio_merge_ok`, `blk_mq_get_driver_tag` live in `block/blk-mq.h` / `include/linux/elevator.h` in 4.19 and are fine; check `sbitmap_queue_min_shallow_depth`, `list_sort`, `blk_add_timer` per tree.

## 6.12 -> 4.19 blk-mq API map (verified)

| 6.x | 4.19 |
|---|---|
| `blk_insert_t insert_flags` | `bool at_head` |
| `insert_flags & BLK_MQ_INSERT_AT_HEAD` | `at_head` |
| `blk_mq_sched_try_merge(q, bio, nr_segs, &free)` | `(q, bio, &free)` — no `nr_segs` |
| `->bio_merge(q, bio, nr_segs)` | `->bio_merge(q, bio)` |
| `blk_mq_free_requests(&list)` | absent -> `list_for_each_entry_safe` + `list_del_init(&rq->queuelist)` + `blk_mq_free_request(rq)` |
| `scoped_guard(spinlock_irqsave, &q->queue_lock)` / `guard()` | explicit `spin_lock_irqsave`/`spin_unlock_irqrestore` + function-scope `unsigned long flags` |
| `bvec_iter_sectors()` | `blk_rq_sectors()` |
| `#include <linux/math.h>` | `<linux/math64.h>` |
| `blk_opf_t` / `bio_op()` / `op_is_*` | `req_op()` / `rq_data_dir()` / `op_is_write(rq->cmd_flags)` |
| `sbitmap_queue_min_shallow_depth()` | absent; `min_shallow_depth` is per-word in 4.19 `sbitmap.h` — drop or reimplement |
| `.ops = { ... }` on `struct elevator_type` | `.ops.mq = { ... }` **plus** `.uses_mq = true` |

`struct blk_mq_alloc_data` in 4.19 lives in `include/linux/elevator.h` (not `include/linux/blk-mq.h`); `struct elevator_mq_ops` is at `include/linux/elevator.h` ~line 99. Use `block/mq-deadline.c` and `block/kyber-iosched.c` as the 4.19 reference for op tables.

## Wiring checklist (all four)

1. `block/Kconfig.iosched` — `config MQ_IOSCHED_<X>` tristate + `config MQ_IOSCHED_DEFAULT_<X>` bool `depends on MQ_IOSCHED_<X>=y`.
2. `block/Makefile` — `obj-$(CONFIG_MQ_IOSCHED_<X>) += <x>.o`, anchored on the *existing* `MQ_IOSCHED_KYBER` line.
3. `block/elevator.c` `elevator_get_default()` — add `#elif defined(CONFIG_MQ_IOSCHED_DEFAULT_<X>)` -> `elevator_get(q, "<x>", false)` **before** the `#else` mq-deadline fallback, and make sure the previously-default branch no longer wins (drop `CONFIG_BFQ_DEFAULT` in the defconfig if bfq was the default).
4. Device defconfig — `CONFIG_MQ_IOSCHED_<X>=y` + `CONFIG_MQ_IOSCHED_DEFAULT_<X>=y`, and drop the old default in the same commit.

## Pitfalls

- **Check the defconfig anchor before `str.replace`.** A replace anchored on `CONFIG_MQ_IOSCHED_KYBER=y` is a silent no-op on trees where only `CONFIG_IOSCHED_BFQ=y` exists — read the actual `grep -n 'IOSCHED'` output first and anchor on a line that is really there. A replace that reports "done" while the symbol is still absent means the anchor never matched.
- `.uses_mq = true` is mandatory for a 4.19 mq scheduler: without it `elevator_init_mq()` rejects the type and the scheduler never registers, with no error beyond a generic fallback to the old default.
- `scoped_guard`/`guard` removal is not mechanical: each guarded block becomes a lock/unlock pair, so verify no `return`/`goto`/`break` escapes between them and that `flags` is declared at function scope (declaration after statement is a C89 error in this tree).
- Grep the transformed file for residual 6.x tokens before copying it in (`blk_opf_t`, `REQ_OP`, `scoped_guard`, `guard(`, `min_shallow_depth`, `->ioc`, `rq->iq`, `bvec_iter_`); one leftover is a CI round each.
- Keep the scheduler's defconfig enablement in a **separate commit** from the source: a new file cannot be bisected to a layer, so dropping one line is the only cheap way to clear a boot regression.
