# Installing Clara

## 1. Before you start

- **An NVIDIA GPU with 12 GB of memory or more**, with the NVIDIA driver installed (`nvidia-smi` should work).
  Bonsai 2 27B with a 100K context uses about 10.5 GB.
- **16 GB RAM** (32 GB recommended), **40 GB of free disk**, **Ubuntu 24.04 or newer**.
- An **Android phone** (Android 9+) on the same Wi-Fi as the PC, for setup.

## 2. Run the installer

```bash
git clone https://github.com/TheWiderLensInitiative/clara ~/clara
cd ~/clara
./install.sh
```

Run it as your normal user; it asks for your password once. It:

1. checks your hardware
2. installs Docker, git, curl and [uv](https://github.com/astral-sh/uv)
3. downloads Bonsai 2 27B and PrismML's llama-server (~12 GB) into `~/.local/share/clara/bonsai`
4. creates a Linux user **`clara`**: no password, no sudo, cannot log in. It is her own computer.
5. installs the Hermes agent, Node 24, agent-browser and its Chrome into `/opt/clara` (read-only for Clara)
6. starts a private SearXNG search engine (Docker, only reachable from this PC)
7. sets up the Bridge, Clara's voice (Kokoro) and the Laya router in `~/.local/share/clara`
8. installs three services that start at boot: `clara-model`, `clara-hermes`, `clara-bridge`
9. prints the computer address and a pairing code

Running it again is safe. `clara update` pulls the latest code and refreshes everything except your data.

## 3. Connect your phone

Install the Clara app (from the project's website or the GitHub release). Open it, enter the **computer address**
(e.g. `192.168.1.20:8700`) and the **pairing code**. Lost the code? Run `clara pair` for a new one (valid 10 minutes).

## 4. Optional extras

| What | How |
|---|---|
| **Use Clara away from home** | `sudo sh setup/tailscale.sh`, then the Tailscale app on your phone (same account). The app switches between Wi-Fi and Tailscale by itself. |
| **Cloud boost** (coding, pictures, videos) | In the app: Clara menu → Cloud AI → add your OpenRouter key, pick models, set caps |
| **Accounts** (Gmail, Calendar, Spotify…) | Clara menu → Connectors; each one has step-by-step setup |
| **Brand kit** for ads | Clara menu → Brand kit |

## Everyday commands

```
clara status            are the three services running, and is she healthy?
clara pair              new pairing code       clara pair list / clara pair revoke <id>
clara logs bridge       last log lines (also: model, agent)
clara restart           restart everything     clara update     update to the latest version
```

## Troubleshooting

- **"Can't reach your computer" on the phone:** same Wi-Fi? Run `clara status`. Firewalls must allow port 8700 on your LAN.
- **The model won't start:** `clara logs model`. Usually the GPU is busy (close games/other AI apps) or the driver is
  older than CUDA 12.8 needs.
- **Slow replies:** the first task after a restart takes ~40 s while the model reads Clara's instructions; later tasks reuse
  them. Quick tasks run without "thinking" and take seconds; research and planning think first and take longer.
- **Something else:** open an issue with the output of `clara status` and `clara logs bridge` (it never contains your keys).

## Uninstall

```bash
sudo systemctl disable --now clara-model clara-bridge clara-hermes
sudo rm /etc/systemd/system/clara-*.service /etc/polkit-1/rules.d/49-clara.rules
sudo docker rm -f clara-searxng
sudo userdel -r clara; sudo rm -rf /opt/clara /srv/clara-state
rm -rf ~/.local/share/clara ~/.local/bin/clara      # your Clara data: chats, keys, models
```
