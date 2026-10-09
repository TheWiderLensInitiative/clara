"""Decisions for Clara's browser loop. Pure functions, no browser and no model, so they can be tested alone.

The loop is the same shape Grok Bot and Antigravity use: look at the page, do one thing, look again.
This module only decides whether a proposed step is allowed.
"""
import ipaddress
import json
import re
from urllib.parse import urlparse

ACTIONS = {"open", "click", "fill", "set", "select", "press", "scroll", "find", "click_at", "drag", "tab", "back", "wait",
           "sign_in", "help", "pay", "done"}
CHOICE_ROLES = {"combobox", "listbox"}
SLIDER_ROLES = {"slider", "spinbutton"}

# A click or a "find and click" whose label is one of these needs the user's OK first. Other buttons
# (Next, Back, Close, menus, tabs) and form settings (sliders, options, checkboxes) don't.
COMMIT = re.compile(
    r"\b(buy|purchase|pay|checkout|place order|order now|subscribe|unsubscribe|delete|remove|send|publish|post|submit|save|share|invite|upload|confirm|accept|agree|register|sign up|transfer|continue|proceed|finish|create)\b",
    re.I,
)
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
HUMAN_CHECK = re.compile(
    r"i'?m not a robot|recaptcha|hcaptcha|verify (that )?you are (a )?human|are you a robot|"
    r"checking (if the site connection is secure|your browser)|security check|press (and|&) hold|"
    r"slide to (verify|complete the puzzle)|drag the (slider|puzzle piece)|complete the puzzle",
    re.I,
)
SIGNIN_BLOCKED = re.compile(
    r"(this )?browser or app may not be secure|couldn.?t sign you in|try using a different browser",
    re.I,
)
_BLOCK_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def blocked_url_reason(url: str):
    """Why this URL must not be opened, or None when it is a normal public web page."""
    raw = (url or "").strip()
    if not raw:
        return "Missing URL."
    lower = raw.lower()
    if lower.startswith(("javascript:", "file:", "data:", "blob:", "about:")):
        return "That is not a web page Clara can open."
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlparse(raw)
    except Exception:
        return "That URL is not usable."
    if parts.scheme not in ("http", "https"):
        return "Clara only opens http and https pages."
    if parts.username or parts.password:
        return "URLs that contain a username or password are blocked."
    host = (parts.hostname or "").strip(".").lower()
    if not host or host in _BLOCK_HOSTS or host.endswith(".local") or host.endswith(".localhost"):
        return "Clara's browser stays off this computer and the local network."
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if not ip.is_global or ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return "Clara's browser stays off this computer and the local network."
    return None


def _ref(value) -> str:
    match = re.search(r"@?e(\d+)", str(value or ""), re.I)
    return f"@e{match.group(1)}" if match else ""


