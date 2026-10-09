"""Purchases: every order Clara placed, kept as a playbook so "Buy again" repeats it fast.

An entry is saved when the pay step reports the order went through. It holds what was bought (photo, title, store,
the exact checkout link), what it cost (items, shipping, tax, total), where it shipped, the order number from the
confirmation page and the steps Clara took (each tool and what it was told). Buy again replays it: open the same
checkout link, same address, then the usual two approvals (Clara's breakdown, then Link) and the pay step. No card
details are ever stored: each order gets a new one-time Link card.
"""
import json
import re
import secrets
import time

import paths

DIR = paths.DATA / "purchases"
ID = re.compile(r"p_[a-f0-9]{10}")
ORDER = re.compile(r"\b(?:order|confirmation)\s*(?:number|no\.?|id|#)?\s*[:#]?\s*#?\s*([A-Z0-9][A-Z0-9-]{3,24})\b", re.I)


def order_number(text: str) -> str:
    """The order number on a confirmation page or in Clara's reply ("Order #1001", "Confirmation #A1B2C3"), or ""."""
    for m in ORDER.finditer(text or ""):
        v = m.group(1)
        if any(ch.isdigit() for ch in v) and v.lower() not in ("2fa",):
            return v.upper() if not v.isdigit() else v
    return ""


def _path(pid):
    if not ID.fullmatch(str(pid)):
        raise ValueError("bad purchase id")
    return DIR / f"{pid}.json"


def save(entry: dict) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    entry = {**entry}
    entry.setdefault("id", "p_" + secrets.token_hex(5))
    entry.setdefault("at", time.time())
    entry.setdefault("times", 1)
    tmp = _path(entry["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, indent=1))
    tmp.replace(_path(entry["id"]))
    return entry


def get(pid):
    try:
        return json.loads(_path(pid).read_text())
    except (OSError, ValueError):
        return None


def update(pid, **fields):
    e = get(pid)
    if e is None:
        return None
    e.update({k: v for k, v in fields.items() if v not in (None, "", [])})
    return save(e)


def all_entries() -> list:
    if not DIR.exists():
        return []
    out = []
    for p in DIR.glob("p_*.json"):
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda e: e.get("at", 0), reverse=True)


def delete(pid) -> bool:
    try:
        _path(pid).unlink()
        return True
    except (OSError, ValueError):
        return False


def same_item(a: dict, b: dict) -> bool:
    ka, kb = a.get("checkout_url") or a.get("product_page"), b.get("checkout_url") or b.get("product_page")
    return bool(ka) and ka == kb


def record(entry: dict) -> dict:
    """Save a new order. Buying the same item again updates its entry (latest price, order number, times bought)
    instead of adding a duplicate card."""
    for old in all_entries():
        if same_item(old, entry):
            return save({**old, **{k: v for k, v in entry.items() if v not in (None, "", [])}, "id": old["id"],
                         "at": time.time(), "times": int(old.get("times", 1)) + 1, "first_at": old.get("first_at", old.get("at"))})
    return save(entry)


def money(cents) -> str:
    return f"${cents / 100:,.2f}" if isinstance(cents, int) else "?"


def playbook(e: dict) -> str:
    """What Clara is told for Buy again: the exact link, address and what it cost, and the steps from last time."""
    steps = "\n".join(f"  {i + 1}. {s['tool']}: {s['detail']}" for i, s in enumerate([s for s in e.get("steps") or [] if s.get("tool")][:12]))
    last = f"{money(e.get('total_cents'))} total"
    if isinstance(e.get("shipping_cents"), int):
        last += f" ({money(e.get('subtotal_cents'))} item + {money(e['shipping_cents'])} shipping" + (
            f" + {money(e['tax_cents'])} tax" if isinstance(e.get("tax_cents"), int) else "") + ")"
    return (f" BUY AGAIN: the user tapped Buy again on a past order. Repeat it exactly; no searching, no choosing.\n"
            f"- Item: {e.get('title')} (quantity {e.get('quantity') or 1}) from {e.get('store') or e.get('merchant_name')}\n"
            + (f"- Checkout link: {e['checkout_url']} : open exactly this with browser_use\n" if e.get("checkout_url") else
               f"- Product page: {e.get('product_page')} : open exactly this with browser_use, add the same item (quantity "
               f"{e.get('quantity') or 1}) to the cart and check out the same way as last time\n") +
            f"- Ship to: {e.get('ship_to')} (copy it exactly)\n"
            f"- Last time: {last}; pick the same (cheapest) shipping again\n"
            + (f"- Steps that worked last time:\n{steps}\n" if steps else "") +
            "Then call pay_with_link with the new breakdown (the user approves it in Clara, then in Link) and use the pay action. "
            "If the item is sold out, the link doesn't work or the total is much higher than last time, stop and tell the user "
            "instead of buying something else.")
