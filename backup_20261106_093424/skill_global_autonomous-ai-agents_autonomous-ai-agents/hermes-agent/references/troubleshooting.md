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

### Multi-profile gateway: one profile offline
1. Diff `$HERMES_HOME/gateway_state.json` against `$HERMES_HOME/profiles/<name>/gateway_state.json` — compare `served_profiles`, `platforms.<platform>.state`, and `multiplex_standalone_reason`.
2. Verify PID liveness before trusting state JSON — it goes stale after a crash: `ls /proc/<pid>`; a missing PID means that profile's gateway is down, not disconnected.
3. Confirm which home the live gateway actually serves: `tr '\0' '\n' < /proc/<pid>/environ | grep HERMES_HOME` — a gateway rooted at the default home only covers profiles in its own `served_profiles`.
4. Keep multiplexed secondaries at `gateway.standalone: false` — flipping one to `standalone: true` pulls it out of the default gateway's served set, and without its own running gateway process that profile goes offline.

### Platform-specific issues
- **Discord bot silent**: Must enable **Message Content Intent** in Bot → Privileged Gateway Intents.
- **Slack bot only works in DMs**: Must subscribe to `message.channels` event. Without it, the bot ignores public channels.
- **Windows-specific issues** (`Alt+Enter` newline, WinError 10106, UTF-8 BOM config, line endings): see `references/windows-quirks.md`.

### Auxiliary models not working
If `auxiliary` tasks (vision, compression, session_search) fail silently, the `auto` provider can't find a backend. Either set `OPENROUTER_API_KEY` or `GOOGLE_API_KEY`, or explicitly configure each auxiliary task's provider:
```bash
hermes config set auxiliary.vision.provider <your_provider>
hermes config set auxiliary.vision.model <model_name>
```

### Web search fails after a keyless provider connection reset
If `web_search` returns nothing after a keyless provider in the ring connection-resets (e.g. Firecrawl `[Errno 104] Connection reset by peer`), the failover chain stops at that provider and never tries the remaining vendors.

**Cause:** A raw TCP connection reset isn't a structured HTTP 401/402/403/5xx refusal, so the ring logic doesn't treat it as a "provider refused me" signal and doesn't fall through to the next vendor.

**Fix:** Mark the failing provider as `paid` so it's excluded from the keyless ring:

```bash
hermes config set web.provider_tier.firecrawl paid
```

This walks the ring `exa → parallel → keenable` instead of hitting the broken provider. Verify with `hermes config get web.provider_tier` — the key should read `firecrawl: paid`.

**Ring order:** `(exa, parallel, firecrawl, keenable)` — the keyless ring tries vendors in this order; a provider marked `paid` is skipped entirely.

**Binary path:** On this host `hermes` is not on PATH — invoke as `/opt/hermes/bin/hermes` or ensure `/opt/hermes/bin` is on PATH before running `hermes` commands.

### "Reset permissions" / auto-approving everything
See `references/security-privacy.md` — wipe the "Always allow" stores, don't touch yolo mode.

