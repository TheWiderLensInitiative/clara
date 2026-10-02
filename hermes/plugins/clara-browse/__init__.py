"""clara-browse: Clara drives her own browser the way Grok Bot and Antigravity do.

One persistent Chrome profile (logins survive from task to task). A tight loop looks at a
labeled screenshot of the viewport plus the short list of controls, then does exactly one
thing: click, type, scroll, sign in, or hand the page back to the user. The chat model
never clicks from a giant text dump, and it never types a password.

The phone already watches this browser (the stream on port 9223) and can take over.
"""
import base64
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
TAKEOVER = "/srv/clara-state/takeover"
STREAM_PORT = os.environ.get("AGENT_BROWSER_STREAM_PORT", "9223")
MAX_STEPS = 16
_lock = threading.Lock()

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
        "max_tokens": 300, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False}, "id_slot": 1,
    }).encode()
    req = urllib.request.Request(LLM, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def _ok(label, url) -> bool:
    try:
        choice = _link("/internal/approvals/ask", {
            "description": f"Clara wants to {label.strip()[:180]} on {url or 'the current page'}",
            "command": url or "",
            "rule": "browser:commit",
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
    _browser(task_id, "stream", ["enable", "--port", str(STREAM_PORT)], timeout=10)
    status = _browser(task_id, "stream", ["status"], timeout=10)
    port = ((status or {}).get("data") or {}).get("port")
    return str(port or STREAM_PORT)


def _send_tap(x: float, y: float, port: str):
    """Hand the gesture to the stream, which forwards each event without waiting for Chrome.

    The click command cannot do this: it waits for the press to finish before sending the release,
    and a slider's press does not finish until that release arrives.
    """
    from websockets.sync.client import connect
    with connect(f"ws://127.0.0.1:{port}", open_timeout=2, close_timeout=1, max_size=8_000_000) as ws:
        for event in actions.tap_events(x, y):
            ws.send(json.dumps(event))


def _tap_point(task_id, x, y):
    try:
        x, y = float(x), float(y)
        _send_tap(x, y, _stream_port(task_id))
        return {"success": True}
    except Exception as e:
        logger.info("browser_use: stream tap failed: %s", e)
        return None


def _tap_ref(task_id, ref):
    box = _browser(task_id, "get", ["box", ref], timeout=10)
    center = actions.box_center((box or {}).get("data") or {})
    if center and _tap_point(task_id, *center):
        return {"success": True, "data": {"clicked": ref}}
    logger.info("browser_use: tap missed %s; falling back to click", ref)
    return _browser(task_id, "click", [ref])


def _tap_text(task_id, text):
    """Click visible text without the waiting click command. Falls back to that command if the text has no box."""
    script = (
        "(() => {"
        f"const want = {json.dumps((text or '').strip().lower())};"
        "if (!want) return null;"
        "const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();"
        "const nodes = document.querySelectorAll('a,button,summary,label,[role],input,textarea,select');"
        "for (const el of nodes) {"
        "  const name = norm(el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '');"
        "  if (!name.includes(want)) continue;"
        "  const r = el.getBoundingClientRect();"
        "  if (r.width < 1 || r.height < 1) continue;"
        "  return {x: r.x + r.width / 2, y: r.y + r.height / 2};"
        "}"
        "return null;"
        "})()"
    )
    found = _browser(task_id, "eval", [script], timeout=15)
    point = ((found or {}).get("data") or {}).get("result")
    if isinstance(point, str):
        try:
            point = json.loads(point)
        except Exception:
            point = None
    if isinstance(point, dict) and _tap_point(task_id, point.get("x"), point.get("y")):
        return {"success": True, "data": {"clicked": text}}
    return _browser(task_id, "find", ["text", text, "click"])


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
        return _tap_ref(task_id, action["ref"])
    if kind == "fill":
        return _browser(task_id, "fill", [action["ref"], action["text"]])
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


def _prepare(task_id):
    _browser(task_id, "set", ["viewport", "1280", "800"], timeout=20)
    _browser(task_id, "stream", ["enable", "--port", STREAM_PORT], timeout=15)


def handle_browser_use(args, task_id=None, session_id=None, **_):
    goal = str((args or {}).get("goal") or "").strip()
    if not goal:
        return json.dumps({"success": False, "error": "Tell browser_use what to accomplish."})
    if not _lock.acquire(blocking=False):
        return json.dumps({"success": False, "error": "Clara's browser is already in the middle of a task. Wait until it finishes."})
    try:
        return json.dumps(_drive(goal, str((args or {}).get("url") or "").strip(), task_id or "default", session_id))
    finally:
        _lock.release()


def _drive(goal, start_url, task_id, session_id):
    _pin_session()
    logins = _logins()
    history = []
    repeated = None
    repeat_count = 0
    try:
        _prepare(task_id)
    except Exception as e:
        logger.info("browser_use: prepare failed: %s", e)
    if start_url:
        why = actions.blocked_url_reason(start_url) or ("That address is on the local network." if _resolves_local(start_url) else None)
        if why:
            return {"success": False, "error": why}
        opened = _do(task_id, {"action": "open", "url": start_url})
        if not (opened or {}).get("success", True) and opened.get("error"):
            return {"success": False, "error": str(opened.get("error"))[:300]}
        time.sleep(0.8)

    for _ in range(MAX_STEPS):
        _wait_if_taken_over()
        snap_result = _browser(task_id, "snapshot", ["-i", "-c"])
        snapshot = _snapshot_text(snap_result)
        url = _page_url(task_id)
        if actions.signin_blocked(snapshot):
            return {"success": False, "url": url,
                    "summary": "This site blocks signing in from an automated browser. It has to be done in the user's own browser, or through a connected service (Clara menu → Connectors) if there is one."}
        if actions.looks_like_human_check(snapshot):
            outcome = _help("There's a CAPTCHA or 'are you human' check on the page. Please solve it, then hand the browser back.", session_id)
            if not outcome.get("success"):
                return {"success": False, "url": url, "summary": outcome.get("error") or "The user didn't take over for the human check.", "steps": history[-12:]}
            history.append("user solved a human check and handed the browser back")
            time.sleep(0.6)
            continue
        image = _shot(task_id)
        try:
            reply = _ask(goal, url, snapshot, image, "\n".join(history[-8:]), logins)
            action = actions.parse_action(reply)
        except Exception as e:
            logger.info("browser_use: could not read a step (%s)", e)
            history.append("the last reply was not a usable step; try a different action")
            if history[-3:].count(history[-1]) >= 2:
                return {"success": False, "url": url, "summary": "I couldn't decide the next click. Here's where I got to: " + url}
            continue

        if action["action"] == "done":
            return {"success": True, "url": url or _page_url(task_id), "summary": action.get("summary") or "Done.", "steps": history[-12:]}
        if action["action"] == "help":
            outcome = _help(action["reason"], session_id)
            if not outcome.get("success"):
                return {"success": False, "url": url, "summary": outcome.get("error") or "The user didn't take over.", "steps": history[-12:]}
            history.append("user took over and handed the browser back")
            continue

        if actions.same_step(action, repeated or {}):
            repeat_count += 1
        else:
            repeated, repeat_count = action, 1
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
        if label and not _ok(label, url):
            history.append(f"the user did not approve: {label[:80]}")
            continue
        if action["action"] == "sign_in":
            outcome = _sign_in(action["name"], task_id, session_id)
            history.append(f"sign_in {action['name']}: " + ("ok" if outcome.get("success") else str(outcome.get("error"))[:160]))
            time.sleep(0.8)
            continue

        result = _do(task_id, action)
        detail = action["action"]
        if action.get("ref"):
            detail += " " + action["ref"]
        elif action.get("text"):
            detail += " " + action["text"][:60]
        elif action.get("url"):
            detail += " " + action["url"][:80]
        if not (result or {}).get("success", True):
            detail += " failed: " + str((result or {}).get("error") or "")[:120]
        history.append(detail)
        logger.info("browser_use: %s", detail[:200])
        time.sleep(0.4 if action["action"] == "scroll" else 0.8)

    return {"success": False, "url": _page_url(task_id),
            "summary": "I used the browser for a while and didn't finish. " + (history[-1] if history else ""),
            "steps": history[-12:]}


def register(ctx) -> None:
    _pin_session()
    from tools.browser_tool import check_browser_requirements
    ctx.register_tool(name="browser_use", toolset="clara_browse", schema=SCHEMA, handler=handle_browser_use,
                      check_fn=check_browser_requirements, emoji="🌐")
