"""Outlook mail and calendar end to end against tools/fake_microsoft.py (started here on a free port): the one-tap
sign-in with Clara's built-in Microsoft app, then every email_* / calendar_* tool through the Bridge, with temporary
state only. Also the Gmail-syntax translation and routing between two accounts.

    python bridge/test_outlook.py      (Bridge environment; ends with "all checks passed")
"""
import asyncio
import datetime as dt
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(tempfile.mkdtemp(prefix="clara-outlook-"))
for key, folder in {"CLARA_DATA_DIR": "data", "CLARA_WORKSPACE": "workspace", "CLARA_STATE_DIR": "state", "HERMES_HOME": "hermes"}.items():
    os.environ[key] = str(BASE / folder); (BASE / folder).mkdir()
(BASE / "hermes/.env").write_text("API_SERVER_KEY=isolated-test\n")
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
FAKE = f"http://127.0.0.1:{PORT}"
os.environ["CLARA_FAKE_MICROSOFT"] = FAKE
sys.path.insert(0, str(ROOT / "bridge"))

import httpx  # noqa: E402
import app  # noqa: E402
import connectors  # noqa: E402
import outlook  # noqa: E402

if BASE not in Path(app.store.db.execute("PRAGMA database_list").fetchone()[2]).resolve().parents:
    raise SystemExit("Refusing to run: the Bridge database is outside the test folder.")

fails = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def translation():
    now = dt.datetime(2026, 10, 6, 12, 0, tzinfo=dt.timezone.utc)
    folder, filters, kql, _ = outlook.to_graph("is:unread is:important newer_than:2d", now)
    check("unread+important+age become a $filter led by the date",
          folder == "inbox" and filters == ["receivedDateTime ge 2026-10-04T12:00:00Z", "isRead eq false", "inferenceClassification eq 'focused'"]
          and kql == "", (folder, filters, kql))
    folder, filters, kql, checks = outlook.to_graph('from:sam subject:"lunch plans" in:anywhere label:x is:unread', now)
    check("from/subject/words become a KQL search, label: is dropped", folder is None and kql == "from:sam subject:lunch subject:plans", kql)
    check("search keeps unread as a local check", any(not c({"isRead": True}) for c in checks))
    _, filters, _, _ = outlook.to_graph("after:2026/10/01 before:2026/10/03", now)
    check("after/before become a date range", filters[0].startswith("receivedDateTime ge 2026-10-0") and filters[1].startswith("receivedDateTime lt 2026-10-0"), filters)
    body = outlook.event_body(title="Trip", start="2026-10-08", all_day=True)
    check("all-day event: midnight to next midnight", body["start"]["dateTime"] == "2026-10-08T00:00:00" and body["end"]["dateTime"] == "2026-10-09T00:00:00"
          and body["isAllDay"], body)
    body = outlook.event_body(start="2026-10-08T15:00:00-04:00")
    check("timed event: sent in UTC, one hour default", body["start"] == {"dateTime": "2026-10-08T19:00:00", "timeZone": "UTC"}
          and body["end"]["dateTime"] == "2026-10-08T20:00:00", body)
    check("partial update sends only the change", outlook.event_body(defaults=False, location="Room 2") == {"location": {"displayName": "Room 2"}})
    ev = outlook.summarize_event({"id": "x", "subject": "s", "start": {"dateTime": "2026-10-08T19:00:00.0000000"},
                                  "end": {"dateTime": "2026-10-08T20:00:00.0000000"}, "showAs": "busy"})
    check("Graph's 7-digit fractions parse, times come back local with an offset",
          ev["id"] == "ms:x" and dt.datetime.fromisoformat(ev["start"]).utcoffset() is not None
          and dt.datetime.fromisoformat(ev["start"]).astimezone(dt.timezone.utc).hour == 19, ev)


async def sign_in():
    view = app._connector_view("microsoft")
    check("Microsoft has a built-in app (one tap, no secret)", view["builtin"] and not view["needs_secret"], view)
    url = connectors.start(app.store, "microsoft")
    q = parse_qs(urlparse(url).query)
    check("sign-in uses PKCE and asks for offline access", q["code_challenge_method"] == ["S256"] and "offline_access" in q["scope"][0])
    async with httpx.AsyncClient() as c:
        r = await c.get(url, follow_redirects=False)
    back = parse_qs(urlparse(r.headers["location"]).query)
    done = await connectors.finish(app.store, back["state"][0], back["code"][0])
    check("connected and shows the account", done["account"] == "me@outlook.example", done)


