#!/usr/bin/env python3
"""Import markdown files to Memos — one memo per file.

Usage:
    export MEMOS_API_URL="http://<memos-host>:5230"
    export MEMOS_ACCESS_TOKEN="<token>"
    export MEMOS_VISIBILITY="PRIVATE"   # optional, default PRIVATE
    export MEMOS_DEDUP="false"          # optional, skip if content already exists
    python3 memos-import-markdown.py /path/to/markdown/files
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MEMO_URL = os.getenv("MEMOS_URL", "").rstrip("/") + "/api/v1/memos"
if not MEMO_URL:
    api_url = os.getenv("MEMOS_API_URL", "").rstrip("/")
    MEMO_URL = f"{api_url}/api/v1/memos"

API_TOKEN = os.getenv("MEMOS_TOKEN") or os.getenv("MEMOS_ACCESS_TOKEN", "")
VISIBILITY = os.getenv("MEMOS_VISIBILITY", "PRIVATE")
DEDUP = os.getenv("MEMOS_DEDUP", "false").lower() == "true"


def http_get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def http_post(url, token, payload):
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


def fetch_existing_contents(token):
    existing = set()
    try:
        data = http_get(MEMO_URL, token)
        for m in data.get("memos", []):
            existing.add(m.get("content", ""))
    except Exception:
        pass
    return existing


def create_memo(content, token, visibility=VISIBILITY):
    payload = {"content": content, "visibility": visibility}
    return http_post(MEMO_URL, token, payload)


def main(directory):
    if not MEMO_URL.endswith("/api/v1/memos"):
        print("ERROR: Set MEMOS_API_URL or MEMOS_URL env var", file=sys.stderr)
        sys.exit(1)
    if not API_TOKEN:
        print("ERROR: Set MEMOS_TOKEN or MEMOS_ACCESS_TOKEN env var", file=sys.stderr)
        sys.exit(1)

    md_files = sorted(Path(directory).glob("*.md"))
    if not md_files:
        print(f"No .md files found in {directory}")
        return

    existing = fetch_existing_contents(API_TOKEN) if DEDUP else set()

    imported = skipped = 0
    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8").strip()
        if not content:
            print(f"Skipped (empty): {md_file}")
            skipped += 1
            continue
        if DEDUP and content in existing:
            print(f"Skipped (duplicate): {md_file}")
            skipped += 1
            continue
        try:
            create_memo(content, API_TOKEN, VISIBILITY)
            print(f"Imported: {md_file}")
            imported += 1
            if DEDUP:
                existing.add(content)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            print(f"Failed {md_file}: {e.code} {body}", file=sys.stderr)
        except Exception as e:
            print(f"Failed {md_file}: {e}", file=sys.stderr)

    print(f"\nDone: {imported} imported, {skipped} skipped, {len(md_files)} total")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    main(target)