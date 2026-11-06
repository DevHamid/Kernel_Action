# Telegram gateway status bubbles: taxonomy and modification

The gateway shows three distinct status bubbles over Telegram. They are often
confused; each has a different data source, edit behavior, and disable path.
Identify which one you're looking at before modifying anything.

## The three bubble types

| Bubble | Looks like | Source | Editable? |
|---|---|---|---|
| Busy-ack | "Working — 6 min — waiting for stream response (211s, first_chunk)" | `gateway/run_busy.py` `_compose_busy_ack_message` | No — one-shot, debounced 30s, never re-edit |
| Tool-progress | Tool label while tools fire | `gateway/run_turn_runner.py` `_send_progress_text` | Yes — re-edit same message per tool call (`_edit_progress_message`) |
| Wait-notice | "⏳ waiting on {model} — {n}s waiting for the first stream chunk" | `agent/chat_completion_stream_monitor.py` → `status_output.py._emit_wait_notice` | No — sent once, rewritten only on phase/watchdog-deadline change |

**The "Working — N min" bubble is the busy-ack**, not the tool-progress bubble.
Its detail string (`waiting for stream response (Ns, first_chunk)`) is the
stream monitor's liveness touch surfaced by the busy-ack renderer. It carries
`elapsed_min` and iteration data, but it is one-shot — so an animated progress
bar cannot live on it.

## Disabling the busy-ack (native kill-switch, no code patch)

The busy-ack gates on `HERMES_GATEWAY_BUSY_ACK_ENABLED` (default `true`),
checked at call time via `os.environ` just before the debounce. Set it to
`false` in the profile's `.env` (and the shared `.env` if multiplexed) and
restart the gateway. Input is still processed; only the ack is suppressed.

Pitfall: the var is **not** visible in `/proc/<pid>/environ` — the gateway loads
`.env` at runtime via `load_hermes_dotenv`, so absence from the initial process
environ is expected, not a failure. Verify by reading the code gate
(`run_busy.py` ~line 884), not the environ.

Pitfall: a screenshot's bubble timestamps predate the gateway restart that
applied the kill-switch. Check mtime of the image vs the restart time before
concluding the disable failed.

## Rendering a real progress bar on the tool-progress bubbles

The tool-progress bubble is the correct home for an animated bar because it is
re-edited in place per tool call. Real percentage data exists:

- Agent is reachable at `ctx.agent_holder[0]`.
- `_agent_activity_summary(agent)` (static, in `run_turn.py`) returns
  `api_call_count` and `max_iterations`.
- `format_iteration_progress(api_call_count, max_iterations)` (from
  `agent/session_activity.py`) gives the text form, but not a visual bar.

Implement the bar in the redirect plugin's `_send_progress_text` (isolated — no
core gateway edits). Bar chars: `▬` filled, `▭` empty.

Pitfall: `max_iterations` defaults to `sys.maxsize` (unbounded). A percentage is
mathematically wrong there — render a full indeterminate block bar (`▬` × length)
with no percent instead of a bogus 0%.

Pitfall: the percent reflects API-call iterations, not wall-clock time, and
reports 0% until the first activity report lands. This is inherent to the data
source, not a renderer bug.

Pitfall (read-before-write): the plugin exists in both the default and per-profile
plugin dirs (`/opt/data/plugins/…` and `profiles/<p>/plugins/…`). Patch the
shared copy, then `cp` to the profile copy and `diff` to confirm identical; the
gateway must be restarted (`s6-svc -r /run/service/gateway-default`) to reload
plugin code.

Pitfall (stale code after restart): when a restart races the patch flight, the
just-restarted gateway can still run the pre-patch code. Verify the change is
live by reading the runtime log behavior (e.g. the last SEND has no following
DELETE), not only the on-disk file — the file may be correct while the loaded
plugin is stale. Compile-check with `python3 -m py_compile` before syncing.

## 24h auto-delete sweep for accumulated progress bubbles

To delete old progress bubbles by age instead of immediately replacing the
previous one (the pattern this user settled on after rejecting immediate-delete
twice), persist the sent-bubble ids in a JSON file and sweep on each send. This
survives gateway restarts and needs no external bot or cron:

- Record each sent bubble as `{message_id, sent_ts}` in a small JSON list,
  capped (e.g. 300 entries), path from an env var with a `/tmp` default.
- On each send, load the list, delete any recorded bubble whose `sent_ts` is
  older than the window (24h), then prune the list.
- The sweep runs inside the same `_send_progress_text` hook, piggybacked on
  sends — no separate cron/external delete bot.
- Telegram only lets a bot delete its own messages within 48h of send, so keep
  the window ≤ 24h (24h chosen).
- Make the window a module constant (e.g. `AUTO_DELETE_S = 24 * 3600`).
- Pitfall: the sweep function must be `async def` if it is awaited — a sync
  `def` that is awaited fails at compile time (`exit 1`), not at runtime.
- Pitfall: `/tmp` history means the sweep state resets on reboot. If that
  matters, point the history path at a durable location via the env var.

## Publishing the plugin (public repo)

Before `git init` + push, scan the plugin dir for secrets (`grep -rniE
'token|apikey|api_key|secret|password'`); target chat/thread ids are not
secrets but are install-specific. For a public repo, replace hardcoded ids with
env vars that default to the author's values (`os.environ.get('PROGRESS_TARGET_CHAT_ID',
"-100…")`), add a README documenting the env vars and how to derive chat/thread
ids from a topic link (`https://t.me/c/<chat>/<thread>` → chat `-100<chat>`,
thread `<thread>`), and add a `.gitignore` for the runtime history file. Set a
local git identity (`git config user.email/user.name`) — don't rely on global
config. This keeps behavior unchanged locally while making the plugin generic.

## Working practice

- The wait-notice's `thinking_callback` is an agent callback, not a Telegram
  message; it only reaches Telegram via the busy-ack (now disabled) or a status
  touch. Don't route it through the redirect plugin by name.
- Never try to animate the busy-ack or wait-notice — one-shot messages can't
  re-edit; a bar there would be fake.
- When asked "can these bubbles show a progress bar?", answer by type: the
  busy-ack is now disabled (moot), the tool-progress bubbles already carry the
  real bar, the wait-notice is a provider-wait with no iteration data.
