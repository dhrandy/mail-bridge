#!/usr/bin/env python3
"""mail-bridge: tiny HTTP -> SMTP bridge. Python stdlib only.

Endpoints:
  GET  /health          -> {"ok": true}
  POST /send            -> {"ok": true} on success, {"ok": false, "error": ...} on failure
                         Requires header X-Api-Key matching the API_KEY env var.
                         JSON body: {"to": "...", "subject": "...", "body": "..."}
                         The recipient must be on ALLOWED_RECIPIENTS (403 otherwise).

Hardening:
  - X-Api-Key checked with hmac.compare_digest; missing/invalid -> 401
  - ALLOWED_RECIPIENTS allowlist -> 403 for anyone else (no open relay)
  - Rate limit: max 10 /send requests per rolling 60 seconds -> 429
  - Secrets (API key, SMTP password) never appear in logs or error responses
  - Intended to sit behind a Cloudflare Tunnel; tunnel + API key are the access control

Env:
  SMTP_HOST           default smtp.gmail.com
  SMTP_PORT           default 587 (STARTTLS)
  SMTP_USER           required for /send (e.g. you@gmail.com)
  SMTP_PASS           required for /send (Gmail app password)
  SMTP_FROM           default SMTP_USER
  API_KEY             required
  ALLOWED_RECIPIENTS  comma-separated emails, default (empty; set via env)
  PORT                default 8025
"""

import collections
import hmac
import json
import os
import re
import smtplib
import sys
import threading
import time
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "") or SMTP_USER
API_KEY = os.environ.get("API_KEY", "")
ALLOWED_RECIPIENTS = {
    addr.strip().lower()
    for addr in os.environ.get("ALLOWED_RECIPIENTS", "").split(",")
    if addr.strip()
}
PORT = int(os.environ.get("PORT", "8025"))

MAX_BODY = 1024 * 1024  # 1 MB request cap
EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
RATE_LIMIT = 10          # max /send requests
RATE_WINDOW = 60.0       # per rolling seconds

_rate_lock = threading.Lock()
_rate_hits = collections.deque()  # timestamps of recent /send requests

if not API_KEY:
    print("mail-bridge: WARNING: API_KEY is not set; /send will reject everything",
          file=sys.stderr, flush=True)


def _scrub(text):
    """Remove the SMTP password from a string before it goes anywhere visible."""
    if SMTP_PASS and text:
        return text.replace(SMTP_PASS, "***")
    return text


def json_response(handler, status, payload):
    data = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def rate_limited():
    now = time.monotonic()
    with _rate_lock:
        while _rate_hits and _rate_hits[0] <= now - RATE_WINDOW:
            _rate_hits.popleft()
        if len(_rate_hits) >= RATE_LIMIT:
            return True
        _rate_hits.append(now)
        return False


def send_email(to_addr, subject, body_text):
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body_text)
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)


class Handler(BaseHTTPRequestHandler):
    server_version = "mail-bridge/1.0"

    def log_message(self, fmt, *args):
        # Access log only: method + path. Never headers, bodies, or secrets.
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))
        sys.stderr.flush()

    def _ok(self, payload):
        json_response(self, 200, payload)

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._ok({"ok": True})
        else:
            json_response(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/send":
            json_response(self, 404, {"ok": False, "error": "not found"})
            return

        key = self.headers.get("X-Api-Key", "")
        if not API_KEY or not hmac.compare_digest(key, API_KEY):
            json_response(self, 401, {"ok": False, "error": "unauthorized"})
            return

        if rate_limited():
            json_response(self, 429, {"ok": False, "error": "rate limit exceeded"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            json_response(self, 400, {"ok": False, "error": "invalid request size"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            json_response(self, 400, {"ok": False, "error": "invalid JSON"})
            return

        to_addr = payload.get("to") if isinstance(payload, dict) else None
        subject = payload.get("subject") if isinstance(payload, dict) else None
        body_text = payload.get("body") if isinstance(payload, dict) else None
        if (not isinstance(to_addr, str) or not EMAIL_RE.match(to_addr.strip())
                or not isinstance(subject, str) or not subject.strip()
                or not isinstance(body_text, str) or not body_text.strip()):
            json_response(self, 400, {"ok": False,
                                      "error": "need to, subject, body (to must be an email address)"})
            return

        if to_addr.strip().lower() not in ALLOWED_RECIPIENTS:
            json_response(self, 403, {"ok": False, "error": "recipient not allowed"})
            return

        if not SMTP_USER or not SMTP_PASS:
            json_response(self, 500, {"ok": False,
                                      "error": "SMTP credentials not configured on bridge"})
            return
        try:
            send_email(to_addr.strip(), subject.strip(), body_text)
        except smtplib.SMTPAuthenticationError:
            json_response(self, 500, {"ok": False,
                                      "error": "SMTP authentication failed (check SMTP_USER/SMTP_PASS)"})
            return
        except Exception as exc:  # connection / TLS / recipient errors
            json_response(self, 500, {"ok": False,
                                      "error": "send failed: " + _scrub(str(exc))[:300]})
            return

        self._ok({"ok": True})


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("mail-bridge listening on :%d (smtp %s:%d, %d allowlisted recipient(s))"
          % (PORT, SMTP_HOST, SMTP_PORT, len(ALLOWED_RECIPIENTS)), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
