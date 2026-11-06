#!/usr/bin/env python3
"""Watch a folder for .md changes and auto-publish them to Memos.

One memo per file. Re-imports when a file is created or modified.
Deduplicates by mtime so re-saving an unchanged file won't spam Memos.
Optional MEMOS_TAGS are prepended as #tag headers.

Memos caps each memo's content at 8192 BYTES of UTF-8 by default (the
API count is bytes, not characters). Files larger than that are split
into numbered (i/N) memos; split on byte length so multibyte text
(diacritics, emoji) can't slip a too-large chunk through. If you raise
the server limit (Memos workspace setting), bump MAX_CONTENT below to
just under the new ceiling.

Config via env:
  MEMOS_API_URL        Memos instance URL (e.g. http://127.0.0.1:5230)
  MEMOS_ACCESS_TOKEN   Memos API access token
  MEMOS_VISIBILITY     PRIVATE | PROTECTED | PUBLIC  (default PRIVATE)
  MEMOS_TAGS           comma-separated tags appended to every memo
  MEMOS_POLL_SECONDS   how often to scan the folder (default 10)
  MEMOS_STATE_FILE     json file to remember imported file mtimes (default ~/.memossync-state.json)

Usage:
    MEMOS_API_URL=... MEMOS_ACCESS_TOKEN=... \
    python3 memos-watch-folder.py /srv/ssd/my-project
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

API_URL = os.getenv("MEMOS_API_URL", "").rstrip("/")
TOKEN = os.getenv("MEMOS_ACCESS_TOKEN", "") or os.getenv("MEMOS_TOKEN", "")
VISIBILITY = os.getenv("MEMOS_VISIBILITY", "PRIVATE")
TAGS = [t.strip() for t in os.getenv("MEMOS_TAGS", "").split(",") if t.strip()]
POLL = float(os.getenv("MEMOS_POLL_SECONDS", "10"))
STATE_FILE = Path(os.getenv("MEMOS_STATE_FILE", "~/.memossync-state.json")).expanduser()

MEMO_URL = f"{API_URL}/api/v1/memos" if API_URL else ""

# Memos default content ceiling is 8192 bytes; leave headroom for the
# (i/N) split header. If you raised the server limit, rise this to just
# under the new ceiling (e.g. 32700 for a 32768 server limit).
MAX_CONTENT = 8000


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def http_post(url, token, payload):
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def make_content(text):
    """Prepend tags as a header block if TAGS are configured."""
    if TAGS:
        tag_line = " ".join(f"#{t}" for t in TAGS)
        return f"{tag_line}\n\n{text}".strip()
    return text


def split_content(text, limit=MAX_CONTENT):
    """Split text into chunks whose UTF-8 bytes <= limit (Memos counts bytes), breaking on newlines when possible."""
    if len(text.encode("utf-8")) <= limit:
        return [text]
    lines = text.splitlines(keepends=True)
    chunks, cur, cur_bytes = [], [], 0
    for line in lines:
        lb = len(line.encode("utf-8"))
        if cur_bytes + lb > limit and cur:
            chunks.append("".join(cur).strip())
            cur, cur_bytes = [], 0
        cur.append(line)
        cur_bytes += lb
    if cur:
        chunks.append("".join(cur).strip())
    return chunks


def import_file(md_file, token):
    text = md_file.read_text(encoding="utf-8").strip()
    if not text:
        return "skipped-empty"
    content = make_content(text)
    chunks = split_content(content)
    if len(chunks) > 1:
        for i, chunk in enumerate(chunks, 1):
            header = f"({i}/{len(chunks)})"
            payload = {"content": f"{header} {chunk}".strip(), "visibility": VISIBILITY}
            try:
                http_post(MEMO_URL, token, payload)
            except Exception as e:
                return f"failed:{e}"
        return f"imported:{len(chunks)}-parts"
    payload = {"content": content, "visibility": VISIBILITY}
    try:
        http_post(MEMO_URL, token, payload)
        return "imported"
    except Exception as e:
        return f"failed:{e}"


def watch(directory):
    if not MEMO_URL.endswith("/api/v1/memos"):
        log("ERROR: Set MEMOS_API_URL env var")
        sys.exit(1)
    if not TOKEN:
        log("ERROR: Set MEMOS_ACCESS_TOKEN env var")
        sys.exit(1)

    dir_path = Path(directory)
    if not dir_path.is_dir():
        log(f"ERROR: Not a directory: {directory}")
        sys.exit(1)

    state = load_state()
    log(f"Watching {dir_path} -> Memos (poll {POLL}s, tags={TAGS or 'none'})")

    while True:
        changed = False
        for md_file in sorted(dir_path.glob("*.md")):
            key = str(md_file)
            try:
                mtime = md_file.stat().st_mtime
            except FileNotFoundError:
                continue
            prev = state.get(key)
            if prev is not None and prev >= mtime:
                continue
            result = import_file(md_file, TOKEN)
            # Only record a file as synced when the import actually
            # succeeded. If a failed file is recorded, it never retries.
            if result.startswith("imported"):
                state[key] = mtime
                changed = True
            log(f"{result}: {md_file.name}")
        if changed:
            save_state(state)
        time.sleep(POLL)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    watch(target)
