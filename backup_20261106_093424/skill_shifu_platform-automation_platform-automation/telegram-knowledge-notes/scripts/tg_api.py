#!/usr/bin/env python3
"""Telegram Bot API client that survives hosts which block the plain API path.

WHY THIS EXISTS: on some deployments `https://api.telegram.org/...` and
IP-literal HTTPS both fail (connection reset by peer, or
CERTIFICATE_VERIFY_FAILED 'IP address mismatch'). The Hermes gateway works
because it pins a known Telegram IPv4 as the TCP peer while presenting
SNI/Host = api.telegram.org, so certificate validation succeeds against the
hostname. This module reproduces exactly that, so forward/document sends work
even when the plain hostname path is blocked.

Use for the two operations the knowledge-notes workflow needs that have no
`hermes send` equivalent:
  * forwardMessage  (native forward of an existing message)
  * sendDocument    (post the .md as a real file attachment)

Token comes from the profile .env (TELEGRAM_BOT_TOKEN). Never print the token.

CLI:
  python3 tg_api.py forward <from_chat_id> <message_id> <to_chat_id> <thread_id>
  python3 tg_api.py doc <to_chat_id> <file_path> <thread_id> [caption]
"""
import json
import pathlib
import re
import socket
import ssl
import sys
import time
import uuid

HOST = "api.telegram.org"
# Known Telegram Bot API IPv4s; try in order (the peer is an IP, the cert is
# validated against HOST via SNI, so this is not a MITM relaxation).
IPS = ["149.154.166.110", "149.154.167.220", "149.154.175.50"]
_CTX = ssl.create_default_context()


def _token(env_path="/opt/data/profiles/shifu/.env"):
    txt = pathlib.Path(env_path).read_text()
    return re.search(r"TELEGRAM_BOT_TOKEN=(\S+)", txt).group(1)


def _parse_http(data: bytes):
    head, _, resp = data.partition(b"\r\n\r\n")
    if b"transfer-encoding: chunked" in head.lower():
        out, rest = b"", resp
        while True:
            line, _, rest = rest.partition(b"\r\n")
            n = int(line.strip() or b"0", 16)
            if n == 0:
                break
            out += rest[:n]
            rest = rest[n + 2:]
        resp = out
    return json.loads(resp)


def _send_raw(request_bytes: bytes):
    last = None
    for ip in IPS:
        try:
            raw = socket.create_connection((ip, 443), timeout=60)
            s = _CTX.wrap_socket(raw, server_hostname=HOST)
            s.sendall(request_bytes)
            chunks = []
            while True:
                c = s.recv(65536)
                if not c:
                    break
                chunks.append(c)
            s.close()
            return _parse_http(b"".join(chunks))
        except Exception as e:  # noqa: BLE001 - try the next IP
            last = e
            time.sleep(1)
    raise last


def call(method, payload, token=None):
    """POST a JSON Bot API method (e.g. forwardMessage)."""
    token = token or _token()
    body = json.dumps(payload).encode()
    req = (
        f"POST /bot{token}/{method} HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode() + body
    return _send_raw(req)


def send_document(chat_id, path, caption=None, thread_id=None, filename=None, token=None):
    """Post a file as a real document attachment (multipart form-data)."""
    token = token or _token()
    p = pathlib.Path(path)
    content = p.read_bytes()
    filename = filename or p.name
    boundary = uuid.uuid4().hex
    parts = []

    def field(k, v):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        )

    field("chat_id", str(chat_id))
    if thread_id is not None:
        field("message_thread_id", str(thread_id))
    if caption:
        field("caption", caption)
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; "
         f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
        + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = (
        f"POST /bot{token}/sendDocument HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        f"Content-Type: multipart/form-data; boundary={boundary}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode() + body
    return _send_raw(req)


def _main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "forward":
        _, from_chat, msg_id, to_chat, thread = argv[:5]
        res = call("forwardMessage", {
            "chat_id": to_chat, "message_thread_id": int(thread),
            "from_chat_id": from_chat, "message_id": int(msg_id),
        })
    elif cmd == "doc":
        to_chat, path, thread = argv[1:4]
        caption = argv[4] if len(argv) > 4 else None
        thread_id = int(thread) if thread.strip() else None
        res = send_document(to_chat, path, caption=caption, thread_id=thread_id)
    else:
        print(__doc__)
        return 1
    r = res.get("result", {})
    print("ok=", res.get("ok"),
          "chat=", r.get("chat", {}).get("id"),
          "thread=", r.get("message_thread_id"),
          "forward_origin=", bool(r.get("forward_origin")),
          "file=", r.get("document", {}).get("file_name"),
          "desc=", res.get("description"))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