async def tools():
    call = lambda action, **args: app._connector_call(app.ConnectorCall(action=action, args=args))
    r = await call("email_search", query="is:unread newer_than:2d")
    emails = r.get("emails") or []
    check("search unread (filter path)", [e["subject"] for e in emails] == ["Invoice 77 is due"] and emails[0]["id"].startswith("ms:")
          and "untrusted" in r.get("note", "").lower(), r)
    r = await call("email_search", query="from:sam lunch")
    check("search words (KQL path)", [e["subject"] for e in r.get("emails") or []] == ["Lunch Thursday?"], r)
    first = emails[0]["id"]
    r = await call("email_read", id=first)
    body = (r.get("email") or {}).get("body", "")
    check("read an email whose id has / + = in it, as text", "Invoice 77" in body and r["email"]["message_id"] == "<m1@vendor>", r)
    r = await call("email_read", id=next(e["id"] for e in (await call("email_search", query="lunch"))["emails"]))
    check("HTML email comes back as text", r.get("email", {}).get("body", "").strip() == "Want to grab lunch Thursday?", r)

    with patch.object(app, "_phone_approval", new=AsyncMock(return_value="deny")) as ask:
        r = await call("email_send", to="sam@example.com", subject="Hi", body="Yes!")
    check("send asks the phone and respects no", ask.await_count == 1 and "didn't approve" in r.get("error", ""), r)
    with patch.object(app, "_phone_approval", new=AsyncMock(return_value="once")):
        r1 = await call("email_send", to="sam@example.com", subject="Hi", body="See you there")
        r2 = await call("email_send", to="billing@vendor.example", body="Paid, thanks", reply_to_id=first)
        r3 = await call("email_draft", to="sam@example.com", subject="Draft", body="Maybe")
        r4 = await call("email_draft", to="billing@vendor.example", body="Will pay", reply_to_id=first)
    async with httpx.AsyncClient() as c:
        st = (await c.get(FAKE + "/_state")).json()
    sent = st["sent"][-1]["message"] if st["sent"] else {}
    check("new email sent with sendMail", r1.get("sent") and sent.get("subject") == "Hi" and sent["toRecipients"][0]["emailAddress"]["address"] == "sam@example.com", st["sent"])
    check("reply keeps the thread", r2.get("sent") and r2["subject"] == "Re: Invoice 77 is due" and st["replies"][-1]["comment"] == "Paid, thanks", (r2, st["replies"]))
    check("draft and reply draft saved (not sent)", r3.get("draft_id", "").startswith("ms:") and r4.get("draft_id", "").startswith("ms:")
          and "Outlook" in r3.get("note", "") and len(st["sent"]) == 1, (r3, r4))

    now = dt.datetime.now().astimezone()
    r = await call("calendar_events", start=now.isoformat(), end=(now + dt.timedelta(days=4)).isoformat(), limit=1)
    titles = [e["title"] for e in r.get("events") or []]
    check("calendar lists events (first page only by default)", titles == ["Dentist"], r)
    tomorrow = (now + dt.timedelta(days=1)).date().isoformat()
    r = await call("calendar_free", day=tomorrow, minutes=60)
    dentist = next(e for e in (await outlook.events(app.store, now.isoformat(), (now + dt.timedelta(days=4)).isoformat())) if e["title"] == "Dentist")
    ds = dt.datetime.fromisoformat(dentist["start"])
    free = [(dt.datetime.fromisoformat(s["start"]), dt.datetime.fromisoformat(s["end"])) for s in r.get("free") or []]
    check("free slots go around the Outlook event", free and not any(s < ds < e for s, e in free), (r, dentist))
    all_events = await outlook.events(app.store, now.isoformat(), (now + dt.timedelta(days=4)).isoformat(), limit=1, all_pages=True)
    check("calendar follows Graph's next-page links", {"Dentist", "Holiday"} <= {e["title"] for e in all_events}, all_events)
    holiday = next(e for e in all_events if e["title"] == "Holiday")
    check("all-day events keep their date and 'free' shows as not busy", holiday["all_day"] and len(holiday["start"]) == 10 and not holiday["busy"], holiday)

    with patch.object(app, "_phone_approval", new=AsyncMock(return_value="once")) as ask:
        added = await call("calendar_add", title="Call mom", start=f"{tomorrow}T18:00")
        moved = await call("calendar_update", event_id=dentist["id"], start=f"{tomorrow}T16:30")
        gone = await call("calendar_delete", event_id=added.get("id", "x"))
    check("add/change/delete each asked the phone", ask.await_count == 3, ask.await_args_list)
    check("added event comes back with an ms: id", added.get("id", "").startswith("ms:") and added.get("title") == "Call mom", added)
    length = dt.datetime.fromisoformat(moved["end"]) - dt.datetime.fromisoformat(moved["start"]) if moved.get("end") else None
    check("moving keeps the length", length == dt.timedelta(hours=1) and dt.datetime.fromisoformat(moved["start"]).hour == 16, moved)
    check("delete", gone == {"deleted": True}, gone)
    async with httpx.AsyncClient() as c:
        st = (await c.get(FAKE + "/_state")).json()
    import broker
    tok = json.loads(broker.unseal(app.store.connector("microsoft")["tokens"]))
    old_refresh = tok["refresh_token"]; tok["expires_at"] = 0
    app.store.save_connector("microsoft", tokens=broker.seal(json.dumps(tok)))
    r = await call("email_search", query="is:unread")
    tok = json.loads(broker.unseal(app.store.connector("microsoft")["tokens"]))
    check("expired sign-in refreshes without a secret and keeps Microsoft's new refresh token",
          r.get("emails") and tok["refresh_token"] != old_refresh, r)
    check("calendar reads ask Graph for UTC, mail reads for text", 'outlook.timezone="UTC"' in st["prefer"] and 'outlook.body-content-type="text"' in st["prefer"])


