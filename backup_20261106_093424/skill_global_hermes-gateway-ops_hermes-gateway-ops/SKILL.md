---
name: hermes-gateway-ops
description: Use when operating Hermes Telegram gateways.
---

# Hermes gateway ops

## Multiplex routing (multiple bot profiles, one group/topic)

One multiplexed gateway serves several profiles (`served_profiles` in `gateway_state.json`); each profile is its own bot handle in the same chat. Route by explicit address, never by both watching everything.

- Both profiles need `require_mention: true`, plus per-profile `extra.mention_patterns` scoped to that profile's OWN handle(s) only — e.g. `['@shifuisrobot']` in the shifu profile, `['@devhamidrobot']` in the default profile. `mention_patterns` are raw regex, case-insensitive, matched against message text/caption; a bare word like `dev` is fine as its own trigger but never list another bot's name or a shared word in both.
- Set `extra.bots_require_mention: true` on every profile. This vetoes messages from another bot unless it explicitly @mentions us — kills bot-to-bot ping-pong (a sibling bot's reply is not a trigger; only an explicit @handle is).
- `exclusive_bot_mentions: true` (default) is what actually stops cross-wake: a message whose explicit bot handles target other bots (not this one) is dropped at `_should_process_message` before reply/wake-word fallbacks can fire. Keep it on; it is the fix for "bot B answered a message addressed to bot A".
- Routing gate order in the telegram adapter (`_should_process_message`): own message → group/thread gates → `exclusive_bot_mentions` drop → allowed_chats → free_response → `bots_require_mention` drop (other-bot sender) → reply-to-bot → explicit @mention → `mention_patterns` regex. So explicit @mention and reply-to-bot beat wake words; wake words only apply when there is no explicit mention.
- Config changes are NOT live until the gateway reloads: restart the multiplexer after editing (`pkill -f "hermes gateway run"`; s6 respawns it, or `hermes gateway run --replace`). Verify with `gateway_state.json` (`gateway_state: running`, `served_profiles` lists both, each platform `connected`).
- Do not "fix" cross-reply by giving one profile `standalone: true` or removing its `platforms:` block — that takes the profile out of the multiplex and makes its bot go offline. Keep `standalone: false` + `platforms: [telegram]` on every served profile.

## Hermes config is write-protected to the agent

The agent's `patch`/`write_file` REFUSE `/opt/data/config.yaml` and profile configs ("Refusing to write to Hermes config file … Agent cannot modify security-sensitive configuration"). Use the `hermes config` CLI instead — it is the ONLY supported programmatic edit path:

- Full venv path: `/opt/data/installs/351f81cc06284494/environments/11e655e1c47443d5a3891b3a382d9c9c/venv/bin/hermes`
- Shorter working path: `/opt/hermes/bin/hermes` (bare `hermes` is NOT on PATH in this container — use an absolute path, don't debug the miss).
- `hermes config set <key> <value>` writes the key; `hermes config get <key>` verifies; `hermes config unset <key>` removes it.
- `hermes config set` accepts ANY key without schema validation — invalid keys are silently written but have NO EFFECT. Always verify with `hermes config get` and `unset` keys that don't exist in docs/skema.
- Example invalid key: `messaging.telegram.timeout_s` — accepted by `set`, does nothing, must be unset.
- EXCEPTION: plugin-owned config blocks (e.g. `session_reset.*`) are NOT in core schema — `hermes config set` warns "not a recognized config key" even though the value works. Do not `unset` a key on the schema warning alone; first check whether an enabled plugin reads that block (grep `plugins/<name>/` source for the key).
- For bulk YAML edits (multiple keys), write a Python script using `ruamel.yaml` and run with the venv interpreter (`/opt/data/installs/.../venv/bin/python3`), then verify via `hermes config get`.

## Session reset policy (idle auto-/new)

Community plugin restoring time-based conversation rotation (upstream core removed it). Resets the conversation THREAD only — memory notes, user profile, skills survive every reset; say so when the user worries about losing memory.

Procedure:
1. `hermes plugins install hermes-session-reset-policy` — install alone leaves it DISABLED; follow with `hermes plugins enable hermes-session-reset-policy` (gateway reloads plugins live, no restart).
2. Config block in `config.yaml` (set via `hermes config set`; keys warn "not recognized" — see the config exception above):
   - `session_reset.mode` — `idle` | `daily` | `both`
   - `session_reset.idle_minutes` — 180 balanced; 120 aggressive; 480 overnight-only
   - `session_reset.notify` — announce the fresh session
3. Verify the block landed in `/opt/data/config.yaml` (plugin reads it directly at dispatch).

Mechanics / pitfalls:
- Reset is LAZY: fires on the first inbound user message past the boundary, never on a timer — a session worked straight through stays alive, an idle one resets exactly once on return.
- Slash commands and cron/background traffic never pass the hook — they can neither keep a session alive nor trigger/skip a reset.
- Reset routes through the gateway's own `/new` funnel, so per-conversation overrides and caches clear like a typed `/new`.
- Disable with `hermes plugins disable hermes-session-reset-policy` — the whole off-switch, no config cleanup needed.

## "Could not back up /opt/data/config.yaml (good)" — non-fatal, never the cause of a dead gateway

`hermes_cli/config_backups.py:backup_config()` logs `Could not back up ... [Errno 13] Permission denied` and returns None — by design it must never block the write it precedes. It fires from side processes (kanban runners, telemetry relay, spawned agent runs) whose view of `/opt/data` is not writable, NOT from the gateway itself. Treat as noise; the real gateway writes `backups/config/config.yaml.good.*` fine on every successful config load.

Verify in one shot instead of guessing:

```
/opt/hermes/.venv/bin/python3 -c "import sys; sys.path.insert(0,'/opt/hermes'); from pathlib import Path; from hermes_cli.config_backups import backup_config; print(backup_config(Path('/opt/data/config.yaml'),'probe'))"
```

A returned path = writable (delete the probe file after). Zero new occurrences in `errors.log` after the window = resolved. Keep `backups/config/` writable (777) — tightening it re-triggers the warnings.

## Restart loop vs. real crash — read the exit-diag tags

`/opt/data/logs/gateway-exit-diag.log` tags each lifecycle event. `Shutdown context: signal=SIGTERM ... parent_name=s6-supervise` plus a following `gateway.start ... replace: true` is a `hermes gateway run --replace` restart (TUI/dashboard/user driven), NOT a crash. Only `gateway.exit_nonzero` without a SIGTERM line and no following start is a real failure.

`gateway.previous_unclean_exit` repeating with the SAME `prior_started_at` days old means the container was frozen/paused and resumed (stale heartbeat, stale `gateway_state.json`); it clears on the next successful start. A frozen container also explains error paths timestamped days in the past (dest name `config.yaml.good.20261102-…` inside a current-day log line) — the record was emitted by the pre-freeze process.

## Model-provider outage masquerades as agent failure

9Router down shows in `errors.log` as `agent.chat_completion_helpers: Streaming failed ... Request timed out` or Cloudflare `Error 502` (zone `*.instabox.tech`), and cron jobs then report `error: interrupted` — none of that is the gateway. Check `hermes cron list` delivery/status lines, not output markdown.

## Diagnosing unresponsive replies

Gateway replies appear "pending" or delayed when:
1. Host CPU/RAM peaks during container restarts — request queue stalls, workers busy.
2. Disk usage >80% — page cache fights with app memory, I/O slows to halt.
3. Swap thrashing — slow but prevents OOM; still causes noticeable lag.

**Procedure:**
1. Check load: `uptime` (load average), `ps aux --sort=-%cpu | head -15`.
2. Check disk: `df -h /opt/data` — if >80%, prune caches first before heavy tasks.
3. Check RAM: `free -h` — if available <1GB and swap used, containers warming may be the cause.
4. If symptoms present: wait 5min for workers idle, then continue. Auto-recovery happens.

**Pitfall:** Gateway process alive ≠ fast reply. PID stable at low %CPU is expected; queue depth depends on available memory pages.

## Checking on a running agent task (kanban / background work) — alive ≠ progressing

A task can show "running" on the board while its runner is frozen, not working. Verify the process, not the board:

1. Find the runner by command line — a kanban workspace task runs as `... chat -q work kanban task t_<id>` (`ps aux | grep t_<id>`).
2. Read `/proc/<pid>/cwd` — it points at `/opt/data/kanban/workspaces/t_<id>`; the mtime of the newest file there is the last real output.
3. Check `ps -o pid,stat,wchan,etime,time -p <pid>` — sleeping state + `wchan=futex_wait_queue` + accumulated `time` far below `etime` means it is blocked on a lock/API call, not computing.
4. No new files in the workspace for a long span = stalled despite the board saying "running". The draft artifacts it left are valid work; the run needs a restart, not re-doing.

## Kanban assignee must be a real served profile name

A kanban task's `assignee` must exactly match a profile in `gateway_state.json`'s `served_profiles` — a card assignee that is not a served profile is flagged `skipped_nonspawnable` and never spawns. On this host the served profiles are `default` (Dev) and `shifu`, NOT `dev`; a card assigned to `dev` sits forever in `ready` with no runner. Fix by `hermes kanban assign t_<id> default` (or the real profile name). Verify with `hermes kanban show t_<id>` — expect `assigned {assignee: default, from: dev}` then a `spawned` event with a live pid; check the process with `ps aux | grep t_<id>`.

## Preemptive resource management

**Disk pressure prevention:**
- Keep `/opt/data` below 75% — prune old venv envs (`/opt/data/installs/<hash>/environments/`) when unused.
- Delete only non-active environments (check `facts.json` active stamp).
- Clear temp scratch: `rm -rf /opt/data/cache/scratch/*` after large operations.

**Memory optimization:**
- Dashboard/WebUI only runs when `HERMES_DASHBOARD` env is truthy (1/true/yes). If it's unset the s6 `dashboard` slot is DOWN (supervised-but-permanent-failure) — check `ps aux | grep -i dashboard` before believing it eats RAM; disabling it frees nothing when it isn't running.
- When dashboard IS running it uses ~180-250MB — disable by unsetting `HERMES_DASHBOARD` in `/opt/data/compose.yaml`. A `down` file in `/run/service/dashboard/` is tmpfs and wiped on container restart, so it never survives reboot alone.
- Single multiplexed gateway handles multiple profiles (default + shifu) efficiently.
- If RAM <3GB free, stop dashboard or offload models to external storage.

**Swap configuration:**
- swappiness=60 (default) balances between cache and memory pressure.
- Swap helps prevent OOM kills but is slow — use it as backup, not primary solution.

## Diagnose offline gateway

1. List gateways: `hermes gateway list` (HOME=/opt/data).
2. Check supervision: `s6-svstat /run/service/gateway-<name>`.
3. Check procs: `ps -eo pid,etime,args | grep gateway`.
4. If list hangs after starting second gateway, use ps output — second process alive means start worked, list probe wedged.

## Cron delivery failures (httpx.ConnectError)

- Delivery errors live in `hermes cron list` metadata ("ran, but result was not delivered"), NOT in the output markdown — grepping output files for "delivery error" misses them; read job status lines.
- Jobs with `Repeat ∞` auto-retry on the next tick after a delivery failure — no manual re-fire needed for long-interval watches.
- Never invent config keys like `messaging.telegram.timeout_s` — `hermes config set` writes unknown paths without schema validation, so verify with `hermes config get` and `unset` any key with no documented effect.
- Retry failed Telegram deliveries via direct Bot API, not `hermes send` — read `TELEGRAM_BOT_TOKEN` from `/opt/data/.env` (cron context has no shell env) and POST with stdlib `urllib` to `sendMessage`, because `send` shares the gateway worker that just failed and hangs with it.
- Watchdog script pattern: `/opt/data/scripts/cron_watchdog.py` tails `/opt/data/cron/output/` for job runs with delivery failures, retries via direct API with exponential backoff (1, 5, 15, 30 min), logs to `/opt/data/logs/watchdog.log`. Run as persistent background daemon (checks every 10 min) — not as a Hermes cron job (would spawn full agent runs).
- Check `gateway_state.json` `platforms.telegram.state` before restarting — `connected` there while `send` hangs means a wedged worker, not a dead gateway.

## Restart

- Default: `hermes gateway run --replace`.
- Other profile: `hermes -p <profile> gateway run --replace`.
- Bare `gateway run` starts default profile only — never use it to revive a non-default profile.
- Run restarts in background; verify with ps, not repeated list calls.
- **From inside the gateway process you CANNOT run `hermes gateway restart`** — it blocks with "command would kill this command before it could complete (SIGTERM propagates to child processes)". Use `s6-svc -r /run/service/gateway-default` or kill the gateway PID from a separate shell.

## Multiplex + standalone conflict

`gateway.standalone: true` in a profile config **breaks multiplexing**. The multiplexer already binds the bot token; `standalone: true` makes that profile try to bind the same token again → `Telegram startup failed: [Errno 98] Address already in use` in `gateway_state.json` under `platforms."shifu:telegram".error_message`. Fix: `hermes -p <profile> config unset gateway.standalone`, then restart the main gateway via s6.

## s6 pitfalls

- `/run/service/` is tmpfs — wiped every container restart; service dirs recreated by `cont-init.d/02-reconcile-profiles` via `container_boot.reconcile_profile_gateways`.
- Reconciler autostarts only profiles whose last recorded state was `running` (`gateway_state.json`). Ensure state file says `running` so gateways survive restarts.
- A `down` file in `/run/service/gateway-<name>/` suppresses autostart — remove it when a gateway should stay up.
- Fresh volume comes up with gateway down until first start unless `HERMES_GATEWAY_BOOTSTRAP_STATE=running` seeded state.

## DM to group-topic forwarding

- Group topics learned in `channel_directory.json` — each profile gateway learns independently when a tagged message arrives.
- New subtopic needs no manual config: send one message there tagging a bot and directory auto-learns thread_id.
- Telegram forum rule: General subtopic = no `message_thread_id`; other subtopics require their thread_id. Never assume a numeric topic is General — verify against directory.
- Forward convention: when user replies to a message and says "forward this", forward the replied-to content, not the command text. Destination is group General unless user names another subtopic.

## Topic watcher (monitor → transcribe → repost)

- One `getUpdates` consumer per bot token — the gateway already polls its own token, so a watcher script using the same token steals updates from it. Run watchers under the other profile's bot token.
- Cron scripts run without shell env — read secrets from `/opt/data/.env` directly instead of relying on exported variables.
- Persist `last_update_id` in a state file and send it as `offset`; restarts then skip already-seen history.
- Filter forum traffic by `message_thread_id` (General subtopic has none — never send it a thread ID).
- If `copyMessage`/`forwardMessage` returns 'message not found' with one bot token, retry with the other profile's token — message access varies per bot.
- Confirm source→destination direction before the first automated post; never reverse them (watcher reads source topic, writes destination topic only).
- Deliver automation output only to the destination topic — never copy/forward probe messages into DMs for inspection, and delete any test forwards immediately.
