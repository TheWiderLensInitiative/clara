"""clara-browse: Clara drives her own browser the way Grok Bot and Antigravity do.

One persistent Chrome profile (logins survive from task to task). A tight loop looks at a
labeled screenshot of the viewport plus the page the way Antigravity's page reader does (the
controls with refs, the text on screen, the open tabs), then does exactly one thing: click, type,
set a slider, pick from a dropdown, scroll the page or a panel, point at an unlabeled spot on a
0-1000 grid, switch tabs, sign in, or hand the page back to the user. A second look checks the
page before a task counts as done, and the path that worked is saved as a playbook for next time
(playbooks.py). The chat model never clicks from a giant text dump, and it never types a password.

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

from . import actions, playbooks

logger = logging.getLogger(__name__)

BRIDGE = os.environ.get("CLARA_BRIDGE_URL", "http://127.0.0.1:8700")
LLM = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/") + "/chat/completions"
STATE_DIR = os.environ.get("CLARA_STATE_DIR", "/srv/clara-state")
TAKEOVER = os.path.join(STATE_DIR, "takeover")
CONTROL_LOCK = os.path.join(STATE_DIR, "browser-control.lock")
HANDBACK = os.path.join(STATE_DIR, "handback")
STREAM_PORT = os.environ.get("AGENT_BROWSER_STREAM_PORT", "9223")
MAX_STEPS = 40
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
    'set a slider to one of its settings (never click a slider): {"action":"set","ref":"@e4","value":"Anyone on the web"}\n'
    'choose from a dropdown or list: {"action":"select","ref":"@e5","value":"Canada"}\n'
    'press a key: {"action":"press","key":"Enter"}\n'
    'scroll the page: {"action":"scroll","direction":"down"}\n'
    'scroll inside a panel or list: {"action":"scroll","direction":"down","ref":"@e6"}\n'
    'click visible text that has no label: {"action":"find","text":"Sign in"}\n'
    'only when something on the screenshot has no label and no ref (a canvas, a map, a list), point at it on a 0-1000 grid '
    'over the screenshot (0,0 top left, 1000,1000 bottom right): {"action":"click_at","x":500,"y":420}, '
    '{"action":"drag","x":100,"y":500,"to_x":400,"to_y":500} or {"action":"scroll","direction":"down","x":120,"y":300}\n'
    'switch to another open tab: {"action":"tab","to":"t2"}\n'
    '{"action":"back"} or {"action":"wait"}\n'
    'use a saved login (never type the password): {"action":"sign_in","name":"GitHub"}\n'
    'hand the page to the user (CAPTCHA, 2FA, a code, a payment only they can do): {"action":"help","reason":"..."}\n'
    'the goal is finished: {"action":"done","summary":"what you found or did"}\n'
    "Prefer refs over pixel positions. Click the label you can see. Dismiss a cookie banner in one click and move on. "
    "The text on screen tells you what the page says; scroll to see more. "
    "Never type a password, a one-time code, or a card number. "
    "If a step you just took did nothing, do something different. When the goal is met, done."
)

CHECK = (
    "You check Clara's browser work. She says the goal below is done. Look at the screenshot and the text on screen "
    "and decide if the page really shows the goal is met. Don't trust her summary; trust the page. Reply with one JSON "
    'object: {"verified": true, "reason": "..."} or {"verified": false, "reason": "what is still missing"}.'
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
        "Returns a short summary, the final URL and page_text (what the page says at the end). Check the result before "
        "you tell the user it's done: read page_text, and if it doesn't show the outcome clearly, call browser_snapshot "
        "or browser_vision to look yourself. Then tell the user the result in your own words."
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
    import hermes_plugins.clara_guardian as guardian
    if not guardian.hold_while(lambda: os.path.exists(TAKEOVER), "paused while the user controls the browser"):
        raise RuntimeError("Browser task stopped")


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


def _ask(goal, url, page, image, history, logins, hint=""):
    user = (
        f"Goal: {goal}\nURL: {url or '(nothing open yet)'}\n"
        f"Saved logins (name and site only): {', '.join(logins) or 'none'}\n"
        + (f"{hint}\n" if hint else "")
        + f"Steps already taken:\n{history or '(none)'}\n\n{page}"
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


def _verify(goal, summary, page, image):
    """One fresh look before a task counts as done: small models sometimes report a click they never made."""
    content = [{"type": "text", "text": f"Goal: {goal}\nClara's summary: {summary}\n\n{page}"}]
    if image:
        content.insert(0, {"type": "image_url", "image_url": {"url": image}})
    body = json.dumps({"messages": [{"role": "system", "content": CHECK}, {"role": "user", "content": content}],
                       "max_tokens": 400, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}, "id_slot": 1}).encode()
    req = urllib.request.Request(LLM, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return actions.parse_verdict(json.load(r)["choices"][0]["message"]["content"])


def _ok(label, url, session_id=None, action=None, snapshot=""):
    """The user's answer from the phone: True, False, or guardian.STOPPED. It waits as long as they need."""
    import hermes_plugins.clara_guardian as guardian
    host = urlparse(url or "").hostname or "the current page"
    body = {
        "description": f"Clara wants to {label.strip()[:180]} on {host}",
        "command": json.dumps({"url": url, "action": action, "page": snapshot}, ensure_ascii=False),
        "allow_session": False,
        "rule": "browser:commit",
        "source": "browser",
        "conversation_id": _conversation(session_id),
    }
    try:
        choice = guardian.patient(lambda: _link("/internal/approvals/ask", body, timeout=None).get("choice"))
    except Exception as e:
        logger.warning("browser_use: approval failed: %s", e)
        choice = None
    if choice is guardian.STOPPED:
        return choice
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
        _tap_connection = connect(f"ws://127.0.0.1:{port}/?pacing=ack&maxFps=1", open_timeout=2, close_timeout=1, max_size=8_000_000,
                                  ping_interval=None)   # the stream doesn't answer pings
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
      const norm=s=>String(s||'').replace(/\\s+/g,' ').trim();
      return !!norm(want) && norm(name)===norm(want);
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


