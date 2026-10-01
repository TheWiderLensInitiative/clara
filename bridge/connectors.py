"""Connectors: Clara using the user's accounts (Google, Microsoft, Spotify, Notion…) without ever seeing their tokens.

Every service is defined in connector_defs.py. OAuth services use the user's own app/client (so it stays theirs): sign-in
happens on the phone, which catches the redirect on 127.0.0.1 (see REDIRECT) and hands the one-time code to the Bridge;
PKCE is always used. Token services take a personal token pasted in the app. Either way the secrets are sealed with the
key broker, calls only go to that service's own hosts, and the token is scrubbed from anything returned to Clara.
"""
import asyncio
import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import time
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from urllib.parse import urlparse

import httpx

import broker
from connector_defs import PROVIDERS, REDIRECT, REDIRECT_PORT

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3"
YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"

import os as _os
if _os.environ.get("CLARA_FAKE_GOOGLE"):   # tests only: a local stand-in for Google (tools/fake_google.py)
    _fake, _pub = _os.environ["CLARA_FAKE_GOOGLE"], _os.environ.get("CLARA_FAKE_GOOGLE_PUBLIC", _os.environ["CLARA_FAKE_GOOGLE"])
    PROVIDERS["google"].update(auth_url=_pub + "/auth", token_url=_fake + "/token", revoke_url=_fake + "/revoke")
    PROVIDERS["google"]["hosts"] = PROVIDERS["google"]["hosts"] + [urlparse(_fake).netloc]
    GMAIL, CAL, YT_UPLOAD = _fake + "/gmail/v1/users/me", _fake + "/calendar/v3", _fake + "/upload/youtube/v3/videos"


if _os.environ.get("CLARA_TEST_OVERRIDES"):   # tests only: {"spotify": {"auth_url": ..., "hosts": [...]}, ...}
    for _p, _f in json.loads(_os.environ["CLARA_TEST_OVERRIDES"]).items():
        PROVIDERS[_p].update({k: tuple(v) if k == "account" else v for k, v in _f.items()})


def override(provider: str, **fields):   # tests: point a provider at a local stand-in
    PROVIDERS[provider].update(fields)


class NotConnected(Exception):
    def __init__(self, provider, why=None):
        super().__init__(why or f"{PROVIDERS[provider]['name']} isn't connected")
        self.provider = provider


# --- OAuth sign-in -------------------------------------------------------------------------------------------
_pending: dict = {}   # state -> {provider, verifier, redirect_uri, created}