def parse_action(text: str) -> dict:
    """Pull the one JSON action out of a model reply. Raises ValueError when it isn't one."""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json object")
    data = json.loads(raw[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("not an object")
    action = str(data.get("action") or "").strip().lower()
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    out = {"action": action}
    if action == "open":
        out["url"] = str(data.get("url") or "").strip()[:2000]
        if not out["url"]:
            raise ValueError("open needs a url")
    elif action == "click":
        out["ref"] = _ref(data.get("ref"))
        if not out["ref"]:
            raise ValueError("click needs a ref")
    elif action == "fill":
        out["ref"] = _ref(data.get("ref"))
        out["text"] = str(data.get("text") if data.get("text") is not None else "")
        if len(out["text"]) > 100000:
            raise ValueError("fill text exceeds 100000 characters")
        if not out["ref"]:
            raise ValueError("fill needs a ref")
    elif action == "set":
        out["ref"] = _ref(data.get("ref"))
        out["value"] = str(data.get("value") if data.get("value") is not None else "").strip()[:120]
        if not out["ref"] or not out["value"]:
            raise ValueError("set needs a ref and a value")
    elif action == "press":
        out["key"] = str(data.get("key") or "").strip()[:40]
        if not out["key"]:
            raise ValueError("press needs a key")
    elif action == "select":
        out["ref"] = _ref(data.get("ref"))
        out["value"] = str(data.get("value") if data.get("value") is not None else "").strip()[:200]
        if not out["ref"] or not out["value"]:
            raise ValueError("select needs a ref and a value")
    elif action == "scroll":
        direction = str(data.get("direction") or "down").strip().lower()
        out["direction"] = direction if direction in ("up", "down") else "down"
        if data.get("ref"):
            out["ref"] = _ref(data.get("ref"))   # scroll inside this panel or list instead of the whole page
        elif data.get("x") is not None and data.get("y") is not None:
            try:   # or inside the panel at this spot on the 0-1000 grid, for lists that have no ref
                out["x"], out["y"] = float(data["x"]), float(data["y"])
            except (TypeError, ValueError):
                raise ValueError("scroll x and y must be numbers")
            if not (0 <= out["x"] <= 1000 and 0 <= out["y"] <= 1000):
                raise ValueError("scroll x and y are on the 0-1000 grid")
    elif action in ("click_at", "drag"):
        keys = ("x", "y") if action == "click_at" else ("x", "y", "to_x", "to_y")
        for key in keys:
            try:
                out[key] = float(data.get(key))
            except (TypeError, ValueError):
                raise ValueError(f"{action} needs numbers for {', '.join(keys)}")
            if not 0 <= out[key] <= 1000:
                raise ValueError(f"{action} coordinates are on the 0-1000 grid over the screenshot")
    elif action == "tab":
        out["to"] = str(data.get("to") or "").strip()
        if not re.fullmatch(r"t\d{1,4}", out["to"]):
            raise ValueError('tab needs a tab id like "t2"')
    elif action == "find":
        out["text"] = str(data.get("text") or "").strip()[:200]
        if not out["text"]:
            raise ValueError("find needs text")
    elif action == "sign_in":
        out["name"] = str(data.get("name") or "").strip()[:64]
        if not out["name"]:
            raise ValueError("sign_in needs a name")
    elif action == "help":
        out["reason"] = str(data.get("reason") or "").strip()[:300] or "I'm stuck on this page and need you for a moment."
    elif action == "done":
        out["summary"] = str(data.get("summary") or "").strip()[:1500]
    return out


def _line(snapshot: str, ref: str) -> str:
    """The snapshot row for this ref. Agent-browser writes [ref=e3]; the model says @e3."""
    token = (ref or "").strip()
    bare = token[1:] if token.startswith("@") else token
    if not bare:
        return ""
    pattern = re.compile(rf"(?:@|ref=){re.escape(bare)}\b")
    for line in (snapshot or "").splitlines():
        if pattern.search(line):
            return line
    return ""


def box_points(box: dict):
    """Where to press inside an element, best first: its center, then spots away from the middle. A big card (Dropbox's
    "Scoped access" option) can have a link or an image in its center; another spot on the card still presses it."""
    c = box_center(box)
    if not c:
        return []
    x, y, w, h = float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])
    spots = [c] + [(x + w * fx, y + h * fy) for fx, fy in ((.5, .25), (.15, .5), (.15, .25), (.85, .5), (.5, .75))]
    return spots if w > 24 and h > 24 else [c]


def same_control(seen: str, want: str) -> bool:
    """Is the control under the pointer the one meant? The snapshot's accessible name can include text that isn't on
    the page (an image's alt text, a 'New' badge's label), so an exact match refused real cards. Accept equal names,
    or one name being the start of the other when the shared part is long enough to be specific."""
    norm = lambda t: re.sub(r"\s+", " ", str(t or "")).strip().casefold()
    a, b = norm(seen), norm(want)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 12 and long_.startswith(short)


