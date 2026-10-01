"""clara-guardian: escalate risky tool calls to the human approval gate, block self-tampering,
and pause Clara completely while the user has taken over her browser from the phone."""
import logging
import os
import time
from typing import Any, Dict, Optional
from . import rules

logger = logging.getLogger(__name__)

STATE = rules.STATE
TAKEOVER = os.path.join(STATE, "takeover")    # exists while the user is driving the browser
HANDBACK = os.path.join(STATE, "handback")    # touched when the user hands control back
MAX_TAKEOVER_WAIT = 30 * 60
_seen_handback = 0.0


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _wait_for_handback():
    """Hold every tool call while the user is in control. Returns True if we waited."""
    if not os.path.exists(TAKEOVER):
        return False
    logger.info("guardian: user has taken over the browser; pausing Clara")
    deadline = time.time() + MAX_TAKEOVER_WAIT
    while os.path.exists(TAKEOVER) and time.time() < deadline:
        time.sleep(0.5)
    return True


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[Dict[str, str]]:
    global _seen_handback
    _wait_for_handback()
    if tool_name.startswith("browser"):
        hb = _mtime(HANDBACK)
        if hb > _seen_handback:
            _seen_handback = hb
            if time.time() - hb < 3600:
                return {"action": "block", "message": (
                    "The user just took over your browser from their phone and has now handed it back. "
                    "The page may have changed (they may have logged in, solved a CAPTCHA, or navigated). "
                    "Take a fresh browser_snapshot and look at the current page before doing anything else.")}
    try:
        verdict = rules.decide(tool_name, args if isinstance(args, dict) else {})
    except Exception:
        logger.exception("guardian rule error; failing closed")
        return {"action": "approve", "message": f"Guardian could not check this {tool_name} call; asking you to be safe."}
    if not verdict:
        return None
    action, message = verdict
    logger.info("guardian %s %s: %s", action, tool_name, message)
    if action == "approve" and _is_helper_context():
        return _ask_phone(tool_name, args if isinstance(args, dict) else {}, message)
    return {"action": action, "message": message}


def _is_helper_context() -> bool:
    """True inside a delegate_task sub-agent: no phone session is bound, so Hermes's own gate would
    silently deny. Cron jobs keep Hermes's cron rules."""
    try:
        from tools import approval
        if os.environ.get("HERMES_CRON_SESSION"):
            return False
        return not approval._is_gateway_approval_context()
    except Exception:
        return False


def _ask_phone(tool_name, args, message):
    """Put the approval card on the user's phone via the Bridge and wait for their answer."""
    import json
    import urllib.request
    cmd = str(args.get("command") or args.get("path") or args.get("code") or "")[:500]
    body = json.dumps({"description": message, "command": cmd, "rule": f"{tool_name}:{message.split(':')[0]}"}).encode()
    req = urllib.request.Request(os.environ.get("CLARA_BRIDGE_URL", "http://127.0.0.1:8700") + "/internal/approvals/ask",
                                 data=body, method="POST", headers={"Content-Type": "application/json",
                                 "Authorization": "Bearer " + os.environ.get("CLARA_LINK_TOKEN", "")})
    try:
        with urllib.request.urlopen(req, timeout=1900) as r:
            choice = json.loads(r.read()).get("choice")
    except Exception as e:
        logger.warning("guardian: couldn't reach the phone for a helper approval: %s", e)
        choice = None
    logger.info("guardian helper approval %s: %s", tool_name, choice)
    if choice in ("once", "session"):
        return None
    reason = "The user declined this on their phone." if choice == "deny" else "The user didn't answer the approval on their phone."
    return {"action": "block", "message": f"{reason} Don't retry it; find another way or report back that it needs their OK."}


def register(ctx) -> None:
    global _seen_handback
    _seen_handback = _mtime(HANDBACK)   # don't replay an old handback after a restart
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
