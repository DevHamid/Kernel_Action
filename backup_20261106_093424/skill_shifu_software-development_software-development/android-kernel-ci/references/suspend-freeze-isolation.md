# Isolating a suspend/wake freeze between scheduler backports

How to pin which half of a backport causes a "lock-screen freeze" (system hangs
after screen-off; no crash line; logcat shows nothing; collect pstore/live
`/proc/kmsg` instead). Verified on the sdm660 wayne 4.19 kernel where the POC
backport was the confirmed cause.

## The 2×2 isolation matrix

When a backport bundle has two live components (e.g. a scheduler selector wired
into `select_idle_cpu()` plus a cpufreq governor), flip exactly ONE config per
build. Keep the third feature present in both — it is the control.

- Test A: component 2 ON, component 1 OFF → isolates component 1.
- Test B: component 1 ON, component 2 OFF → isolates component 2.
- Run Test A first when it is a direct contrast against a known-good build.
- Each flip is a one-line change in the vendor defconfig (e.g.
  `arch/arm64/configs/vendor/wayne-oss-perf_defconfig`):
  `CONFIG_<FEATURE>=y` → `# CONFIG_<FEATURE> is not set`.

## Decision table

| Test A result | Test B result | Verdict |
|---|---|---|---|
| wakes clean | — | component 1 cleared; component 2 is the culprit |
| freezes | — | component 1 is the culprit |
| freezes | freezes | neither is the cause — stop chasing this backport, test the stock base |
| freezes | wakes clean | inconclusive / shared interaction — examine both |

## Verify Kconfig independence BEFORE flipping

Two configs are only cleanly flippable if one does not `select` the other.
Fetch the Kconfig at the exact branch (`raw.githubusercontent.com/<repo>/<branch>`)
and check for `select` lines. `CONFIG_SCHED_POC_SELECTOR` was standalone
(no select on REFLEX), so each flip was clean. If one selects the other, a flip
is not single-variable — resolve the dependency first.

## Default-governor fallback (cpufreq)

When you drop the governor that the system was running on and no
`CONFIG_CPU_FREQ_DEFAULT_GOV_*` line exists in the defconfig, the default
falls back to the Kconfig default (`CPU_FREQ_DEFAULT_GOV_PERFORMANCE`). For a
valid Test B (no REFLEX), add `CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL=y` so the
only variable is "REFLEX off, POC on" — otherwise you are also switching the
default governor.

## Suspect shape: a governor with no suspend/resume handler

A governor that spawns a `SCHED_FIFO` per-policy kthread (polling
`idle_cpu()`) and defines only `init/exit/start/stop/limits` — no
`suspend`/`resume` — never stops that kthread on suspend. That is the classic
wake-block shape. Priority suspect when the freeze happens only after screen-off.

## Cross-lineage bisect-branch drift

A "no-feature" bisect branch is not the feature branch minus the feature. Check
`compare <branch-a>...<branch-b>` (`ahead_by`/`behind_by`, changed-file list)
before treating it as a single-variable control — it may sit on a newer base
with the feature (or an unrelated feature) fully implemented rather than removed.
Confirm the resolved config of the branch you actually flash (the defconfig file
may even be renamed, e.g. a `.bak` suffix).

## Validating a user-nominated control branch before dispatching

When the user names a specific commit/branch ("build from base X") as the
feature-off control, do NOT dispatch it blind. Verify two things first:

- **It is a descendant of the tree you understand.** `compare <working-branch>...<nominated>` — a stale fork that is `behind_by` and `0 ahead` predates the feature entirely (the "control" then lacks the feature not because it was flipped off but because it never had it) and can be missing unrelated symbols.
- **It actually compiles.** Fetch its tree's source for any symbol you know the newer tree declares. A stale base can fail to build for a reason unrelated to the feature under test (e.g. `mm/vmscan.c` referencing `shrinker_rwsem` without the `DECLARE_RWSEM` a later commit added) — that failure tells you nothing about the feature and burns a full CI cycle.

If the nomination is invalid, build the control yourself instead of dispatching it: branch the CURRENT working tip, flip the one Kconfig on that branch, and dispatch that. The single-file flip is a one-shot GitHub Contents API edit, not the full git-data flow: `PUT /repos/<o>/<r>/contents/<defconfig-path>` with `{content, sha:<blob sha>, branch:<new-branch>}` (GET the file first to read its blob sha). Creating the branch itself needs `POST /git/refs` with the FULL 40-char HEAD sha — a shortened 12-char sha is rejected with `422: At least 40 characters are required`.

## Freeze hypothesis tested and FALSIFIED: single-writer violation

A candidate root cause was a lost-wakeup from a shared idle bit touched by BOTH
the waker and the idle CPU:

- The waker cleared the idle bit inside `poc_commit_selection` only when
  `nr_running <= 2`. On a busy lock-screen CPU (many runnable tasks) that
  condition is false, so the bit stays set.
- The idle CPU's exit path was gated on a "committed" flag that assumed the
  waker already cleared the bit — but the waker skipped its clear, so the flag
  never fired.
- The selector returns the busy CPU as idle; wakeups pile up behind it; latency
  grows into a freeze at the lock screen.

