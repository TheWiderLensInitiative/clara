"""clara-vault: sign in with the user's logins, which live ONLY on their phone.

sign_in(name):
  1. make a one-time P-256 key pair, send the public half to the Bridge with the request;
  2. the phone asks the user (fingerprint/PIN) and encrypts that one login to this key (ECDH + HKDF + AES-256-GCM,
     bound to the request id, name and site), so the Bridge in between only relays ciphertext;
  3. decrypt in memory, hand it to the browser's own vault over stdin (never argv, never the model), log in with the
     vault's origin check, and delete it right away.
Tool results are rebuilt from scratch (status + URL) so nothing secret can reach the model.
"""
import base64
import json
import logging
import os
import re
import secrets
import subprocess
import urllib.request

logger = logging.getLogger(__name__)
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BRIDGE = os.environ.get("CLARA_BRIDGE_URL", "http://127.0.0.1:8700")

LIST_SCHEMA = {
    "name": "list_logins",
    "description": "List the website logins the user keeps on their phone for you to use: name, site and username only. "
                   "You never see passwords. Use sign_in to log in with one.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}
SIGN_IN_SCHEMA = {
    "name": "sign_in",
    "description": "Sign in to a website with one of the user's saved logins (see list_logins). The user confirms on their phone "
                   "with their fingerprint, the phone sends that login encrypted for this one sign-in, and it is typed into the "
                   "login form in your browser and submitted. You never see the password. If the browser is already on that "
                   "site's login page it signs in there, otherwise it opens the saved login page. If there is no saved login "
                   "for a site, ask the user to add it in the Clara app (tap Clara → Passwords). Never ask the user to tell you a password.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "The saved login's name, e.g. \"GitHub\""}},
                   "required": ["name"]},
}


def _link(path, body=None, timeout=15):
    req = urllib.request.Request(BRIDGE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + os.environ.get("CLARA_LINK_TOKEN", ""), "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _index():
    return _link("/internal/vault/index").get("logins", [])


def handle_list(args, **_):
    try:
        return json.dumps({"logins": _index()})
    except Exception as e:
        return json.dumps({"error": f"Couldn't reach the Clara Bridge: {type(e).__name__}"})


def _open(sealed, name, site, priv):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    phone_pub = serialization.load_der_public_key(base64.b64decode(sealed["phone_pub"]))
    shared = priv.exchange(ec.ECDH(), phone_pub)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=sealed["id"].encode(), info=b"clara-vault-v1").derive(shared)
    aad = f"{sealed['id']}|{name}|{site}".encode()
    return json.loads(AESGCM(key).decrypt(base64.b64decode(sealed["nonce"]), base64.b64decode(sealed["ct"]), aad))


def _browser(task_id, *args):
    from tools.browser_tool import _run_browser_command
    return _run_browser_command(task_id or "default", "auth", list(args))


def _vault_cli(task_id, *args, secret=None):
    """Run a vault command against THIS task's browser session (the daemon Hermes already started with the right
    sandbox flags), so no second Chrome is launched. The secret goes over stdin only."""
    import tools.browser_tool as bt
    from tools.browser_tool import (_build_browser_env, _find_agent_browser, _get_session_info, _merge_browser_path,
                                    _run_browser_command, _socket_safe_tmpdir)
    _run_browser_command(task_id or "default", "get", ["url"])     # make sure the session's daemon is up
    info = _get_session_info(task_id or "default")
    env = _build_browser_env()
    env["PATH"] = _merge_browser_path(env.get("PATH", ""))
    env["AGENT_BROWSER_SOCKET_DIR"] = os.path.join(_socket_safe_tmpdir(), f"agent-browser-{info['session_name']}")
    # Match Hermes's launch settings exactly, or agent-browser treats it as a new config and relaunches Chrome.
    env.setdefault("AGENT_BROWSER_IDLE_TIMEOUT_MS", str(bt.BROWSER_SESSION_INACTIVITY_TIMEOUT * 1000))
    if "AGENT_BROWSER_ARGS" not in env and "AGENT_BROWSER_CHROME_FLAGS" not in env and bt._needs_chromium_sandbox_bypass():
        env["AGENT_BROWSER_ARGS"] = "--no-sandbox,--disable-dev-shm-usage"
    ab = _find_agent_browser(validate=False)
    cmd = (ab if isinstance(ab, list) else [ab]) + ["--session", info["session_name"], "--json", *args]
    r = subprocess.run(cmd, input=(secret or "").encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60, check=False)
    try:  # log only the vault's status/error, never inputs
        out = json.loads(r.stdout.decode().strip().splitlines()[-1])
        if not out.get("success"):
            logger.warning("clara-vault: agent-browser %s failed: %s", args[:2], str(out.get("error"))[:200])
    except Exception:
        logger.warning("clara-vault: agent-browser %s rc=%s stderr=%s", args[:2], r.returncode, r.stderr.decode(errors="replace")[:200])


