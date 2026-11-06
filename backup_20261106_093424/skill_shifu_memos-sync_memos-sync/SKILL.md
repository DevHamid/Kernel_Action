---
name: memos-sync
description: Use when syncing notes to Memos via API or watcher.
---

# Memos API & Watcher

## Instance details
- API base: `http://127.0.0.1:5230/api/v1` (local). Token in `/opt/data/usememos.json` (`access_token`). Content limit default 8192 bytes; this instance raised to 32768.
- Current memos: 20 notes + 1 pinned index (00-WAYNE-INDEX) in space `spaces/<uuid>` (uuid read from `/srv/ssd/config-edit/uuid.txt`, which may contain `title : uuid` — regex-extract the uuid).

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

## Pitfalls
- Deleting in a loop deletes only the first page unless you paginate via `nextPageToken`.
- PATCH `tags` field alone → 400; edit content instead.
- `pinned` accepted on PATCH, not on POST.
- Keep UUIDs out of chat; read from files.
