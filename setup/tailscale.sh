#!/bin/sh
# Clara remote access with Tailscale: reach Clara from anywhere, privately (only your own devices can connect).
#   sudo sh ~/clara/setup/tailscale.sh
# It installs Tailscale, signs this PC in (a link to open in your browser), and publishes the Clara Bridge at
# https://<this-pc>.<your-tailnet>.ts.net with a real certificate. Nothing is opened to the public internet.
set -e
ME="${SUDO_USER:-$(logname 2>/dev/null || id -un)}"

if [ "$(id -u)" != "0" ]; then echo "Run it with sudo:  sudo sh $0"; exit 1; fi

if ! command -v tailscale >/dev/null 2>&1; then
    echo "==> Installing Tailscale (official installer from tailscale.com)"
    curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled

echo "==> Signing this PC in to Tailscale"
echo "    If a link appears, open it, sign in (Google/Microsoft/GitHub/Apple all work) and approve this PC."
# --operator lets Clara's Bridge (running as $ME) read Tailscale status and manage 'serve' without sudo later
tailscale up --operator="$ME" --hostname=clara-pc

echo "==> Publishing the Clara Bridge over HTTPS inside your tailnet"
if ! tailscale serve --bg --https=443 http://127.0.0.1:8700; then
    echo
    echo "Tailscale needs HTTPS certificates switched on for your tailnet (one time):"
    echo "  1. Open https://login.tailscale.com/admin/dns"
    echo "  2. Make sure MagicDNS is enabled, then click 'Enable HTTPS'"
    echo "  3. Run this script again."
    exit 1
fi

NAME=$(tailscale status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))")
echo
echo "Done. Clara is reachable from your devices at:  https://$NAME"
echo "Next: install the Tailscale app on your phone, sign in with the same account, and Clara switches over by herself"
echo "when you're away from home Wi-Fi."