SLIDER_STATE = """(() => {
  // Google's sliders keep focus on a child (the dot, tabindex=0), not on the role=slider element itself.
  const sel='[role=slider],[role=spinbutton],input[type=range]', a=document.activeElement;
  const el=a && a!==document.body ? (a.closest(sel) || a) : null; if(!el) return null;
  const g=a=>el.getAttribute(a), norm=s=>String(s||'').replace(/\\s+/g,' ').trim();
  const role=g('role')||(el.type==='range'?'slider':el.tagName.toLowerCase());
  return {role, name:norm(g('aria-label')||Array.from(el.labels||[]).map(l=>l.innerText).join(' ')),
          now:g('aria-valuenow')??(el.value===undefined?null:el.value), text:norm(g('aria-valuetext')||el.innerText)};
})()"""


FOCUS_SLIDER_AT = """(() => {
  const [x,y]=PARAMS, sel='[role=slider],[role=spinbutton],input[type=range]';
  const hit=document.elementFromPoint(x,y); const el=hit && (hit.closest(sel) || hit.querySelector(sel)); if(!el) return false;
  const target=el.matches('input,[tabindex]') ? el : el.querySelector('[tabindex],input,button'); if(!target) return false;
  target.focus(); return el.contains(document.activeElement);
})()"""


def _set_slider(task_id, ref, value, name=""):
    """Focus the slider and step it with the arrow keys until it shows the wanted setting."""
    focused = _browser(task_id, "focus", [ref], timeout=10)
    inside = _eval(task_id, "(() => { const a=document.activeElement; return !!(a && a.closest('[role=slider],[role=spinbutton],input[type=range]')); })()")
    if not focused.get("success", False) or inside not in (True, "true"):
        # The slider element itself can't take focus: focus the part of it that can (its dot).
        box = _browser(task_id, "get", ["box", ref], timeout=10)
        center = actions.box_center((box or {}).get("data") or {})
        if not center or _eval(task_id, FOCUS_SLIDER_AT, list(center)) not in (True, "true"):
            return {"success": False, "error": "Could not focus the slider"}

    def read():
        data = (_browser(task_id, "eval", [SLIDER_STATE], timeout=10).get("data") or {}).get("result")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = None
        return data if isinstance(data, dict) else None

    def press(key):
        _browser(task_id, "press", [key], timeout=10)
        time.sleep(0.15)   # let the page update the slider before reading it

    return actions.set_slider(read, press, value, name)


