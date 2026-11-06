# Multi-agent collaboration on one shared kernel repo

The user runs feature projects with two agents (Dev + Shifu) committing and
pushing to the SAME GitHub repo on a shared branch. Rules keep the two from
overlapping and prevent push conflicts.

## Task ownership — Kanban is the arbiter

- Cut ONE kanban card per feature/change, assigned to exactly one agent. The
  card's owner is the only one who edits those files. No two cards touch the
  same file.
- **A child card cannot complete while its parent is still running** — Kanban
  enforces parent-gating (complete fails with "unsatisfied parent
  dependencies"). If your card's work is verified green but the card will not
  complete, the blocker is almost always an un-done parent in a chain
  (e.g. a B card awaiting its A predecessor). Ask the parent's owner to mark
  it done to unlock yours; do not treat a blocked complete as a failed push
  or re-do the work.
- Kanban is durable (SQLite board, survives process death); `delegate_task`
  is not (dies with the parent). Use Kanban for ownership + commit
  arbitration; use `delegate_task` only for parallel one-off heavy work
  (e.g. one agent researches while the other patches).
- This project must set up the empty board first: create the first task cards
  before any clone/patch work.

## Commit/push arbitration

- Before ANY git commit+push, confirm with the other agent (the board or
  chat). If the other agent is mid-work, it pauses until the push lands —
  this is the protocol the user asked for.
- **Parallel work under a pending gate (the user's current plan):** when a
  compile-check gate is red (or one card is blocked on a parent), BOTH agents
  keep working their own corresponding tasks in parallel instead of idling —
  the user rescinded the strict one-at-a-time stall. Pushes stay held until
  the compile check is green AND the two agents confirm each other before
  pushing, so no two pushes race. Lane separation is unchanged: each agent
  touches only its own files.
- On a conflict, the card owner retries after pulling, never force-pushes.
- **Branch alignment must follow the compile gate, not your assumption.** Find
  which branch the project's Compile Check actually watches (the workflow
  YAML `branches:` trigger); any task whose completion gate is that check MUST
  land on that branch. A separate feature branch that does not match the
  trigger never runs the workflow, so the gated task is silently never
  validated — a "green-feeling" state on the wrong branch proves nothing.
- Before endorsing a coworker's separate branch as correct practice, read the
  card's event history for a reset/realign (e.g. "chain realigned to
  <base>") — that event is the authoritative instruction for where the work
  belongs, and it overrides the generic assumption that any feature branch is
  fine. Big exploratory/backport work can live on a scratch branch, but the
  task's deliverable push must go to the gate-tracked branch; say that
  explicitly when relaying the correction.
- **Cancel a known-wrong run before replacing it — don't let it finish.** When
  a user (or the other agent) rejects an approach mid-build, tell the owner to
  cancel the in-progress run AND push the replacement, so the doomed run does
  not finish green and get mistaken for the validated fix. Verify the cancel
  actually landed (a `cancelled` conclusion) before crediting the new approach.
- **Compile-failure ownership: the card that BROKE the build fixes it.** The
  user's standing rule: if a CI compile failure is caused by one agent's task,
  that agent fixes it; the other agent keeps to its own lane ("if the error
  cause by dev task right? If yes. Dev should fix it and u focuse with ur
  task"). Determine WHICH task introduced the failing code before assigning —
  verify against the base tree (`git show <base>:<file>`), because a defect
  may already exist in the shared base, in which case the rule does not map
  cleanly to either agent and the fix should be surfaced to the user for
  assignment. Stop before committing when ownership is unresolved; do not
  unilaterally commit a base-level fix the user's rule assigns elsewhere.

## What may be relayed to the other agent

Anything you hand to the other agent as an instruction gets executed without
re-verification — they act on your word. So the bar for relaying a technical
instruction is higher than the bar for stating one to the user:

- **Never relay a build-file or config edit as "the fix" without naming which
  build path it rides and how you confirmed it.** If you have not grepped the
  kit workflow for the make invocation that actually runs, the edit is
  unverified — say so explicitly in the handoff, or hold it back entirely.
  A confident mechanism story ("the `=m` overrides the defconfig, so the .ko
  gets discarded") plus a folksy analogy is the shape of a verified finding
  without any of its substance, and the receiving agent has no way to tell the
  difference.
- **Include the verification step in the relayed instruction, not just the
  change.** "Apply this, then confirm `wlan0` appears" is checkable;
  "apply this and it will work" is not.
- **Correct a relayed error in the same turn you discover it**, and tell the
  user plainly that the earlier instruction was wrong. A no-op edit relayed as
  a fix costs the other agent a build cycle and the user's confidence in both
  of you.

## Verifying a reported "done"

- When a card's completion report cites a commit, branch, or HEAD, NEVER trust
  it as proof the work landed on the CURRENT pinned base — the worker agent may
  have verified against a dead/deleted branch tree (repeatedly seen: reports
  citing the old branch HEAD while the v5 tree lacked the change). Verify the
  ARTIFACT in the actual working tree: grep/wc the file content, check the
  defconfig/config symbols, and confirm the gitlink
  (`git ls-files --stage <submodule>`) — never accept the cited SHA as ground
  truth.
- In a shallow clone (`--depth=1`), non-tip commits are unreachable:
  `git cat-file -t <sha>` / `git show` fail even though the code IS present.
  Confirm presence by reading the working-tree file or the index, not by
  resolving the commit. Submodule dirs are often uninitialized (empty) — the
  pin lives in the index gitlink, not in the (empty) subdir's `git log`.

## User re-scoping a task mid-flight

- The user can re-scope a card's CONTENT after the card is created (e.g. A7 went from POC/REFLEX to MGLRU v5, and POC/REFLEX became new A8/B8 cards). When that happens, relay the corrected spec to the card's owner via `kanban_comment` (the worker reads the body), and update the verification reference so future checks target the right feature. The new work is a FRESH backport from the named upstream source, never cherry-picked from the abandoned branch.

## Assignee profile mapping

- Kanban `assignee` takes the PROFILE name on this host, not the agent's
  nickname: Dev = `default`, Shifu = `shifu`. A card assigned `default`
  dispatches to Dev; assigning a non-existent name leaves the card stuck.
  This project's only two profiles are `default` and `shifu`.

## User overriding a delegation mid-flight

- When the user first says "delegate to dev" then reverses with a stop
  directive (e.g. "Stop dev. NO reply. I talk with shifu"), act immediately:
  `kanban_block` the dev-assigned card (kind=`needs_input`) so it can never
  dispatch, confirm no pending run, and bring the work back to your own lane.
  A superseded card left `ready` will auto-dispatch to the other agent and
  run against your intent.
- Do not re-route a stopped agent's work by creating a second duplicate card
  unless you intend to reparent it — the original card stays the live record;
  supersede explicitly by blocking the copy and pointing at the original.

## Silent-work directive (user-mandated)

- When the user says "Don't reply. Silent" (or similar) for a task, the assigned agent must execute and complete the work WITHOUT posting progress updates/comments to the chat. Only the card's final completion is the acknowledgement. This is a standing preference for Dev's tasks — re-confirm for your own if asked.

## Reporting style (user's standing rules)

- Every progress update: coffee-in-the-morning context first (everyday
  analogy), then the exact technical detail. English only.
- Post progress to knowledge notes exactly like Shifu does.
- At session boundaries write a checkpoint summary to the project folder so a
  fresh session resumes without the user re-explaining.
- Confirm the auto-pilot approval mode BEFORE starting (check
  `approvals.mode` in config; `smart` prompts on destructive commands, `off`
  is fully autonomous).
