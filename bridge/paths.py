"""Where Clara keeps things. Code lives in the repo; everything private lives in the data folder (never in git).

    CLARA_DATA_DIR   default ~/.local/share/clara   database, keys, tokens, models (voice, router), fonts
    CLARA_WORKSPACE  default /var/lib/clara/workspace   what Clara makes (her Library)
    CLARA_STATE_DIR  default /srv/clara-state           small switches shared with Clara (browser takeover)
    HERMES_HOME      default /var/lib/clara/hermes-home  the agent's home
Each file below can also be pointed elsewhere with its own variable (handy for development).
"""
import os
from pathlib import Path


def _p(env, default):
    return Path(os.path.expanduser(os.environ.get(env) or str(default)))


DATA = _p("CLARA_DATA_DIR", "~/.local/share/clara")
DB = _p("CLARA_DB", DATA / "clara.db")
LINK_TOKEN = _p("CLARA_LINK_TOKEN_FILE", DATA / "link_token")      # what Clara's plugins use to call the Bridge
BROKER_KEY = _p("CLARA_BROKER_KEY", DATA / "broker.key")           # encrypts saved API keys and account logins
IDENTITY_CACHE = _p("CLARA_IDENTITY_CACHE", DATA / "identity.json")
VOICE_DIR = _p("CLARA_VOICE_DIR", DATA / "voice")                   # Kokoro model files
FONT_DIR = _p("CLARA_FONT_DIR", DATA / "fonts")                     # caption fonts for social videos
ROUTER_MODEL = _p("CLARA_ROUTER_MODEL", DATA / "laya-for-clara")    # the fine-tuned Laya router
WORKSPACE = _p("CLARA_WORKSPACE", "/var/lib/clara/workspace")
STATE_DIR = _p("CLARA_STATE_DIR", "/srv/clara-state")
HERMES_HOME = _p("HERMES_HOME", "/var/lib/clara/hermes-home")

DATA.mkdir(parents=True, exist_ok=True)
try:
    DATA.chmod(0o700)
except OSError:
    pass