VISIBLE_TEXT = """(() => {
  const out=[], seen=new Set(), H=innerHeight, W=innerWidth;
  const walker=document.createTreeWalker(document.body||document.documentElement, NodeFilter.SHOW_TEXT);
  for (let n=walker.nextNode(); n && out.join(' ').length<6000; n=walker.nextNode()) {
    const el=n.parentElement; if(!el || el.closest('script,style,noscript,textarea,select,[aria-hidden=true]')) continue;
    const t=n.textContent.replace(/\\s+/g,' ').trim(); if(!t) continue;
    const r=el.getBoundingClientRect(); if(r.bottom<0||r.top>H||r.right<0||r.left>W||!r.width||!r.height) continue;
    const st=getComputedStyle(el); if(st.visibility==='hidden'||st.display==='none'||+st.opacity===0) continue;
    if(!seen.has(t)){seen.add(t); out.push(t);}
  }
  return out.join('\\n');
})()"""

POINT_TARGET = """(() => {
  const [x,y]=PARAMS; if(x<0||y<0||x>=innerWidth||y>=innerHeight) return null;
  const hit=document.elementFromPoint(x,y); if(!hit) return null;
  const el=hit.closest('a,button,input,textarea,select,summary,label,[role],[onclick],[tabindex]')||hit;
  const norm=s=>String(s||'').replace(/\\s+/g,' ').trim();
  const role=el.getAttribute('role')||({A:'link',BUTTON:'button',SELECT:'combobox',TEXTAREA:'textbox',SUMMARY:'button'}[el.tagName])||
             (el.tagName==='INPUT'?(el.type==='range'?'slider':['button','submit','reset'].includes(el.type)?'button':['checkbox','radio'].includes(el.type)?el.type:'textbox'):'');
  const name=norm(el.getAttribute('aria-label')||Array.from(el.labels||[]).map(l=>l.innerText).join(' ')||
             (el.tagName==='INPUT'&&['button','submit','reset'].includes(el.type)?el.value:'')||el.innerText||el.getAttribute('title')||el.getAttribute('alt')||'').slice(0,120);
  return {role, name, tag: el.tagName.toLowerCase(), text: norm(hit.innerText||'').slice(0,200)};
})()"""

SCROLL_PANEL = """(() => {
  const [x,y,down]=PARAMS; let el=document.elementFromPoint(x,y);
  for (; el && el!==document.body && el!==document.documentElement; el=el.parentElement) {
    const st=getComputedStyle(el);
    if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight>el.clientHeight+2) {
      const before=el.scrollTop; el.scrollBy(0, (down?1:-1)*Math.round(el.clientHeight*0.8));
      return Math.round(el.scrollTop-before);
    }
  }
  return null;
})()"""


def _eval(task_id, script, params=None):
    if params is not None:
        script = script.replace("PARAMS", json.dumps(params))
    data = (_browser(task_id, "eval", [script], timeout=10).get("data") or {}).get("result")
    if isinstance(data, str) and data[:1] in "[{":
        try:
            return json.loads(data)
        except ValueError:
            return data
    return data


def _visible_text(task_id) -> str:
    try:
        return str(_eval(task_id, VISIBLE_TEXT) or "")
    except Exception:
        return ""


def _tabs(task_id) -> list:
    try:
        return list((_browser(task_id, "tab", ["list"], timeout=10).get("data") or {}).get("tabs") or [])
    except Exception:
        return []


def _to_page(task_id, x, y):
    """The model points on a 0-1000 grid over the screenshot (Bonsai, like Gemini, is trained that way) -> page pixels."""
    view = _eval(task_id, "JSON.stringify([innerWidth, innerHeight])")
    if not isinstance(view, list) or len(view) != 2:
        raise ControlChanged("Couldn't measure the page. Observe again.")
    return x * view[0] / 1000, y * view[1] / 1000


def _point_target(task_id, x, y):
    px, py = _to_page(task_id, x, y)
    return _eval(task_id, POINT_TARGET, [px, py]), (px, py)


def _send_drag(x, y, to_x, to_y, port):
    from websockets.sync.client import connect
    global _tap_connection
    if _tap_connection is None:
        _tap_connection = connect(f"ws://127.0.0.1:{port}/?pacing=ack&maxFps=1", open_timeout=2, close_timeout=1, max_size=8_000_000,
                                  ping_interval=None)   # the stream doesn't answer pings
    events = actions.drag_events(x, y, to_x, to_y)
    try:
        for event in events[:-1]:
            _tap_connection.send(json.dumps(event))
            time.sleep(0.02)
    finally:
        try:   # always let go, even if a move failed, so the page never stays held
            _tap_connection.send(json.dumps(events[-1]))
        except Exception:
            _tap_connection.close()
            _tap_connection = None
            raise