def start(store, provider: str, redirect_uri: str = REDIRECT) -> str:
    """Authorization URL for the phone's browser (PKCE S256 + random state)."""
    p = PROVIDERS[provider]
    if p["kind"] != "oauth":
        raise ValueError("this service uses a token, not a sign-in")
    client = get_client(store, provider)
    if not client:
        raise ValueError("no client")
    if not re.fullmatch(r"http://(127\.0\.0\.1|localhost):\d{2,5}/cb", redirect_uri):
        raise ValueError("redirect must be a loopback URL")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    for st in [st for st, v in _pending.items() if time.time() - v["created"] > 900]:
        _pending.pop(st, None)
    _pending[state] = {"provider": provider, "verifier": verifier, "redirect_uri": redirect_uri, "created": time.time()}
    q = {"client_id": client["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(p["scopes"]),
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256", **p.get("extra", {})}
    return p["auth_url"] + "?" + str(httpx.QueryParams(q))


def _client_form(client, extra):
    f = {"client_id": client["client_id"], **extra}
    if client.get("client_secret"):
        f["client_secret"] = client["client_secret"]
    return f


async def finish(store, state: str, code: str) -> dict:
    """Exchange the one-time code for tokens and remember them (encrypted)."""
    pend = _pending.pop(state, None)
    if not pend or time.time() - pend["created"] > 900:
        raise ValueError("this sign-in link expired; start again")
    provider = pend["provider"]
    p, client = PROVIDERS[provider], get_client(store, provider)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(p["token_url"], data=_client_form(client, {"code": code, "redirect_uri": pend["redirect_uri"],
                                                                     "grant_type": "authorization_code", "code_verifier": pend["verifier"]}))
    try:
        tok = r.json()
    except Exception:
        tok = {"error": r.text[:200]}
    if r.status_code >= 400 or "access_token" not in tok:
        raise ValueError(f"{p['name']} said: {tok.get('error_description') or tok.get('error') or r.status_code}")
    if not tok.get("refresh_token"):
        raise ValueError(f"{p['name']} didn't allow offline access; remove Clara's access in your {p['name']} account settings and connect again")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    store.save_connector(provider, tokens=broker.seal(json.dumps(tok)), scopes=tok.get("scope", " ".join(p["scopes"])))
    account = await _account(store, provider, tok)
    store.save_connector(provider, account=account)
    return {"provider": provider, "account": account}


def _dig(data, spec):
    for key in spec:
        v = data
        for k in (key if isinstance(key, tuple) else (key,)):
            v = v.get(k) if isinstance(v, dict) else None
        if v:
            return str(v)
    return ""


async def _account(store, provider, tok=None) -> str:
    """A friendly name for the connected account (email, username…)."""
    method, url, keys = PROVIDERS[provider]["account"]
    try:
        if method == "id_token":
            payload = (tok or {}).get("id_token", "").split(".")[1]
            return _dig(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))), keys)
        r = await request(store, provider, method, url, body=None if method == "GET" else None)
        return _dig(r.json(), keys) or PROVIDERS[provider]["name"]
    except Exception:
        return PROVIDERS[provider]["name"]


def _builtin_clients() -> dict:
    """The Wider Lens's own sign-in apps (bridge/builtin_clients.json), so people connect in one tap without a developer
    console. Desktop-app clients: Google treats their secret as not confidential; users still approve on the service's
    own screen, with PKCE, from their own PC."""
    try:
        return json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin_clients.json")))
    except (OSError, ValueError):
        return {}


def builtin_client(provider):
    return _builtin_clients().get(provider)


def get_client(store, provider):
    """The user's own app if they set one up, otherwise Clara's built-in one (if this service has it)."""
    row = store.connector(provider)
    if not row or not row.get("client"):
        return builtin_client(provider)
    return json.loads(broker.unseal(row["client"]))


