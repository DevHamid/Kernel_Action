# Diagnosing "bot is silent in a group chat"

Applies to a gateway serving one or more profiles over Telegram (multiplexed or
single). The bot answers DMs instantly but never replies in a group, or one bot
in the group answers while another stays silent.

Work top-down. Each step eliminates a whole layer; skipping to the bottom wastes
the most time because every layer below it looks like a plausible cause.

## 1. Prove whether the update ever reached the agent

The gateway log is the only source of truth. Session ids carry the profile:
`agent:<profile>:telegram:<dm|group>:<chat_id>[:<thread_id>]`.

```bash
# Which profile actually received group traffic?
grep -E 'Flushing text batch agent:|inbound message:' ~/.hermes/logs/gateway.log | tail -40

# Did a specific profile get ANY inbound, or only idle evictions?
grep -E 'agent:<profile>:telegram' ~/.hermes/logs/gateway.log | tail -40
```

Read the shape of the result:

- `inbound message:` + `Flushing text batch agent:<profile>:…` → delivery works;
  the problem is response generation, not routing. Stop here and debug the model.
- Only `Agent cache idle-TTL evict: session=agent:<profile>:telegram:group:…`
  lines → the session was created but never fed. **Zero inbound.** The fault is
  upstream of the agent: adapter, Telegram delivery, or the mention gate. Never
  debug the model in this state.
- Group traffic appears only under `agent:main:…` while the second bot's profile
  shows nothing → the other bot's adapter is connected but its updates are being
  dropped by gating, not missing.

`Re-scanned profile '<name>' after config/.env change (0 adapter(s) connected)`
is a *reconcile* line — it says the rescan attached nothing new, not that the
profile has no adapters. Confirm with the `✓ telegram connected (profile: <name>)`
lines instead, and prefer the most recent connect per profile.

## 2. Rule out Telegram-side delivery before touching config

Two API calls settle it. Both are cheap and both are frequently the actual
answer, so run them before anything else.

```python
# Privacy mode: true means the bot CAN read all group messages.
tg_api.call('getMe', {})['result']['can_read_all_group_messages']

# Admin status + per-right detail in this chat.
tg_api.call('getChatMember', {'chat_id': CHAT_ID, 'user_id': BOT_ID})
```

- `can_read_all_group_messages: false` → BotFather privacy mode is on. Telegram
  delivers only commands and @mentions to that bot. Fix in BotFather
  (`/setprivacy` → Disable) or make the bot a group admin with read access.
- `status: administrator` alone does **not** make group messages flow. Admin
  rights and privacy mode are separate gates; a bot can be a full admin and still
  receive only mentions.
- Both fine → delivery is not the problem. Go to step 3.

## 3. Webhook vs polling — confirm which mode the gateway uses

`getWebhookInfo` returning an empty `url` means the bot is in **polling** mode,
not broken. An empty webhook plus a healthy adapter is normal for a gateway that
long-polls; do not "fix" it by registering a webhook.

To prove a gateway is actively polling a token, call `getUpdates` yourself — a
live poller makes your call fail with a conflict:

```
409 Conflict: terminated by other getUpdates request
```

That 409 is the *positive* signal: something is polling. A clean `getUpdates`
result instead means nothing holds the token and the adapter really is dead.

Never leave your own `getUpdates` poller running against a token the gateway
uses — it steals updates and the two fight over the offset.

## 4. The mention gate (the usual culprit for a silent second bot)

The Telegram adapter drops group messages before dispatch unless the message
addresses the bot. Each gate resolves **scoped env var → `config.extra[key]` →
default**, so setting either the profile `.env` var or the `telegram.extra` key
works:

