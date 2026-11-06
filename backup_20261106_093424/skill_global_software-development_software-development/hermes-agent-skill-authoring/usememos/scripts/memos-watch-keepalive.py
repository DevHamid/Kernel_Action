#!/usr/bin/env python3
"""Keepalive for the memos folder watcher.

If the watcher (memos-watch-folder.py) is not running, restart it with the
same env the watcher needs. Print status; non-empty stdout is what Hermes
cron (no_agent mode) delivers.

Run via a no_agent cron job (~every 5m) so it survives host reboot — the
Hermes gateway auto-restarts and resumes its cron jobs.
"""
import json
import os
import subprocess
import sys

SCRIPT = "/opt/data/scripts/memos-watch-folder.py"
FOLDER = "/srv/ssd/wayne/notes"
STATE = "/srv/ssd/.memossync-state.json"
TOKEN_FILE = "/opt/data/usememos.json"


def watcher_pid():
    out = subprocess.run(
        ["pgrep", "-f", "memos-watch-folder[.]py"],
        capture_output=True, text=True,
    )
    return [int(p) for p in out.stdout.split() if p.strip()]


def main():
    pids = watcher_pid()
    if pids:
        print(f"memos-watch running (pid {' '.join(map(str,pids))})")
        return 0

    try:
        token = json.load(open(TOKEN_FILE))["access_token"]
    except Exception as e:
        print(f"restart FAILED: cannot read token: {e}")
        return 1

    env = dict(os.environ)
    env.update({
        "MEMOS_API_URL": "http://127.0.0.1:5230",
        "MEMOS_ACCESS_TOKEN": token,
        "MEMOS_VISIBILITY": "PRIVATE",
        "MEMOS_TAGS": "project,summary",
        "MEMOS_POLL_SECONDS": "10",
        "MEMOS_STATE_FILE": STATE,
    })
    try:
        proc = subprocess.Popen(
            [sys.executable, SCRIPT, FOLDER],
            env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        print(f"memos-watch was dead; restarted (pid {proc.pid})")
        return 0
    except Exception as e:
        print(f"restart FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