async def token(store, provider: str) -> str:
    """A valid OAuth access token, refreshed when needed."""
    row = store.connector(provider)
    if not row or not row.get("tokens"):
        raise NotConnected(provider)
    tok = json.loads(broker.unseal(row["tokens"]))
    if time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    client, p = get_client(store, provider), PROVIDERS[provider]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(p["token_url"], data=_client_form(client, {"refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}))
    try:
        new = r.json()
    except Exception:
        new = {"error": r.status_code}
    if r.status_code >= 400 or "access_token" not in new:
        if new.get("error") in ("invalid_grant", "invalid_client"):   # revoked or expired: the user has to connect again
            store.save_connector(provider, tokens=None)
            raise NotConnected(provider, f"{p['name']} access was revoked or expired")
        raise RuntimeError(f"couldn't refresh the {p['name']} token ({new.get('error') or r.status_code})")
    tok.update(access_token=new["access_token"], expires_at=time.time() + int(new.get("expires_in", 3600)) - 60)
    if new.get("refresh_token"):   # some services rotate refresh tokens
        tok["refresh_token"] = new["refresh_token"]
    store.save_connector(provider, tokens=broker.seal(json.dumps(tok)))
    return tok["access_token"]


# --- token services -------------------------------------------------------------------------------------------
async def save_token(store, provider: str, fields: dict) -> dict:
    """Validate and store a pasted token (and base URL), then check it works."""
    p = PROVIDERS[provider]
    clean = {}
    for f in p["fields"]:
        v = str(fields.get(f["key"]) or "").strip().rstrip("/") if f["key"] == "base_url" else str(fields.get(f["key"]) or "").strip()
        if not re.fullmatch(f["pattern"], v):
            raise ValueError(f"That doesn't look like a {p['name']} {f['label'].lower()}.")
        clean[f["key"]] = v
    old = store.connector(provider)
    store.save_connector(provider, tokens=broker.seal(json.dumps(clean)))
    try:
        method, url, keys = p["account"]
        r = await request(store, provider, method, url)
        if r.status_code >= 400:
            raise ValueError(f"{p['name']} rejected it (HTTP {r.status_code}). Check the token and its permissions.")
        account = _dig(r.json(), keys) or p["name"]
    except ValueError:
        store.save_connector(provider, tokens=(old or {}).get("tokens"))
        raise
    except httpx.HTTPError as e:
        store.save_connector(provider, tokens=(old or {}).get("tokens"))
        raise ValueError(f"Couldn't reach {p['name']}: {type(e).__name__}")
    store.save_connector(provider, account=account)
    return {"provider": provider, "account": account}


def _creds(store, provider) -> dict:
    row = store.connector(provider)
    if not row or not row.get("tokens"):
        raise NotConnected(provider)
    return json.loads(broker.unseal(row["tokens"]))


# --- the one way any connector call goes out -------------------------------------------------------------------
def allowed_hosts(store, provider) -> list[str]:
    p = PROVIDERS[provider]
    hosts = []
    for h in p["hosts"]:
        if h == "{base_url}":
            try:
                hosts.append(urlparse(_creds(store, provider).get("base_url", "")).netloc)
            except NotConnected:
                pass
        else:
            hosts.append(h)
    return hosts


def resolve_url(store, provider, url: str) -> str:
    """Fill in {base_url}/{token} placeholders and refuse anything outside the service's own hosts."""
    p = PROVIDERS[provider]
    if "{" in url and p["kind"] == "token":   # {base_url}, {page_id}… (never {token}: that's filled at send time)
        for k, v in _creds(store, provider).items():
            if k != "token":
                url = url.replace("{" + k + "}", v)
    u = urlparse(url.replace("{token}", "TOKEN"))
    if u.scheme not in ("https", "http") or u.netloc not in allowed_hosts(store, provider) or "@" in u.netloc:
        raise PermissionError(f"{p['name']} calls may only go to {', '.join(allowed_hosts(store, provider))}")
    if u.scheme == "http" and not (p["hosts"] == ["{base_url}"] or u.netloc.startswith("127.0.0.1")):
        raise PermissionError("plain http is only allowed for self-hosted services")
    return url


async def request(store, provider, method, url, *, query=None, body=None, content=None, headers=None, timeout=60):
    """Authenticated call to a connected service (no redirects, so the token can't be carried elsewhere)."""
    p = PROVIDERS[provider]
    url = resolve_url(store, provider, url)
    h = {**p.get("headers", {}), **{k: v for k, v in (headers or {}).items() if k.lower() not in ("authorization", "host", "cookie")}}
    if p["kind"] == "oauth":
        h["Authorization"] = f"Bearer {await token(store, provider)}"
    else:
        cred = _creds(store, provider)
        if p["auth"] == "bearer":
            h["Authorization"] = f"Bearer {cred['token']}"
        elif p["auth"] == "bot":
            h["Authorization"] = f"Bot {cred['token']}"
        elif p["auth"] == "path":
            url = url.replace("{token}", cred["token"])
    kw = {"params": query or None, "headers": h}
    if content is not None:
        kw["content"] = content
    elif body is not None:
        kw["json"] = body
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as c:
        r = await c.request(method, url, **kw)
        if r.status_code == 401 and p["kind"] == "oauth":   # token died early: refresh once
            row = store.connector(provider)
            tok = json.loads(broker.unseal(row["tokens"]))
            tok["expires_at"] = 0
            store.save_connector(provider, tokens=broker.seal(json.dumps(tok)))
            kw["headers"]["Authorization"] = f"Bearer {await token(store, provider)}"
            r = await c.request(method, url, **kw)
    return r


def secrets_of(store, provider) -> list[str]:
    """Everything that must never appear in what Clara sees."""
    out = []
    try:
        row = store.connector(provider)
        if row and row.get("tokens"):
            t = json.loads(broker.unseal(row["tokens"]))
            out += [v for k, v in t.items() if k in ("access_token", "refresh_token", "token", "id_token") and v]
    except Exception:
        pass
    return out


def is_read(provider, method, url) -> bool:
    if method.upper() in ("GET", "HEAD"):
        return True
    path = urlparse(url).path
    return method.upper() == "POST" and any(re.search(rx, path) for rx in PROVIDERS[provider].get("read_posts", []))


async def api(store, provider, method, url, **kw):
    """JSON call used by the Gmail/Calendar helpers."""
    r = await request(store, provider, method, url, query=kw.get("params"), body=kw.get("json"))
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message")
        except Exception:
            msg = r.text[:200]
        raise RuntimeError(f"{PROVIDERS[provider]['name']} API error {r.status_code}: {msg}")
    return r.json() if r.content else {}


async def revoke(store, provider):
    p = PROVIDERS[provider]
    row = store.connector(provider)
    if p["kind"] == "oauth" and p.get("revoke_url") and row and row.get("tokens"):
        try:
            tok = json.loads(broker.unseal(row["tokens"]))
            async with httpx.AsyncClient(timeout=15) as c:
                await c.post(p["revoke_url"], data={"token": tok.get("refresh_token") or tok.get("access_token")})
        except Exception:
            pass
    store.save_connector(provider, tokens=None, account="")


# --- Gmail ------------------------------------------------------------------------------------------
def _header(msg, name):
    return next((h["value"] for h in msg.get("payload", {}).get("headers", []) if h["name"].lower() == name.lower()), "")


def _body_text(part) -> str:
    """Plain text of a message: prefer text/plain, fall back to stripped HTML."""
    def walk(p):
        yield p
        for c in p.get("parts", []) or []:
            yield from walk(c)
    plain, html = [], []
    for p in walk(part):
        data = (p.get("body") or {}).get("data")
        if not data:
            continue
        text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
        (plain if p.get("mimeType") == "text/plain" else html if p.get("mimeType") == "text/html" else plain).append(text)
    if plain:
        return "\n".join(plain)
    h = "\n".join(html)
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h)
    h = re.sub(r"&nbsp;", " ", h)
    return re.sub(r"\n{3,}", "\n\n", h).strip()


def summarize_message(m, with_body=False, body_limit=6000):
    out = {"id": m["id"], "thread_id": m.get("threadId"), "from": _header(m, "From"), "to": _header(m, "To"),
           "subject": _header(m, "Subject"), "date": _header(m, "Date"), "snippet": m.get("snippet", ""),
           "unread": "UNREAD" in m.get("labelIds", []), "important": "IMPORTANT" in m.get("labelIds", [])}
    if with_body:
        out["body"] = _body_text(m.get("payload", {}))[:body_limit]
        out["message_id"] = _header(m, "Message-ID")
        out["cc"] = _header(m, "Cc")
    return out


async def gmail_search(store, query="", limit=10):
    lst = await api(store, "google", "GET", f"{GMAIL}/messages", params={"q": query or "in:inbox", "maxResults": max(1, min(limit, 25))})
    out = []
    for ref in lst.get("messages", []):
        m = await api(store, "google", "GET", f"{GMAIL}/messages/{ref['id']}",
                      params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]})
        out.append(summarize_message(m))
    return out


