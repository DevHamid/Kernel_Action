# Troubleshooting

### Voice not working
1. Check `stt.enabled: true` in config.yaml
2. Verify provider: `python -c "import pm; pm.sync_venv(['stt-whisper'], explicit=True)"` or set API key
3. In gateway: `/restart`. In CLI: exit and relaunch.

### Tool not available
1. `hermes tools` — check if toolset is enabled for your platform
2. Some tools need env vars (check `.env`)
3. `/reset` after enabling tools

### Model/provider issues
1. `hermes doctor` — check config and dependencies
2. `hermes auth` — re-authenticate OAuth providers (or `hermes auth add <provider>`)
3. Check `.env` has the right API key
4. **Copilot 403**: `gh auth login` tokens do NOT work for Copilot API. You must use the Copilot-specific OAuth device code flow via `hermes model` → GitHub Copilot.

### Changes not taking effect
- **Tools/skills:** `/reset` starts a new session with updated toolset
- **Config changes:** In gateway: `/restart`. In CLI: exit and relaunch.
- **Code changes:** Restart the CLI or gateway process

#### Multi-profile s6-supervised container (one gateway, both profiles)
Config is read **only at gateway startup**. `/new` reloads config for the *current* profile's session only — it does NOT apply to another profile served by the same gateway. To load changes for any other profile, restart the whole gateway:
```bash
# the service is `main-hermes` under s6; s6-svc lives in /package/admin/s6-<ver>/command
/package/admin/s6-2.15.0.0/command/s6-svc -r /run/s6-rc/s6-rc-init:<id>/servicedirs/main-hermes
```
The servicedir id (`<id>`) is opaque — discover it with `find /run -path "*main-hermes*supervise" -type d`. Restarting the gateway drops the in-flight turn (s6 respawns it), so a restart is the LAST action of a task — config, env, and the verification plan must already be in place before it fires; the session can survive it, but never assume that. On the multiplexed host the service dirs are `/run/service/gateway-default` and `/run/service/gateway-shifu`, hermes-owned and regenerated at every boot, so service-level edits there do not survive — put configuration in `.env`. Don't try `systemctl` — s6-overlay, not systemd.

#### One gateway per host — never spawn a second
`hermes -p <profile> gateway run --replace` exits **78** when the host gateway already serves that profile: exactly one gateway per host is the inbound process for every profile, and a second one would double-bind its platforms (two pollers on one bot token, port conflicts). Restart the host gateway instead — `hermes -p default gateway restart`.

A config write to a profile served by a multiplexed host gateway triggers an automatic re-scan (gateway.log: `run_profile_reconcile ... Re-scanned profile '<name>' after config/.env change`), so new sessions pick the change up with no restart. An **in-flight session is the exception**: it keeps the aux client it resolved at startup, so a fixed `auxiliary.*` provider still fails in the very session where you diagnosed it. Confirm the fix in a fresh session — or after the host restart — before calling it working.

