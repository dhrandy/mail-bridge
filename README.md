# mail-bridge

Tiny HTTP-to-SMTP bridge. Lets automation send email through your own
infrastructure with a single key-gated HTTP call. Python stdlib only,
no dependencies.

## Endpoints

- `GET /health` -> `{"ok": true}`
- `POST /send` with header `X-Api-Key` and JSON body
  `{"to": "...", "subject": "...", "body": "..."}` ->
  `{"ok": true}` on success, `{"ok": false, "error": "..."}` on failure.

## Security

How this bridge stays safe, in plain language:

- **API key required on every request.** The bridge only accepts `/send`
  requests that carry the secret API key in the `X-Api-Key` header. No key,
  or the wrong key, gets rejected (401). Without the key, the bridge will
  not send anything for anyone.
- **Recipient allowlist.** The bridge will only send mail to addresses on
  its `ALLOWED_RECIPIENTS` list, which defaults to just
  recipient@example.com. Any other address is refused (403). This means
  that even if the API key somehow leaked, nobody could use the bridge to
  send spam to strangers or turn it into an open relay. You can add more
  addresses to the list in Dockhand's Environment tab any time.
- **Rate limiting on /send.** At most 10 sends per minute. If something goes
  wrong or someone tries to hammer it, extra requests get a "slow down"
  (429) response instead of sending mail.
- **No secrets in logs or error messages.** Your API key and Gmail app
  password never appear in the bridge's logs, and error responses never
  include them either. If an error message happens to contain the password,
  it is scrubbed out before the response is sent.
- **Non-root container user.** Inside the container the app runs as a
  limited user account, not as root, so a bug in the app cannot easily take
  over the container.
- **Secrets only via environment variables.** The API key and app password
  are set in Dockhand's Environment tab. They are never written into files,
  never committed to this repo, and should never be pasted into chat.
- **Access control is the API key plus your Cloudflare Tunnel.** The bridge
  is only reachable through your Cloudflare Tunnel (like your other
  bridges), not directly from the internet. The tunnel keeps it off the
  public web; the API key keeps out anyone who finds the tunnel address.
  Do not expose the container's port to the internet directly.

## Environment

Set these in Dockhand's Environment tab (never in a file):

| Var | Default | Notes |
| --- | ------- | ----- |
| `SMTP_HOST` | `smtp.gmail.com` | |
| `SMTP_PORT` | `587` | STARTTLS; use `465` for implicit TLS |
| `SMTP_USER` | (required) | Your Gmail address |
| `SMTP_PASS` | (required) | Your Gmail **app password** (16 chars, generated at myaccount.google.com/apppasswords) |
| `SMTP_FROM` | `SMTP_USER` | From address on sent mail |
| `API_KEY` | (required) | Long random secret; the client sends it as `X-Api-Key` |
| `ALLOWED_RECIPIENTS` | `recipient@example.com` | Comma-separated. Extend this list in Dockhand any time you want to allow more recipients |
| `PORT` | `8025` | Container listen port |

## Dockhand compose

```yaml
services:
  mail-bridge:
    image: ghcr.io/dhrandy/smtp-bridge:latest
    container_name: mail-bridge
    restart: unless-stopped
    ports:
      - "8025:8025"
    environment:
      SMTP_HOST: smtp.gmail.com
      SMTP_PORT: "587"
      SMTP_USER: you@gmail.com
      SMTP_PASS: xxxx-xxxx-xxxx-xxxx
      SMTP_FROM: you@gmail.com
      API_KEY: <paste the generated key>
      ALLOWED_RECIPIENTS: recipient@example.com
```

## Setup

1. Generate a Gmail app password (Google Account -> Security -> App passwords,
   needs 2-Step Verification on). Paste it into Dockhand as `SMTP_PASS`.
   Never share it with anyone, including your AI assistant.
2. Generate a long random API key (e.g. `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`).
   Paste it into Dockhand as `API_KEY` and store it in the assistant's
   credential vault as `custom.mail-bridge` (X-Api-Key header placement).
3. Deploy the compose above in Dockhand. Update flow: stop, pull, start.
4. Add the container's hostname/port to your Cloudflare Tunnel, same as the
   other bridges (e.g. `mail.example.com`).
5. Test: `curl https://mail.example.com/health` should return
   `{"ok": true}`.

## AI agent

Setting it up with an AI agent? Just point it at this page.

A drop-in skill lives in `skill/`: `skill/SKILL.md` plus the `skill/mail`
CLI (`mail health`, `mail send --to ... --subject ... --body ...`). It reads
the API key from the `MAIL_BRIDGE_API_KEY` environment variable and sends it
as the `X-Api-Key` header to the configured bridge host only. Nothing in the
skill collects, prints, logs, or persists the key.

Rules baked into the skill: send only what the user explicitly asked to
send, to recipients they named, never unprompted; the bridge is send-only
(no inbox, no replies). The bridge itself enforces the recipient allowlist
and the 10-sends-per-minute rate limit.
