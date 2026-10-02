"""clara-browse: Clara drives her own browser the way Grok Bot and Antigravity do.

One persistent Chrome profile (logins survive from task to task). A tight loop looks at a
labeled screenshot of the viewport plus the short list of controls, then does exactly one
thing: click, type, scroll, sign in, or hand the page back to the user. The chat model
never clicks from a giant text dump, and it never types a password.

The phone already watches this browser (the stream on port 9223) and can take over.
"""
import base64
import fcntl
from contextlib import contextmanager
import json
import logging
import os
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlparse

from . import actions

logger = logging.getLogger(__name__)

BRIDGE = os.environ.get("CLARA_BRIDGE_URL", "http://127.0.0.1:8700")
LLM = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/") + "/chat/completions"
STATE_DIR = os.environ.get("CLARA_STATE_DIR", "/srv/clara-state")
TAKEOVER = os.path.join(STATE_DIR, "takeover")
CONTROL_LOCK = os.path.join(STATE_DIR, "browser-control.lock")
HANDBACK = os.path.join(STATE_DIR, "handback")
STREAM_PORT = os.environ.get("AGENT_BROWSER_STREAM_PORT", "9223")
MAX_STEPS = 16
_lock = threading.Lock()
_tap_connection = None
_cached_port = None

EYES = (
    "You are Clara's hands on her browser. You can see a screenshot of the page. Numbered labels [N] on it "
    "are the controls; label N is ref @eN. Do the single next step toward the goal. Reply with one JSON object "
    "and nothing else.\n"
    'open a page: {"action":"open","url":"https://..."}\n'
    'click a labeled control: {"action":"click","ref":"@e3"}\n'
    'replace the text in a field: {"action":"fill","ref":"@e2","text":"..."}\n'
    'press a key: {"action":"press","key":"Enter"}\n'
    'scroll: {"action":"scroll","direction":"down"}\n'
    'click visible text that has no label: {"action":"find","text":"Sign in"}\n'
    '{"action":"back"} or {"action":"wait"}\n'
    'use a saved login (never type the password): {"action":"sign_in","name":"GitHub"}\n'
    'hand the page to the user (CAPTCHA, 2FA, a code, a payment only they can do): {"action":"help","reason":"..."}\n'
    'the goal is finished: {"action":"done","summary":"what you found or did"}\n'
    "Click the label you can see. Dismiss a cookie banner in one click and move on. "
    "Never type a password, a one-time code, or a card number. "
    "If a step you just took did nothing, do something different. When the goal is met, done."
)

SCHEMA = {
    "name": "browser_use",
    "description": (
        "Drive Clara's browser the way a person would. She looks at the page, then clicks, types, or scrolls, "
        "one step at a time, until the goal is done. Use this for any website task: searching a site, filling a form, "
        "checking a page, comparing products. Pass the whole goal in one call, including what done looks like, and a "
        "starting URL when you know one. Her browser is persistent, so a site she signed into before is still signed in. "
        "Saved logins go through the user's phone; she never sees the password. A CAPTCHA or two-factor code is handed "
        "to the user on their phone. Buying, sending, and deleting ask the user first. Prefer a connected service "
        "(email_*, calendar_*, connection_call, youtube_upload) over the browser when the task is one of those accounts. "
        "For a quick fact from a public page, prefer web_search or web_extract. "
        "Returns a short summary and the final URL. Tell the user the result in your own words."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "What to accomplish, and how you'll know it's done."},
            "url": {"type": "string", "description": "Optional page to open first, e.g. https://example.com"},
        },
        "required": ["goal"],
    },
}


def _conversation(session_id):
    from hermes_plugins.clara_guardian import session_owner
    return session_owner(session_id)[0]