### web_extract shows a stale page (result caching)
`web_search`/`web_extract` cache results for 20 minutes (PR #94618) — a
repeat fetch of the same URL within the TTL is served from cache, which
can look like "my website changes aren't showing up."

Automatic carveouts (always fetched live, never cached):
- localhost / 127.0.0.1 / `*.local` / `*.localhost` / single-label LAN
  hostnames / private + link-local IP ranges (dev servers, hot-reload
  builds, chat-GUI artifact previews)
- URLs matched by `security.website_blocklist`
- failed responses and keyless-rescue-served responses

Developing a site tested over the PUBLIC internet (Vercel/Netlify
preview, ngrok/cloudflared tunnel, staging domain)? Public DNS isn't
auto-carved-out — list the host in config.yaml:

```yaml
web:
  cache_exempt_hosts:      # always fetched live; effective immediately
    - mysite.vercel.app
    - "*.ngrok-free.app"
    - mysite.dev           # suffix match: also covers preview.mysite.dev
```

Blunt instruments: `web.cache_ttl_minutes: 1` (min) or
`web.cache_enabled: false` disables both caches entirely.

### Skills not showing
1. `hermes skills list` — verify installed
2. `hermes skills config` — check platform enablement
3. Load explicitly: `hermes -s name` (or the skill's own `/<name>` slash command)

### Gateway issues
Check logs first:
```bash
grep -i "failed to send\|error" ~/.hermes/logs/gateway.log | tail -20
```

Common gateway problems:
- **Gateway dies on SSH logout**: Enable linger: `sudo loginctl enable-linger $USER`
- **Gateway dies on WSL2 close**: WSL2 requires `systemd=true` in `/etc/wsl.conf` for systemd services to work. Without it, gateway falls back to `nohup` (dies when session closes).
- **Gateway crash loop**: Reset the failed state: `systemctl --user reset-failed hermes-gateway`

### Gateway platform down: "token lock cannot be taken" / "not usable by this user"

A per-bot token lock is mutual exclusion for `getUpdates` — when it cannot be taken that platform is DOWN, not degraded. Treat the message as a gateway outage, not a warning.

Diagnose in this order:
1. Grep the logs for the exact strings (`gateway-locks is not usable`, `Host gateway lock could not be opened`, `Host backend lock could not be opened`) and time-box with `awk` so only post-restart lines count.
2. `ls -ln` the lock dir named in the error and compare its owner to the running gateway's uid. Mode `700` owned by another uid is the classic failure: the dir was created before a UID remap and is unwritable forever.
3. Read a healthy `.lock` file — JSON carrying `pid`, holder, and profile — to confirm the new process actually acquired the lock.

Root cause on s6-overlay hosts: the stage hook chowns a FIXED subdir list at boot, so any state dir outside that list keeps its pre-remap uid. Recurring victims: `.local/state`, `.hermes`, `cache`, `kanban`, `runtime`, `pending_messages`, `shared-state.db`. Each fails closed somewhere different (bot deliveries pause, dispatcher tick fails, readonly-db errors) — fix the ownership, not the symptom.

Repair without root (no `sudo`, no docker socket, `s6-overlay-suexec` is pid-1-only):
- `HERMES_GATEWAY_LOCK_DIR` overrides the lock root for both `gateway.status._get_lock_dir()` and `host_state_dir()`. Set it in `$HERMES_HOME/.env` AND every `profiles/<name>/.env` (each profile loads its own dotenv), `mkdir -p` the new dir with `chmod 700`, then restart the gateway.
- It is an env override with no config.yaml key, so `.env` is its correct home — the value must be in the gateway's process environment at startup. Verify with `/proc/<pid>/environ`, never your own shell.

The durable repair is host-side `chown -R` over the whole state tree; the env override unblocks only the lock path while the other stale dirs keep failing. Say so in the reply so the host fix is not skipped.

After a rejected or interrupted command: it has NO side effects — a `chmod +x` that lived inside a rejected command never ran. Re-verify every step you believe you took.

### Platform-specific issues
- **Discord bot silent**: Must enable **Message Content Intent** in Bot → Privileged Gateway Intents.
- **Slack bot only works in DMs**: Must subscribe to `message.channels` event. Without it, the bot ignores public channels.
- **Windows-specific issues** (`Alt+Enter` newline, WinError 10106, UTF-8 BOM config, line endings): see `references/windows-quirks.md`.

### Auxiliary models not working
When `auxiliary.vision` is left `auto`, vision follows the **delegated main model** (`delegation.model`), not `model.default` — so a combo/rotating delegation alias that routes to a dead or deprecated upstream makes `vision_analyze` 410 even though chat works. Fix: pin a healthy vision-capable model, and a custom provider also needs `base_url`:
```bash
hermes config set auxiliary.vision.provider <your_provider>
hermes config set auxiliary.vision.model <vision_model>
hermes config set auxiliary.vision.base_url http://<router>:<port>/v1
```
If `auxiliary` tasks (vision, compression, session_search) fail silently, the `auto` provider can't find a backend. Either set `OPENROUTER_API_KEY` or `GOOGLE_API_KEY`, or explicitly configure each auxiliary task's provider:
```bash
hermes config set auxiliary.vision.provider <your_provider>
hermes config set auxiliary.vision.model <model_name>
```

A `401 invalid_api_key` on an auxiliary task means the request left with **no usable credential** — prove it by curling the same endpoint with the key from `.env`; a 200 there isolates the fault to Hermes's provider resolution, not the gateway or key. The usual cause is `custom:<name>` matching no registered `custom_providers[].name` (the `custom:` prefix is stripped before matching, and matching is exact on the normalized name — `custom:9router` does not match an entry named `9router-shifu`), so `key_env` is never resolved. The named branch then returns nothing and resolution falls through to the bare `custom` route, which substitutes the literal placeholder `no-key-required` as the api_key and still sends an `Authorization` header — so hunt that placeholder, not a missing header. List the real names before setting anything:
```bash
/opt/hermes/.venv/bin/python -c "
import sys; sys.argv[0]='hermes'
from hermes_cli.config_providers import get_compatible_custom_providers
from hermes_cli.config import load_config
for e in get_compatible_custom_providers(load_config()):
    print(e.get('name'), '->', e.get('key_env'))
"
```
**Verify the fix actually loads a key** — resolution succeeding is not the same as a credential resolving. Probe it under the profile's own env (the secret scope is per-profile, so a bare shell reads the wrong `.env`):

```bash
HERMES_HOME=<profile-home> HOME=<profile-home>/home HERMES_PROFILE=<name> /opt/hermes/.venv/bin/python - <<'PY'
import os, sys, site
sys.argv[0] = 'hermes'
site.addsitedir(os.environ.get('HERMES_SITE', '/opt/hermes/.venv/lib/python3.13/site-packages'))
from agent.auxiliary_client import resolve_provider_client
client, model = resolve_provider_client('custom:<name>', model='<model>',
    explicit_base_url='<base_url>', is_vision=True, task='vision')
if client is None:
    print('NO CLIENT — provider unknown to the registry')
else:
    k = getattr(client, 'api_key', None) or ''
    print('model:', model, '| base:', getattr(client, 'base_url', None), '| key:', k[:8] or 'NONE')
PY
```

`key: sk-…` means the credential resolved; `key: no-key-` (or `NONE`) means the placeholder path — the name still does not match. Use `resolve_vision_provider_client()` for the vision task specifically; it applies the `auxiliary.vision` overrides first.

When reading a live gateway's environment, a `grep -c` returning `0` on `/proc/<pid>/environ` can mean the file was unreadable (permission denied) rather than that the variable is absent — confirm readability before concluding the gateway lacks the var.

Env vars in `_AUXILIARY_TASK_ENV` (`AUXILIARY_VISION_PROVIDER`, `_MODEL`, `_BASE_URL`, `_API_KEY`) override config.yaml, but only exist if the gateway inherited them — read `/proc/<gateway-pid>/environ`, never your own shell, or a var exported in your shell masks which value is actually live.

### Compression warning: "Context is over the compression threshold … structural_backoff:N"
This is NOT an error — it's the anti-thrash guard. Auto-compression no-ops when the middle of the transcript holds nothing summarizable, and each no-op arms a 300s `structural_backoff` (so the next turns skip auto-compression with this warning instead of retrying). It loops: over threshold → auto-compress → no-op → backoff → warning → backoff lapses → retry → no-op again.

Diagnose by reading the telemetry (the failure_class is the answer):
```bash
grep -n "compression attempt telemetry" ~/.hermes/logs/agent.log | tail -15
# failure_class tells you WHY the no-op happened
```
Recurring no-op classes and their meaning:
- `insufficient_messages` — too few messages in the middle to bother summarizing
- `empty_post_handoff_window` — the compressible middle is already compressed handoffs; the session is structurally exhausted

Model limit lives in config: `compression.context_length` (default 65536); threshold = `threshold_percent` of it (85% → 55705).

Fix ladder:
1. **Checkpoint before restarting** — `/new` resets the chat window but not the repo: the session's in-context mid-flight state is lost unless it was written to disk. Before `/new`, commit/push git or write a STATUS.md in the project dir, and refresh memory/skills with durable facts. A project must be resumable from disk alone, never reliant on in-chat state. Do this as soon as the warning starts repeating — don't let the session die at the wall.
2. `/new` — clean, honest fix when the session is structurally exhausted (compressible middle gone).
3. `/compress` — force: bypasses the backoff and retries immediately, but will likely no-op again if the window is all handoffs.
4. Config headroom (postpones, doesn't cure): raise `compression.context_length` if the model supports it, or shrink `tail_token_budget` (a fat tail leaves a thin middle).

This habit is per-profile: memory is isolated per profile, so a compression-checkpoint rule recorded in one profile does NOT carry to another — mirror it into each profile's memory store if you want it everywhere.

Aborted compressions keep the original transcript intact — no data loss.

### "Reset permissions" / auto-approving everything
See `references/security-privacy.md` — wipe the "Always allow" stores, don't touch yolo mode.

