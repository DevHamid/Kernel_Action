---
name: memos-sync
description: Use when syncing notes to Memos via API or watcher.
---

# Memos API & Watcher

## Instance details
- API base: `https://5230-agqz5xm6pygj5mofy56lzkpiom.instabox.tech` (remote). Token in `/opt/data/usememos.json` (`access_token`). Content limit: 8192 bytes (hard quota, cannot be raised).
- Current memos: 20 notes + 1 pinned index (00-WAYNE-INDEX) in space `spaces/<uuid>` (uuid read from `/srv/ssd/config-edit/uuid.txt`, which may contain `title : uuid` — regex-extract the uuid).
- Local fallback: `/opt/data/backups/hermes_memos/` contains complete Hermes state (memories + skills + configs) backed up hourly.

## Auth
All requests need header `Authorization: Bearer <token>`. Do NOT print the token in chat.

## Key endpoints
- List: `GET /memos?limit=100` — paginated via `nextPageToken`; loop until absent. Page cap 100.
- Get: `GET /memos/{uid}`
- Create: `POST /memos` body `{content, visibility, space?}` — full memo. `pinned` is NOT accepted here.
- Update: `PATCH /memos/{uid}` body `{content?, pinned?}` — works for content & pinned. Setting `tags` alone via PATCH returns 400; strip `#n` from content instead (tags derive from content).
- Delete: `DELETE /memos/{uid}` — returns 200.
- Relations: `PATCH /memos/{uid}/relations` body `{name, relations:[{relatedMemo:{name}, type:"REFERENCE"}]}`. Replaces the FULL set (not append). Type must be `REFERENCE` (COMMENT is output-only). Markdown links DO NOT create relations.
- Spaces: `GET /spaces` lists spaces. A memo's `space` field is `spaces/<uuid>`. Space memos are routed under the space in the UI.

## URL routing (frontend)
Memo detail path in the UI is `/memos/<uid>` — NOT `/m/<uid>` (which falls to the `*` NotFound route). Use relative links `/memos/<uid>` in memo content so they auto-adapt to the current host (IP or domain).

## Memo content & tags
- Prepending `#wayne-openwrt` (or configured tags) as a header line makes it a tag.
- Inline `#n` (numeric, e.g. `see #9`) become auto-detected numeric tags in Memos. Strip them with `re.sub(r'#\d+\b', '', content)` then collapse spaces, otherwise they clutter the tag list.

## Folder watcher (`/opt/data/scripts/memos-watch-folder.py`)
- Watches `/srv/ssd/wayne/notes/` for `*.md`; imports each as one memo (or split parts if over `MAX_CONTENT=32700` bytes, byte-aware UTF-8).
- Sorts newest-first by a date in the filename (`20YY-MM-DD`), else ctime — NOT mtime.
- Skips files starting `00-` (the index) so editing the index never duplicates it. Other files re-import when mtime changes → duplicates possible if you edit a synced file; delete dupes manually.
- State file `/srv/ssd/.memossync-state.json` records imported mtimes; only saves on success. Clear it to force full re-import.
- Keepalive: `/opt/data/scripts/memos-watch-keepalive.py` (cron `8c66caf2229e`, every 5m) restarts the watcher if dead; passes env from `/opt/data/usememos.json`, visibility PUBLIC, tags `wayne-openwrt`, space from uuid.txt.
- Watcher env: `MEMOS_API_URL`, `MEMOS_ACCESS_TOKEN`, `MEMOS_VISIBILITY`, `MEMOS_TAGS`, `MEMOS_POLL_SECONDS`, `MEMOS_STATE_FILE`, optional `MEMOS_SPACE`.

## Restarting the watcher
```bash
PIDS=$(pgrep -f 'memos-watch-folder[.]py'); for p in $PIDS; do kill $p 2>/dev/null; done; sleep 1
TOKEN=$(python3 -c "import json; print(json.load(open('/opt/data/usememos.json'))['access_token'])") && \
  MEMOS_API_URL=http://127.0.0.1:5230 MEMOS_ACCESS_TOKEN="$TOKEN" \
  MEMOS_VISIBILITY=PUBLIC MEMOS_TAGS=wayne-openwrt \
  MEMOS_POLL_SECONDS=10 MEMOS_STATE_FILE=/srv/ssd/.memossync-state.json \
  python3 /opt/data/scripts/memos-watch-folder.py /srv/ssd/wayne/notes/ > /tmp/memos-watch.log 2>&1 &
```
Killing via `pkill -f` can kill your own shell (SIGTERM); prefer `pgrep` + `kill` with the `[.]` bracket trick.

## Plugin repo (github.com/DevHamid/hermes-memos-integration)
The usememos plugin source is published at `github.com/DevHamid/hermes-memos-integration` (public). The plugin is the runnable code path (`__init__.py`, `plugin.yaml`, README under `plugins/usememos/`); the skill is the operational documentation. They are intentionally separate — the skill documents the API/watcher, the plugin executes against the instance. When publishing/updating the plugin, follow `references/plugin-github-publish.md` (git root quirk, gh device-flow auth, secret scan before push). Spaces support lives in the plugin (`space` param on `memos_add` + `MEMOS_SPACE` config), not in this skill's code.

## Verifying state (no dupes)
To confirm there is exactly one index memo, do NOT substring-search content for the title/path — other notes legitimately reference `/memos/<uid>` or mention the index, so a content hit is not a duplicate. Instead list all memos and count those whose memo name/title IS the index (e.g. the pinned one). A single pinned index + N real notes is correct; content matches beyond that are references, not dupes.