def same_box(rect, box: dict, slack: float = 2.0) -> bool:
    """Is the control under the pointer (x, y, width, height) the very element the snapshot ref points at?"""
    try:
        want = [float(box[k]) for k in ("x", "y", "width", "height")]
        got = [float(v) for v in rect]
    except (KeyError, TypeError, ValueError):
        return False
    return len(got) == 4 and want[2] > 0 and want[3] > 0 and all(abs(a - b) <= slack for a, b in zip(got, want))


_FIELD = re.compile(r'^(\s*)- (textbox|combobox|spinbutton|listbox) "([^"]*)"[^\n]*\[[^\]]*ref=(e\d+)')
_IFRAME = re.compile(r'^(\s*)- [Ii]frame\b')
CARD_KINDS = [
    ("number", re.compile(r"card ?number|credit card|debit card|card no\b|cc-number|^number$", re.I)),
    ("cvc", re.compile(r"\b(cvc|cvv|cvn|csc)\b|security code|card code|verification code", re.I)),
    ("exp", re.compile(r"mm ?/ ?yy|exp\w*\.? ?date|valid thru|^exp(iry|iration)?$", re.I)),   # one box: MM/YY
    ("exp_month", re.compile(r"(exp\w*|expir\w*) month|^month$|^mm$", re.I)),
    ("exp_year", re.compile(r"(exp\w*|expir\w*) year|^year$|^yy(yy)?$", re.I)),
    ("exp", re.compile(r"expir", re.I)),
    ("name", re.compile(r"name on card|cardholder|card holder", re.I)),
    ("zip", re.compile(r"\b(zip|postal)\b", re.I)),
]


def card_fields(snapshot: str) -> dict:
    """Card form fields on a checkout page (also inside a payment iframe): kind -> (ref, role, name). A ZIP field only
    counts inside the payment frame or when it says billing, so a shipping ZIP is never touched."""
    found, frame_indent = {}, None
    for line in snapshot.splitlines():
        f = _IFRAME.match(line)
        if f:
            frame_indent = len(f.group(1))
            continue
        m = _FIELD.match(line)
        if not m:
            continue
        indent, role, name, ref = len(m.group(1)), m.group(2), m.group(3), m.group(4)
        in_frame = frame_indent is not None and indent > frame_indent
        if frame_indent is not None and indent <= frame_indent:
            frame_indent = None
        for kind, rx in CARD_KINDS:
            if rx.search(name) and kind not in found:
                if kind == "zip" and not (in_frame or "billing" in name.lower()):
                    break
                found[kind] = ("@" + ref, role, name)
                break
    return found


def card_values(card: dict, fields: dict) -> list:
    """What to put in each field: [(ref, role, value)]. Expiry as MM/YY in one box, or month and year separately."""
    mm, yy = int(card["exp_month"]), int(card["exp_year"])
    addr = card.get("billing_address") or {}
    out = []
    for kind, (ref, role, name) in fields.items():
        if kind == "number":
            v = str(card["number"])
        elif kind == "cvc":
            v = str(card["cvc"])
        elif kind == "exp":
            v = f"{mm:02d} / {yy % 100:02d}" if " / " in name else f"{mm:02d}/{yy % 100:02d}"
        elif kind == "exp_month":
            v = f"{mm:02d}"
        elif kind == "exp_year":
            v = str(yy) if "yyyy" in name.lower() or role == "combobox" else f"{yy % 100:02d}"
        elif kind == "name":
            v = str(addr.get("name") or "")
        elif kind == "zip":
            v = str(addr.get("postal_code") or "")
        else:
            continue
        if v:
            out.append((ref, role, v))
    return out


def scrub(text: str, secrets) -> str:
    """Card digits never reach the model: the number becomes ••••last4, the CVC and expiry dots."""
    for s in sorted({str(x) for x in secrets if x and len(str(x)) >= 3}, key=len, reverse=True):
        text = text.replace(s, "••••" + s[-4:] if len(s) >= 12 else "•" * len(s))
    return text


