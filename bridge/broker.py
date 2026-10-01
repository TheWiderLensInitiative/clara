"""API key broker: Clara calls any saved API through the Bridge without ever seeing the key.

Keys are encrypted at rest (Fernet, key file readable only by the user; Clara runs as another Linux user).
Each key is only ever sent to its own service's host, redirects are never followed with a key attached,
and the key is scrubbed from anything that comes back.
"""
import base64
import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from cryptography.fernet import Fernet

from paths import BROKER_KEY as KEY_FILE
AUTH_TYPES = {"bearer", "header", "query", "basic"}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MAX_RESPONSE = 200_000


def _fernet() -> Fernet:
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key())
        KEY_FILE.chmod(0o600)
    return Fernet(KEY_FILE.read_bytes())


def seal(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode())


def unseal(blob: bytes) -> str:
    return _fernet().decrypt(blob).decode()


def validate_service(name, base_url, auth_type, auth_name):
    if not NAME.match(name or ""):
        return "Name can use letters, numbers, - and _ (no spaces), e.g. openweather"
    u = urlsplit(base_url or "")
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
        return "Base URL must be a plain https:// address, e.g. https://api.openweathermap.org"
    if auth_type not in AUTH_TYPES:
        return f"Auth type must be one of {sorted(AUTH_TYPES)}"
    if auth_type in ("header", "query") and not re.match(r"^[A-Za-z0-9_.-]{1,64}$", auth_name or ""):
        return "Give the header or query parameter name the service expects, e.g. X-API-Key or appid"
    return None


def build_url(base_url: str, path: str) -> str:
    """Join a relative path onto the service's base URL; anything that could change the host is refused."""
    path = (path or "").strip()
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", path) or path.startswith("//") or "\\" in path or "@" in path:
        raise ValueError("path must be relative to the service, e.g. /v1/items")
    segments = [seg for seg in path.split("?")[0].split("/") if seg]
    if any(seg in (".", "..") for seg in segments):
        raise ValueError("path may not contain . or .. segments")
    base = base_url.rstrip("/")
    joined = base + "/" + "/".join(quote(seg, safe="-._~:!$&'()*+,;=%") for seg in segments)
    if urlsplit(joined).hostname != urlsplit(base_url).hostname:
        raise ValueError("path would leave the service's host")
    return joined


def scrub(text: str, secret: str) -> str:
    if not secret:
        return text
    variants = {secret, quote(secret, safe=""), base64.b64encode(secret.encode()).decode()}
    if ":" in secret:
        variants.add(base64.b64encode(secret.encode()).decode())
    for v in sorted(variants, key=len, reverse=True):
        if len(v) >= 4:
            text = text.replace(v, "[redacted]")
    return text


async def call(service: dict, method: str, path: str, query: dict | None, body, headers: dict | None) -> dict:
    method = method.upper()
    if method not in READ_METHODS | WRITE_METHODS:
        return {"error": f"Unsupported method {method}"}
    url = build_url(service["base_url"], path)
    secret = unseal(service["secret"])
    from urllib.parse import parse_qsl
    params = dict(parse_qsl(path.split("?", 1)[1])) if "?" in (path or "") else {}
    params.update({str(k): str(v) for k, v in (query or {}).items()})
    hdrs = {str(k): str(v) for k, v in (headers or {}).items()
            if str(k).lower() not in ("authorization", "cookie", "host", "proxy-authorization")}
    hdrs.setdefault("User-Agent", "Clara/0.1")
    auth = None
    at, an = service["auth_type"], service["auth_name"]
    if at == "bearer":
        hdrs["Authorization"] = f"Bearer {secret}"
    elif at == "header":
        hdrs[an] = secret
    elif at == "query":
        params[an] = secret
    elif at == "basic":
        user, _, pw = secret.partition(":")
        auth = (user, pw)
    kwargs = {"params": params, "headers": hdrs, "auth": auth}
    if body is not None and method in WRITE_METHODS:
        kwargs["json" if not isinstance(body, str) else "content"] = body
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:   # never carry a key across a redirect
        r = await client.request(method, url, **kwargs)
        raw = r.content[:MAX_RESPONSE].decode(errors="replace")
    keep = {"content-type", "location", "retry-after", "x-ratelimit-remaining", "x-ratelimit-limit"}
    return {
        "status": r.status_code,
        "headers": {k: scrub(v, secret) for k, v in r.headers.items() if k.lower() in keep},
        "body": scrub(raw, secret),
        "truncated": len(r.content) > MAX_RESPONSE,
    }
