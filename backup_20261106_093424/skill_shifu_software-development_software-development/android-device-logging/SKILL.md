---
name: android-device-logging
description: "Use when capturing Android device logs via adb."
version: 1.0.0
author: shifu
license: MIT
metadata:
  hermes:
    tags: [android, adb, logcat, dmesg, logging]
    related_skills: [android-kernel-ci]
---

## When to Use
Use when the user needs to capture or read logs from an Android device over adb — user-space (logcat) or kernel (dmesg) — or when a capture comes back empty and needs diagnosing.

# Android device logging over adb

Capturing logs from an Android device. The user is a beginner on low-level systems: give the exact command plus a one-line everyday analogy for why it behaves as it does, layered under the precise mechanism.

## First step: connection state
Always start with `adb devices`. Read the states before diagnosing anything else:
- Empty list → cable (data, not charge-only), USB debugging off, or no auth.
- `unauthorized` → accept the prompt on the phone, re-run.
- `offline` → `adb kill-server && adb start-server`, unplug/replug.
A silent/empty capture is usually a plumbing problem, not a buffer problem. Verify the pipe before blaming the buffers.

## User-space logs: logcat
- Snapshot (dump-and-exit): `adb logcat -d > log.txt`. This is a point-in-time snapshot — it has NO time dimension, you cannot add a duration to `-d`.
- Live timed recording: `timeout 60 adb logcat > log.txt`. If `timeout` is missing, background + reap: `adb logcat > log.txt & p=$!; sleep 60; kill $p`.
- Pitfall: `-b all` frequently fails on non-root builds because it includes the `kernel` buffer, which needs root and kills the whole dump. Drop it — default buffers (main, system, crash, events) cover ~99% of app/system debugging. The symptom is an empty file with a clean `exit=0`, which misleads.
- Capture errors separately so a silent failure is visible: append `2> err.txt` and read it.

## Kernel logs: dmesg
- `dmesg` reads the kernel ring buffer (~64KB); old entries are overwritten, so a snapshot is only what is still in the ring. `-w` follows new messages like `tail -f` and records only what occurs during the window.
- Pitfall: `dmesg` is ROOT-ONLY on Android. Without root you get `dmesg: klogctl: Permission denied`. `adb root` fails on production builds ("adbd cannot run as root in production builds"). If the device is not rootable, dmesg is off-limits — use logcat instead. `-b all`/`/proc/kmsg` hit the same wall.
- Pitfall: redirecting to `/` fails with `Read-only file system` — the redirect target, not dmesg. Write to a writable path: `dmesg > /data/local/tmp/k.txt`, then `adb pull /data/local/tmp/k.txt`. Check uid with `id` (uid=0 = root; otherwise need `su -c '...'`).
- Pitfall: a long silent `-w` session over adb can die with `error: closed` (idle timeout on the adb session). Keep the hold short, or run the capture inside the device shell writing to /sdcard and pull it, rather than holding one long adb session.

## Checklist when a capture is empty
1. `adb devices` → connection/authorization.
2. `cat err.txt` → was stderr carrying the real error (permission, closed)?
3. Run the capture command WITHOUT the redirect to the terminal: does it stream? If yes, the redirect/`-b all` was the culprit.
4. Confirm the file was written where you are looking (`pwd`; Termux writes to home by default).
