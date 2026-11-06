# Durable & Background Systems

Four systems run alongside the main conversation loop. Quick reference
here; full developer notes live in `AGENTS.md`, user-facing docs under
`website/docs/user-guide/features/`.

### Delegation (`delegate_task`)

Spawn a subagent with an isolated context + terminal session.

- **Single:** `delegate_task(goal, context)`.
- **Batch:** `delegate_task(tasks=[{goal, ...}, ...])` runs children in
  parallel, capped by `delegation.max_concurrent_children` (default 3).
- **Background:** `delegate_task(background=true)` returns a handle
  immediately and keeps the parent loop going; the child's result
  re-enters the conversation as a new turn when it finishes.
- **Roles:** `leaf` (default; cannot re-delegate) vs `orchestrator`
  (can spawn its own workers, bounded by `delegation.max_spawn_depth`).
- **Not durable.** A backgrounded child is still process-local — if the
  parent process exits, the child is lost. For work that must outlive
  the process, use `cronjob` or
  `terminal(background=True, notify_on_complete=True)`.

Config: `delegation.*` in `config.yaml`.

### Cron (scheduled jobs)

Durable scheduler — `cron/jobs.py` + `cron/scheduler.py`. Drive it via
the `cronjob` tool, the `hermes cron` CLI (`list`, `add`, `edit`,
`pause`, `resume`, `run`, `remove`), or the `/cron` slash command.

- **Schedules:** duration (`"30m"`, `"2h"`), "every" phrase
  (`"every monday 9am"`), 5-field cron (`"0 9 * * *"`), or ISO timestamp.
- **Per-job knobs:** `skills`, `model`/`provider` override, `script`
  (pre-run data collection; `no_agent=True` makes the script the whole
  job), `context_from` (chain job A's output into job B), `workdir`
  (run in a specific dir with its `AGENTS.md` / `CLAUDE.md` loaded),
  multi-platform delivery.
- **Invariants:** 3-minute hard interrupt per run, `.tick.lock` file
  prevents duplicate ticks across processes, cron sessions pass
  `skip_memory=True` by default, and cron deliveries are framed with a
  header/footer instead of being mirrored into the target gateway
  session (keeps role alternation intact).

User docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/cron

### Curator (skill lifecycle)

Background maintenance for agent-created skills. Tracks usage, marks
idle skills stale, archives stale ones, keeps a pre-run tar.gz backup
so nothing is lost.

- **CLI:** `hermes curator <verb>` — `status`, `usage`, `run`, `pause`,
  `resume`, `pin`, `unpin`, `archive`, `restore`, `list-archived`, `prune`,
  `backup`, `rollback`.
- **Slash:** `/curator <subcommand>` mirrors the CLI.
- **Scope:** only touches skills with `created_by: "agent"` provenance.
  Bundled + hub-installed skills are off-limits. **Never deletes** —
  max destructive action is archive. Pinned skills are exempt from
  every auto-transition and every LLM review pass.
- **Cost:** the deterministic inactivity/prune sweep runs for free. The
  aux-model "consolidate overlapping skills into umbrellas" pass is
  **off by default** — opt in with `curator.consolidate: true` or
  `hermes curator run --consolidate`. Routine background curation costs
  zero tokens.
- **Telemetry:** sidecar at `~/.hermes/skills/.usage.json` holds
  per-skill `use_count`, `view_count`, `patch_count`,
  `last_activity_at`, `state`, `pinned`.

Config: `curator.*` (`enabled`, `interval_hours`, `min_idle_hours`,
`stale_after_days`, `archive_after_days`, `backup.*`).
User docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/curator

### Kanban (multi-agent work queue)

Durable SQLite board for multi-profile / multi-worker collaboration.
Users drive it via `hermes kanban <verb>`; dispatcher-spawned workers
see a focused `kanban_*` toolset gated by `HERMES_KANBAN_TASK`, and
orchestrator profiles can opt into the broader `kanban` toolset. Normal
sessions still have zero `kanban_*` schema footprint unless configured.

- **CLI verbs (common):** `init`, `create`, `list` (alias `ls`),
  `show`, `assign`, `link`, `unlink`, `comment`, `complete`, `block`,
  `unblock`, `archive`, `tail`. Less common: `watch`, `stats`, `runs`,
  `log`, `dispatch`, `daemon`, `gc`.
- **Worker/orchestrator toolset:** `kanban_show`, `kanban_complete`,
  `kanban_block`, `kanban_heartbeat`, `kanban_comment`, `kanban_create`,
  `kanban_link`; profiles that explicitly enable the `kanban` toolset
  outside a dispatcher-spawned task also get `kanban_list` and
  `kanban_unblock` for board routing.
- **Dispatcher** runs inside the gateway by default
  (`kanban.dispatch_in_gateway: true`) — reclaims stale claims,
  promotes ready tasks, atomically claims, spawns assigned profiles.
  Auto-blocks a task after `failure_limit` consecutive spawn failures
  (default 2; configurable via `kanban.failure_limit` or per-task
  `max_retries`).
- **Isolation:** board is the hard boundary (workers get
  `HERMES_KANBAN_BOARD` pinned in env); tenant is a soft namespace
  within a board for workspace-path + memory-key isolation.

Orchestration pitfalls (verified in multi-agent chain work):

- **Auto-spawn on `ready`:** the dispatcher claims a card and spawns
  the assignee's worker the moment its parents complete. The card then
  holds a live run claim, so `kanban_complete` from outside is refused
  unless you pass `expected_run_id` (worker ownership) or `force=True`
  (some tool versions accept neither — then the refused complete is a
  signal the run is already over). Don't race the dispatcher to complete
  — either verify before the worker spawns, or let the worker verify and
  just report. Trust a `kanban_list`/fresh `kanban_show` over a
  snapshot: a stale `show` can report `status: running` on a card the
  worker has already auto-completed; re-show before acting on the claim.
- **Reset stale body paths:** after realigning a board onto a new base
  tree (fresh clone replacing a deleted branch), rewrite every affected
  card's body/comment to name the current tree path — workers and
  retries treat the body as their source of truth, and a stale `repo`
  path makes them inspect a tree that no longer exists. Direct DB
  update is the reliable path: `python3` + `sqlite3`,
  `UPDATE tasks SET body=? WHERE id=?` (the CLI's `edit` is unreliable
  for body + status).
- **Result prose vs live tree:** a worker's completion summary may name
  a stale branch inherited from card metadata even when the verified
  tree is a different branch. Confirm against git state
  (`git rev-parse --abbrev-ref HEAD`, HEAD sha,
  `git status --porcelain`) before trusting the prose branch name.
- **Stale crash notifications:** an automatic "task crashed"
  notification may describe a killed pre-reset run. Inspect the board
  (`kanban_list` / `kanban_show`: status, current_run_id, parents)
  before creating work or unblocking — the card may already be `todo`
  and gated behind unfinished parents, in which case no action is needed.
- **Assignee must be a live profile:** a card assigned to a profile with
  no running gateway silently never dispatches — the dispatcher records
  `skipped_nonspawnable` and moves on, so the task appears stuck in
  `ready` forever. Before creating or assigning a card, verify the
  assignee name matches a profile actually served by a running gateway
  process: check config `multiplex_profiles` and which telegram/command
  channels are defined vs the live `hermes gateway run` processes (a
  channel name is NOT a profile name — a `secondary` telegram channel can
  route to the `default` profile). Reassign to a real profile
  (`hermes kanban assign <id> <profile>`) rather than waiting for the
  dispatcher.

User docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban
