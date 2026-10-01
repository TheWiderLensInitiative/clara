#!/bin/sh
# Clara installer: your private AI assistant, running entirely on your own PC.
#
#   git clone https://github.com/<you>/clara ~/clara && cd ~/clara && ./install.sh
#
# Run it as your normal user (not root). It asks for your password once for the system parts.
# Safe to run again: it skips what's already done. `./install.sh --update` refreshes code and services only.
#
# What it sets up (details in docs/ARCHITECTURE.md):
#   1. Bonsai 2 27B (PrismML) on llama-server, on your NVIDIA GPU             -> service clara-model
#   2. A separate, sandboxed Linux user "clara" running the Hermes agent       -> service clara-hermes
#   3. SearXNG (private web search, Docker, localhost only)
#   4. The Clara Bridge: the phone app's server, Laya router, voice, approvals -> service clara-bridge
#   Then it prints a pairing code for the Clara Android app.
set -eu

REPO="$(cd "$(dirname "$0")" && pwd)"
ME="$(id -un)"
DATA="${CLARA_DATA_DIR:-$HOME/.local/share/clara}"
BONSAI_DIR="${BONSAI_DIR:-$DATA/bonsai}"
LAYA_REPO="${LAYA_REPO:-TheWiderLensInitiative/laya-for-clara}"   # the fine-tuned router on Hugging Face
HERMES_REF="c387be0"            # hermes-agent 0.18.2: the exact commit Clara is tested with
AGENT_BROWSER_VERSION="0.38.1"
NODE_VERSION="24.21.0"
MIN_VRAM_MB=11500
UPDATE=0; [ "${1:-}" = "--update" ] && UPDATE=1

say()  { printf '\n\033[1;35m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mError:\033[0m %s\n' "$*" >&2; exit 1; }
render() {  # fill a template's @PLACEHOLDERS@
    sed -e "s|@USER@|$ME|g" -e "s|@REPO@|$REPO|g" -e "s|@DATA@|$DATA|g" -e "s|@BONSAI_DIR@|$BONSAI_DIR|g" "$1"
}
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }

[ "$(id -u)" != "0" ] || die "Run ./install.sh as your normal user, not with sudo. It asks for your password when it needs it."

# ---------------------------------------------------------------------------------------------------------------------
say "Checking this PC"
[ "$(uname -s)" = "Linux" ] && [ "$(uname -m)" = "x86_64" ] || die "Clara needs Linux on x86_64 (Ubuntu 24.04 or newer recommended)."
command -v apt-get >/dev/null || die "This installer supports Ubuntu/Debian (apt). See docs/INSTALL.md for other distros."
command -v nvidia-smi >/dev/null || die "No NVIDIA driver found (nvidia-smi). Install the NVIDIA driver first, then rerun."
VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | sort -n | tail -1)
[ "${VRAM:-0}" -ge "$MIN_VRAM_MB" ] || die "Clara needs an NVIDIA GPU with 12 GB of memory or more (found ${VRAM} MB)."
ok "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1), ${VRAM} MB"
RAM_GB=$(awk '/MemTotal/ {printf "%d", $2/1048576}' /proc/meminfo)
[ "$RAM_GB" -ge 15 ] || die "Clara needs 16 GB of RAM or more (found ${RAM_GB} GB)."
ok "RAM: ${RAM_GB} GB"
mkdir -p "$DATA"; chmod 700 "$DATA"
FREE_GB=$(df -BG --output=avail "$DATA" | tail -1 | tr -dc 0-9)
[ "$UPDATE" = 1 ] || [ "$FREE_GB" -ge 40 ] || die "Clara needs about 40 GB of free disk space in $DATA (found ${FREE_GB} GB)."
ok "Disk: ${FREE_GB} GB free"

say "Asking for your password once (for system packages, Clara's own user, and her services)"
sudo -v || die "sudo is needed for the system parts."

# ---------------------------------------------------------------------------------------------------------------------
if [ "$UPDATE" = 0 ]; then
say "System packages"
sudo apt-get update -qq
sudo apt-get install -y -qq git curl ca-certificates python3 docker.io acl libgomp1 >/dev/null
sudo systemctl enable --now docker >/dev/null 2>&1 || true
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
ok "git, curl, docker, OpenMP, uv"

