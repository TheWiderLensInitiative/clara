"""Outlook mail and calendar through Microsoft Graph, in the same shapes as the Gmail / Google Calendar helpers in
connectors.py, so Clara's email_* and calendar_* tools work the same for either account.

Ids are prefixed "ms:" so a later email_read / reply / calendar change goes back to the account the item came from.
Clara writes Gmail search syntax for both; to_graph() turns the common parts of it into a Graph query.
"""
import datetime as dt
import re
from urllib.parse import quote

import connectors

PREFIX = "ms:"
UTC = {"Prefer": 'outlook.timezone="UTC"'}
TEXT = {"Prefer": 'outlook.body-content-type="text"'}
LIST_FIELDS = "id,conversationId,subject,from,toRecipients,receivedDateTime,bodyPreview,isRead,importance,inferenceClassification"
EVENT_FIELDS = "id,subject,start,end,isAllDay,showAs,isCancelled,location,bodyPreview,attendees,webLink"


def is_outlook(item_id) -> bool:
    return str(item_id or "").startswith(PREFIX)


def _raw(item_id) -> str:
    return quote(str(item_id)[len(PREFIX):] if is_outlook(item_id) else str(item_id), safe="")


async def _api(store, method, path, **kw):
    url = path if path.startswith("http") else connectors.MS_GRAPH + path
    return await connectors.api(store, "microsoft", method, url, **kw)


# --- mail --------------------------------------------------------------------------------------------------------
def _person(r) -> str:
    a = (r or {}).get("emailAddress") or {}
    name, addr = a.get("name") or "", a.get("address") or ""
    return f"{name} <{addr}>" if name and addr and name != addr else (addr or name)


def _recipients(field):
    from email.utils import getaddresses
    return [{"emailAddress": {"address": addr}} for _, addr in getaddresses([field or ""]) if addr]


def summarize_message(m, with_body=False, body_limit=6000):
    out = {"id": PREFIX + m["id"], "thread_id": m.get("conversationId"), "from": _person(m.get("from")),
           "to": ", ".join(_person(r) for r in m.get("toRecipients") or []), "subject": m.get("subject") or "",
           "date": m.get("receivedDateTime") or "", "snippet": connectors.clean_body(m.get("bodyPreview") or "")[:300], "unread": not m.get("isRead", True),
           "important": m.get("importance") == "high" or m.get("inferenceClassification") == "focused"}
    if with_body:
        out["body"] = connectors.clean_body((m.get("body") or {}).get("content") or "")[:body_limit]
        out["message_id"] = m.get("internetMessageId") or ""
        out["cc"] = ", ".join(_person(r) for r in m.get("ccRecipients") or [])
    return out


_AGE = {"h": "hours", "d": "days", "m": "days", "y": "days"}
_AGE_MULT = {"h": 1, "d": 1, "m": 30, "y": 365}
_FOLDERS = {"inbox": "inbox", "sent": "sentitems", "drafts": "drafts", "trash": "deleteditems", "spam": "junkemail", "anywhere": None}


def _date_bound(op, value, now):
    if op in ("newer_than", "older_than"):
        m = re.fullmatch(r"(\d+)([hdmy])", value)
        if not m:
            return None
        n, unit = int(m.group(1)), m.group(2)
        return now - dt.timedelta(**{_AGE[unit]: n * _AGE_MULT[unit]})
    try:   # after:/before: YYYY/MM/DD (Gmail reads them as local midnight)
        return dt.datetime.combine(dt.date.fromisoformat(value.replace("/", "-")), dt.time()).astimezone()
    except ValueError:
        return None


