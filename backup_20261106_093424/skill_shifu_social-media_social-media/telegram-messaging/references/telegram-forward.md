# Native Telegram forwarding and verification

## Ordered recipe

1. Resolve source chat and original message ID from explicit reply metadata. The current instruction's `message_id` or `source_message_id` is not automatically the replied-to source.
2. Resolve destination chat and confirmed forum topic. Resolve a document attachment separately from its accompanying text.
3. Use the active profile's native forwarding tool or configured Bot API transport with its approved credential loader. Keep tokens inside that channel; do not read credential files directly or put tokens in shell arguments, logs, artifacts, or chat. If approval is denied or expires, stop rather than changing execution route.
4. Call `forwardMessage`, not `sendMessage`, `sendDocument`, or `copyMessage`. Forwarding preserves original content and attribution; a fresh upload changes message identity and may expose a cache-generated filename. Native forwarding does not guarantee preservation of the source message's reply relationship.
5. Inspect the complete returned `Message` before reporting done. Verify destination chat, topic, `forward_origin`, and content class. For a document, require `document.file_name` to match the original exactly.
6. Keep the successful returned message ID. If delivery becomes unknown through a timeout or interruption, inspect destination state before retrying. If one part of a pair is already correct, send only the other part.

## Bot API request

Use `POST /bot<token>/forwardMessage` on Telegram's configured API endpoint with a JSON body:

```json
{
  "chat_id": "<destination_chat_id>",
  "message_thread_id": "<confirmed_topic_id>",
  "from_chat_id": "<original_source_chat_id>",
  "message_id": "<original_message_id>"
}
```

Replace placeholders with validated platform IDs; use integers for `message_id` and `message_thread_id`. Omit `message_thread_id` outside a topic. Preserve any configured proxy or network transport rather than inventing a separate credential/network path.

## Runnable response check

Save the token-free Bot API response as JSON and validate it with this stdlib-only check. Pass the expected filename for a document; omit it for a text message. Omit the topic argument when targeting a non-topic chat.

```bash
python3 - response.json '<destination_chat_id>' '<topic_id>' 'notes.md' <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    response = json.load(stream)
assert response.get("ok") is True, response.get("description", "forward failed")
message = response["result"]
assert str(message["chat"]["id"]) == sys.argv[2], "wrong destination"
if len(sys.argv) > 3:
    assert str(message.get("message_thread_id")) == sys.argv[3], "wrong topic"
assert message.get("forward_origin"), "not a native forward"
if len(sys.argv) > 4:
    assert message.get("document"), "forwarded text instead of document"
    assert message["document"].get("file_name") == sys.argv[4], "wrong filename"
else:
    assert isinstance(message.get("text"), str), "forwarded item is not text"
print("verified message_id:", message["message_id"])
PY
```

Also compare returned text, filename, and available attribution against the selected source. A matching filename alone cannot prove that an unrelated document with the same name is the intended message.

## Source lookup without guessing

- Use explicit replied-to IDs recorded by the gateway; document replies may have no reply text even though their document metadata was cached.
- Treat a cached local path as file bytes, not as a Telegram message ID. Its basename may include an internal prefix absent from the original filename.
- Do not probe unknown candidate IDs by forwarding them into the destination; that publishes unrelated messages. If the original ID cannot be recovered, ask for a reply to the original document or its message link.
- Keep API success distinct from semantic success: forwarding the instruction or announcement can succeed while failing the user's request.