# ---------------------------------------------------------------------------------------------------------------------
say "Bonsai 2 27B (the model, ~12 GB download)"
if [ ! -d "$BONSAI_DIR/.git" ]; then git clone -q https://github.com/PrismML-Eng/Bonsai-demo.git "$BONSAI_DIR"; fi
cd "$BONSAI_DIR"
[ -x bin/cuda/llama-server ] || sh scripts/download_binaries.sh
[ -x .venv/bin/python ] || "$UV" venv -q --python 3.12 .venv
"$UV" pip install -q --python .venv/bin/python huggingface-hub
warn "If it asks for a Hugging Face token, just press Enter: Bonsai is public."
BONSAI_FAMILY=bonsai2 BONSAI_MODEL=27B sh scripts/download_models.sh
if ! LD_LIBRARY_PATH="$BONSAI_DIR/bin/cuda" ldd bin/cuda/llama-server | grep -q "libcudart.so.12 => /"; then
    # the prebuilt binaries use the CUDA 12 runtime; newer drivers ship CUDA 13 only, so bring the CUDA 12 libraries along
    [ -x .venv-cudart/bin/python ] || "$UV" venv -q --python 3.12 .venv-cudart
    "$UV" pip install -q --python .venv-cudart/bin/python nvidia-cuda-runtime-cu12==12.8.90 nvidia-cublas-cu12==12.8.5.5 nvidia-cuda-nvrtc-cu12==12.9.86
    SP=$(.venv-cudart/bin/python -c "import site; print(site.getsitepackages()[0])")
    for lib in "$SP"/nvidia/cuda_runtime/lib/libcudart.so.12 "$SP"/nvidia/cublas/lib/libcublas.so.12 "$SP"/nvidia/cublas/lib/libcublasLt.so.12; do
        ln -sf "$lib" bin/cuda/
    done
    ok "CUDA 12 runtime libraries added"
