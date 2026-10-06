"""clara-guardian: escalate risky tool calls to the human approval gate, block self-tampering,
and pause Clara completely while the user has taken over her browser from the phone."""
import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional
from . import rules

logger = logging.getLogger(__name__)

STATE = rules.STATE
TAKEOVER = os.path.join(STATE, "takeover")    # exists while the user is driving the browser
HANDBACK = os.path.join(STATE, "handback")    # touched when the user hands control back
_seen_handback = 0.0


# Hermes supplies these IDs through lifecycle hooks, never tool arguments or page content.
_session_owners = {}


def session_owner(session_id=None):
    return _session_owners.get(session_id, (session_id, None))


STOPPED = object()


def patient(call):
    """Run a Bridge call that waits on the user's phone, for as long as they need: people miss notifications.
    Returns STOPPED as soon as the user stops the task. Meanwhile it tells Hermes the run is still alive,
    so its idle timeout doesn't end a task that is only waiting for an answer."""
    import threading
    box = {}

    def run():
        try:
            box["value"] = call()
        except BaseException as e:
            box["error"] = e

    worker = threading.Thread(target=run, daemon=True, name="clara-wait-for-phone")
    worker.start()
    if not hold_while(worker.is_alive, "waiting for the user's answer on their phone", step=worker.join):
        return STOPPED   # the Bridge's Stop also ends its side of the wait
    if "error" in box:
        raise box["error"]
    return box["value"]


def hold_while(waiting, label, step=None):
    """Pause while waiting() is true, keeping the Hermes run alive. False if the user stopped the task."""
    try:
        from tools.interrupt import is_interrupted
    except Exception:
        is_interrupted = lambda: False
    try:
        from tools.environments.base import touch_activity_if_due
    except Exception:
        touch_activity_if_due = None
    state = {"last_touch": time.monotonic(), "start": time.monotonic()}
    while waiting():
        if is_interrupted():
            return False
        (step or time.sleep)(0.5)
        if touch_activity_if_due is not None:
            touch_activity_if_due(state, label)
    return True


def _on_subagent_start(parent_session_id=None, child_session_id=None, **_):
    if not child_session_id or not parent_session_id:
        return
    cid, run_id = session_owner(parent_session_id)
    if not run_id:
        try:
            from tools.approval import get_current_session_key
            run_id = get_current_session_key(default="") or None
        except ImportError:
            pass
    _session_owners[child_session_id] = (cid, run_id)


def _on_subagent_stop(child_session_id=None, **_):
    _session_owners.pop(child_session_id, None)


def _cloud_request(request, base_url="", session_id=None, **_):
    bridge = os.environ.get("CLARA_BRIDGE_URL", "http://127.0.0.1:8700").rstrip("/")
    if base_url.rstrip("/") != bridge + "/cloud/v1":
        return None
    cid, run_id = session_owner(session_id)
    if not cid:
        return None
    headers = dict(request.get("extra_headers") or {})
    headers["x-clara-conversation-id"] = cid
    if run_id:
        headers["x-clara-run-id"] = run_id
    return {"request": {**request, "extra_headers": headers}}


# Hermes's own browser tools that Guardian always refuses (everything goes through browser_use). Leaving their
# descriptions in every request costs prompt space and invites wasted turns (she tried browser_click/navigate),
# so they're removed before the model sees them. Guardian still blocks them if one is called anyway.
VISIBLE_BROWSER_TOOLS = {"browser_use", "browser_snapshot", "browser_vision"}


def hidden_tool(name: str) -> bool:
    return name.startswith("browser") and name not in VISIBLE_BROWSER_TOOLS


def _hide_blocked_tools(request, **_):
    tools = request.get("tools")
    if not isinstance(tools, list):
        return None
    kept = [t for t in tools if not hidden_tool(str(((t or {}).get("function") or {}).get("name") or (t or {}).get("name") or ""))]
    if len(kept) == len(tools):
        return None
    return {"request": {**request, "tools": kept}}


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
    # No time limit: the user hands back when they're done (a phone that disconnects hands back by itself).
    if not hold_while(lambda: os.path.exists(TAKEOVER), "paused while the user controls the browser"):
        raise TimeoutError("The user stopped this task")
    return True


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[Dict[str, str]]:
    global _seen_handback
    if tool_name.startswith("browser"):
        _point_at_real_chrome()
    try:
        _wait_for_handback()
    except TimeoutError:
        return {"action": "block", "message": "The user stopped this task."}
    # After the user hands the browser back, the page may have changed. A snapshot is allowed
    # through (it's how she looks); every other browser action waits until she has looked.
    if tool_name.startswith("browser"):
        hb = _mtime(HANDBACK)
        fresh = hb > _seen_handback and time.time() - hb < 3600
        if fresh and tool_name in ("browser_snapshot", "browser_vision", "browser_use"):
            _seen_handback = hb
        elif fresh:
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
        return _ask_phone(tool_name, args if isinstance(args, dict) else {}, message, _.get("session_id"))
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