def box_center(box: dict):
    """Viewport center of an element box, or None when the box is missing or empty."""
    if not isinstance(box, dict):
        return None
    try:
        x, y = float(box["x"]), float(box["y"])
        width, height = float(box["width"]), float(box["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return x + width / 2, y + height / 2


def tap_events(x: float, y: float) -> list:
    """A click as four mouse events, sent back to back.

    The click command waits until Chrome finishes the press before it sends the
    release. A slider captures the pointer on that press, so the release never
    arrives and the page stays frozen. Releasing first also drops a drag that a
    previous press left behind.
    """
    names = ("mouseMoved", "mouseReleased", "mousePressed", "mouseReleased")
    events = []
    for name in names:
        events.append({
            "type": "input_mouse",
            "eventType": name,
            "x": x,
            "y": y,
            "button": "none" if name == "mouseMoved" else "left",
            "clickCount": 0 if name == "mouseMoved" else 1,
        })
    return events


# Buttons that place an order and charge money: only the pay action presses them (with the one-time Link card the user
# approved). A plain click there could pay with a saved wallet (Shop Pay, a stored card) the user never approved.
ORDER_BUTTON = re.compile(r"^\s*(pay now|pay \$|place (my |your )?order|complete (my |your )?(order|purchase)|submit (my |your )?order|"
                          r"confirm (and pay|order|purchase)|buy now with|pay with shop|checkout with shop|shop ?pay\b)", re.I)
SAVED_WALLET = re.compile(r"shop ?pay|apple pay|google pay|paypal|•{2,}\s?\d{4}|\*{2,}\s?\d{4}|ending in \d{4}", re.I)
_TOTAL = re.compile(r"(?<![a-z])total\b(?! savings)[^$\d]{0,40}\$\s?([\d,]+\.\d{2})", re.I)


def page_totals(text: str) -> list:
    """Every "Total ... $X.XX" on the checkout page in cents (not subtotals), so the pay step can refuse a total above
    what the user approved."""
    out = []
    for m in _TOTAL.finditer(text or ""):
        if text[max(0, m.start() - 3):m.start()].lower().endswith("sub"):
            continue
        out.append(int(round(float(m.group(1).replace(",", "")) * 100)))
    return out


def pay_check(text: str, approved_cents, ship_zip: str = ""):
    """Why the order must not be placed on this page, or None. Checked before the card is fetched."""
    totals = page_totals(text)
    if not totals:
        return "couldn't read the order total on the checkout page; scroll to the order summary and try again"
    if approved_cents and max(totals) > approved_cents:
        return (f"the checkout total (${max(totals) / 100:,.2f}) is more than the ${approved_cents / 100:,.2f} the user approved; "
                "don't pay. Tell the user the new total")
    if ship_zip and ship_zip not in (text or ""):
        return f"the checkout doesn't show the user's ZIP {ship_zip}: check the delivery address before paying"
    return None


def veto(action: dict, snapshot: str):
    """A hard stop for this step, or None when it may run. Passwords and card numbers never get typed."""
    kind = action.get("action")
    if kind == "open":
        return blocked_url_reason(action.get("url") or "")
    if (kind in ("fill", "click", "set", "select") or (kind == "scroll" and action.get("ref"))) and not _line(snapshot, action.get("ref") or ""):
        return "That element is missing from the current snapshot. Observe the page again."
    if kind == "select" and control(_line(snapshot, action.get("ref") or ""))[0] not in CHOICE_ROLES:
        return "select is only for dropdowns and lists. Click buttons; use set for sliders."
    if kind in ("click_at", "drag"):
        target = action.get("_target") or {}
        if looks_like_human_check(" ".join(str(target.get(k) or "") for k in ("name", "text"))):
            return "That's a human check. Hand the page to the user with help; never solve it yourself."
        if kind == "drag" and target.get("role") in SLIDER_ROLES:
            return "That's a slider: use set with the setting you want instead of dragging it."
    if kind in ("click", "click_at", "press"):
        name = control(_line(snapshot, action.get("ref") or ""))[1] if kind == "click" else \
            str((action.get("_target") or {}).get("name") or "")
        if name and ORDER_BUTTON.search(name):
            return ("That button places the order and charges money. Orders are only placed with the pay action, after "
                    "pay_with_link: make sure the card form shows (pick 'Credit card', not Shop Pay or a saved card), then use pay.")
    if kind == "set" and control(_line(snapshot, action.get("ref") or ""))[0] not in SLIDER_ROLES:
        return "set is only for sliders. Click options, buttons and checkboxes instead."
    if kind == "fill":
        text = action.get("text") or ""
        if CARD.search(text):
            return "Clara never types card numbers. Ask the user to take over for payment."
        line = _line(snapshot, action.get("ref") or "")
        if re.search(r"password|one.time|verification.code|security.code|\botp\b|\b2fa\b", line, re.I):
            return "That field is a password. Use sign_in with a saved login, or ask the user to take over. Never type it."
    return None


# Settings inside a form: changing one never sends anything by itself.
SETTING_ROLES = {"slider", "option", "checkbox", "radio", "switch", "tab", "textbox", "searchbox", "combobox",
                 "listbox", "spinbutton", "menuitemcheckbox", "menuitemradio", "treeitem"}
SEARCH_FIELD = re.compile(r"^\s*-?\s*(?:searchbox\b|(?:combobox|textbox)\s+\"[^\"]*search)", re.I | re.M)


def control(line: str):
    """(role, name) of a snapshot row: '- button "Next" [ref=e3]' or '@e3 [button] "Next"'."""
    role = re.match(r"\s*-\s*([a-z]+)", line or "") or re.search(r"\[([a-z]+)\]", line or "")
    name = re.search(r'"([^"\n]*)"', line or "")
    return (role.group(1).lower() if role else ""), (name.group(1).strip(" ,") if name else "")


def commit_label(action: dict, snapshot: str):
    """What the user is asked to approve when this step is risky (buy, delete, send, submit, continue…), else None."""
    kind = action.get("action")
    if kind == "press":
        # Enter in a search field just searches; elsewhere it may submit the form.
        if any(k in str(action.get("key", "")).lower() for k in ("enter", "return")) and not SEARCH_FIELD.search(snapshot or ""):
            return "press Enter (this may submit the form)"
        return None
    if kind == "find":
        text = str(action.get("text") or "").strip()
        return f'click "{text[:120]}"' if COMMIT.search(text) else None
    if kind == "click":
        line = _line(snapshot, action.get("ref") or "")
        if not line:
            return "click a control I can't identify"
        role, name = control(line)
        if role in SETTING_ROLES:
            return None
        return f'click "{name[:120]}"' if COMMIT.search(name) else None
    if kind in ("click_at", "drag"):
        # A spot on the screenshot: judged by the element under it, found before anything happens.
        target = action.get("_target") or {}
        role, name = str(target.get("role") or ""), str(target.get("name") or "").strip()
        verb = "click" if kind == "click_at" else "drag"
        if not name:
            return f"{verb} a spot on the page I can't identify ({target.get('tag') or 'nothing'} at {action['x']:.0f}, {action['y']:.0f})"
        if role in SETTING_ROLES and kind == "click_at":
            return None
        return f'{verb} "{name[:120]}"' if COMMIT.search(name) else None
    return None


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" ,").casefold()


def set_slider(read, press, want: str, name: str = "", limit: int = 40) -> dict:
    """Move a focused slider to `want` (its visible label, e.g. "Anyone on the web", or a number) with arrow keys,
    which every accessible slider supports. Clicking can't do this: a tap lands on the middle of the track.
    read() -> {"role", "name", "now", "text"} of the focused element; press(key) sends one key."""
    number = re.fullmatch(r"-?\d+(?:\.\d+)?", want.strip())

    def matches(state):
        if number:
            try:
                return float(state.get("now")) == float(want)
            except (TypeError, ValueError):
                return False
        text, goal = _norm(state.get("text")), _norm(want)
        return bool(text) and (text == goal or goal in text)

    def label(state):
        return str(state.get("text") or state.get("now") or "").strip()

    state = read()
    if not state or state.get("role") not in SLIDER_ROLES:
        return {"success": False, "error": "That control isn't a slider, or it couldn't be focused."}
    if name and _norm(state.get("name")) != _norm(name):
        return {"success": False, "error": "Focus landed on a different control. Observe again."}
    seen = [label(state)]
    if matches(state):
        return {"success": True, "value": label(state)}
    # Sweep to one end, then across to the other, checking every stop on the way.
    for key in ("ArrowLeft", "ArrowRight"):
        for _ in range(limit):
            before = (state.get("now"), state.get("text"))
            press(key)
            state = read() or {}
            if name and _norm(state.get("name")) != _norm(name):
                return {"success": False, "error": "Focus moved off the slider. Observe again."}
            if label(state) and label(state) not in seen:
                seen.append(label(state))
            if matches(state):
                return {"success": True, "value": label(state)}
            if (state.get("now"), state.get("text")) == before:
                break   # reached this end
    choices = ", ".join(c for c in seen if c)
    return {"success": False, "error": f'This slider has no setting "{want}". Its settings are: {choices}.'}


def option_owner(snapshot: str, ref: str) -> str:
    """For an option row, the ref of the dropdown or list it sits in (options are indented under it), else ""."""
    lines = (snapshot or "").splitlines()
    mine = _line(snapshot, ref)
    if not mine or control(mine)[0] != "option":
        return ""
    depth = len(mine) - len(mine.lstrip())
    for line in reversed(lines[:lines.index(mine)]):
        indent = len(line) - len(line.lstrip())
        if indent < depth and control(line)[0] in CHOICE_ROLES:
            found = re.search(r"(?:ref=|@)(e\d+)", line)
            return f"@{found.group(1)}" if found else ""
        if indent < depth and line.strip():
            depth = indent
    return ""


def parse_verdict(text: str) -> dict:
    """The checker's answer to "is the goal really done?": {"verified": bool, "reason": str}."""
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.I)
    start, end = raw.find("{"), raw.rfind("}")
    try:
        data = json.loads(raw[start:end + 1]) if start >= 0 < end else {}
    except ValueError:
        data = {}
    verified = data.get("verified")
    return {"verified": verified is True or str(verified).lower() == "true", "reason": str(data.get("reason") or "")[:300]}