async def gmail_read(store, msg_id):
    m = await api(store, "google", "GET", f"{GMAIL}/messages/{msg_id}", params={"format": "full"})
    return summarize_message(m, with_body=True)


def build_mime(to, subject, body, cc=None, in_reply_to=None, sender=None):
    em = EmailMessage()
    em["To"] = to
    if cc:
        em["Cc"] = cc
    if sender:
        em["From"] = sender
    em["Subject"] = subject
    if in_reply_to:
        em["In-Reply-To"] = in_reply_to
        em["References"] = in_reply_to
    em.set_content(body)
    return base64.urlsafe_b64encode(em.as_bytes()).decode()


def valid_addresses(field: str) -> bool:
    addrs = [a for _, a in getaddresses([field or ""]) if a]
    return bool(addrs) and all(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a) for a in addrs)


async def gmail_draft(store, to, subject, body, cc=None, reply_to_id=None):
    msg = {"raw": None}
    thread, in_reply_to = None, None
    if reply_to_id:
        orig = await gmail_read(store, reply_to_id)
        thread, in_reply_to = orig.get("thread_id"), orig.get("message_id")
        if not subject:
            subject = "Re: " + re.sub(r"^(re:\s*)+", "", orig["subject"], flags=re.I)
    msg["raw"] = build_mime(to, subject, body, cc, in_reply_to)
    if thread:
        msg["threadId"] = thread
    d = await api(store, "google", "POST", f"{GMAIL}/drafts", json={"message": msg})
    return {"draft_id": d.get("id"), "subject": subject}