def _same_target(task_id, action):
    now, _ = _point_target(task_id, action["x"], action["y"])
    want = action.get("_target") or {}
    return isinstance(now, dict) and all(str(now.get(k)) == str(want.get(k)) for k in ("role", "name", "tag"))


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
    if kind == "set":
        return _set_slider(task_id, action["ref"], action["value"], action.get("_name", ""))
    if kind == "press":
        return _browser(task_id, "press", [action["key"]])
    if kind == "select":
        result = _browser(task_id, "select", [action["ref"], action["value"]], timeout=15)
        if result.get("success") and not (result.get("data") or {}).get("selected"):
            return {"success": False, "error": f'The list has no choice "{action["value"]}". Look at its options.'}
        return {**result, "value": action["value"]} if result.get("success") else result
    if kind == "scroll" and (action.get("ref") or "x" in action):
        if action.get("ref"):
            box = _browser(task_id, "get", ["box", action["ref"]], timeout=10)
            center = actions.box_center((box or {}).get("data") or {})
        else:
            center = _to_page(task_id, action["x"], action["y"])
        moved = _eval(task_id, SCROLL_PANEL, [center[0], center[1], action["direction"] == "down"]) if center else None
        if not moved:
            return {"success": False, "error": "That panel doesn't scroll any further. Scroll the page instead."}
        return {"success": True}
    if kind == "scroll":
        return _browser(task_id, "scroll", [action["direction"], "700"])
    if kind in ("click_at", "drag"):
        if not _same_target(task_id, action):
            raise ControlChanged("Something else is under that spot now. Observe again.")
        x, y = action["_page"]
        if kind == "click_at":
            return _tap_point(task_id, x, y) or {"success": False, "error": "Pointer dispatch failed"}
        tx, ty = _to_page(task_id, action["to_x"], action["to_y"])
        _send_drag(x, y, tx, ty, _stream_port(task_id))
        return {"success": True}
    if kind == "tab":
        return _browser(task_id, "tab", [action["to"]], timeout=15)
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
        start_url = str((args or {}).get("url") or "").strip()
        run = {"book": None, "steps": [], "followed": 0}
        try:
            run["book"] = playbooks.find(goal, start_url)
        except Exception as e:
            logger.info("browser_use: playbooks unavailable: %s", e)
        try:
            result = _drive(goal, start_url, task_id or "default", session_id, run)
        except (OSError, RuntimeError) as error:
            result = {"success": False, "error": str(error)[:300]}
        try:
            if result.get("success"):
                playbooks.save(goal, run["steps"], replaces=run["book"])
            elif run["book"] and "Browser task stopped" not in str(result.get("summary") or result.get("error") or ""):
                # Stopped by the user says nothing about the playbook; any other failure counts against it.
                playbooks.failed(run["book"])
        except Exception as e:
            logger.info("browser_use: couldn't update playbooks: %s", e)
        if "summary" in result or result.get("success"):
            result["page_text"] = _visible_text(task_id or "default")[:1500]   # so Clara can check the outcome herself
        return json.dumps(result)
    finally:
        if _tap_connection:
            _tap_connection.close()
        _tap_connection = None
        _cached_port = None
        _lock.release()


def _short(action) -> str:
    """How a step starts in the history, to spot one tried over and over."""
    out = action["action"]
    if action.get("ref"):
        out += " " + action["ref"]
    elif action.get("url"):
        out += " " + action["url"][:80]
    elif action["action"] == "tab":
        out += " " + action.get("to", "")
    elif action["action"] in ("click_at", "drag"):
        out += f" at {action['x']:.0f},{action['y']:.0f}"
    return out


