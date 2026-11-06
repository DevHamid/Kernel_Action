---
name: hermes-webui-setup
description: Use when configuring the Hermes WebUI dashboard.
---

# Hermes WebUI (dashboard) setup

## How auth works
- Dashboard requires an auth provider to bind. No provider → `list_providers()` empty → gate blocks bind, process spins in state R/wchan 0, no TCP listener.
- `--insecure` is a no-op now. Auth is mandatory.
- Cleanest path: `dashboard.basic_auth` in config.yaml (username + password_hash + secret) OR env vars `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `..._PASSWORD` / `..._SECRET`. Config file is the durable route.
- Plugin lives at `/opt/hermes/plugins/dashboard_auth/basic/`. It reads `dashboard.basic_auth.*`.
- Interactive first-run auth setup prompts only run in a tty; in background it's skipped and the gate takes over.

## Steps that work
1. Generate password + secret + scrypt hash in Python (secrets.token_urlsafe; hashlib.scrypt n=2**14, r=8, p=1; store as `scrypt$<n>$<r>$<p>$<b64 salt>$<b64 dk>`). Save to `~/.cache/scratch/dashboard_creds.txt` (chmod 600).
2. Append to `/opt/data/config.yaml`:
   ```
   dashboard:
     basic_auth:
       username: admin
       password_hash: "scrypt$..."
       secret: "..."
   ```
3. Launch via terminal `background=true` (nohup/`&` foreground is blocked):
   ```
   export PATH=/opt/hermes/bin:$PATH; export HERMES_HOME=/opt/data; hermes dashboard --host 0.0.0.0 --port 9119 --skip-build --no-open
   ```
4. Verify: `awk 'NR>1 && $4=="0A" {print $2}' /proc/net/tcp /proc/net/tcp6 | grep -i :239f` (9119). `ss`/`netstat` are ABSENT on this box — /proc/net/tcp is the only valid listener check. Check `/opt/data/logs/gui.log` for `Dashboard binding to 0.0.0.0 with auth gate enabled. Providers: basic`.

## Login contract
- Login page: `GET /login?next=%2F` (302 from `/`).
- Auth: `POST /auth/password-login` JSON body `{"provider":"basic","username":...,"password":...,"next":...}` → 200 `{"ok":true,"next":"/"}`. Provider field is required (else 422 missing).
- Carry session cookies; `GET /api/auth/me` → `{"user_id":"admin",...,"provider":"basic"}`.

## Pitfalls
- Don't pass password in login URL or omit `provider` → 422.
- Background stdout is captured by the process stream, not a file; no `dashboard.log` gets created. gui.log is under `/opt/data/logs/`.
- Don't use `kill -9` to stop a stuck dashboard: dispatcher counts kills as crashes → auto-block. Use block/unblock instead.
- `hermes config get` without `HERMES_HOME` returns stale values — always export `HERMES_HOME=/opt/data` first.

## Credentials
- Current dashboard username/password live in `/opt/data/profiles/shifu/cache/scratch/dashboard_creds.txt` (mode 600). Re-read from there; never invent or echo old ones.
