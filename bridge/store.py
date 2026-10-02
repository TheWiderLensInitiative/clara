"""SQLite persistence for the Clara Bridge: devices, conversations, messages, activity, approvals, router log."""
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid

from paths import DB
DB_PATH = str(DB)

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, name TEXT, token_hash TEXT UNIQUE, created REAL, last_seen REAL);
CREATE TABLE IF NOT EXISTS pairing_codes (code TEXT PRIMARY KEY, expires REAL);
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL, active_run TEXT);
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT, route TEXT, run_id TEXT, created REAL);
CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, run_id TEXT, kind TEXT, tool TEXT, detail TEXT, created REAL);
CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, conversation_id TEXT, run_id TEXT, description TEXT, command TEXT, choices TEXT, status TEXT, created REAL, resolved REAL);
CREATE TABLE IF NOT EXISTS router_log (message_id TEXT PRIMARY KEY, text TEXT, route TEXT, source TEXT, confidence REAL, ms REAL, corrected TEXT, created REAL);
CREATE TABLE IF NOT EXISTS job_conversations (job_id TEXT PRIMARY KEY, conversation_id TEXT);
CREATE TABLE IF NOT EXISTS apis (name TEXT PRIMARY KEY, base_url TEXT, auth_type TEXT, auth_name TEXT, secret BLOB, notes TEXT, write_policy TEXT, created REAL, last_used REAL);
CREATE TABLE IF NOT EXISTS api_grants (service TEXT, scope TEXT, conversation_id TEXT, created REAL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS cloud_spend (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, model TEXT, cost REAL, conversation_id TEXT);
CREATE TABLE IF NOT EXISTS cloud_grants (run_id TEXT PRIMARY KEY, created REAL);
CREATE TABLE IF NOT EXISTS vault_index (name TEXT PRIMARY KEY, site TEXT, username TEXT);
CREATE TABLE IF NOT EXISTS goals (id TEXT PRIMARY KEY, title TEXT, area TEXT, done INTEGER DEFAULT 0, notes TEXT, created REAL, updated REAL);
CREATE INDEX IF NOT EXISTS messages_conv ON messages(conversation_id, created);
CREATE INDEX IF NOT EXISTS activity_conv ON activity(conversation_id, created);
"""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table, column in (("messages", "attachments TEXT"),      # files the user attached (workspace paths, JSON)
                              ("messages", "suggestions TEXT"),      # tap-to-send replies under Clara's message (JSON)
                              ("messages", "meta TEXT"),             # e.g. {"kind": "checkin", "goal_id": ...}
                              ("goals", "checkin TEXT DEFAULT 'off'"),        # off | daily | weekly
                              ("goals", "checkin_time TEXT DEFAULT '19:00'"),
                              ("goals", "checkin_day INTEGER DEFAULT 6"),     # weekly: 0=Mon … 6=Sun
                              ("goals", "last_checkin REAL"),
                              ("cloud_spend", "label TEXT")):             # what the money was for, e.g. "Video · bakery ad"
            try:  # columns added after v1
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass
        self.db.execute("CREATE TABLE IF NOT EXISTS connectors (provider TEXT PRIMARY KEY, client BLOB, tokens BLOB, account TEXT, "
                        "scopes TEXT, connected REAL, policy TEXT)")   # client/tokens are sealed with the key broker
        self.db.execute("CREATE TABLE IF NOT EXISTS goal_log (id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id TEXT, kind TEXT, text TEXT, created REAL)")
        os.chmod(path, 0o600)
        self.lock = threading.Lock()

    def _x(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args)

    # rows are read while holding the lock: concurrent requests share this connection, and a statement
    # from another thread between execute and fetch could hand back nothing (a phantom "not paired")
    def _all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        with self.lock:
            r = self.db.execute(sql, args).fetchone()
        return dict(r) if r else None

    # --- pairing / devices -------------------------------------------------
    def new_pairing_code(self, ttl=600) -> str:
        code = f"{secrets.randbelow(10**6):06d}"
        self._x("DELETE FROM pairing_codes WHERE expires < ?", (time.time(),))
        self._x("INSERT OR REPLACE INTO pairing_codes VALUES (?, ?)", (code, time.time() + ttl))
        return code

    def redeem_pairing_code(self, code: str, device_name: str):
        row = self._one("DELETE FROM pairing_codes WHERE code = ? RETURNING *", (code,))
        if not row or row["expires"] < time.time():
            return None
        token = secrets.token_urlsafe(32)
        dev_id = uuid.uuid4().hex
        self._x("INSERT INTO devices VALUES (?, ?, ?, ?, ?)", (dev_id, device_name[:80], _hash(token), time.time(), time.time()))
        return dev_id, token

    def device_for_token(self, token: str):
        dev = self._one("SELECT id, name FROM devices WHERE token_hash = ?", (_hash(token),))
        if dev:
            self._x("UPDATE devices SET last_seen = ? WHERE id = ?", (time.time(), dev["id"]))
        return dev

    def list_devices(self):
        return self._all("SELECT id, name, created, last_seen FROM devices ORDER BY created")

    def revoke_device(self, dev_id):
        self._x("DELETE FROM devices WHERE id = ?", (dev_id,))

    # --- conversations & messages ------------------------------------------
    def create_conversation(self, title="New chat"):
        cid = uuid.uuid4().hex
        now = time.time()
        self._x("INSERT INTO conversations VALUES (?, ?, ?, ?, NULL)", (cid, title, now, now))
        return self.get_conversation(cid)

    def get_conversation(self, cid):
        return self._one("SELECT * FROM conversations WHERE id = ?", (cid,))

    def list_conversations(self, limit=50):
        return self._all("SELECT * FROM conversations ORDER BY updated DESC LIMIT ?", (limit,))

    def set_active_run(self, cid, run_id):
        self._x("UPDATE conversations SET active_run = ?, updated = ? WHERE id = ?", (run_id, time.time(), cid))

    def clear_active_run(self, cid, run_id):
        self._x("UPDATE conversations SET active_run = NULL WHERE id = ? AND active_run = ?", (cid, run_id))

    def set_title(self, cid, title):
        self._x("UPDATE conversations SET title = ? WHERE id = ?", (title[:80], cid))

    def delete_conversation(self, cid):
        for t in ("messages", "activity", "approvals"):
            self._x(f"DELETE FROM {t} WHERE conversation_id = ?", (cid,))
        self._x("DELETE FROM job_conversations WHERE conversation_id = ?", (cid,))
        self._x("DELETE FROM conversations WHERE id = ?", (cid,))

    def add_message(self, cid, role, content, route=None, run_id=None, attachments=None, suggestions=None, meta=None):
        mid = uuid.uuid4().hex
        now = time.time()
        att, sug = list(attachments or []), list(suggestions or [])
        self._x("INSERT INTO messages (id, conversation_id, role, content, route, run_id, created, attachments, suggestions, meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (mid, cid, role, content, route, run_id, now, json.dumps(att) if att else None,
                 json.dumps(sug) if sug else None, json.dumps(meta) if meta else None))
        self._x("UPDATE conversations SET updated = ? WHERE id = ?", (now, cid))
        return {"id": mid, "conversation_id": cid, "role": role, "content": content, "route": route, "run_id": run_id,
                "created": now, "attachments": att, "suggestions": sug, "meta": meta}

    def messages(self, cid, limit=200):
        rows = self._all("SELECT * FROM messages WHERE conversation_id = ? ORDER BY created DESC LIMIT ?", (cid, limit))
        for r in rows:
            r["attachments"] = json.loads(r.get("attachments") or "[]")
            r["suggestions"] = json.loads(r.get("suggestions") or "[]")
            r["meta"] = json.loads(r["meta"]) if r.get("meta") else None
        return list(reversed(rows))

    def latest_conversation_id(self, exclude=("clara-notifications",)):
        for c in self.list_conversations(10):
            if c["id"] not in exclude:
                return c["id"]
        return None

    # --- settings -------------------------------------------------------------
    def setting(self, key, default=None):
        row = self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        self._x("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    # --- cloud AI spend ledger & per-task grants ----------------------------------
    def add_spend(self, kind, model, cost, conversation_id=None, label=None):
        self._x("INSERT INTO cloud_spend (ts, kind, model, cost, conversation_id, label) VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), kind, model, float(cost or 0), conversation_id, (label or "")[:120] or None))

    def spend_rows(self, since):
        return self._all("SELECT s.ts, s.kind, s.model, s.cost, s.conversation_id, s.label, c.title AS chat FROM cloud_spend s "
                         "LEFT JOIN conversations c ON c.id = s.conversation_id WHERE s.ts >= ? ORDER BY s.ts", (since,))

    def spend_since(self, ts):
        return float(self._one("SELECT COALESCE(SUM(cost), 0) AS s FROM cloud_spend WHERE ts >= ?", (ts,))["s"])

    def recent_spend(self, limit=50):
        return self._all("SELECT ts, kind, model, cost FROM cloud_spend ORDER BY id DESC LIMIT ?", (limit,))

    def grant_run(self, run_id):
        self._x("INSERT OR REPLACE INTO cloud_grants VALUES (?, ?)", (run_id, time.time()))

    def run_granted(self, run_ids):
        return any(self._one("SELECT 1 FROM cloud_grants WHERE run_id = ?", (r,)) for r in run_ids)

    def active_runs(self):
        return [r["active_run"] for r in self._all("SELECT active_run FROM conversations WHERE active_run IS NOT NULL")]

    # --- API key broker (keys encrypted at rest; never returned to any client) --
    def apis(self):
        return self._all("SELECT name, base_url, auth_type, auth_name, notes, write_policy, created, last_used FROM apis ORDER BY name")

    def api(self, name):
        return self._one("SELECT * FROM apis WHERE name = ?", (name,))

    def save_api(self, name, base_url, auth_type, auth_name, secret: bytes, notes, write_policy):
        self._x("INSERT OR REPLACE INTO apis VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (name, base_url, auth_type, auth_name, secret, notes, write_policy, time.time()))
        self._x("DELETE FROM api_grants WHERE service = ?", (name,))   # a new key means fresh approvals

    def delete_api(self, name):
        self._x("DELETE FROM apis WHERE name = ?", (name,))
        self._x("DELETE FROM api_grants WHERE service = ?", (name,))

    def touch_api(self, name):
        self._x("UPDATE apis SET last_used = ? WHERE name = ?", (time.time(), name))

    def grant(self, service, scope, conversation_id=None):
        self._x("INSERT INTO api_grants VALUES (?, ?, ?, ?)", (service, scope, conversation_id, time.time()))

    def granted(self, service, scope, conversation_id):
        return bool(self._one("SELECT 1 FROM api_grants WHERE service = ? AND scope = ? AND (conversation_id IS NULL OR conversation_id = ?)",
                              (service, scope, conversation_id)))

    # --- password index (no secrets: passwords live only on the phone) -------
    def vault_index(self):
        return self._all("SELECT name, site, username FROM vault_index ORDER BY name")

    def set_vault_index(self, entries):
        with self.lock:
            self.db.execute("BEGIN")
            self.db.execute("DELETE FROM vault_index")
            self.db.executemany("INSERT INTO vault_index VALUES (?, ?, ?)", [(e["name"], e["site"], e["username"]) for e in entries])
            self.db.execute("COMMIT")

    # --- goals ---------------------------------------------------------------
    def goals(self):
        return [dict(g, done=bool(g["done"])) for g in self._all("SELECT * FROM goals ORDER BY done, area, created")]

    def add_goal(self, title, area="General", notes=""):
        gid = uuid.uuid4().hex
        now = time.time()
        self._x("INSERT INTO goals (id, title, area, done, notes, created, updated) VALUES (?, ?, ?, 0, ?, ?, ?)", (gid, title[:200], (area or "General")[:40], notes[:2000], now, now))
        return dict(self._one("SELECT * FROM goals WHERE id = ?", (gid,)), done=False)

    def update_goal(self, gid, **fields):
        allowed = {k: v for k, v in fields.items() if k in ("title", "area", "done", "notes", "checkin", "checkin_time", "checkin_day") and v is not None}
        for k, v in allowed.items():
            self._x(f"UPDATE goals SET {k} = ?, updated = ? WHERE id = ?", (int(v) if k == "done" else v, time.time(), gid))
        g = self._one("SELECT * FROM goals WHERE id = ?", (gid,))
        return dict(g, done=bool(g["done"])) if g else None

    def delete_goal(self, gid):
        self._x("DELETE FROM goals WHERE id = ?", (gid,))
        self._x("DELETE FROM goal_log WHERE goal_id = ?", (gid,))

    # --- connectors (Google…): sealed OAuth client + tokens --------------------
    def connector(self, provider):
        return self._one("SELECT * FROM connectors WHERE provider = ?", (provider,))

    _UNSET = object()

    def save_connector(self, provider, client=_UNSET, tokens=_UNSET, account=_UNSET, scopes=_UNSET, policy=_UNSET):
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO connectors (provider) VALUES (?)", (provider,))
            for col, val in (("client", client), ("tokens", tokens), ("account", account), ("scopes", scopes), ("policy", policy)):
                if val is not Store._UNSET:
                    self.db.execute(f"UPDATE connectors SET {col} = ? WHERE provider = ?", (val, provider))
            if tokens is not Store._UNSET:
                self.db.execute("UPDATE connectors SET connected = ? WHERE provider = ?", (time.time() if tokens else None, provider))

    def goal(self, gid):
        g = self._one("SELECT * FROM goals WHERE id = ?", (gid,))
        return dict(g, done=bool(g["done"])) if g else None

    def log_goal(self, gid, kind, text):
        self._x("INSERT INTO goal_log (goal_id, kind, text, created) VALUES (?, ?, ?, ?)", (gid, kind, text[:1000], time.time()))

    def goal_log(self, gid, limit=20):
        return self._all("SELECT kind, text, created FROM goal_log WHERE goal_id = ? ORDER BY created DESC LIMIT ?", (gid, limit))

    def mark_checkin(self, gid):
        self._x("UPDATE goals SET last_checkin = ? WHERE id = ?", (time.time(), gid))

    # --- scheduled jobs report back into the chat that created them --------
    def set_job_conversation(self, job_id, cid):
        self._x("INSERT OR REPLACE INTO job_conversations VALUES (?, ?)", (job_id, cid))

    def job_conversation(self, job_id):
        row = self._one("SELECT conversation_id FROM job_conversations WHERE job_id = ?", (job_id,))
        return row["conversation_id"] if row and self.get_conversation(row["conversation_id"]) else None

    # --- activity & approvals ----------------------------------------------
    def add_activity(self, cid, run_id, kind, tool=None, detail=None):
        self._x("INSERT INTO activity (conversation_id, run_id, kind, tool, detail, created) VALUES (?, ?, ?, ?, ?, ?)",
                (cid, run_id, kind, tool, (detail or "")[:2000], time.time()))

    def activity(self, cid=None, limit=200):
        if cid:
            return self._all("SELECT * FROM activity WHERE conversation_id = ? ORDER BY id DESC LIMIT ?", (cid, limit))
        return self._all("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))

    def add_approval(self, cid, run_id, description, command, choices):
        aid = uuid.uuid4().hex
        self._x("INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, NULL)",
                (aid, cid, run_id, description, command, json.dumps(choices), time.time()))
        return self.get_approval(aid)

    def get_approval(self, aid):
        a = self._one("SELECT * FROM approvals WHERE id = ?", (aid,))
        if a:
            a["choices"] = json.loads(a["choices"])
        return a

    def approvals(self, status=None, limit=100):
        if status:
            rows = self._all("SELECT * FROM approvals WHERE status = ? ORDER BY created DESC LIMIT ?", (status, limit))
        else:
            rows = self._all("SELECT * FROM approvals ORDER BY created DESC LIMIT ?", (limit,))
        for a in rows:
            a["choices"] = json.loads(a["choices"])
        return rows

    def resolve_approval(self, aid, status):
        self._x("UPDATE approvals SET status = ?, resolved = ? WHERE id = ?", (status, time.time(), aid))

    def expire_run_approvals(self, run_id):
        self._x("UPDATE approvals SET status = 'expired', resolved = ? WHERE run_id = ? AND status = 'pending'", (time.time(), run_id))

    # --- router log (training data for the next Laya fine-tune) -------------
    def log_route(self, mid, text, r):
        self._x("INSERT OR REPLACE INTO router_log VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                (mid, text, r.route, r.source, r.confidence, r.ms, time.time()))

    def correct_route(self, mid, route):
        self._x("UPDATE router_log SET corrected = ? WHERE message_id = ?", (route, mid))
