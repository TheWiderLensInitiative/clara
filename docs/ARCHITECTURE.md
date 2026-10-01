# How Clara works

## The pieces

| Piece | Runs as | Where | Job |
|---|---|---|---|
| **clara-model** | you | GPU | Bonsai 2 27B on PrismML's llama-server (100K context, 4-bit KV cache, 2 slots sharing one cache) |
| **clara-hermes** | user `clara`, sandboxed | CPU | The Hermes agent: tools (terminal, files, browser, search, cron), plus Clara's plugins |
| **clara-bridge** | you (+ group `clara`) | CPU | The phone's server (port 8700): chats, router, approvals, voice, video, connectors, cloud boost |
| **SearXNG** | Docker | 127.0.0.1:8888 | Private meta-search for the agent |

## A message's journey

1. The phone sends a message to the Bridge.
2. **Routing.** Simple rules catch obvious cases (reminders, "remember…", make/draw/code, connected services). Everything
   else goes to **Laya** (`laya-for-clara`, ~0.35 s on CPU): `chat`, `task` or `schedule`. If Laya is unsure, Bonsai votes;
   if they disagree, the agent handles it.
3. **chat** goes straight to Bonsai with thinking off and streams back in a few seconds.
4. **schedule:** plain reminders are parsed by Bonsai (thinking off) and created directly in Hermes's scheduler (~3 s).
5. **task:** Laya's second answer decides **quick** (agent with thinking off, via the Hermes model route `bonsai-fast`)
   or **deep** (thinking on). The Bridge relays every tool step to the phone as it happens.
6. Risky steps hit **Guardian** (a Hermes plugin with rules Clara can't edit), which asks the phone for approval.

## Speed tricks

- **Two llama.cpp slots with a unified KV cache.** Slot 0 keeps the agent's ~21K-token instructions cached; everything the
  Bridge asks directly (chat, notes, routing) uses slot 1, so it never evicts the agent's cache.
- **Thinking only when needed** (Laya's quick/deep), and a fast lane for reminders.

## Clara's sandbox

Clara is a separate Linux user. `clara-hermes.service` adds systemd sandboxing: `ProtectHome=yes` (your home is
invisible), `ProtectSystem=strict` (only `/var/lib/clara` is writable), `NoNewPrivileges`, `PrivateTmp`, and more.
Her config, `.env`, personality and plugins are owned by you and read-only to her. Programs in `/opt/clara` are owned by
root.

## Plugins (`hermes/plugins/`)

| Plugin | Tools / role |
|---|---|
| `clara-guardian` | approval rules and blocks (self-tampering, killing Clara's own services, browser takeover pause) |
| `clara-vault` | `list_logins`, `sign_in`: logins sealed by the phone (ECDH P-256 + HKDF + AES-GCM) and decrypted only in memory |
| `clara-connect` | `call_api`, `email_*`, `calendar_*`, `list_connections`, `connection_call`, `youtube_upload` |
| `clara-cloud` | `generate_image`, `make_video`, brand kit, `restyle_yourself`, cloud status and budget suggestions |
| `clara-link` | delivers scheduled-job results, mirrors memory to the Bridge, shares workspace files with the Library |

## Secrets

All in `~/.local/share/clara` (mode 700): the database, `link_token` (how Clara's plugins authenticate to the Bridge) and
`broker.key` (encrypts API keys and account tokens with Fernet). Account tokens never reach Clara: the Bridge makes the
calls, only to each service's own hosts, without following redirects, and scrubs tokens from responses.

## Phone ↔ PC

Pairing gives the phone a device token (stored hashed on the PC). The Bridge streams events over SSE. With Tailscale,
`tailscale serve` publishes the Bridge at `https://<pc>.<tailnet>.ts.net`; the app learns that address and switches
between home Wi-Fi and Tailscale automatically.
