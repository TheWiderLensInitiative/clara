"""Decisions for Clara's browser loop. Pure functions, no browser and no model, so they can be tested alone.

The loop is the same shape Grok Bot and Antigravity use: look at the page, do one thing, look again.
This module only decides whether a proposed step is allowed.
"""
import ipaddress
import json
import re
from urllib.parse import urlparse

ACTIONS = {"open", "click", "fill", "press", "scroll", "find", "back", "wait", "sign_in", "help", "done"}

# A click or a "find and click" whose label is one of these needs the user's OK first.
COMMIT = re.compile(
    r"\b(buy|purchase|pay|checkout|place order|order now|subscribe|unsubscribe|delete|remove|send|publish|post|submit|save|share|invite|upload|confirm|accept|agree|register|sign up|transfer)\b",
    re.I,
)
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
HUMAN_CHECK = re.compile(
    r"i'?m not a robot|recaptcha|hcaptcha|verify (that )?you are (a )?human|are you a robot|"
    r"checking (if the site connection is secure|your browser)|security check|press (and|&) hold",
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
    elif action == "press":
        out["key"] = str(data.get("key") or "").strip()[:40]
        if not out["key"]:
            raise ValueError("press needs a key")
    elif action == "scroll":
        direction = str(data.get("direction") or "down").strip().lower()
        out["direction"] = direction if direction in ("up", "down") else "down"
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


def veto(action: dict, snapshot: str):
    """A hard stop for this step, or None when it may run. Passwords and card numbers never get typed."""
    kind = action.get("action")
    if kind == "open":
        return blocked_url_reason(action.get("url") or "")
    if kind in ("fill", "click") and not _line(snapshot, action.get("ref") or ""):
        return "That element is missing from the current snapshot. Observe the page again."
    if kind == "fill":
        text = action.get("text") or ""
        if CARD.search(text):
            return "Clara never types card numbers. Ask the user to take over for payment."
        line = _line(snapshot, action.get("ref") or "")
        if re.search(r"password|one.time|verification.code|security.code|\botp\b|\b2fa\b", line, re.I):
            return "That field is a password. Use sign_in with a saved login, or ask the user to take over. Never type it."
    return None


def commit_label(action: dict, snapshot: str):
    """The button or link text when this step would buy, send, or delete, else None."""
    kind = action.get("action")
    if kind == "press":
        if any(k in str(action.get("key", "")).lower() for k in ("enter", "return", "space")):
            return "activate the focused control (may submit this form)"
    if kind == "find":
        return "activate control: " + str(action.get("text") or "")
    if kind == "click":
        line = _line(snapshot, action.get("ref") or "")
        if COMMIT.search(line) or not line or re.search(r"\bbutton\b", line, re.I):
            return line.strip()[:180] or "activate an unidentified control"
        return None
    return None


def looks_like_human_check(text: str) -> bool:
    return bool(HUMAN_CHECK.search(text or ""))


def signin_blocked(text: str) -> bool:
    return bool(SIGNIN_BLOCKED.search(text or ""))


def same_step(a: dict, b: dict) -> bool:
    return a.get("action") == b.get("action") and {k: v for k, v in a.items() if k != "summary"} == {
        k: v for k, v in b.items() if k != "summary"
    }