async def gmail_send(store, to, subject, body, cc=None, reply_to_id=None):
    thread, in_reply_to = None, None
    if reply_to_id:
        orig = await gmail_read(store, reply_to_id)
        thread, in_reply_to = orig.get("thread_id"), orig.get("message_id")
        if not subject:
            subject = "Re: " + re.sub(r"^(re:\s*)+", "", orig["subject"], flags=re.I)
    msg = {"raw": build_mime(to, subject, body, cc, in_reply_to)}
    if thread:
        msg["threadId"] = thread
    s = await api(store, "google", "POST", f"{GMAIL}/messages/send", json=msg)
    return {"sent": True, "id": s.get("id"), "subject": subject}


# --- Calendar ---------------------------------------------------------------------------------------
def _when(e, key):
    v = e.get(key) or {}
    return v.get("dateTime") or v.get("date") or ""


def summarize_event(e):
    return {"id": e["id"], "title": e.get("summary", "(no title)"), "start": _when(e, "start"), "end": _when(e, "end"),
            "all_day": "date" in (e.get("start") or {}), "location": e.get("location", ""), "description": (e.get("description") or "")[:500],
            "attendees": [a.get("email") for a in e.get("attendees", [])][:20], "link": e.get("htmlLink", "")}


def _iso(t: str | None, default: dt.datetime) -> str:
    if not t:
        return default.isoformat()
    d = dt.datetime.fromisoformat(t)
    if d.tzinfo is None:
        d = d.astimezone()
    return d.isoformat()


async def calendar_events(store, start=None, end=None, query=None, limit=25):
    now = dt.datetime.now().astimezone()
    params = {"timeMin": _iso(start, now), "timeMax": _iso(end, now + dt.timedelta(days=7)), "singleEvents": "true",
              "orderBy": "startTime", "maxResults": max(1, min(limit, 50))}
    if query:
        params["q"] = query
    r = await api(store, "google", "GET", f"{CAL}/calendars/primary/events", params=params)
    return [summarize_event(e) for e in r.get("items", [])]