The single-writer invariant fix was built, shipped and TESTED on device
(`6c5cdafdc`: waker-side commit → no-op, drop the committed-flag gate,
re-validate `!idle_cpu(cpu)` → `return -1`). **The device still froze.** Same
for the idle-hook removal (`7f5962981`). A hypothesized mechanism that survives
a clean fix build but fails on the device is FALSIFIED — do not keep iterating
inside the same theory. Fall back to the config-level isolation control to first
confirm WHICH subsystem is guilty before tuning a fix inside it: build a branch
that flips the whole feature off (`CONFIG_SCHED_POC_SELECTOR` unset, governor
kept) as the decisive control.

**CONFIRMED (2026-10-29):** the config-level control proved POC itself is the
freeze source. POC ON freezes in EVERY shipped variant — idle-hook removal
(`fix-poc-idle`/`7f5962981`), single-writer fix (`6c5cdafdc`), the stock
POC build, and the PM-notifier idle-bitmap reset (`fix-poc-suspend`,
`061f79ed7`). The ONLY clean wake was `CONFIG_SCHED_POC_SELECTOR` unset with
REFLEX kept (branch `no-poc-pstore`). So: when the control boots clean, the
feature is the freeze source. The FIX is then a proper code fix inside the
feature, NOT a permanent config-off — the user rejects feature-disabling
workarounds as final and wants the feature kept. The enum-sizing check further
down remains valid independent of this outcome.

**FINAL DISPOSITION (2026-10-29, user-verified):** the root cause is the POC
SELECTOR ITSELF, not any of the three idle-path hypotheses above — the
idle-hook removal did not fix it, so the defect is in the selector's wake path
(`poc_selector.c`), not in `do_idle()` hooks. The known-good configuration is
`no-poc-pstore` @ `3c769881a`: `CONFIG_SCHED_POC_SELECTOR` off, REFLEX on,
plus the ramoops dump-zone fix. Treat that as the settled baseline.

**A confirmed verdict is closed — do not reopen it as a "next step".** When the
user asks "what next" after a root cause is confirmed, the answer is built on
the known-good branch/config, not on re-enabling the convicted feature or
shipping another fix attempt inside it. Check MEMORY.md for the recorded
known-good before proposing anything; a status answer that contradicts the
recorded verdict sends the user back through a verification round they already
paid for.

## Rejected fix: PM-notifier idle-bitmap reset (wake-freeze)

A candidate fix for a wake-freeze whose root cause was believed to be a
scheduler idle selector that caches an idle bitmap only on `do_idle()` with no
suspend/resume callback: register a PM suspend/resume notifier that ZEROES the
idle bitmap at suspend-prepare, so stale pre-suspend idle claims cannot survive
into resume.

- `#include <linux/suspend.h>`.
- Notifier zeroes each per-LLC POC idle bitmap (`poc_idle_cpus_mask` on
  `struct sched_domain_shared`, reached via `rcu_dereference(per_cpu(
  sd_llc_shared, cpu))`) for `for_each_possible_cpu` under
  `rcu_read_lock()`, at `PM_SUSPEND_PREPARE` / `PM_HIBERNATION_PREPARE` /
  `PM_RESTORE_PREPARE`; else `NOTIFY_OK`.
- Register with `register_pm_notifier(&nb)` in the scheduler's `__init`.
- Why PM notifier over a cpuhp callback: `CPUHP_AP_ACTIVE` is a STATIC cpuhp
  slot (kernel/cpu.c), not a dynamic registration point, and the PM notifier
  fires on every suspend regardless of whether secondary CPUs are hotplugged
  off — the safer, complete target.

**FALSIFIED on device (2026-10-30):** shipped as `fix-poc-suspend`/
`061f79ed7` (bitmap-zeroing at `PM_SUSPEND_PREPARE`); the phone BOOTS but still
cannot wake after sleep — identical freeze. The zero-at-prepare mechanism does
NOT fix the wake-freeze. Why the rationale failed: the notifier clears the
bitmap during suspend-prepare, but CPUs re-set their idle bits while still
idling after the notifier fires, so bits are stale again by resume — a clear at
`PM_POST_SUSPEND` (after resume) would be the analogous untested variant, and
the present hypothesis is a race between POC selection and hotplug bring-up.
Do NOT ship this as a fix. A green build is NOT evidence on a hang with no
crash line — only the on-device test is.

Generalizable checks for a freeze shaped like this:
- Is every shared bit owned by exactly ONE writer (the entity whose state it
  represents)? A conditional waker-side clear is the classic second writer.
- Does a gating flag assume another path ran that might not have? Every gate
  must be satisfiable by the path that consumes it.
- A green build is NOT evidence a fix works on a hang with no crash line —
  only the on-device test is. Ship the fix as a flashable build and get a real
  boot result before claiming a cause is resolved.
- When adding an enum value (e.g. a rejection level `POC_LV_REJECT`), check how
  arrays/tables referencing the enum are sized: if they list members EXPLICITLY
  (`DEFINE_POC_COUNT_ATTR` per level) the addition is safe; if any array is
  sized by the enum count, you must resize it too — a bare enum insertion can
  otherwise silently overflow or shift indices.