def to_graph(query: str, now=None):
    """Gmail search syntax -> (folder, filters, kql words, python checks). Unknown operators (label:, category:) are dropped."""
    now = now or dt.datetime.now().astimezone()
    folder, filters, words, checks = "inbox", [], [], []
    since = until = None
    for token in re.findall(r'(?:[\w-]+:)?"[^"]*"|\S+', query or ""):
        op, _, value = token.partition(":") if re.match(r"[\w-]+:", token) else ("", "", token)
        op, value = op.lower(), value.strip('"')
        if op == "is" and value.lower() in ("unread", "read"):
            want = value.lower() == "read"
            filters.append(f"isRead eq {str(want).lower()}"); checks.append(lambda m, w=want: m.get("isRead", True) == w)
        elif op == "is" and value.lower() == "important":
            filters.append("inferenceClassification eq 'focused'")
            checks.append(lambda m: m.get("inferenceClassification") == "focused" or m.get("importance") == "high")
        elif op == "is" and value.lower() == "starred":
            filters.append("flag/flagStatus eq 'flagged'"); checks.append(lambda m: (m.get("flag") or {}).get("flagStatus") == "flagged")
        elif op == "has" and value.lower() == "attachment":
            filters.append("hasAttachments eq true"); checks.append(lambda m: m.get("hasAttachments"))
        elif op in ("newer_than", "after"):
            b = _date_bound(op, value, now)
            since = max(since, b) if since and b else (b or since)
        elif op in ("older_than", "before"):
            b = _date_bound(op, value, now)
            until = min(until, b) if until and b else (b or until)
        elif op == "in" and value.lower() in _FOLDERS:
            folder = _FOLDERS[value.lower()]
        elif op in ("from", "to", "cc", "subject"):
            words += [f"{op}:{w}" for w in value.split()]
        elif op in ("label", "category", "is", "has", "in", "list", "filename", "larger", "smaller"):
            continue
        elif token.strip('"'):
            words += token.strip('"').split()
    z = lambda d: d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Graph wants the $orderby property first in $filter, so the date bound always leads.
    filters.insert(0, f"receivedDateTime ge {z(since) if since else '1900-01-01T00:00:00Z'}")
    if until:
        filters.insert(1, f"receivedDateTime lt {z(until)}")
    if since:
        checks.append(lambda m: m.get("receivedDateTime", "") >= z(since))
    if until:
        checks.append(lambda m: m.get("receivedDateTime", "") < z(until))
    return folder, filters, " ".join(words), checks


async def search(store, query="", limit=10):
    limit = max(1, min(int(limit), 25))
    folder, filters, kql, checks = to_graph(query)
    path = f"/me/mailFolders/{folder}/messages" if folder else "/me/messages"
    select = LIST_FIELDS + ",flag,hasAttachments"
    if kql:   # Graph can't combine $search with $filter/$orderby on mail: search, then filter and sort here
        r = await _api(store, "GET", path, params={"$search": '"' + kql.replace('"', "") + '"', "$top": 50, "$select": select})
        found = [m for m in r.get("value", []) if all(c(m) for c in checks)]
        found.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)
    else:
        r = await _api(store, "GET", path, params={"$filter": " and ".join(filters), "$orderby": "receivedDateTime desc",
                                                   "$top": limit, "$select": select})
        found = r.get("value", [])
    return [summarize_message(m) for m in found[:limit]]


async def read(store, msg_id):
    m = await _api(store, "GET", f"/me/messages/{_raw(msg_id)}", headers=TEXT,
                   params={"$select": LIST_FIELDS + ",body,ccRecipients,internetMessageId"})
    return summarize_message(m, with_body=True)


def _reply_subject(subject, original):
    return subject or "Re: " + re.sub(r"^((re|aw|sv):\s*)+", "", original or "", flags=re.I)


async def draft(store, to, subject, body, cc=None, reply_to_id=None):
    if reply_to_id:
        orig = await read(store, reply_to_id)
        msg = {"toRecipients": _recipients(to), **({"ccRecipients": _recipients(cc)} if cc else {})}
        d = await _api(store, "POST", f"/me/messages/{_raw(reply_to_id)}/createReply", json={"comment": body, "message": msg})
        return {"draft_id": PREFIX + d.get("id", ""), "subject": d.get("subject") or _reply_subject(subject, orig["subject"])}
    d = await _api(store, "POST", "/me/messages", json={"subject": subject, "body": {"contentType": "Text", "content": body},
                                                         "toRecipients": _recipients(to),
                                                         **({"ccRecipients": _recipients(cc)} if cc else {})})
    return {"draft_id": PREFIX + d.get("id", ""), "subject": subject}


async def send(store, to, subject, body, cc=None, reply_to_id=None):
    msg = {"toRecipients": _recipients(to), **({"ccRecipients": _recipients(cc)} if cc else {})}
    if reply_to_id:   # reply keeps the thread and quotes the original under the text
        orig = await read(store, reply_to_id)
        await _api(store, "POST", f"/me/messages/{_raw(reply_to_id)}/reply", json={"comment": body, "message": msg})
        return {"sent": True, "subject": _reply_subject(subject, orig["subject"])}
    await _api(store, "POST", "/me/sendMail", json={"message": {**msg, "subject": subject, "body": {"contentType": "Text", "content": body}},
                                                    "saveToSentItems": True})
    return {"sent": True, "subject": subject}


# --- calendar -----------------------------------------------------------------------------------------------------
def _local(v) -> dt.datetime:
    """Graph's {dateTime: '2026-10-07T14:00:00.0000000', timeZone: 'UTC'} -> an aware local datetime."""
    s = re.sub(r"(\.\d{1,6})\d*", r"\1", (v or {}).get("dateTime") or "")
    d = dt.datetime.fromisoformat(s)
    return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).astimezone()


