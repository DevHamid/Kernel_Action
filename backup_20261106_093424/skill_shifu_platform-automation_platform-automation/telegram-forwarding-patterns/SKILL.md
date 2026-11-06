---
name: telegram-forwarding-patterns
description: "Correct Telegram forward procedure: message IDs & files."
version: 1.0.0
author: Ahmad Syarwan Hamid + Shifu
license: MIT
platforms: [linux]
tags:
- telegram
- forwarding
- bot-api
- knowledge-notes
related_skills:
- hermes-agent
---

# Telegram Forwarding Patterns (Hermes Agent)

## When to Use This Skill

Use this procedure whenever you're asked to:
- Forward a Telegram message from one chat/group to another
- Forward an attachment/file that someone uploaded to a chat
- Preserve "Forwarded from" attribution when moving messages between chats

**Critical**: Always use native forwards (API `forwardMessage`) instead of re-typing or re-uploading. This preserves timestamps, author attribution, and original filenames.

## Core Principle

**Always use native forwards** → preserve "Forwarded from" labels, original filenames, timestamps.

Never re-type or re-upload when asked to forward something existing.

## The Correct Procedure

### For Text Messages:

1. Identify original message ID from DM/group chat
2. Use `forwardMessage` API call with `from_chat_id`, `message_id`
3. Target destination: `chat_id` + `message_thread_id` (for topics/subtopics)
4. **Verify**: new forwarded message retains attribution label

### For Document/File Attachments:

1. Locate original DM message containing the actual file upload
2. Confirm it's the real document, not a message *about* the file
3. Use `forwardMessage` API (same as text) – Telegram auto-forwards as attachment
4. **Verify**: new message shows document bubble with original filename

## Common Mistakes to Avoid

### ❌ WRONG Approaches

| Mistake | Why It Fails | Correct Alternative |
|---|---|---|
| Re-typing explanation text | Loses timestamp, author attribution | Native forward of original message |
| Uploading .md file from disk with same content | Loses "Forwarded from" label, may rename | Forward DM message containing original doc |
| Guessing message IDs without verification | Wrong message gets forwarded | Check logs (`gateway.log`) or ask user for share link |
| Confusing message about file vs. actual file | User sees caption-only, no attachment | Look for `doc_XXXXXX_cached` entries in gateway logs |

### ✅ RIGHT Approach Flow

```
User says: "Forward this message/file from our chat"
    ↓
Ask: Which exact message?
    ↓
Option A: Send Telegram share link → extract message ID
Option B: Check gateway.log for reply_to_id patterns
    ↓
Identify correct source: DM chat ID + message thread
    ↓
Use Python/Terminal to run:
curl/post to bot API forwardMessage(from_chat_id=X, message_id=Y, ...)
    ↓
Verify result has document attachment AND/or attribution label
```

## When in Doubt

Ask the user:
- "Which message ID do you want forwarded?" (they can see it in Telegram by long-press → Info)
- OR: "Send me the Telegram share link (t.me/user/chatid/msgid)" – extract ID from URL

Never assume or guess.

### Critical Rule: Reply Context

When a user says "forward **this message**" while replying to another message:
- The reference is to the **original message being replied to**, not the user's reply.
- Extract the `reply_to_id` from gateway logs (`grep "reply_to_id=X"`), then forward **that source**.

Example flow:
```
User A: "Here is the data."                (ID 10)
User B: [replies to 10] "Yes, forward this."  (ID 12)
→ Target ID = 10 (the data), NOT 12 (the reply).
```

This rule applies even if the user's wording seems ambiguous ("forward this file I sent") — verify which message contains the actual attachment, not just its mention.

### Example Pattern for Kernel Documentation

If a session requires sending both explanation text and file attachments to the same thread:
1. Forward the original explanation message first
2. Forward the original document message separately (never re-upload)
3. Both must retain "Forwarded from" attribution labels and original filenames

Always check the destination chat supports topics/subtopics; specify `message_thread_id` explicitly when needed.

## Log Reference Commands

Find message IDs in gateway.log:
```bash
# Recent inbound messages
tail -100 /opt/data/profiles/shifu/logs/gateway.log | grep "inbound message"

# Messages with documents cached
grep "Cached replied-to document" /opt/data/profiles/shifu/logs/gateway.log

# Find specific pattern
grep -B5 "msg='Yeah slightly, but not close'" /opt/data/profiles/shifu/logs/gateway.log
```

## Tool Integration

### Standalone CLI Forward (via python/urllib):

```python
import json, urllib.request
token = get_token_from_env()  # read TELEGRAM_BOT_TOKEN from .env

data = json.dumps({
    "chat_id": "-1003628710660",
    "message_thread_id": 28,
    "from_chat_id": 410848670,
    "message_id": 18  # <-- CRITICAL: correct message ID
}).encode()

req = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/forwardMessage",
    data=data,
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read())
    assert result.get("ok"), result.get("error")
    print("Forwarded to msg_id:", result["result"]["message_id"])
```

### Using Hermes CLI (if available):

```bash
# List available targets
hermes send --list telegram

# Check channel directory
cat ~/.hermes/channel_directory.json

# Note: Hermes send tool does NOT support native forwards yet
# Must use raw API via terminal/python script
```

## Lessons Learned Summary

1. **Native forwards only** → preserves metadata and authenticity
2. **Document ≠ text about document** → verify message contains actual file
3. **Log inspection saves guesses** → check gateway.log for exact IDs
4. **Topic threading matters** → always specify `message_thread_id` for forum groups
5. **Don't re-upload from disk** → original DM message is source of truth

## When in Doubt

Ask the user:
- "Which message ID do you want forwarded?" (they can see it in Telegram by long-press → Info)
- OR: "Send me the Telegram share link (t.me/user/chatid/msgid)" – extract ID from URL

Never assume or guess.