| Key | Env var | Default | Effect |
|---|---|---|---|
| `require_mention` | `TELEGRAM_REQUIRE_MENTION` | `false` | Group messages need an explicit trigger |
| `exclusive_bot_mentions` | `TELEGRAM_EXCLUSIVE_BOT_MENTIONS` | `true` | An explicit @mention of another bot routes the message away, not to us |
| `bots_require_mention` | `TELEGRAM_BOTS_REQUIRE_MENTION` | `false` | Another bot's message must @mention us (quote-reply is not enough) — the anti-loop switch |
| `guest_mode` | `TELEGRAM_GUEST_MODE` | `false` | Non-allowlisted groups may still trigger via @mention |
| `allowed_chats` | `TELEGRAM_ALLOWED_CHATS` | — | Chat ids the bot responds in at all |
| `free_response_chats` | `TELEGRAM_FREE_RESPONSE_CHATS` | — | Chats where mention is not required |
| `free_response_topics` | `TELEGRAM_FREE_RESPONSE_TOPICS` | — | `<chat_id>:<thread_id>` pairs, General topic = `1` |
| `observe_unmentioned_group_messages` | `TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES` | `false` | Store skipped messages as context without dispatching |

Diagnostic order: read the *effective* values for the silent profile (its own
`config.yaml` under `telegram.extra`, plus its `.env`) — a value inherited from
the default profile does not apply to a profile that has its own config.

Fixes, most surgical first:

1. `free_response_chats: [-100…]` — bot answers everything in that one group,
   nothing elsewhere. Preferred when only one group should be free-response.
2. `require_mention: false` — bot behaves like a normal participant everywhere it
   is allowed. Only correct when the group is already narrow.
3. Keep `require_mention: true` and tell the user to @mention the bot. Correct
   answer when the user actually wants on-demand behaviour; say so instead of
   silently widening the gate.

Set these with `hermes config set` / the profile's `.env`, never by hand-editing
`config.yaml` — a stray indent corrupts the file and takes the live gateway down.

## 5. Two bots in one group: loop hygiene

With two Hermes bots in a chat, an unmentioned reply from bot A can trigger bot B
which replies and triggers A again. `exclusive_bot_mentions: true` (default) plus
`bots_require_mention: true` on both sides is what prevents it. Do not disable
`bots_require_mention` to "make the second bot hear everything" — that converts a
silence bug into a reply loop. Widening `free_response_chats` is the safe knob.

## 6. Owning a thread when two bots share the same group

When two bots carry the same trigger words (`hello guys`, `hi dudes`, `hey
everyone`, …) and a group thread is owned by neither, a single greeting fires
BOTH bots — no @mention needed. Ownership is per-thread, not per-chat:

- Bot A owns the thread: `telegram.free_response_topics` += `<chat_id>:<thread_id>`
  (General topic = `1`).
- Bot B stays out of it: `telegram.ignored_threads` += `<thread_id>` (int, no chat prefix).

Apply both sides. Set with `hermes config set`, never hand-editing. After each
set, verify the file re-parses as a YAML string list (`python3 -c "import yaml;
print(yaml.safe_load(open('…/config.yaml'))['telegram']['…'])"`) before moving on —
an unquoted write can land as a map key and silently corrupt the value.

### Secondary profiles hot-apply; the primary profile does NOT

The multiplex reconcile watcher (`gateway/run_profile_reconcile.py`) rescans served
**non-primary** profiles on config/.env change — it deliberately skips the
active/primary profile (`n != active`). So:

- A change to a secondary profile (e.g. `profiles/shifu/config.yaml`) is picked up
  live. The log line `[MULTIPLEX] Re-scanned profile '<name>' after config/.env
  change` confirms it; you'll see one rescan per edit.
- A change to the **primary** profile's own config (or the root `config.yaml`
  when `default` is primary) is NOT hot-applied. The Telegram adapter builds its
  `PlatformConfig` once at adapter start and serves `config.extra` from that
  cached object, so even a fresh-read helper sees the old values. Apply it at the
  next gateway restart — don't expect a rescan line for it.

Before assuming a second daemon serves a profile, check the processes: only one
multiplexed gateway python process may be running. s6 service dirs live under
`/run/service/`; a `gateway-<profile>` dir carrying a `down` flag is a supervised
but disabled service, not a running one.

## Working practice on gateway logs

`gateway.log` is large and lines are long. Bound every read:

```bash
grep -n '' ~/.hermes/logs/gateway.log | tail -60 | cut -c1-220
grep -iE '<narrow pattern>' ~/.hermes/logs/gateway.log | tail -40
```

Dumping a whole section or several `sed -n` ranges into one tool result can
overflow the call and lose the result entirely; grep narrowly, truncate columns,
and make several small reads instead of one large one.