def second_opinion_control(action: dict, snapshot: str = ""):
    """The control to ask Laya about ('button "Done"'), for a click the word list let through; None when there is
    nothing to ask (not a click, a form setting, or already asking the user)."""
    if commit_label(action, snapshot):
        return None
    kind = action.get("action")
    if kind == "click":
        role, name = control(_line(snapshot, action.get("ref") or ""))
    elif kind == "find":
        role, name = "control", str(action.get("text") or "")
    elif kind == "click_at":
        target = action.get("_target") or {}
        role, name = str(target.get("role") or target.get("tag") or "control"), str(target.get("name") or "")
    else:
        return None
    if not name or role in SETTING_ROLES:
        return None
    return f'{role or "control"} "{name[:120]}"'


def dialog_text(snapshot: str) -> str:
    """The name of an open dialog in the snapshot ("Delete 3 files?"), which changes what OK or Yes means."""
    found = re.search(r'^\s*-\s*(?:alertdialog|dialog)\s+"([^"]+)"', snapshot or "", re.M)
    return found.group(1)[:240] if found else ""


def step_text(action: dict, snapshot: str = "", result: dict = None, url: str = "") -> str:
    """One browser step as a short sentence for the activity log. Never includes what was typed into a field."""
    kind = action.get("action")
    name = control(_line(snapshot, action.get("ref") or ""))[1] if action.get("ref") else ""
    target = action.get("_target") or {}
    if kind == "open":
        text = f"Opened {urlparse(action.get('url') or '').hostname or action.get('url')}"
    elif kind in ("click", "find"):
        text = f'Clicked "{name or action.get("text") or "a control"}"'
    elif kind == "fill":
        text = f'Typed into "{name or "a field"}"'
    elif kind == "set":
        text = f'Set "{name or "a slider"}" to {(result or {}).get("value") or action.get("value")}'
    elif kind == "select":
        text = f'Chose {action.get("value")} in "{name or "a list"}"'
    elif kind == "press":
        text = f"Pressed {action.get('key')}"
    elif kind == "scroll":
        text = f"Scrolled {action.get('direction') or 'down'}" + (f' in "{name}"' if name else "")
    elif kind in ("click_at", "drag"):
        text = f'{"Clicked" if kind == "click_at" else "Dragged"} "{target.get("name") or target.get("tag") or "a spot"}" (by position)'
    elif kind == "tab":
        text = f"Switched to tab {action.get('to')}"
    elif kind == "back":
        text = "Went back"
    elif kind == "sign_in":
        text = f"Signed in with the saved login {action.get('name')}"
    elif kind == "wait":
        text = "Waited for the page"
    else:
        text = str(kind)
    if result is not None and not result.get("success", True):
        text += f" (didn't work: {str(result.get('error') or '')[:80]})"
    return text[:300]


