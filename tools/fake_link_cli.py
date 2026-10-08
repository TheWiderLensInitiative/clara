#!/usr/bin/env python3
"""A stand-in for Stripe's link-cli (tests only): the commands Clara's Bridge uses, with state in a JSON file next to
LINK_AUTH_FILE. FAKE_LINK_DECISION=approved|denied decides what the "user" does in the Link app."""
import json, os, sys
from pathlib import Path

args = [a for a in sys.argv[1:] if a not in ("--format", "json")]
auth = Path(os.environ["LINK_AUTH_FILE"]); state_f = auth.with_suffix(".fake-state.json")
state = json.loads(state_f.read_text()) if state_f.exists() else {"requests": {}}
def save(): state_f.write_text(json.dumps(state))
def out(obj): print(json.dumps([obj] if isinstance(obj, dict) else obj)); save(); sys.exit(0)
def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default

cmd = args[:2]
if cmd == ["auth", "login"]:
    state["pending"] = True; out({"verification_url": "https://app.link.com/device/setup?code=fake-calm-word-pair", "phrase": "fake-calm-word-pair"})
if cmd == ["auth", "status"]:
    if state.get("pending"): state["authed"] = True
    out({"authenticated": bool(state.get("authed"))})
if cmd == ["auth", "logout"]:
    state["authed"] = False; out({"ok": True})
if cmd == ["user-info", "retrieve"]:
    out({"email": "tester@example.com", "agent_wallet_spend_limits": {"per_transaction": {"limit": 50000, "remaining": 50000}}})
if cmd == ["spend-request", "create"]:
    rid = f"lsrq_fake{len(state['requests']) + 1}"
    state["requests"][rid] = {"id": rid, "status": "pending_approval", "amount": int(opt("--amount")), "currency": "usd",
                              "merchant_name": opt("--merchant-name"), "merchant_url": opt("--merchant-url"),
                              "context": opt("--context"), "test": "--test" in args,
                              "approval_url": f"https://app.link.com/activity/approve/{rid}"}
    out(state["requests"][rid])
if cmd == ["spend-request", "retrieve"]:
    r = state["requests"][args[2]]
    if r["status"] == "pending_approval": r["status"] = os.environ.get("FAKE_LINK_DECISION", "approved")
    if "--include" in args and r["status"] == "approved":
        Path(opt("--output-file")).write_text(json.dumps({**r, "card": {"brand": "visa", "number": "4000009990001984", "cvc": "100",
            "exp_month": 6, "exp_year": 2029, "billing_address": {"name": "Tester", "postal_code": "32277"}}}))
        out({"id": r["id"], "status": r["status"], "card_output_file": opt("--output-file")})
    out(r)
if cmd == ["spend-request", "cancel"]:
    state["requests"][args[2]]["status"] = "canceled"; out(state["requests"][args[2]])
print(json.dumps({"error": {"message": "unknown command " + " ".join(args)}})); sys.exit(1)