def summarize_event(e):
    all_day = bool(e.get("isAllDay"))
    if all_day:   # all-day events float: their date is the date Graph gives, whatever the zone
        start, end = (str((e.get(k) or {}).get("dateTime", ""))[:10] for k in ("start", "end"))
    else:
        start, end = _local(e.get("start")).isoformat(), _local(e.get("end")).isoformat()
    return {"id": PREFIX + e["id"], "title": e.get("subject") or "(no title)", "start": start, "end": end, "all_day": all_day,
            "busy": e.get("showAs") not in ("free", "workingElsewhere") and not e.get("isCancelled"),
            "location": (e.get("location") or {}).get("displayName", ""), "description": (e.get("bodyPreview") or "")[:500],
            "attendees": [(a.get("emailAddress") or {}).get("address") for a in e.get("attendees") or []][:20], "link": e.get("webLink", "")}


def _utc(value: str) -> str:
    d = dt.datetime.fromisoformat(value)
    return (d if d.tzinfo else d.astimezone()).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


async def events(store, start=None, end=None, query=None, limit=25, all_pages=False):
    now = dt.datetime.now().astimezone()
    params = {"startDateTime": _utc(start or now.isoformat()) + "Z", "endDateTime": _utc(end or (now + dt.timedelta(days=7)).isoformat()) + "Z",
              "$orderby": "start/dateTime", "$top": max(1, min(int(limit), 50)), "$select": EVENT_FIELDS}
    out, url, seen = [], "/me/calendarView", set()
    while True:
        r = await _api(store, "GET", url, params=params, headers=UTC)
        out.extend(summarize_event(e) for e in r.get("value", []) if not e.get("isCancelled"))
        url, params = r.get("@odata.nextLink"), None
        if not all_pages or not url:
            break
        if url in seen:
            raise RuntimeError("Outlook returned a repeated page link")
        seen.add(url)
    if query:   # calendarView has no text search
        q = query.lower()
        out = [e for e in out if q in f"{e['title']} {e['location']} {e['description']}".lower()]
    return out


def event_body(title=None, start=None, end=None, all_day=False, location=None, description=None, attendees=None, defaults=True):
    b = {}
    if title is not None:
        b["subject"] = title
    if all_day and (start or end):
        b["isAllDay"] = True
        first = dt.date.fromisoformat((start or end)[:10])
        last = dt.date.fromisoformat(end[:10]) if end and (not start or end[:10] != start[:10]) else first + dt.timedelta(days=1)
        if start:
            b["start"] = {"dateTime": f"{first.isoformat()}T00:00:00", "timeZone": "UTC"}
        if end or (start and defaults):
            b["end"] = {"dateTime": f"{last.isoformat()}T00:00:00", "timeZone": "UTC"}
    else:
        if start:
            b["start"] = {"dateTime": _utc(start), "timeZone": "UTC"}
        if end:
            b["end"] = {"dateTime": _utc(end), "timeZone": "UTC"}
        elif start and defaults:
            s = dt.datetime.fromisoformat(start)
            b["end"] = {"dateTime": _utc(((s if s.tzinfo else s.astimezone()) + dt.timedelta(hours=1)).isoformat()), "timeZone": "UTC"}
        if start and defaults:
            b["isAllDay"] = False
    if location is not None:
        b["location"] = {"displayName": location}
    if description is not None:
        b["body"] = {"contentType": "Text", "content": description}
    if attendees is not None:
        b["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees]
    return b


async def event_get(store, event_id):
    return summarize_event(await _api(store, "GET", f"/me/events/{_raw(event_id)}", headers=UTC, params={"$select": EVENT_FIELDS}))


async def event_add(store, **fields):
    return summarize_event(await _api(store, "POST", "/me/events", json=event_body(**fields), headers=UTC))


async def event_update(store, event_id, **fields):
    current = await event_get(store, event_id)
    fields.setdefault("all_day", current["all_day"])
    if fields.get("start") and not fields.get("end"):   # moving an event keeps its length
        if fields["all_day"]:
            span = dt.date.fromisoformat(current["end"][:10]) - dt.date.fromisoformat(current["start"][:10])
            fields["end"] = (dt.date.fromisoformat(fields["start"][:10]) + span).isoformat()
        else:
            span = dt.datetime.fromisoformat(current["end"]) - dt.datetime.fromisoformat(current["start"])
            s = dt.datetime.fromisoformat(fields["start"])
            fields["end"] = ((s if s.tzinfo else s.astimezone()) + span).isoformat()
    e = await _api(store, "PATCH", f"/me/events/{_raw(event_id)}", json=event_body(defaults=False, **fields), headers=UTC)
    return summarize_event(e)


async def event_delete(store, event_id):
    await _api(store, "DELETE", f"/me/events/{_raw(event_id)}")
    return {"deleted": True}
