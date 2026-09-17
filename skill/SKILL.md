---
name: "mail-bridge-send"
description: "Send email through this repo's mail-bridge HTTP-to-SMTP relay."
---

# Mail Bridge Send

Companion skill for the mail-bridge in this repo. Gives an AI agent a
send-only email path through your own infrastructure: one key-gated HTTP
call, no SMTP client config on the agent side.

## Setup

The bridge must be deployed (see the repo README). Note the API key chosen
at setup, then export:

```
export MAIL_BRIDGE_URL="https://your-bridge-host"
export MAIL_BRIDGE_API_KEY=<redacted>
```

## Tooling

CLI at `skill/mail`:

- `mail health` — bridge health check (unauthenticated `/health`).
- `mail send --to addr --subject "s" --body "text"` — send one email.

Bridge endpoints used:

- `GET /health` — no auth; returns `{"ok": true}` when the service is up.
- `POST /send` — `X-Api-Key` header; JSON body
  `{"to": "...", "subject": "...", "body": "..."}`; returns `{"ok": true}`
  on success. The bridge enforces its own recipient allowlist (403 for
  non-listed addresses) and a 10-sends-per-minute rate limit (429).

## Auth

The API key is read from the `MAIL_BRIDGE_API_KEY` environment variable at
runtime and sent as the `X-Api-Key` header to the configured bridge host only.
Nothing here collects, prints, logs, or persists the key.

## Operating Rules

1. Restrict requests to the configured bridge host only.

2. Never print, log, or persist the API key.

3. The bridge is send-only; it cannot read mail or check for replies.
   Don't imply it can.

4. Send only what the user explicitly asked to send, to recipients they
   named. Never send unprompted, and never widen the recipient list on
   your own.

5. If the bridge is unreachable, say so plainly instead of guessing
   the mail went out.