def _ask_phone(tool_name, args, message, session_id=None):
    """Put the approval card on the user's phone via the Bridge and wait for their answer."""
    import json
    import urllib.request
    session_id, run_id = session_owner(session_id)
    cmd = json.dumps(args, ensure_ascii=False)
    if len(cmd) > 100000:
        return {"action": "block", "message": "This operation is too large to preview for approval. Split it into smaller steps."}
    body = json.dumps({"description": message, "command": cmd, "conversation_id": session_id, "run_id": run_id, "rule": f"{tool_name}:{message.split(':')[0]}"}).encode()
    req = urllib.request.Request(os.environ.get("CLARA_BRIDGE_URL", "http://127.0.0.1:8700") + "/internal/approvals/ask",
                                 data=body, method="POST", headers={"Content-Type": "application/json",
                                 "Authorization": "Bearer " + os.environ.get("CLARA_LINK_TOKEN", "")})
    def ask():
        with urllib.request.urlopen(req, timeout=None) as r:   # no limit: Clara waits until the user answers
            return json.loads(r.read()).get("choice")
    try:
        choice = patient(ask)
    except Exception as e:
        logger.warning("guardian: couldn't reach the phone for a helper approval: %s", e)
        choice = None
    if choice is STOPPED:
        return {"action": "block", "message": "The user stopped this task."}
    logger.info("guardian helper approval %s: %s", tool_name, choice)
    if choice in ("once", "session"):
        return None
    reason = "The user declined this on their phone." if choice == "deny" else "Clara couldn't reach the user's phone for this approval."
    return {"action": "block", "message": f"{reason} Don't retry it; find another way or report back that it needs their OK."}


HELP_SCHEMA = {
    "name": "ask_user_for_browser_help",
    "description": (
        "Ask the user to take over your browser from their phone when you're stuck on something only a person should do: a CAPTCHA "
        "or 'are you human' check, a two-factor or SMS code, a sign-in your saved logins can't complete, a payment or consent step, "
        "or a page you can't get past after trying. Their phone gets a notification; they take over, fix it, and hand it back. "
        "This waits as long as they need until they're done, then tells you. Afterwards take a fresh browser_snapshot: the page has "
        "probably changed. Don't use it for things you can do yourself, and never ask them for a password in chat."),
    "parameters": {"type": "object", "properties": {
        "reason": {"type": "string", "description": "What you need them to do, short and specific, e.g. 'There's a CAPTCHA on the Amazon sign-in page'."},
    }, "required": ["reason"]},
}


def handle_help(args, session_id=None, **_):
    """Ask the phone for help via the Bridge, which waits until the user has taken over and handed back."""
    global _seen_handback
    import json
    import urllib.request
    reason = str((args or {}).get("reason", "")).strip()[:300] or "I'm stuck in the browser and need you for a moment."
    body = json.dumps({"reason": reason, "conversation_id": session_owner(session_id)[0]}).encode()
    req = urllib.request.Request(os.environ.get("CLARA_BRIDGE_URL", "http://127.0.0.1:8700") + "/internal/help",
                                 data=body, method="POST", headers={"Content-Type": "application/json",
                                 "Authorization": "Bearer " + os.environ.get("CLARA_LINK_TOKEN", "")})
    def ask():
        with urllib.request.urlopen(req, timeout=None) as r:   # no limit: the user may be away from their phone
            return json.loads(r.read()).get("result")
    try:
        result = patient(ask)
    except Exception as e:
        logger.warning("guardian: couldn't ask the phone for help: %s", e)
        result = None
    if result is STOPPED or result == "stopped":
        return json.dumps({"success": False, "error": "The user stopped this task."})
    _seen_handback = _mtime(HANDBACK)   # this tool already tells Clara to look again; don't repeat it on her next step
    if result == "handed_back":
        return json.dumps({"success": True, "message": "The user took over your browser and has handed it back. Take a fresh "
                                                       "browser_snapshot to see where things are now, then continue the task."})
    if result == "busy":
        return json.dumps({"success": False, "error": "The user is already in control of your browser; wait for them."})
    return json.dumps({"success": False, "error": "Clara couldn't reach the user's phone. Stop here and tell them what you need "
                                                   "(they can take over from the Screen page later), or find another way."})


# Seen in a browser result: a human check Clara can't pass. Guardian asks the user for help itself, so it never depends
# on the model choosing to (a small local model often tries to script around it instead).
HUMAN_CHECK = re.compile(r"i'?m not a robot|recaptcha|hcaptcha|verify (that )?you are (a )?human|are you a robot|"
                         r"checking (if the site connection is secure|your browser)|security check|press (and|&) hold", re.I)
SIGNIN_BLOCKED = re.compile(r"(this )?browser or app may not be secure|couldn.?t sign you in|try using a different browser", re.I)
_auto_help_at: Dict[str, float] = {}   # session -> when Guardian last asked, so one stuck page asks only once in 10 minutes