def event_body(title=None, start=None, end=None, all_day=False, location=None, description=None, attendees=None):
    b = {}
    if title is not None:
        b["summary"] = title
    if start:
        if all_day:
            b["start"] = {"date": start[:10]}
            b["end"] = {"date": (end or start)[:10] if end and end[:10] != start[:10] else
                        (dt.date.fromisoformat(start[:10]) + dt.timedelta(days=1)).isoformat()}
        else:
            s = dt.datetime.fromisoformat(start)
            s = s if s.tzinfo else s.astimezone()
            e = dt.datetime.fromisoformat(end) if end else s + dt.timedelta(hours=1)
            e = e if e.tzinfo else e.astimezone()
            b["start"], b["end"] = {"dateTime": s.isoformat()}, {"dateTime": e.isoformat()}
    if location is not None:
        b["location"] = location
    if description is not None:
        b["description"] = description
    if attendees:
        b["attendees"] = [{"email": a} for a in attendees]
    return b


async def calendar_add(store, **fields):
    e = await api(store, "google", "POST", f"{CAL}/calendars/primary/events", json=event_body(**fields))
    return summarize_event(e)


async def calendar_update(store, event_id, **fields):
    e = await api(store, "google", "PATCH", f"{CAL}/calendars/primary/events/{event_id}", json=event_body(**fields))
    return summarize_event(e)


async def calendar_delete(store, event_id):
    await api(store, "google", "DELETE", f"{CAL}/calendars/primary/events/{event_id}")
    return {"deleted": True}


async def calendar_get(store, event_id):
    return summarize_event(await api(store, "google", "GET", f"{CAL}/calendars/primary/events/{event_id}"))


async def free_slots(store, day: str, minutes=60, work_start="09:00", work_end="18:00"):
    """Open gaps on a day between the user's events (inside working hours)."""
    d = dt.date.fromisoformat(day[:10])
    tz = dt.datetime.now().astimezone().tzinfo
    ws = dt.datetime.combine(d, dt.time.fromisoformat(work_start), tz)
    we = dt.datetime.combine(d, dt.time.fromisoformat(work_end), tz)
    events = await calendar_events(store, ws.isoformat(), we.isoformat(), limit=50)
    busy = []
    for e in events:
        if e["all_day"]:
            continue
        busy.append((dt.datetime.fromisoformat(e["start"]), dt.datetime.fromisoformat(e["end"])))
    busy.sort()
    slots, cur = [], ws
    for s, e in busy:
        if s - cur >= dt.timedelta(minutes=minutes):
            slots.append({"start": cur.isoformat(), "end": s.isoformat()})
        cur = max(cur, e)
    if we - cur >= dt.timedelta(minutes=minutes):
        slots.append({"start": cur.isoformat(), "end": we.isoformat()})
    return slots


