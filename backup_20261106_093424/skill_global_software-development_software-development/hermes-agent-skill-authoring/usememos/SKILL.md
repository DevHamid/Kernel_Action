---
name: usememos-skill
description: Integrate Hermes with Memos memory via usememos plugin.
version: 0.1.0
author: Ahmad Syarwan Hamid (ahmadsh), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [usememos, memory, integration]
    related_skills: [hermes-agent]
---
# usememos-skill

## Overview

This skill enables Hermes to interact with the Memos self-hosted note service, allowing you to list, search, and create memos directly from the Hermes terminal or TUI.

## When to Use

- You want to store and retrieve notes programmatically from Hermes
- You need to reference memos in your workflows or agent tasks
- You have a running Memos instance with valid API credentials

**Don't use for:**
- Storing large binary files
- Real-time collaborative editing
- Persistent system state (use dedicated databases)

## Prerequisites

- Hermes installed and running
- Memos instance running (self-hosted or cloud)
- API URL and access token for Memos
- Environment variables set: `MEMOS_API_URL`, `MEMOS_ACCESS_TOKEN`
- Optionally create `usememos.json` in `$HERMES_HOME` for config

## Activation (required before any tool call works)

1. **Set credentials** — export `MEMOS_API_URL` and `MEMOS_ACCESS_TOKEN`, or write them to `$HERMES_HOME/usememos.json` (file permissions `0o600`).
2. **Activate provider** — `hermes config set memory.provider usememos`
3. **Restart gateway** — `hermes -p <profile> gateway run --replace` so the plugin loads into the active session.
4. **Confirm availability** — `hermes doctor` or verify `is_available()` returns true; `memos_list`, `memos_search`, `memos_add` should appear in the toolset.

## How to Run

```bash
hermes chat -q "list recent memos"
hermes chat -q "search memos for test"
hermes chat -q "create memo: 'Task completed'"
```

## Quick Reference

- `hermes chat -q "list"` — list recent memos
- `hermes chat -q "search <keyword>"` — search memos by keyword
- `hermes chat -q "summarize"` — summarize recent memos into a short catch-up
- `hermes chat -q "create memo: <content>"` — create a new memo

## Procedure

1. **Verify Memos is configured**  
   Run `hermes memory list` — if Memos is not available, you will see an error.  
   Ensure `MEMOS_API_URL` and `MEMOS_ACCESS_TOKEN` are set.

2. **List recent memos**  
   Run `hermes chat -q "list recent memos"` — should return a JSON list of memos with content, creation time, and visibility.

3. **Search memos**  
   Run `hermes chat -q "search memos for project"` — should return matching memos containing "project" in their content.

4. **Create a new memo**  
   Run `hermes chat -q "create memo: 'Task completed successfully'"` — should store the memo and return a success message with the memo ID.

5. **Verify memo creation** 
   Run `hermes chat -q "search memos for 'Task completed'"` — should find the memo you just created.

6. **Summarize recent memos**
   Run `hermes chat -q "summarize recent memos"` — returns a short, human-readable catch-up of the most recent memos without listing every field.

## Bulk import — one memo per file

### When to use

Import a directory of `.md` files into Memos, each file becoming exactly one memo (raw markdown preserved). Use this when your notes are already split by file and you don't want heading-based parsing.

### Procedure

1. **Set credentials**
   ```bash
   export MEMOS_API_URL="http://<memos-host>:5230"
   export MEMOS_ACCESS_TOKEN="<token>"
   export MEMOS_VISIBILITY="PRIVATE"
   export MEMOS_DEDUP="false"
   ```
   `MEMOS_VISIBILITY` default is `PRIVATE`. `MEMOS_DEDUP=true` skips files whose content already exists in Memos.

2. **Run the import script**
   ```bash
   python3 scripts/memos-import-markdown.py /path/to/markdown/files
   ```
   Each `.md` file is read as raw markdown and POSTed as one memo. Empty files are skipped.

3. **Review output**
   The script prints one line per file: `Imported: <file>`, `Skipped (empty): <file>`, or `Skipped (duplicate): <file>`. At the end it prints totals.

### Why one memo per file

- Simpler code — no markdown parsing logic
- Works with any markdown structure, no heading assumptions
- No data loss if a single file fails
- Trade-off: search inside Memos is at file granularity, not section granularity. For long files (50+ lines), consider splitting by `# ` headings instead.

## Pitfalls

- **Memos >= 26.11 (2026-02 release) removed all `/api/v1/...` and `/memos.api.v1.*` routes.** REST is now `/api/...` (e.g. `GET /api/memos`, `POST /api/memos`), Connect is `/memos.api.<Service>/<Method>`. Old paths return `410 Gone` with an `UNIMPLEMENTED` error pointing at the changelog. Any plugin or script pinned to `/api/v1` breaks silently after upgrade.
- **That same upgrade invalidated every existing Personal Access Token** — "Everyone signs in again: access tokens are tied to the account password." Reads keep working (public instances serve reads without auth), so only writes fail, with `401 authentication required`. Reads succeeding is NOT proof the token is valid — always test a write.
- **Cloudflare in front of Memos returns 403 error 1010 `browser_signature_banned` for the default `Python-urllib/3.x` User-Agent.** Send a browser UA header (Chrome 131 string works) or every request from stdlib urllib gets blocked.
- **`DELETE /api/memos/<name>` is the delete route** — the resource `name` (`memos/<id>`), not `uid`, is the URL segment.
- Memos API rate limiting — if you get HTTP 429 errors, wait 1 minute before retrying.
- Invalid or expired API token — refresh the token in Memos settings and update `MEMOS_ACCESS_TOKEN`.
- Memos instance not reachable — ensure network connectivity and correct API URL.

## Support files

`scripts/memos-import-markdown.py` — the import script referenced in the Bulk import section above.

## Verification

- Confirm `hermes memory list` returns memos without errors.
- Check that `hermes chat -q "create memo: test"` results in a new entry in `hermes chat -q "search memos for test"`.
- Ensure the memo's visibility matches the default setting.

**Note:** The Memos plugin uses standard HTTP calls and does not require additional dependencies beyond Hermes.