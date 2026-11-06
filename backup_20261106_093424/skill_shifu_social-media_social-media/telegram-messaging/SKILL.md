---
name: telegram-messaging
description: Use when sending or forwarding Telegram messages/files.
---

# Telegram Messaging via Hermes

## Semantics first — match the user's words exactly
- Treat "forward this" in a reply as a request to **natively forward the replied-to message**, not the user's instruction message; the author may be the assistant or someone else. Do not regenerate, paraphrase, or use `copyMessage`, because those lose the requested forward attribution.
- Forward an existing document message natively when the user asks to forward a file; this preserves its filename and forward attribution. Do not re-upload a cached copy or forward the text announcing the file.
- Attach a newly created file as a **Telegram document** via `MEDIA:<abs path>` when no original document message exists. Preserve the intended filename rather than exposing a cache-generated basename.

## Resolve source messages before sending
1. Read the current instruction and its reply metadata. Distinguish the instruction's `message_id` / `source_message_id` from the replied-to message's ID; origin IDs alone do not identify the message the user replied to.
2. Resolve the original source chat and explicit `reply_to_id` / replied-to message ID from gateway metadata, scoped logs, or stored message records. Resolve text and document IDs separately: the file announcement and document attachment are different messages.
3. Confirm each source's content class against available evidence. A document reply plus its explicit `reply_to_id` identifies a document; a neighboring ID does not. Never infer IDs from adjacency or message order.
4. If source evidence is insufficient, ask the user to reply to the original message or document. Do not demand manually typed IDs when the reply metadata or message link already resolves them.
5. Forward only the missing or incorrect item after a correction; leave an already-confirmed correct forward alone.

## Resolving targets
- Use `telegram:<chat_id>` for DMs/groups and `telegram:<chat_id>:<topic_id>` for confirmed forum topics.
- Check `$HERMES_HOME/channel_directory.json` and the user's supplied links before requesting IDs; scope lookup and credentials to the active profile.
- Decode `https://t.me/c/<internal_id>/...` as chat ID `-100<internal_id>`. Use the final number as `message_thread_id` only when the link is confirmed as the forum topic destination; an ordinary message link identifies a message, not necessarily its topic.

## Dispatch the requested operation
- Prefer the available native forwarding tool. Otherwise use the configured Bot API transport's `forwardMessage` with the **resolved original** `from_chat_id` and `message_id`, destination `chat_id`, and confirmed topic's `message_thread_id`. See [native forwarding and verification](references/telegram-forward.md).
- For a fresh send, use the installed Hermes CLI with `--json` so the result includes a message ID:
```bash
hermes send --to "telegram:<chat_id>:<topic_id>" --json "message text"
hermes send --to "telegram:<chat_id>:<topic_id>" --json "MEDIA:/abs/path/file.md"
```
- Use `--file PATH` only to read a text message body; a bare positional path sends the path string. Neither produces an attachment.
- Preserve approvals and credential boundaries. Use the active profile's approved credential loader; do not dump credential stores, expose tokens, or bypass a blocked command by rewriting it.

## Verify before claiming completion
- Check returned destination, topic, message ID, and `forward_origin` for a native forward. For a file, also require `result.document` and exact `document.file_name`; API success alone cannot distinguish the intended file from an unrelated text message.
- Report each item's verified result separately. Do not claim a pair is complete when only one content class was verified.
- Retry only a failure known to occur before dispatch or an explicit retryable API rejection. Treat timeouts and interrupted side effects as unknown delivery; inspect state before resending, because blind retries create duplicates.
- Never delete suspected duplicates using guessed IDs. Verify destination and content, obtain deletion authorization, and retain the correct pair.

## Bulk deletion and retention sweeps
- For bulk-deleting many bot-sent messages under flaky egress, follow [references/telegram-bulk-delete.md](references/telegram-bulk-delete.md): recover IDs from history + send-logs (union), route via fallback IPs with socket+SNI TLS, treat `message to delete not found` as success, persist progress for resumability.
- Retention sweeps must cap **by time**, never by a fixed count. A count cap evicts the oldest entries before they reach the expiry age when send volume is high, so the sweep never sees them and they orphan forever. Keep entries for ≥2× the delete window.
- Mark an item as deleted only when the delete call returns truthy. Marking it deleted on failure (or on a bare `success=None` result) prunes it from the sweep's tracking and it is never retried.