# --- YouTube: post a video from the workspace -------------------------------------------------------------------
async def youtube_upload(store, path, title, description="", privacy="private", tags=None, made_for_kids=False):
    """Resumable upload of a workspace video to the user's channel. Vertical videos under ~3 min become Shorts."""
    data = path.read_bytes()
    meta = {"snippet": {"title": title[:100], "description": description[:4900], "tags": (tags or [])[:30], "categoryId": "22"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids)}}
    r = await request(store, "google", "POST", YT_UPLOAD,
                      query={"uploadType": "resumable", "part": "snippet,status"}, body=meta,
                      headers={"X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(len(data))})
    if r.status_code >= 400 or "location" not in r.headers:
        raise RuntimeError(f"YouTube refused the upload ({r.status_code}): {r.text[:200]}")
    up = await request(store, "google", "PUT", r.headers["location"], content=data, headers={"Content-Type": "video/mp4"}, timeout=900)
    if up.status_code >= 400:
        raise RuntimeError(f"YouTube upload failed ({up.status_code}): {up.text[:200]}")
    v = up.json()
    return {"video_id": v.get("id"), "url": f"https://youtu.be/{v.get('id')}", "privacy": privacy, "title": title}


# --- Social posting ---------------------------------------------------------------------------------------------
X_API = "https://api.x.com/2"
GRAPH = "https://graph.facebook.com/v23.0"
CHUNK = 4 * 1024 * 1024


def _mime(path):
    ext = path.suffix.lower()
    return {".mp4": "video/mp4", ".mov": "video/quicktime", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "application/octet-stream")


async def _x_media(store, path):
    """X's v2 chunked upload: initialize, append ≤4 MB pieces, finalize, wait for processing."""
    data, mime = path.read_bytes(), _mime(path)
    cat = "tweet_video" if mime.startswith("video") else ("tweet_gif" if mime == "image/gif" else "tweet_image")
    r = await request(store, "x", "POST", f"{X_API}/media/upload/initialize",
                      body={"media_type": mime, "total_bytes": len(data), "media_category": cat})
    if r.status_code >= 400:
        raise RuntimeError(f"X refused the upload ({r.status_code}): {r.text[:200]}")
    mid = r.json()["data"]["id"]
    for i in range(0, len(data), CHUNK):
        boundary = "clara" + os.urandom(8).hex()
        part = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"segment_index\"\r\n\r\n{i // CHUNK}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"{path.name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data[i:i + CHUNK] + f"\r\n--{boundary}--\r\n".encode()
        a = await request(store, "x", "POST", f"{X_API}/media/upload/{mid}/append", content=part,
                          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=300)
        if a.status_code >= 400:
            raise RuntimeError(f"X upload failed ({a.status_code}): {a.text[:200]}")
    f = await request(store, "x", "POST", f"{X_API}/media/upload/{mid}/finalize")
    if f.status_code >= 400:
        raise RuntimeError(f"X couldn't finish the upload ({f.status_code}): {f.text[:200]}")
    info = (f.json().get("data") or {}).get("processing_info")
    for _ in range(60):   # videos are processed after upload
        if not info or info.get("state") == "succeeded":
            return mid
        if info.get("state") == "failed":
            raise RuntimeError(f"X couldn't process the video: {info.get('error')}")
        await asyncio.sleep(min(10, info.get("check_after_secs", 3)))
        st = await request(store, "x", "GET", f"{X_API}/media/upload", query={"command": "STATUS", "media_id": mid})
        info = (st.json().get("data") or {}).get("processing_info")
    raise RuntimeError("X took too long processing the video")


async def x_post(store, texts, media=None):
    """A post (or a thread: one post per text, each replying to the last). Media goes on the first post."""
    out, reply_to = [], None
    for i, text in enumerate(texts):
        body = {"text": text[:4000]}
        if i == 0 and media is not None:
            body["media"] = {"media_ids": [await _x_media(store, media)]}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        r = await request(store, "x", "POST", f"{X_API}/tweets", body=body)
        if r.status_code >= 400:
            raise RuntimeError(f"X refused the post ({r.status_code}): {r.text[:200]}")
        reply_to = r.json()["data"]["id"]
        out.append(reply_to)
    user = await request(store, "x", "GET", f"{X_API}/users/me")
    handle = (user.json().get("data") or {}).get("username", "i")
    return {"url": f"https://x.com/{handle}/status/{out[0]}", "ids": out}


async def _meta_rupload(store, url, data):
    """Meta's resumable upload host wants 'Authorization: OAuth <token>', not Bearer."""
    url = resolve_url(store, "meta", url)
    tok = _creds(store, "meta")["token"]
    async with httpx.AsyncClient(timeout=900, follow_redirects=False) as c:
        r = await c.post(url, content=data, headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(data))})
    if r.status_code >= 400:
        raise RuntimeError(f"Meta upload failed ({r.status_code}): {r.text[:200]}")


async def facebook_post(store, text, media=None):
    """A Page post: text (and link), a photo, or a video (vertical short videos go up as Reels)."""
    cred = _creds(store, "meta")
    page = cred["page_id"]
    if media is None:
        r = await request(store, "meta", "POST", f"{GRAPH}/{page}/feed", body={"message": text})
        if r.status_code >= 400:
            raise RuntimeError(f"Facebook refused the post ({r.status_code}): {r.text[:200]}")
        pid = r.json()["id"]
        return {"url": f"https://www.facebook.com/{pid}", "id": pid}
    data, mime = media.read_bytes(), _mime(media)
    if mime.startswith("image"):
        boundary = "clara" + os.urandom(8).hex()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{text}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"source\"; filename=\"{media.name}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        r = await request(store, "meta", "POST", f"{GRAPH}/{page}/photos", content=body,
                          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=300)
        if r.status_code >= 400:
            raise RuntimeError(f"Facebook refused the photo ({r.status_code}): {r.text[:200]}")
        pid = r.json().get("post_id") or r.json()["id"]
        return {"url": f"https://www.facebook.com/{pid}", "id": pid}
    # video → Reel (three phases: start, upload to rupload, finish & publish)
    st = await request(store, "meta", "POST", f"{GRAPH}/{page}/video_reels", body={"upload_phase": "start"})
    if st.status_code >= 400:
        raise RuntimeError(f"Facebook refused the video ({st.status_code}): {st.text[:200]}")
    vid = st.json()["video_id"]
    await _meta_rupload(store, st.json().get("upload_url") or f"https://rupload.facebook.com/video-upload/v23.0/{vid}", data)
    fin = await request(store, "meta", "POST", f"{GRAPH}/{page}/video_reels",
                        query={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": text})
    if fin.status_code >= 400:
        raise RuntimeError(f"Facebook couldn't publish the video ({fin.status_code}): {fin.text[:200]}")
    return {"url": f"https://www.facebook.com/reel/{vid}", "id": vid}


async def instagram_post(store, text, media):
    """An Instagram Reel from a workspace video (resumable upload, then publish once Instagram has processed it)."""
    cred = _creds(store, "meta")
    ig = cred.get("ig_user_id")
    if not ig:
        raise RuntimeError("Add your Instagram account ID in Connectors → Facebook Page & Instagram first.")
    if not _mime(media).startswith("video"):
        raise RuntimeError("Instagram posts from Clara are Reels: give a video.")
    c = await request(store, "meta", "POST", f"{GRAPH}/{ig}/media",
                      query={"media_type": "REELS", "upload_type": "resumable", "caption": text[:2200]})
    if c.status_code >= 400:
        raise RuntimeError(f"Instagram refused the Reel ({c.status_code}): {c.text[:200]}")
    cid = c.json()["id"]
    await _meta_rupload(store, c.json().get("uri") or f"https://rupload.facebook.com/ig-api-upload/v23.0/{cid}", media.read_bytes())
    for _ in range(90):
        s = await request(store, "meta", "GET", f"{GRAPH}/{cid}", query={"fields": "status_code"})
        code = s.json().get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram couldn't process the video ({code})")
        await asyncio.sleep(5)
    else:
        raise RuntimeError("Instagram took too long processing the video")
    p = await request(store, "meta", "POST", f"{GRAPH}/{ig}/media_publish", query={"creation_id": cid})
    if p.status_code >= 400:
        raise RuntimeError(f"Instagram couldn't publish ({p.status_code}): {p.text[:200]}")
    mid = p.json()["id"]
    link = await request(store, "meta", "GET", f"{GRAPH}/{mid}", query={"fields": "permalink"})
    return {"url": link.json().get("permalink") or "https://www.instagram.com/", "id": mid}


def reddit_submit_link(subreddit, title, text="", url=""):
    """Reddit closed self-serve API apps in 2025, so Clara prepares the post and the user taps Post themselves."""
    from urllib.parse import quote
    sub = re.sub(r"^/?r/", "", subreddit.strip()).strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", sub):
        raise ValueError("That isn't a subreddit name.")
    q = f"title={quote(title[:300])}"
    q += f"&url={quote(url)}" if url else f"&selftext=true&text={quote(text[:38000])}"
    return f"https://www.reddit.com/r/{sub}/submit?{q}", sub
