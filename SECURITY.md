# Security

Clara can act on a real computer, so security matters. How she's contained is described in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#clara-s-sandbox) and [docs/PRIVACY.md](docs/PRIVACY.md).

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Use GitHub's private vulnerability reporting
(Security tab → "Report a vulnerability") or email clara@thewiderlens.info, with steps to reproduce. We'll reply as soon
as we can.

## Good practice for users

- Keep the Bridge on your home network or Tailscale. Don't forward port 8700 on your router to the internet.
- Pair only your own phones; `clara pair list` shows them and `clara pair revoke <id>` removes one.
- Keep `~/.local/share/clara` private and backed up; it holds your keys.
- Set cloud spending caps if you add an OpenRouter key.
