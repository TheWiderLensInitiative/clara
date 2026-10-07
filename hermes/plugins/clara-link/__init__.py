"""clara-link: Clara runs as her own Linux user, so the Bridge (the user's account) can't read her private files.
Two watchers run inside her Hermes process and talk to the Bridge over localhost:
  * fired reminders / scheduled-job results are pushed to the Bridge (-> the user's phone);
  * her memory files (USER.md, MEMORY.md) are mirrored to the Bridge, and edits the user makes in the app come back."""
import json
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)
BRIDGE = os.environ.get("CLARA_BRIDGE_URL", "http://127.0.0.1:8700")
MARKER = "## Response"


def _push(job_id, text):
    req = urllib.request.Request(
        BRIDGE + "/internal/cron-output", data=json.dumps({"job_id": job_id, "text": text}).encode(),
        headers={"Authorization": "Bearer " + os.environ.get("CLARA_LINK_TOKEN", ""), "Content-Type": "application/json"}, method="POST",
    )
    urllib.request.urlopen(req, timeout=15).read()


def _watch():
    """Deliver each new cron output file once. What's been delivered is kept on disk: a result written while the
    Bridge was down used to live only in memory here, so a Hermes restart before the Bridge came back (install.sh
    restarts both) lost that morning's brief."""
    out = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "cron" / "output"
    ledger = out.parent / "delivered.txt"
    if ledger.exists():
        seen = set(ledger.read_text().split("\n"))
    else:   # first run with the ledger: everything already there counts as delivered
        seen = {str(p) for p in out.glob("*/*.md")}
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("\n".join(sorted(seen)))
    while True:
        time.sleep(5)
        for p in sorted(out.glob("*/*.md"), key=lambda p: p.stat().st_mtime):
            if str(p) in seen or time.time() - p.stat().st_mtime < 2:   # skip a file still being written
                continue
            md = p.read_text(errors="replace")
            try:
                _push(p.parent.name, (md.split(MARKER, 1)[1] if MARKER in md else md).strip())
            except Exception as e:  # Bridge restarting: not marked, so it's sent next tick (or after a restart)
                logger.info("clara-link: will retry delivering %s (%s)", p.parent.name, type(e).__name__)
                break
            seen.add(str(p))
            with ledger.open("a") as f:
                f.write("\n" + str(p))


def _call(method, path, body=None):
    req = urllib.request.Request(BRIDGE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + os.environ.get("CLARA_LINK_TOKEN", ""), "Content-Type": "application/json"},
                                 method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _memory_sync():
    mem = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "memories"
    files = {"user": mem / "USER.md", "memory": mem / "MEMORY.md"}
    last = None
    while True:
        try:
            # 1. apply edits the user made in the Clara app
            for name, text in (_call("GET", "/internal/identity/pending").get("pending") or {}).items():
                if name in files:
                    mem.mkdir(parents=True, exist_ok=True)
                    files[name].write_text(text)
                    _call("POST", "/internal/identity/applied", {"name": name})
            # 2. mirror the current files to the Bridge when they change
            now = {k: (p.read_text(errors="replace") if p.exists() else "") for k, p in files.items()}
            if now != last:
                _call("POST", "/internal/identity", now)
                last = now
        except Exception as e:
            logger.debug("clara-link memory sync: %s", type(e).__name__)
        time.sleep(5)


def _share_workspace():
    """Hermes writes files owner-only (0600). Keep Clara's workspace readable by her group so the user's Library can show it."""
    import stat
    ws = Path(os.environ.get("HOME", "/var/lib/clara")) / "workspace"
    while True:
        try:
            for p in ws.rglob("*"):
                if p.name == "__pycache__" or "__pycache__" in p.parts:
                    continue
                m = p.stat().st_mode
                want = m | stat.S_IRGRP | (stat.S_IXGRP if p.is_dir() else 0)
                if want != m:
                    p.chmod(want)
        except Exception as e:
            logger.debug("clara-link share: %s", type(e).__name__)
        time.sleep(5)


def register(ctx) -> None:
    threading.Thread(target=_watch, name="clara-link-cron", daemon=True).start()
    threading.Thread(target=_memory_sync, name="clara-link-memory", daemon=True).start()
    threading.Thread(target=_share_workspace, name="clara-link-share", daemon=True).start()
