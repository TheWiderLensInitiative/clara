"""Paying with Link (by Stripe): one-time cards for purchases, approved by the user in the Link app.

Clara never sees a card. The Bridge runs Stripe's link-cli as the user (its sign-in lives in a file only the
Bridge's account can read), creates a spend request for one store and one amount, and waits while the user
approves it in Link. The card is handed only to the browser plugin's pay step, which fills it into the checkout
and submits the order without the model seeing the page.

Docs: https://docs.stripe.com/agentic-commerce/agents/link-agent-wallet (US and Canada).
"""
import asyncio
import json
import os
import secrets
from pathlib import Path

import paths

CLI = Path(os.environ.get("CLARA_LINK_CLI", str(paths.DATA / "link-cli" / "node_modules" / ".bin" / "link-cli")))
AUTH = paths.DATA / "link" / "auth.json"          # link-cli's sign-in, 0600, the Bridge's user only
NODE_DIRS = ["/opt/clara/node/bin", str(Path.home() / ".local" / "bin")]
MAX_AMOUNT = 50000                                  # Link's own cap per request: $500.00
FINAL = {"approved", "denied", "expired", "canceled", "failed", "succeeded", "submitted"}


class LinkError(Exception):
    pass


def installed() -> bool:
    return CLI.exists()


async def run(*args, timeout=60) -> object:
    """One link-cli command, JSON out. Raises LinkError with Link's message on failure."""
    AUTH.parent.mkdir(parents=True, exist_ok=True)
    AUTH.parent.chmod(0o700)
    env = {**os.environ, "LINK_AUTH_FILE": str(AUTH), "PATH": ":".join(NODE_DIRS + [os.environ.get("PATH", "")]),
           "NO_COLOR": "1", "CI": "1"}
    proc = await asyncio.create_subprocess_exec(str(CLI), *args, "--format", "json", env=env,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise LinkError("Link didn't answer in time")
    text = out.decode(errors="replace").strip()
    try:
        data = json.loads(text) if text else None
    except ValueError:
        data = None
    if proc.returncode != 0 or data is None:
        msg = text or err.decode(errors="replace").strip()
        try:
            msg = (json.loads(msg).get("error") or {}).get("message") or msg
        except (ValueError, AttributeError):
            pass
        raise LinkError(str(msg)[:300] or f"link-cli exited {proc.returncode}")
    return data[0] if isinstance(data, list) and len(data) == 1 else data


# --- sign-in -------------------------------------------------------------------------------------------------
async def login_start() -> dict:
    d = await run("auth", "login", "--client-name", "Clara")
    return {"user_code": d["phrase"], "verification_uri": d["verification_url"], "expires_in": 600}


async def login_wait() -> str:
    """Poll until the user approved the connection in Link; returns their email."""
    d = await run("auth", "status", "--interval", "5", "--max-attempts", "120", timeout=660)
    last = d[-1] if isinstance(d, list) else d
    if not (last or {}).get("authenticated"):
        raise LinkError("the Link sign-in wasn't approved in time; tap Connect again")
    return await account()


async def account() -> str:
    info = await run("user-info", "retrieve")
    return str((info or {}).get("email") or "Link")


async def status() -> bool:
    try:
        return bool((await run("auth", "status", timeout=20) or {}).get("authenticated"))
    except LinkError:
        return False


async def logout():
    try:
        await run("auth", "logout", timeout=20)
    except LinkError:
        pass
    AUTH.unlink(missing_ok=True)


# --- spending ------------------------------------------------------------------------------------------------
def check_request(amount_cents, merchant_name, merchant_url, context):
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise LinkError("amount_cents must be a positive whole number of cents (e.g. 799 for $7.99)")
    if amount_cents > MAX_AMOUNT:
        raise LinkError("Link allows at most $500 per purchase")
    if not merchant_name or not str(merchant_url).startswith("https://"):
        raise LinkError("give the store's name and its https:// page")
    if len(context) < 100:
        raise LinkError("context must say what is being bought, from where and why (at least 100 characters)")


async def spend_create(amount_cents, merchant_name, merchant_url, context, items=(), totals=(), test=False) -> dict:
    check_request(amount_cents, merchant_name, merchant_url, context)
    args = ["spend-request", "create", "--amount", str(amount_cents), "--context", context,
            "--merchant-name", merchant_name, "--merchant-url", merchant_url,
            "--idempotency-key", "clara-" + secrets.token_hex(12)]
    for it in items:
        args += ["--line-item", it]
    for t in totals:
        args += ["--total", t]
    if test:
        args.append("--test")
    d = await run(*args)
    return {k: d.get(k) for k in ("id", "status", "amount", "currency", "merchant_name", "merchant_url", "approval_url")}


async def spend_wait(rid: str, stop=lambda: False, poll=asyncio.sleep) -> dict:
    """Wait (Link gives the user 10 minutes) until the request is approved, denied or expired."""
    for _ in range(330):
        d = await run("spend-request", "retrieve", rid)
        if d.get("status") in FINAL or d.get("status") == "requires_action" or stop():
            return d
        await poll(2)
    return {"id": rid, "status": "expired"}


async def card(rid: str) -> dict:
    """The one-time card for an approved request. Written by link-cli to a private file, read and deleted here."""
    out = AUTH.parent / f"card-{secrets.token_hex(8)}.json"
    try:
        await run("spend-request", "retrieve", rid, "--include", "card", "--output-file", str(out))
        data = json.loads(out.read_text())
    finally:
        out.unlink(missing_ok=True)
    c = (data[0] if isinstance(data, list) else data).get("card") or {}
    if not c.get("number"):
        raise LinkError("Link didn't return a card for this purchase")
    return c


async def cancel(rid: str):
    try:
        await run("spend-request", "cancel", rid, timeout=30)
    except LinkError:
        pass


async def limits() -> dict:
    info = await run("user-info", "retrieve")
    return (info or {}).get("agent_wallet_spend_limits") or {}