def _on_tool_result(tool_name: str = "", result: Any = None, session_id: str = "", **_: Any):
    if not tool_name.startswith("browser") or not isinstance(result, str):
        return None
    if SIGNIN_BLOCKED.search(result):
        # Google says this to automation browsers. Clara's Chrome is a normal headed browser with a
        # saved profile, so the user signing in once from their phone usually clears it. Ask once.
        # If they already tried and the page still says it, stop instead of looping.
        key = (session_id or "") + ":signin"
        if time.time() - _auto_help_at.get(key, 0) < 900:
            return ("[Guardian] Google is still refusing sign-in in Clara's browser after you were asked to take over. "
                    "Don't retry it and don't ask again. Tell the user this sign-in has to be done in their own browser, "
                    "or through a connected service (Clara menu → Connectors) if the task has one.\n\n" + result)
        _auto_help_at[key] = time.time()
        logger.info("guardian: site rejected the automated sign-in; asking the user to sign in")
        outcome = json.loads(handle_help(
            {"reason": "Google needs you to sign in. Take over the browser, finish the sign-in, then hand it back."},
            session_id=session_id))
        note = ("[Guardian] The page refused an automatic sign-in. " + (outcome.get("message") or outcome.get("error") or "")
                + " Take a fresh browser_snapshot. If it still says the browser isn't secure, stop and tell the user.")
        return note + "\n\n" + result
    m = HUMAN_CHECK.search(result)
    if not m or os.path.exists(TAKEOVER) or time.time() - _auto_help_at.get(session_id, 0) < 600:
        return None
    _auto_help_at[session_id] = time.time()
    logger.info("guardian: human check on the page (%r); asking the user for help", m.group(0))
    outcome = json.loads(handle_help({"reason": "There's a CAPTCHA or 'are you human' check on the page. Please solve it, then hand back."},
                                     session_id=session_id))
    note = ("[Guardian] This page had a CAPTCHA / human check. " + (outcome.get("message") or outcome.get("error") or "")
            + " Don't try to get around a human check yourself.")
    return note + "\n\n" + result


def register(ctx) -> None:
    global _seen_handback
    _seen_handback = _mtime(HANDBACK)   # don't replay an old handback after a restart
    _pin_browser()
    ctx.register_hook("subagent_start", _on_subagent_start)
    ctx.register_hook("subagent_stop", _on_subagent_stop)
    ctx.register_middleware("llm_request", _cloud_request)
    ctx.register_middleware("llm_request", _hide_blocked_tools)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("transform_tool_result", _on_tool_result)
    ctx.register_tool(name="ask_user_for_browser_help", toolset="clara_guardian", schema=HELP_SCHEMA, handler=handle_help, emoji="🙋")


# Official Chrome, not Chrome for Testing. Google refuses sign-in from the testing build.
# /opt is where install.sh puts it; the hermes-home copy is used until that install has been run.
_CHROME_CANDIDATES = (
    "/opt/clara/google-chrome/opt/google/chrome/chrome",
    "/var/lib/clara/hermes-home/google-chrome/opt/google/chrome/chrome",
)
_XVFB_BIN = "/var/lib/clara/hermes-home/xvfb/usr/bin"


def _point_at_real_chrome():
    chrome = next((p for p in _CHROME_CANDIDATES if os.path.isfile(p) and os.access(p, os.X_OK)), "")
    if chrome:
        os.environ["AGENT_BROWSER_EXECUTABLE_PATH"] = chrome
    os.environ["AGENT_BROWSER_HEADED"] = "true"
    os.environ.setdefault("AGENT_BROWSER_PROFILE", "/var/lib/clara/.browser-profile")
    os.environ.setdefault("AGENT_BROWSER_RESTORE", "clara")
    # Hermes leaves AGENT_BROWSER_ARGS alone once it is set, and will not add --no-sandbox itself.
    # The service sandbox (NoNewPrivileges) makes Chrome's own sandbox fail, so it has to be here.
    # --start-fullscreen: on a virtual screen Chrome otherwise opens a smaller window than the
    # stream reports, and taps from the phone land past the real page.
    os.environ["AGENT_BROWSER_ARGS"] = (
        "--no-sandbox,--disable-dev-shm-usage,--disable-blink-features=AutomationControlled,"
        "--no-first-run,--no-default-browser-check,--start-fullscreen"
    )
    if os.path.isfile(os.path.join(_XVFB_BIN, "Xvfb")):
        path = os.environ.get("PATH", "")
        if _XVFB_BIN not in path.split(":"):
            os.environ["PATH"] = _XVFB_BIN + ":" + path


def _pin_browser():
    """One Chrome profile for every task, so a sign-in from the phone is still there next time."""
    _point_at_real_chrome()
    try:
        import tools.browser_tool as bt
    except Exception:
        return
    if getattr(bt, "_clara_pinned", False):
        return
    original = bt._create_local_session

    def pinned(task_id):
        info = original(task_id)
        info["session_name"] = "clara"
        return info

    bt._create_local_session = pinned
    bt._clara_pinned = True