def handle_sign_in(args, task_id=None, session_id=None, **_):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    name = str((args or {}).get("name", "")).strip()
    if not NAME.match(name):
        return json.dumps({"success": False, "error": "Invalid login name."})
    try:
        entry = next((e for e in _index() if e["name"] == name), None)
    except Exception as e:
        return json.dumps({"success": False, "error": f"Couldn't reach the Clara Bridge: {type(e).__name__}"})
    if not entry:
        return json.dumps({"success": False, "error": f"No saved login named '{name}'. Ask the user to add it in the Clara app (tap Clara → Passwords)."})

    priv = ec.generate_private_key(ec.SECP256R1())
    pub = base64.b64encode(priv.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    try:
        sealed = _link("/internal/vault/request", {"name": name, "pubkey": pub, "conversation_id": session_id}, timeout=330)
    except Exception as e:
        return json.dumps({"success": False, "error": f"The sign-in request failed: {type(e).__name__}"})
    if sealed.get("status") != "approved":
        why = {"timeout": "The user didn't answer in time.", "not_on_phone": "That login isn't on the user's phone."}.get(sealed.get("reason"), "The user declined.")
        return json.dumps({"success": False, "error": f"Sign-in not allowed: {why} Stop here and tell the user. Do NOT type a username or "
                                                      "password into the page yourself, even if you can see one — logins only go through sign_in."})

    tmp = "clara-tmp-" + secrets.token_hex(6)
    ok, url = False, ""
    try:
        cred = _open(sealed, name, entry["site"], priv)
        _vault_cli(task_id, "auth", "save", tmp, "--url", entry["site"], "--username", cred.get("username", ""), "--password-stdin", secret=cred.get("password", ""))
        cred = None
        r = _browser(task_id, "login", tmp, "--no-navigate")
        if not (r or {}).get("success"):
            logger.warning("clara-vault: login in place failed: %s", str((r or {}).get("error"))[:200])
            r = _browser(task_id, "login", tmp)
            if not (r or {}).get("success"):
                logger.warning("clara-vault: login with navigation failed: %s", str((r or {}).get("error"))[:200])
        ok = bool((r or {}).get("success"))
        try:
            from tools.browser_tool import _run_browser_command
            u = _run_browser_command(task_id or "default", "get", ["url"])
            url = str(((u or {}).get("data") or {}).get("url") or "")[:300]
        except Exception:
            pass
    except Exception as e:
        logger.warning("clara-vault sign_in %s failed: %s: %s", name, type(e).__name__, str(e)[:120])
    finally:
        _vault_cli(task_id, "auth", "delete", tmp)
        priv = None
    logger.info("clara-vault sign_in %s: %s", name, "ok" if ok else "failed")
    if ok:
        return json.dumps({"success": True, "message": f"Signed in with the saved login '{name}'. Check the page to confirm it worked.", "url": url})
    return json.dumps({"success": False, "error": "The sign-in did not complete (wrong page, changed login form, or the site rejected it). "
                                                  "Take a snapshot to see what happened, then tell the user. Do NOT type a password yourself; they can take over the "
                                                  "browser from their phone if needed.",
                       "url": url})


def register(ctx) -> None:
    from tools.browser_tool import check_browser_requirements
    ctx.register_tool(name="list_logins", toolset="clara_vault", schema=LIST_SCHEMA, handler=handle_list, emoji="🔐")
    ctx.register_tool(name="sign_in", toolset="clara_vault", schema=SIGN_IN_SCHEMA, handler=handle_sign_in, check_fn=check_browser_requirements, emoji="🔑")
