"""Playbooks: the path that worked last time on a site, handed to the browser model as a hint.

After a browser task succeeds, its steps are saved by control name ("click button "Create group""),
never by position and never with what was typed. The next similar task gets them as a hint; Clara
still looks at the page before every step and approvals still ask every time. If a step's control
is missing from the page, the site has probably changed: the hint says so, and the path that works
this time replaces the old one. A playbook that fails twice in a row is dropped.
"""
import json
import os
import re
import tempfile
import time
from urllib.parse import urlparse

from . import actions

PATH = os.path.join(os.environ.get("HOME", "/var/lib/clara"), "browser-playbooks.json")
MAX_PLAYBOOKS = 60
MAX_PER_SITE = 6
MAX_STEPS_SAVED = 40
MATCH_MIN = 0.35
STOP_WORDS = {"a", "an", "the", "to", "and", "or", "of", "on", "in", "for", "with", "my", "me", "is", "it", "at", "by",
              "please", "go", "use", "your", "you", "i", "if", "we", "our", "this", "that", "then", "be", "are"}


def _words(goal: str) -> set:
    # Quoted names and numbers are what change between runs ("named Clara Support"); leave them out.
    goal = re.sub(r"[\"“”'‘’][^\"“”'‘’]{0,80}[\"“”'‘’]", " ", goal or "")
    return {w for w in re.findall(r"[a-z]+", goal.lower()) if w not in STOP_WORDS and len(w) > 1}


def host(url: str) -> str:
    return (urlparse(url or "").hostname or "").removeprefix("www.")


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def step(action: dict, snapshot: str, url: str = "", result: dict = None):
    """One saved step, or None for steps not worth replaying (waits, failed actions, sign-ins, help)."""
    kind = action.get("action")
    if result is not None and not result.get("success", True):
        return None
    if kind == "open":
        u = urlparse(action.get("url") or "")
        return {"do": "open", "url": f"{u.scheme or 'https'}://{u.netloc}{u.path}"}   # no query: it can hold tokens
    if kind in ("click", "fill", "set", "select") or (kind == "scroll" and action.get("ref")):
        role, name = actions.control(actions._line(snapshot, action.get("ref") or ""))
        if not name:
            return None
        out = {"do": kind, "role": role, "name": name}
        if kind in ("set", "select"):
            out["value"] = (result or {}).get("value") or action.get("value")   # a setting, never typed text
        if kind == "scroll":
            out["direction"] = action.get("direction")
        return out
    if kind in ("click_at", "drag"):
        target = action.get("_target") or {}
        if target.get("name"):
            return {"do": kind, "role": target.get("role") or "", "name": target["name"]}
        if not target.get("tag"):
            return None
        # No name (a canvas, a map): keep where it was on the 0-1000 grid, as a rough hint only.
        return {"do": kind, "tag": target["tag"], "x": round(action["x"]), "y": round(action["y"])}
    if kind == "press" and action.get("key"):
        return {"do": "press", "key": action["key"]}
    if kind == "find":
        return {"do": "click", "role": "", "name": action.get("text")}
    if kind in ("back", "tab"):
        return {"do": kind}
    return None


def describe(s: dict) -> str:
    kind = s.get("do")
    if kind == "open":
        return f"open {s.get('url')}"
    if kind == "press":
        return f"press {s.get('key')}"
    if kind in ("back", "tab"):
        return "go back" if kind == "back" else "switch to the new tab"
    if not s.get("name") and s.get("tag"):
        return f"{'click' if kind == 'click_at' else 'drag'} the {s['tag']} at about x={s.get('x')}, y={s.get('y')} on the grid"
    target = f'{s.get("role") + " " if s.get("role") else ""}"{s.get("name")}"'
    if kind in ("set", "select"):
        return f"{kind} {target} to {s.get('value')}"
    if kind == "fill":
        return f"fill {target} (with what this task needs)"
    if kind == "scroll":
        return f"scroll {target} {s.get('direction') or 'down'}"
    return f"{'click' if kind in ('click', 'click_at') else 'drag'} {target}"


def same(a: dict, b: dict) -> bool:
    keys = ("do", "name", "url", "key", "tag")
    return all(str(a.get(k) or "").casefold() == str(b.get(k) or "").casefold() for k in keys)


def load(path: str = PATH) -> list:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(books: list, path: str = PATH):
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".playbooks-")
    with os.fdopen(fd, "w") as f:
        json.dump(books, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def find(goal: str, start_url: str = "", path: str = PATH):
    """The saved playbook for the most similar goal (on the same site when a start page is known), or None."""
    best, score = None, 0.0
    site = host(start_url)
    for book in load(path):
        if site and book.get("host") and book["host"] != site:
            continue
        s = similarity(goal, book.get("goal", ""))
        if s > score:
            best, score = book, s
    return best if score >= MATCH_MIN else None


def tidy(steps: list) -> list:
    """Keep the path, not the wandering: a click that was undone by switching straight back to the
    previous tab is a detour, and a step that repeats an earlier one adds nothing."""
    out = []
    for s in [s for s in steps if s]:
        if s.get("do") == "tab" and out and out[-1].get("do") == "click":
            out.pop()
            continue
        if any(same(s, kept) and s.get("value") == kept.get("value") for kept in out):
            continue
        out.append(s)
    return out


def save(goal: str, steps: list, path: str = PATH, replaces=None):
    steps = tidy(steps)[:MAX_STEPS_SAVED]
    if len(steps) < 2:
        return None
    site = next((host(s["url"]) for s in steps if s.get("do") == "open"), "") or (replaces or {}).get("host", "")
    books = [b for b in load(path) if not (replaces and b.get("goal") == replaces.get("goal") and b.get("host") == replaces.get("host"))]
    books = [b for b in books if not (b.get("host") == site and similarity(goal, b.get("goal", "")) >= 0.8)]
    book = {"goal": goal[:500], "host": site, "steps": steps, "saved": time.time(), "uses": (replaces or {}).get("uses", 0) + 1,
            "failures": 0}
    books.append(book)
    same_site = [b for b in books if b.get("host") == site]
    if len(same_site) > MAX_PER_SITE:
        oldest = min(same_site, key=lambda b: b.get("saved", 0))
        books.remove(oldest)
    books = sorted(books, key=lambda b: b.get("saved", 0))[-MAX_PLAYBOOKS:]
    _write(books, path)
    return book


def failed(book: dict, path: str = PATH):
    """A run with this playbook didn't finish. Two failures in a row and it's gone."""
    books = load(path)
    for b in books:
        if b.get("goal") == book.get("goal") and b.get("host") == book.get("host"):
            b["failures"] = b.get("failures", 0) + 1
    books = [b for b in books if b.get("failures", 0) < 2]
    _write(books, path)


def hint(book: dict, done: int, snapshot: str, text: str = "") -> str:
    """The playbook as a note for the browser model, with the next expected step marked."""
    steps = book.get("steps") or []
    lines = []
    for i, s in enumerate(steps):
        mark = "→ next" if i == done else ("✓" if i < done else " ")
        lines.append(f"{mark} {i + 1}. {describe(s)}")
    note = ("A similar task worked like this before. Use it as a guide, but trust the page: if it differs, "
            "work it out from what you see.\n" + "\n".join(lines))
    if done < len(steps):
        nxt = steps[done]
        name = str(nxt.get("name") or "")
        if name and nxt.get("do") != "open" and actions._norm(name) not in actions._norm(snapshot + " " + text):
            note += f'\n(The "{name}" control isn\'t on this page right now. The site may have changed; find another way.)'
    return note