def _link(path, body=None, timeout=30):
    req = urllib.request.Request(
        BRIDGE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + os.environ.get("CLARA_LINK_TOKEN", ""), "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _pin_session():
    """Every task shares one Chrome, named clara, so cookies and the phone's live view stay put."""
    import tools.browser_tool as bt
    if getattr(bt, "_clara_pinned", False):
        return
    original = bt._create_local_session

    def pinned(task_id):
        info = original(task_id)
        info["session_name"] = "clara"
        return info

    bt._create_local_session = pinned
    bt._clara_pinned = True


def _browser(task_id, command, args=None, timeout=45):
    from tools.browser_tool import _run_browser_command
    return _run_browser_command(task_id or "default", command, list(args or []), timeout=timeout)


def _snapshot_text(result) -> str:
    data = (result or {}).get("data") or {}
    text = data.get("snapshot") or data.get("output") or ""
    if not text and not (result or {}).get("success", True):
        text = str((result or {}).get("error") or "")
    return str(text)[:5000]


def _page_url(task_id) -> str:
    try:
        data = (_browser(task_id, "get", ["url"], timeout=10).get("data") or {})
        return str(data.get("url") or data.get("result") or "")[:500]
    except Exception:
        return ""


def _shot(task_id):
    """A labeled viewport screenshot as a data URL, or None. Labels [N] match refs @eN."""
    path = os.path.join(tempfile.gettempdir(), f"clara-browse-{os.getpid()}.jpg")
    try:
        result = _browser(task_id, "screenshot", [
            "--annotate", "--screenshot-format", "jpeg", "--screenshot-quality", "55", path,
        ], timeout=25)
        if not os.path.isfile(path) or os.path.getsize(path) < 100:
            logger.info("browser_use: no screenshot (%s)", str((result or {}).get("error"))[:160])
            return None
        from PIL import Image
        with Image.open(path) as img:
            img.thumbnail((1280, 1280))
            img.convert("RGB").save(path, "JPEG", quality=55)
        with open(path, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    except Exception as e:
        logger.info("browser_use: screenshot failed: %s", e)
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _resolves_local(url: str) -> bool:
    import ipaddress
    import socket
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "")
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_loopback or ip.is_private or ip.is_link_local:
            return True
    return False


def _wait_if_taken_over():
    if not os.path.exists(TAKEOVER):
        return
    logger.info("browser_use: user has the browser; waiting")
    deadline = time.time() + 30 * 60
    while os.path.exists(TAKEOVER) and time.time() < deadline:
        time.sleep(0.5)
    if os.path.exists(TAKEOVER):
        raise RuntimeError("The user still controls the browser. Automation stopped.")


class ControlChanged(RuntimeError):
    pass


def _generation():
    try:
        return os.stat(HANDBACK).st_mtime_ns
    except OSError:
        return 0


@contextmanager
def action_guard(generation=None):
    # Bridge and plugins share this lock. A takeover is acknowledged only after the
    # current action finishes; no new action can start after the flag is written.
    with open(CONTROL_LOCK, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            from tools.interrupt import is_interrupted
            if is_interrupted():
                raise RuntimeError("Browser task stopped")
            if os.path.exists(TAKEOVER) or (generation is not None and generation != _generation()):
                raise ControlChanged("Browser ownership changed; observe again after handback.")
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _safe_page(task_id):
    url = _page_url(task_id)
    if not url:
        raise RuntimeError("Unable to verify the current browser address")
    if url != "about:blank":
        reason = actions.blocked_url_reason(url)
        if reason or _resolves_local(url):
            raise RuntimeError(reason or "The browser reached a local-network address; automation stopped.")
    return url


def _progress(task_id, snapshot, url):
    try:
        result = _browser(task_id, "eval", ["JSON.stringify([scrollX,scrollY,document.body?.scrollHeight,document.body?.innerText?.slice(0,8000)])"], timeout=5)
        page = (result.get("data") or {}).get("result")
    except Exception:
        page = None
    return (url, snapshot, str(page))


def _logins():
    try:
        rows = _link("/internal/vault/index").get("logins") or []
    except Exception:
        return []
    return [f"{r.get('name')} ({r.get('site')})" for r in rows if r.get("name")]


def _ask(goal, url, snapshot, image, history, logins):
    user = (
        f"Goal: {goal}\nURL: {url or '(nothing open yet)'}\n"
        f"Saved logins (name and site only): {', '.join(logins) or 'none'}\n"
        f"Steps already taken:\n{history or '(none)'}\n\n"
        f"Controls on the page:\n{snapshot or '(no snapshot)'}"
    )
    content = [{"type": "text", "text": user}]
    if image:
        content.insert(0, {"type": "image_url", "image_url": {"url": image}})
    # Slot 1, thinking off: the agent's prompt stays cached in slot 0, and the page never leaves this PC.
    body = json.dumps({
        "messages": [
            {"role": "system", "content": EYES},
            {"role": "user", "content": content},
        ],
        "max_tokens": 4096, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False}, "id_slot": 1,
    }).encode()
    req = urllib.request.Request(LLM, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def _ok(label, url, session_id=None, action=None, snapshot="") -> bool:
    try:
        choice = _link("/internal/approvals/ask", {
            "description": f"Clara wants to {label.strip()[:180]} on {url or 'the current page'}",
            "command": json.dumps({"url": url, "action": action, "page": snapshot}, ensure_ascii=False),
            "allow_session": False,
            "rule": "browser:commit",
            "conversation_id": _conversation(session_id),
        }, timeout=1900).get("choice")
    except Exception as e:
        logger.warning("browser_use: approval failed: %s", e)
        choice = None
    return choice in ("once", "session")


def _sign_in(name, task_id, session_id):
    import hermes_plugins.clara_vault as vault
    return json.loads(vault.handle_sign_in({"name": name}, task_id=task_id, session_id=session_id))


def _help(reason, session_id):
    import hermes_plugins.clara_guardian as guardian
    return json.loads(guardian.handle_help({"reason": reason}, session_id=session_id))


def _stream_port(task_id) -> str:
    """The live-view port. Enabling it is what makes a tap able to release the mouse immediately."""
    global _cached_port
    if _cached_port:
        return _cached_port
    _browser(task_id, "stream", ["enable", "--port", str(STREAM_PORT)], timeout=10)
    status = _browser(task_id, "stream", ["status"], timeout=10)
    port = ((status or {}).get("data") or {}).get("port")
    _cached_port = str(port or STREAM_PORT)
    return _cached_port


def _send_tap(x: float, y: float, port: str):
    """Hand the gesture to the stream, which forwards each event without waiting for Chrome.

    The click command cannot do this: it waits for the press to finish before sending the release,
    and a slider's press does not finish until that release arrives.
    """
    from websockets.sync.client import connect
    global _tap_connection
    if _tap_connection is None:
        _tap_connection = connect(f"ws://127.0.0.1:{port}/?pacing=ack&maxFps=1", open_timeout=2, close_timeout=1, max_size=8_000_000)
    try:
        for event in actions.tap_events(x, y):
            _tap_connection.send(json.dumps(event))
    except Exception:
        _tap_connection.close()
        _tap_connection = None
        raise  # Never replay an uncertain click automatically.


def _tap_point(task_id, x, y):
    try:
        x, y = float(x), float(y)
        _send_tap(x, y, _stream_port(task_id))
        return {"success": True}
    except Exception as e:
        logger.info("browser_use: stream tap failed: %s", e)
        return None


def _tap_ref(task_id, ref, expected_name=""):
    moved = _browser(task_id, "scrollintoview", [ref], timeout=10)
    if not moved.get("success", False):
        return {"success": False, "error": "Could not bring the target into view"}
    box = _browser(task_id, "get", ["box", ref], timeout=10)
    center = actions.box_center((box or {}).get("data") or {})
    if not center:
        return {"success": False, "error": "Target has no visible box"}
    x, y = center
    # Check both the bounds and the top-most accessible control under the pointer.
    script = """(() => {
      const [x,y,want] = PARAMS;
      if(x<0||y<0||x>=innerWidth||y>=innerHeight) return false;
      const el=document.elementFromPoint(x,y)?.closest('a,button,input,textarea,select,[role]');
      if(!el || el.disabled || getComputedStyle(el).visibility==='hidden') return false;
      const name=(el.getAttribute('aria-label')||Array.from(el.labels||[]).map(l=>l.innerText).join(' ')||el.innerText||el.getAttribute('placeholder')||'').trim();
      return !!want && name===want;
    })()""".replace("PARAMS", json.dumps([x,y,expected_name]))
    check = _browser(task_id, "eval", [script], timeout=10)
    if (check.get("data") or {}).get("result") not in (True, "true"):
        return {"success": False, "error": "The target is covered, ambiguous or changed. Observe again."}
    return _tap_point(task_id, x, y) or {"success": False, "error": "Pointer dispatch failed"}


def _tap_text(task_id, text):
    # Resolve an exact visible name to a fresh ref. Never choose the first substring match.
    snapshot = _snapshot_text(_browser(task_id, "snapshot", ["-i", "-c"]))
    import re
    matches = []
    for line in snapshot.splitlines():
        name = re.search(r'"([^"\n]*)"', line)
        ref = re.search(r'(?:ref=|@)(e\d+)', line)
        if name and ref and name.group(1).casefold() == text.strip().casefold():
            matches.append((ref.group(1), name.group(1)))
    if len(matches) != 1:
        return {"success": False, "error": "Text does not identify exactly one control; use a current ref."}
    return _tap_ref(task_id, *matches[0])


def _do(task_id, action):
    kind = action["action"]
    if kind == "open":
        from tools.browser_tool import browser_navigate
        raw = browser_navigate(action["url"], task_id=task_id)
        try:
            return json.loads(raw)
        except Exception:
            return {"success": False, "error": str(raw)[:300]}
    if kind == "click":
        return _tap_ref(task_id, action["ref"], action.get("_name", ""))
    if kind == "fill":
        for attribute in ("type", "autocomplete"):
            result = _browser(task_id, "get", ["attr", action["ref"], attribute])
            if not result.get("success", False):
                return {"success": False, "error": "Unable to verify the input field type"}
            data = result.get("data") or {}
            value = str(data.get("value") or data.get("attribute") or data.get("result") or "").lower()
            if any(word in value for word in ("password", "one-time-code", "cc-")):
                return {"success": False, "error": "Sensitive fields require vault sign-in or human takeover"}
        result = _browser(task_id, "fill", [action["ref"], action["text"]])
        if result.get("success"):
            actual = _browser(task_id, "get", ["value", action["ref"]])
            value = (actual.get("data") or {}).get("value")
            if value != action["text"]:
                return {"success": False, "error": "The field did not retain the full intended text"}
        return result
    if kind == "press":
        return _browser(task_id, "press", [action["key"]])
    if kind == "scroll":
        return _browser(task_id, "scroll", [action["direction"], "700"])
    if kind == "find":
        return _tap_text(task_id, action["text"])
    if kind == "back":
        return _browser(task_id, "back")
    if kind == "wait":
        time.sleep(1.2)
        return {"success": True}
    return {"success": False, "error": "nothing to do"}


def _ready(task_id):
    started = time.monotonic()
    result = _browser(task_id, "wait", ["--load", "domcontentloaded"], timeout=10)
    logger.info("browser phase=readiness elapsed_ms=%.0f success=%s",
                (time.monotonic()-started)*1000, bool(result.get("success")))
    return bool(result.get("success"))


def _prepare(task_id):
    _browser(task_id, "set", ["viewport", "1280", "800"], timeout=20)
    _browser(task_id, "stream", ["enable", "--port", STREAM_PORT], timeout=15)


def handle_browser_use(args, task_id=None, session_id=None, **_):
    global _tap_connection, _cached_port
    goal = str((args or {}).get("goal") or "").strip()
    if not goal:
        return json.dumps({"success": False, "error": "Tell browser_use what to accomplish."})
    if not _lock.acquire(blocking=False):
        return json.dumps({"success": False, "error": "Clara's browser is already in the middle of a task. Wait until it finishes."})
    try:
        return json.dumps(_drive(goal, str((args or {}).get("url") or "").strip(), task_id or "default", session_id))
    except (OSError, RuntimeError) as error:
        return json.dumps({"success": False, "error": str(error)[:300]})
    finally:
        if _tap_connection:
            _tap_connection.close()
        _tap_connection = None
        _cached_port = None
        _lock.release()


def _drive(goal, start_url, task_id, session_id):
    _pin_session()
    logins = _logins()
    history = []
    repeated = None
    repeat_count = 0
    previous_progress = None
    _wait_if_taken_over()
    with action_guard():
        _prepare(task_id)
    if start_url:
        why = actions.blocked_url_reason(start_url) or ("That address is on the local network." if _resolves_local(start_url) else None)
        if why:
            return {"success": False, "error": why}
        with action_guard():
            opened = _do(task_id, {"action": "open", "url": start_url})
            _safe_page(task_id)
        if not (opened or {}).get("success", True) and opened.get("error"):
            return {"success": False, "error": str(opened.get("error"))[:300]}
        _ready(task_id)

    for _ in range(MAX_STEPS):
        from tools.interrupt import is_interrupted
        if is_interrupted():
            return {"success": False, "summary": "Browser task stopped.", "steps": history[-12:]}
        _wait_if_taken_over()
        generation = _generation()
        url = _safe_page(task_id)
        snap_result = _browser(task_id, "snapshot", ["-i", "-c"])
        snapshot = _snapshot_text(snap_result)
        progress = _progress(task_id, snapshot, url)
        if actions.signin_blocked(snapshot):
            return {"success": False, "url": url,
                    "summary": "This site blocks signing in from an automated browser. It has to be done in the user's own browser, or through a connected service (Clara menu → Connectors) if there is one."}
        if actions.looks_like_human_check(snapshot):
            outcome = _help("There's a CAPTCHA or 'are you human' check on the page. Please solve it, then hand the browser back.", session_id)
            if not outcome.get("success"):
                return {"success": False, "url": url, "summary": outcome.get("error") or "The user didn't take over for the human check.", "steps": history[-12:]}
            history.append("user solved a human check and handed the browser back")
            _ready(task_id)
            continue
        observed = time.monotonic()
        image = _shot(task_id)
        logger.info("browser phase=screenshot elapsed_ms=%.0f", (time.monotonic()-observed)*1000)
        if generation != _generation() or _safe_page(task_id) != url:
            history.append("page changed during observation; looking again")
            continue
        try:
            decided = time.monotonic()
            reply = _ask(goal, url, snapshot, image, "\n".join(history[-8:]), logins)
            logger.info("browser phase=model elapsed_ms=%.0f", (time.monotonic()-decided)*1000)
            action = actions.parse_action(reply)
        except Exception as e:
            logger.info("browser_use: could not read a step (%s)", e)
            history.append("the last reply was not a usable step; try a different action")
            if history[-3:].count(history[-1]) >= 2:
                return {"success": False, "url": url, "summary": "I couldn't decide the next click. Here's where I got to: " + url}
            continue

        if action["action"] == "done":
            return {"success": True, "url": _safe_page(task_id), "summary": action.get("summary") or "Done.", "steps": history[-12:]}
        if action["action"] == "help":
            outcome = _help(action["reason"], session_id)
            if not outcome.get("success"):
                return {"success": False, "url": url, "summary": outcome.get("error") or "The user didn't take over.", "steps": history[-12:]}
            history.append("user took over and handed the browser back")
            continue

        if actions.same_step(action, repeated or {}) and progress == previous_progress:
            repeat_count += 1
        else:
            repeated, repeat_count = action, 1
        previous_progress = progress
        if repeat_count >= 3:
            return {"success": False, "url": url,
                    "summary": f"I kept repeating the same step and stopped. Last page: {url}. Steps: {'; '.join(history[-6:])}",
                    "steps": history[-12:]}

        why = actions.veto(action, snapshot)
        if why:
            history.append(f"blocked ({action['action']}): {why}")
            continue
        if action["action"] == "open" and _resolves_local(action["url"]):
            history.append("blocked (open): that address is on the local network")
            continue
        label = actions.commit_label(action, snapshot)
        if label and not _ok(label, url, session_id, action, snapshot):
            history.append(f"the user did not approve: {label[:80]}")
            continue
        if action["action"] == "sign_in":
            outcome = _sign_in(action["name"], task_id, session_id)
            history.append(f"sign_in {action['name']}: " + ("ok" if outcome.get("success") else str(outcome.get("error"))[:160]))
            _ready(task_id)
            continue

        import re
        name = re.search(r'"([^"\n]*)"', actions._line(snapshot, action.get("ref", "")))
        if name:
            action = {**action, "_name": name.group(1)}
        try:
            with action_guard(generation):
                if _safe_page(task_id) != url:
                    raise ControlChanged("The page changed during the decision. Observe again.")
                if action.get("ref") or label:
                    current = _snapshot_text(_browser(task_id, "snapshot", ["-i", "-c"]))
                    if label and current != snapshot:
                        raise ControlChanged("The page changed after approval. Observe and ask again.")
                    if action.get("ref") and actions._line(current, action["ref"]) != actions._line(snapshot, action["ref"]):
                        raise ControlChanged("The control changed during the decision. Observe again.")
                started = time.monotonic()
                result = _do(task_id, action)
                _safe_page(task_id)
                logger.info("browser action=%s elapsed_ms=%.0f", action["action"], (time.monotonic()-started)*1000)
        except ControlChanged:
            history.append("page or control changed; taking a fresh observation")
            continue
        detail = action["action"]
        if action.get("ref"):
            detail += " " + action["ref"]
        elif action.get("text"):
            detail += f" ({len(action['text'])} characters)"
        elif action.get("url"):
            detail += " " + action["url"][:80]
        if not (result or {}).get("success", True):
            detail += " failed: " + str((result or {}).get("error") or "")[:120]
        history.append(detail)
        logger.info("browser_use: %s", detail[:200])
        if action["action"] not in ("scroll", "wait"):
            _ready(task_id)

    return {"success": False, "url": _page_url(task_id),
            "summary": "I used the browser for a while and didn't finish. " + (history[-1] if history else ""),
            "steps": history[-12:]}


def register(ctx) -> None:
    _pin_session()
    from tools.browser_tool import check_browser_requirements
    ctx.register_tool(name="browser_use", toolset="clara_browse", schema=SCHEMA, handler=handle_browser_use,
                      check_fn=check_browser_requirements, emoji="🌐")