fi
[ -f models/bonsai2-gguf/27B/*kv-bias.gguf ] 2>/dev/null || sh scripts/make_kv_bias.sh >/dev/null 2>&1 || warn "KV-cache bias not built (optional, slightly lower quality)"
ok "Bonsai ready in $BONSAI_DIR"
cd "$REPO"

# ---------------------------------------------------------------------------------------------------------------------
say "Clara's own Linux account (her sandboxed computer)"
id clara >/dev/null 2>&1 || sudo useradd --system --user-group --create-home --home-dir /var/lib/clara --shell /usr/sbin/nologin clara
sudo usermod -aG clara "$ME"
sudo install -d -o clara -g clara -m 2770 /var/lib/clara/workspace
sudo chmod 2750 /var/lib/clara
sudo install -d -o "$ME" -g clara -m 750 /srv/clara-state
ok "user 'clara' (no password, no sudo, cannot log in)"

# ---------------------------------------------------------------------------------------------------------------------
say "Clara's programs in /opt/clara (Hermes agent, Node, browser)"
sudo install -d -o "$ME" -g "$ME" -m 755 /opt/clara
sudo chown -R "$ME":"$ME" /opt/clara    # yours while installing; handed to root again below
hermes_at() { git -C /opt/clara/hermes-agent rev-parse --short=7 HEAD 2>/dev/null; }
if [ ! -x /opt/clara/venv-hermes/bin/hermes ] || [ "$(hermes_at)" != "$HERMES_REF" ]; then
    UV_PYTHON_INSTALL_DIR=/opt/clara/python "$UV" python install -q 3.12
    [ -d /opt/clara/hermes-agent/.git ] || git clone -q https://github.com/NousResearch/hermes-agent.git /opt/clara/hermes-agent
    git -C /opt/clara/hermes-agent fetch -q origin && git -C /opt/clara/hermes-agent checkout -q "$HERMES_REF"
    UV_PYTHON_INSTALL_DIR=/opt/clara/python "$UV" venv -q --python 3.12 /opt/clara/venv-hermes
    "$UV" pip install -q --python /opt/clara/venv-hermes/bin/python -e "/opt/clara/hermes-agent[all]" 2>/dev/null \
        || "$UV" pip install -q --python /opt/clara/venv-hermes/bin/python -e /opt/clara/hermes-agent
fi
"$UV" pip install -q --python /opt/clara/venv-hermes/bin/python trafilatura   # clean page text for clara-fetch
ok "Hermes $(hermes_at)"
if [ "$(/opt/clara/node/bin/node --version 2>/dev/null)" != "v$NODE_VERSION" ]; then
    rm -rf /opt/clara/node
    curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.xz" | tar -xJ -C /opt/clara
    mv "/opt/clara/node-v$NODE_VERSION-linux-x64" /opt/clara/node
fi
ok "Node $(/opt/clara/node/bin/node --version)"
if [ "$(/opt/clara/node/bin/node -p "require('/opt/clara/agent-browser/node_modules/agent-browser/package.json').version" 2>/dev/null)" != "$AGENT_BROWSER_VERSION" ]; then
    PATH="/opt/clara/node/bin:$PATH" npm install --prefix /opt/clara/agent-browser --no-package-lock --silent "agent-browser@$AGENT_BROWSER_VERSION"
fi
if [ ! -x /opt/clara/chrome/chrome ]; then
    # Chrome's libraries. Ubuntu renamed some between releases (24.04 has the "t64" names, 26.04 dropped a few of them),
    # so pick whichever name this system has instead of agent-browser's fixed 24.04 list.
    PKGS=""
    for p in libxcb-shm0 libx11-xcb1 libx11-6 libxcb1 libxext6 libxrandr2 libxcomposite1 libxcursor1 libxdamage1 libxfixes3 \
             libxi6 libgtk-3-0t64 libpangocairo-1.0-0 libpango-1.0-0t64 libatk1.0-0t64 libcairo-gobject2 libcairo2t64 \
             libgdk-pixbuf-2.0-0 libxrender1 libasound2t64 libfreetype6 libfontconfig1 libdbus-1-3t64 libnss3 libnss3-tools \
             libnspr4 libatk-bridge2.0-0t64 libdrm2 libxkbcommon0 libatspi2.0-0t64 libcups2t64 libxshmfence1 libgbm1 \
             fonts-noto-color-emoji fonts-noto-cjk fonts-freefont-ttf; do
        for name in "$p" "${p%t64}"; do
            if apt-cache policy "$name" 2>/dev/null | grep -q 'Candidate: [0-9]'; then PKGS="$PKGS $name"; break; fi
        done
    done
    sudo apt-get install -y -qq $PKGS >/dev/null
    TMPH=$(mktemp -d)
    env HOME="$TMPH" PATH="/opt/clara/node/bin:$PATH" /opt/clara/agent-browser/node_modules/.bin/agent-browser install >/dev/null
    CHROME=$(find "$TMPH" -type f -name chrome -perm -u+x | head -1)
    [ -n "$CHROME" ] || die "agent-browser didn't download its Chrome"
    sudo cp -a "$(dirname "$CHROME")" /opt/clara/chrome; sudo rm -rf "$TMPH"
fi
ok "agent-browser $AGENT_BROWSER_VERSION + Chrome"
sudo chown -R root:root /opt/clara; sudo chmod -R a+rX,go-w /opt/clara    # Clara can run these, never change them

# ---------------------------------------------------------------------------------------------------------------------
say "Private web search (SearXNG, only reachable from this PC)"
mkdir -p "$DATA/searxng"
[ -f "$DATA/searxng/settings.yml" ] || cat > "$DATA/searxng/settings.yml" <<EOF
use_default_settings: true
server:
  secret_key: "$(rand 32)"
  limiter: false
  image_proxy: false
search:
  formats: [html, json]
EOF
if ! sudo docker ps --format '{{.Names}}' | grep -qx clara-searxng; then
    sudo docker rm -f clara-searxng >/dev/null 2>&1 || true    # a leftover from a failed run
    if ss -ltn 2>/dev/null | grep -q '127.0.0.1:8888 '; then
        die "Port 8888 is already used by another program (an older SearXNG? check 'docker ps' as yourself, too). Stop it, then rerun ./install.sh."
    fi
    sudo docker run -d -q --name clara-searxng --restart unless-stopped -p 127.0.0.1:8888:8080 \
        -v "$DATA/searxng:/etc/searxng" searxng/searxng:latest >/dev/null
fi
ok "SearXNG on 127.0.0.1:8888"
fi   # end of full install

# ---------------------------------------------------------------------------------------------------------------------
say "Clara's agent home (personality, safety rules, plugins)"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
H=/var/lib/clara/hermes-home
[ -f "$DATA/link_token" ] || { rand 32 > "$DATA/link_token"; chmod 600 "$DATA/link_token"; }
LINK_TOKEN=$(cat "$DATA/link_token")
sudo install -d -o "$ME" -g clara -m 3770 "$H"
if ! sudo test -f "$H/.env"; then
    sed -e "s|{{LINK_TOKEN}}|$LINK_TOKEN|g" -e "s|{{API_SERVER_KEY}}|$(rand 32)|g" "$REPO/hermes/env.template" | sudo tee "$H/.env" >/dev/null
fi
sed -e "s|{{LINK_TOKEN}}|$LINK_TOKEN|g" "$REPO/hermes/config.yaml.template" | sudo tee "$H/config.yaml" >/dev/null
sudo test -f "$H/SOUL.md" || sudo cp "$REPO/hermes/SOUL.md" "$H/SOUL.md"      # Clara may edit her personality later
sudo rm -rf "$H/plugins"; sudo cp -r "$REPO/hermes/plugins" "$H/plugins"
sudo chown -R "$ME":clara "$H/config.yaml" "$H/.env" "$H/SOUL.md" "$H/plugins"
sudo chmod 640 "$H/config.yaml" "$H/.env" "$H/SOUL.md"
sudo find "$H/plugins" -type d -exec chmod 750 {} +; sudo find "$H/plugins" -type f -exec chmod 640 {} +
ok "config, safety rules (Guardian) and plugins belong to you; Clara can read them, not change them"

# ---------------------------------------------------------------------------------------------------------------------
say "Clara Bridge (Python, CPU)"
[ -x "$DATA/venv/bin/python" ] || "$UV" venv -q --python 3.12 "$DATA/venv"
"$UV" pip install -q --python "$DATA/venv/bin/python" torch --index-url https://download.pytorch.org/whl/cpu
"$UV" pip install -q --python "$DATA/venv/bin/python" -r "$REPO/bridge/requirements.txt"
ok "Bridge dependencies"
if [ ! -f "$DATA/voice/kokoro-v1.0.onnx" ]; then
    mkdir -p "$DATA/voice"
    for f in kokoro-v1.0.onnx voices-v1.0.bin; do
        curl -fsSL -o "$DATA/voice/$f" "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f"
    done
fi
ok "Clara's voice (Kokoro)"
if [ ! -f "$DATA/fonts/Anton-Regular.ttf" ]; then
    mkdir -p "$DATA/fonts"
    for f in poppins/Poppins-ExtraBold.ttf poppins/Poppins-SemiBold.ttf anton/Anton-Regular.ttf bebasneue/BebasNeue-Regular.ttf; do
        curl -fsSL -o "$DATA/fonts/$(basename $f)" "https://github.com/google/fonts/raw/main/ofl/$f" || warn "font $f not downloaded"
    done
fi
ok "Caption fonts (Google Fonts, OFL)"
if [ ! -f "$DATA/laya-for-clara/model.safetensors" ]; then
    "$DATA/venv/bin/python" -c "from huggingface_hub import snapshot_download as d; d('$LAYA_REPO', local_dir='$DATA/laya-for-clara')" >/dev/null 2>&1 \
        && ok "Laya router ($LAYA_REPO)" \
        || warn "Couldn't download $LAYA_REPO; Clara will use the base Laya model (routing works, quick/deep is less accurate)"
else
    ok "Laya router"
fi

# ---------------------------------------------------------------------------------------------------------------------
say "Services (start at boot, no login needed)"
for u in clara-model clara-bridge clara-hermes; do render "$REPO/setup/$u.service" | sudo tee "/etc/systemd/system/$u.service" >/dev/null; done
render "$REPO/setup/49-clara.rules" | sudo tee /etc/polkit-1/rules.d/49-clara.rules >/dev/null
mkdir -p "$HOME/.local/bin"; render "$REPO/setup/clara" > "$HOME/.local/bin/clara"; chmod +x "$HOME/.local/bin/clara"
sudo systemctl daemon-reload
sudo systemctl enable -q clara-model clara-bridge clara-hermes
sudo systemctl restart clara-model clara-hermes clara-bridge
ok "clara-model, clara-hermes, clara-bridge"

say "Waiting for Clara to wake up (loading the model takes a minute)"
i=0
until curl -sf -m 3 localhost:8700/v1/health 2>/dev/null | grep -q '"model":true'; do
    i=$((i + 1)); [ $i -lt 120 ] || die "Clara didn't start. See: clara logs model   /   clara logs bridge"
    sleep 3
done
ok "Clara is up"

LAN=$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}')
CODE=$(cd "$REPO/bridge" && CLARA_DATA_DIR="$DATA" "$DATA/venv/bin/python" pair.py | awk '{print $3}')
cat <<EOF

  Get the Clara app: scan this with your phone's camera, or open
  https://clara.thewiderlens.info/#download

EOF
(cd "$REPO/bridge" && "$DATA/venv/bin/python" qr.py) | sed 's/^/  /'
cat <<EOF

  ┌──────────────────────────────────────────────────────────────┐
  │  Clara is installed.                                         │
  │                                                              │
  │  In the Clara app on your phone (same Wi-Fi), enter:         │
  │      Computer address:  ${LAN}:8700
  │      Pairing code:      ${CODE}   (valid 10 minutes)
  │                                                              │
  │  New code any time:  clara pair                              │
  │  Show the app's QR code again:  clara app                    │
  │  Use Clara away from home:  sudo sh setup/tailscale.sh       │
  └──────────────────────────────────────────────────────────────┘
EOF
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) warn "Add ~/.local/bin to your PATH to use the 'clara' command." ;; esac