def drag_events(x: float, y: float, to_x: float, to_y: float, steps: int = 12) -> list:
    """A press, a smooth move and a release, like a finger dragging. Sent through the stream like a tap,
    so the release always goes out even while the page holds the pointer."""
    def event(kind, px, py):
        return {"type": "input_mouse", "eventType": kind, "x": round(px, 1), "y": round(py, 1),
                "button": "none" if kind == "mouseMoved" else "left", "clickCount": 0 if kind == "mouseMoved" else 1}
    out = [event("mouseMoved", x, y), event("mousePressed", x, y)]
    for i in range(1, steps + 1):
        out.append(event("mouseMoved", x + (to_x - x) * i / steps, y + (to_y - y) * i / steps))
    out.append(event("mouseReleased", to_x, to_y))
    return out


def page_view(snapshot: str, text: str = "", tabs=None, controls_limit: int = 12000, text_limit: int = 3000) -> str:
    """What the browser model reads next to the screenshot, like Antigravity's page reader:
    the controls (with refs) and the text that's on screen right now."""
    parts = []
    if tabs and len(tabs) > 1:
        parts.append("Open tabs: " + "; ".join(
            f'{t.get("tabId")} "{str(t.get("title") or t.get("url") or "")[:60]}"' + (" (this one)" if t.get("active") else "")
            for t in tabs[:8]))
    snap = snapshot or "(no controls found)"
    parts.append("Controls on the page:\n" + (snap if len(snap) <= controls_limit else snap[:controls_limit] + "\n…(more controls below)"))
    words = (text or "").strip()
    if words:
        parts.append("Text on screen:\n" + (words if len(words) <= text_limit else words[:text_limit] + "…"))
    return "\n\n".join(parts)


def looks_like_human_check(text: str) -> bool:
    return bool(HUMAN_CHECK.search(text or ""))


def signin_blocked(text: str) -> bool:
    return bool(SIGNIN_BLOCKED.search(text or ""))


def cycling(trail, size=2, times=3) -> bool:
    """The last steps are the same short pattern over and over (open → click → open → click…), going nowhere.
    Scrolling and waiting don't count: going down a long page is the same step many times on purpose."""
    trail = [t for t in trail if not t.startswith(("scroll", "wait"))]
    for n in range(1, size + 1):
        tail = trail[-n * times:]
        if len(tail) == n * times and all(tail[i] == tail[i % n] for i in range(len(tail))):
            return True
    return False


def same_step(a: dict, b: dict) -> bool:
    return a.get("action") == b.get("action") and {k: v for k, v in a.items() if k != "summary"} == {
        k: v for k, v in b.items() if k != "summary"
    }