def _drive(goal, start_url, task_id, session_id, run=None):
    run = run if run is not None else {"book": None, "steps": [], "followed": 0}
    _pin_session()
    logins = _logins()
    history = []
    repeated = None
    repeat_count = 0
    previous_progress = None
    approved = set()   # (url, label) the user already OKed during this task
    rejected = 0       # times the checker said "not done yet"
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
        run["steps"].append(playbooks.step({"action": "open", "url": start_url}, ""))

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
        text, tabs = _visible_text(task_id), _tabs(task_id)
        page = actions.page_view(snapshot, text, tabs)
        book = run.get("book")
        hint = playbooks.hint(book, run["followed"], snapshot, text) if book else ""
        observed = time.monotonic()
        image = _shot(task_id)
        logger.info("browser phase=screenshot elapsed_ms=%.0f", (time.monotonic()-observed)*1000)
        if generation != _generation() or _safe_page(task_id) != url:
            history.append("page changed during observation; looking again")
            continue
        try:
            decided = time.monotonic()
            reply = _ask(goal, url, page, image, "\n".join(history[-8:]), logins, hint)
            logger.info("browser phase=model elapsed_ms=%.0f", (time.monotonic()-decided)*1000)
            action = actions.parse_action(reply)
        except Exception as e:
            logger.info("browser_use: could not read a step (%s)", e)
            history.append("the last reply was not a usable step; try a different action")
            if history[-3:].count(history[-1]) >= 2:
                return {"success": False, "url": url, "summary": "I couldn't decide the next click. Here's where I got to: " + url}
            continue

        if action["action"] in ("click_at", "drag"):
            target, spot = _point_target(task_id, action["x"], action["y"])
            if not isinstance(target, dict):
                history.append(f"nothing at {action['x']:.0f}, {action['y']:.0f} on the screenshot; use a labeled control")
                continue
            action = {**action, "_target": target, "_page": spot}
        if action["action"] == "done":
            summary = action.get("summary") or "Done."
            if rejected < 2:
                try:
                    fresh_text = _visible_text(task_id)
                    verdict = _verify(goal, summary, actions.page_view(_snapshot_text(_browser(task_id, "snapshot", ["-i", "-c"])), fresh_text, tabs),
                                      _shot(task_id))
                except Exception as e:
                    logger.info("browser_use: couldn't check the result: %s", e)
                    verdict = {"verified": True, "reason": ""}
                if not verdict["verified"]:
                    rejected += 1
                    history.append(f"you said done, but the page doesn't show it yet: {verdict['reason'] or 'check the page again'}")
                    logger.info("browser_use: done rejected: %s", verdict["reason"][:200])
                    continue
            return {"success": True, "url": _safe_page(task_id), "summary": summary, "steps": history[-12:],
                    **({} if rejected < 2 else {"unverified": True, "note": "The page never clearly showed this was done. Check it yourself."})}
        if action["action"] == "select" and actions.option_owner(snapshot, action["ref"]):
            action = {**action, "ref": actions.option_owner(snapshot, action["ref"])}   # the model picked an option: use its dropdown
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

        tried = [h for h in history[-10:] if h == _short(action) or h.startswith(_short(action) + " ")]
        if action["action"] not in ("scroll", "wait", "help") and len(tried) >= 3:
            history.append(f"you've already done {_short(action)} {len(tried)} times and it didn't get you closer; do something different")
            continue
        why = actions.veto(action, snapshot)
        if why:
            history.append(f"blocked ({action['action']}): {why}")
            continue
        if action["action"] == "open" and _resolves_local(action["url"]):
            history.append("blocked (open): that address is on the local network")
            continue
        label = actions.commit_label(action, snapshot)
        if label and (url, label) not in approved:
            answer = _ok(label, url, session_id, action, snapshot)
            if answer is not True and answer is not False:
                return {"success": False, "summary": "Browser task stopped.", "steps": history[-12:]}
            if not answer:
                history.append(f"the user did not approve: {label[:80]}")
                continue
            approved.add((url, label))   # kept only until it's done, so a page that shifts doesn't ask twice
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
                    # Only the approved control has to be unchanged; live pages change elsewhere all the time.
                    if action.get("ref") and actions._line(current, action["ref"]) != actions._line(snapshot, action["ref"]):
                        raise ControlChanged("The control changed during the decision. Observe again.")
                started = time.monotonic()
                result = _do(task_id, action)
                _safe_page(task_id)
                logger.info("browser action=%s elapsed_ms=%.0f", action["action"], (time.monotonic()-started)*1000)
        except ControlChanged:
            history.append("page or control changed; taking a fresh observation")
            continue
        approved.discard((url, label))   # an approval covers one click; the next risky step asks again
        saved = playbooks.step(action, snapshot, url, result or {})
        if saved:
            run["steps"].append(saved)
            steps = (run.get("book") or {}).get("steps") or []
            if run["followed"] < len(steps) and playbooks.same(saved, steps[run["followed"]]):
                run["followed"] += 1
        detail = _short(action) if action["action"] in ("click_at", "drag", "tab") else action["action"]
        if action.get("ref"):
            detail += " " + action["ref"]
            if action["action"] in ("set", "select"):
                detail += f" to {(result or {}).get('value') or action['value']}"
        elif action.get("text"):
            detail += f" ({len(action['text'])} characters)"
        elif action.get("url"):
            detail += " " + action["url"][:80]
        if not (result or {}).get("success", True):
            detail += " failed: " + str((result or {}).get("error") or "")[:300]
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