async def routing():
    real = app._connector_view
    def both(p):
        v = real(p)
        return {**v, "connected": True} if p in ("google", "microsoft") else v
    with patch.object(app, "_connector_view", side_effect=both):
        check("both connected: id decides", app._mail_account({}, "ms:abc") == "microsoft" and app._mail_account({}, "18f2ab") == "google")
        check("both connected: account names", app._mail_account({"account": "outlook"}) == "microsoft" and app._mail_account({"account": "Gmail"}) == "google")
        check("both connected: default is the first (Google)", app._mail_account({}) == "google")
        g = AsyncMock(return_value=[{"id": "g1", "subject": "From Gmail"}])
        with patch.object(app.connectors, "gmail_search", new=g):
            r = await app._connector_call(app.ConnectorCall(action="email_search", args={"query": "is:unread"}))
        accounts = sorted(e.get("account", "") for e in r.get("emails", []))
        check("both connected: search covers both and labels each", accounts == ["Google", "Microsoft"], r)
        with patch.object(app.connectors, "calendar_events", new=AsyncMock(return_value=[])), \
             patch.object(app.connectors, "gmail_search", new=AsyncMock(return_value=[])):
            r = await app._connector_call(app.ConnectorCall(action="email_search", args={"query": "is:unread", "account": "outlook"}))
        check("account='outlook' searches only Outlook", all(e["id"].startswith("ms:") for e in r.get("emails", [])) and r.get("emails"), r)
    payload_text = (ROOT / "bridge/app.py").read_text()
    check("instructions name Outlook when it's connected", "Microsoft (Outlook)" in payload_text)
    connectors.PROVIDERS["microsoft"]["hosts"] = ["graph.microsoft.com"]
    try:
        connectors.resolve_url(app.store, "microsoft", "https://evil.example/v1.0/me")
        check("calls can't leave Microsoft's hosts", False)
    except PermissionError:
        check("calls can't leave Microsoft's hosts", True)


async def main():
    translation()
    await sign_in()
    await tools()
    await routing()


fake = subprocess.Popen([sys.executable, str(ROOT / "tools/fake_microsoft.py"), str(PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    for _ in range(100):
        try:
            httpx.get(FAKE + "/_state", timeout=1); break
        except httpx.HTTPError:
            time.sleep(0.1)
    asyncio.run(main())
finally:
    fake.terminate()
    import shutil; shutil.rmtree(BASE, ignore_errors=True)
print("all checks passed" if not fails else f"{len(fails)} failed: {fails}")
sys.exit(1 if fails else 0)