## Pitfalls
- Deleting in a loop deletes only the first page unless you paginate via `nextPageToken`.
- PATCH `tags` field alone → 400; edit content instead.
- `pinned` accepted on PATCH, not on POST.
- Keep UUIDs out of chat; read from files.

## Hermes Native Memory → Memos Sync

### Purpose
Mirror Hermes' native memory files, skills, and configs to usememos for cloud backup, searchable history, and disaster recovery.

These are the source of truth for Hermes context:

**Memory files (4):**
1. `/opt/data/memories/MEMORY.md` — Global memory (loaded into system prompt every session)
2. `/opt/data/memories/USER.md` — User profile (Ahmad's preferences, rules, role)
3. `/opt/data/profiles/shifu/memories/MEMORY.md` — Shifu profile configs (gateway state, 9router API keys, kernel build references)
4. `/opt/data/profiles/shifu/memories/USER.md` — Shifu user preferences (device test style, modem goals)

**Skills (40 directories):**
- Global: `/opt/data/skills/*/` (32 skills)
- Shifu profile: `/opt/data/profiles/shifu/skills/*/` (8 skills)

**Configs (6 files):**
- `/opt/data/config.yaml` (global), `/opt/data/profiles/shifu/config.yaml`
- `/opt/data/profiles/shifu/profile.yaml`
- `/opt/data/usememos.json` (global), `/opt/data/home/.hermes/usememos.json`
- `/opt/data/cron/jobs.json`

Total local backup size: ~11 MB (316 items per run).

### Procedure — One-time sync (run on session start or via cron)

#### Step 1: Ensure usememos is authenticated

```bash
# Test if memos_add is available and authenticated
if command -v memos_add >/dev/null 2>&1; then
    echo "memos_add available — proceeding with sync"
else
    echo "memos_add not available — local backup only"
fi
```

#### Step 2: Run the sync script

The sync script is at `/opt/data/scripts/hermes_memos_sync.sh`. Run it:

```bash
/opt/data/scripts/hermes_memos_sync.sh
```

This will:
- Read ALL Hermes state (4 memory files + 40 skill directories + 6 config files)
- Back them up to `/opt/data/backups/hermes_memos/<timestamp>/` with prefixes (`global_`, `shifu_`, `skill_global_*`, `skill_shifu_*`, `config_*`, `usememos_*`, `cron_*`) to avoid filename collisions
- Attempt usememos cloud write:
  - **Memory files (4)** — ✅ always synced (total ~6 KB, well under 8 KB limit)
  - **Skills + Configs** — ❌ blocked by 8 KB hard quota per memo (~11 MB total)
- Report status of all operations

#### Step 3: Verify the backup

```bash
# List backed-up files
find /opt/data/backups/hermes_memos/ -name '*.md' | sort

# Verify content of each
head -3 /opt/data/backups/hermes_memos/$(ls -t /opt/data/backups/hermes_memos/ | head -1)/global_MEMORY.md
```

#### Step 4: Recurring cron (always up to date)

Cron job `c2cfc542148c` runs hourly:

```bash
0 * * * * /opt/data/scripts/hermes_memos_sync.sh
```

Or for session-start auto-sync, add to shell RC:

```bash
# Hermes memory → usememos sync on every session start
/opt/data/scripts/hermes_memos_sync.sh
```

### Cloud sync limitation: 8 KB per memo

The Memos API enforces a hard limit of 8192 bytes per memo content. The full Hermes state (~11 MB) exceeds this by ~1000x. Options:

1. **Current (working):** Sync only 4 memory files to cloud (6 KB total). Local backup at `/opt/data/backups/hermes_memos/` is the complete source of truth.
2. **Chunk per-file:** Create 40+ memos per sync (one per skill/config). Messy, many API calls.
3. **Git push (recommended):** Push `/opt/data/backups/hermes_memos/` to a private repo (unlimited, versioned, free). Uses existing `/opt/data/github_token`.

### Pitfalls (Hermes‑specific)
- **401: authentication required** — usememos writes need `MEMOS_ACCESS_TOKEN` set. Reads work without auth, but writes require the token. Run `hermes config set memory.provider usememos` and set `MEMOS_API_URL` + `MEMOS_ACCESS_TOKEN` env vars.
- **Filename collisions** — the script uses `global_` and `shifu_` prefixes to avoid overwriting. Do not rename files to remove these prefixes.
- **8 KB hard quota** — Memos enforces 8192 bytes per memo. Full Hermes state (~11 MB) cannot fit in one memo. Only 4 memory files (~6 KB) sync to cloud. Skills/configs are local-only unless you implement chunking or Git push.
- **Local URL not running** — `/opt/data/home/.hermes/usememos.json` points to `http://127.0.0.1:5230` but no local Memos instance runs. The working instance is the remote one.
- **Session state** — the script creates a new timestamped subdirectory each run. Old backups are preserved; the latest is always the current state.
- **Content encoding** — multi-line markdown must be JSON-encoded via Python `json.dumps` before sending to Memos API; raw newlines in curl `-d` break the request.

### Verification
- Run `/opt/data/scripts/hermes_memos_sync.sh` and confirm all 4 memory files + skills + configs are backed up locally
- Run `memos_list` and confirm the 4 memory memos appear in your Memos instance
- Run `memos_search -q "Hermes Memory"` to verify searchability
- If usememos auth changes, re-authorize and re-run the script
- Local backup integrity: `ls -la /opt/data/backups/hermes_memos/$(ls -t /opt/data/backups/hermes_memos/ | head -1)/ | wc -l` should show ~316 items

## Related support files
- `/opt/data/scripts/hermes_memos_sync.sh` — the sync script itself
- `/opt/data/backups/hermes_memos/` — backup directory (created automatically)
