"""Cloud boost: Clara's sub-agents and image generation go through OpenRouter, via the Bridge.

The OpenRouter key lives in the key broker (the user's account). Clara's side talks to the Bridge with the link
token; the Bridge swaps in the model the user chose, attaches the real key, records the exact cost OpenRouter reports,
enforces the user's daily cap, and asks the phone before a task first uses the cloud.
"""
import datetime as dt
import json

import httpx

import broker

OPENROUTER = "https://openrouter.ai/api/v1"
DEFAULTS = {
    "cloud_agent_model": "anthropic/claude-opus-5.5",
    "cloud_image_model": "google/gemini-3.1-flash-image",
    "cloud_video_model": "google/veo-3.1-lite",
    "cloud_daily_cap": None,          # dollars/day; None = no cap (spend is still logged and shown)
    "cloud_monthly_cap": None,        # dollars per calendar month; None = no cap
    "cloud_always": False,            # True = don't ask before each task
}


def settings(store):
    return {k: store.setting(k, v) for k, v in DEFAULTS.items()}


def key(store):
    svc = store.api("openrouter")
    return broker.unseal(svc["secret"]) if svc else None


def today_start():
    now = dt.datetime.now()
    return dt.datetime(now.year, now.month, now.day).timestamp()


def month_start():
    now = dt.datetime.now()
    return dt.datetime(now.year, now.month, 1).timestamp()


def over_cap(store):
    st = settings(store)
    if st["cloud_daily_cap"] is not None and store.spend_since(today_start()) >= float(st["cloud_daily_cap"]):
        return True
    return st["cloud_monthly_cap"] is not None and store.spend_since(month_start()) >= float(st["cloud_monthly_cap"])


def _headers(k):
    return {"Authorization": f"Bearer {k}", "HTTP-Referer": "https://clara.local", "X-Title": "Clara"}


async def chat(store, body: dict, cid=None, label=None):
    """Forward one chat-completions request (non-streaming) with the user's chosen model. Returns (status, json)."""
    k = key(store)
    body = dict(body)
    body["model"] = settings(store)["cloud_agent_model"]
    body.pop("stream_options", None)
    async with httpx.AsyncClient(timeout=600) as c:
        r = await c.post(f"{OPENROUTER}/chat/completions", headers=_headers(k), json=body)
    try:
        data = r.json()
    except Exception:
        data = {"error": {"message": broker.scrub(r.text[:500], k)}}
    cost = ((data.get("usage") or {}).get("cost")) if isinstance(data, dict) else None
    if cost:
        store.add_spend("agent", body["model"], cost, cid, label)
    return r.status_code, data


async def chat_stream(store, body: dict, cid=None, label=None):
    """Streaming variant: yields raw SSE lines; records the cost from the final usage chunk."""
    k = key(store)
    body = dict(body)
    body["model"] = settings(store)["cloud_agent_model"]
    async with httpx.AsyncClient(timeout=600) as c:
        async with c.stream("POST", f"{OPENROUTER}/chat/completions", headers=_headers(k), json=body) as r:
            async for line in r.aiter_lines():
                if line.startswith("data: ") and '"usage"' in line:
                    try:
                        cost = (json.loads(line[6:]).get("usage") or {}).get("cost")
                        if cost:
                            store.add_spend("agent", body["model"], cost, cid, label)
                    except Exception:
                        pass
                yield line + "\n"


async def image(store, prompt: str, aspect_ratio: str | None, model: str | None = None, cid=None):
    k = key(store)
    m = model or settings(store)["cloud_image_model"]
    body = {"model": m, "prompt": prompt}
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(f"{OPENROUTER}/images", headers=_headers(k), json=body)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        return None, {"error": broker.scrub(json.dumps(data.get("error") or data)[:400], k), "model": m}
    cost = (data.get("usage") or {}).get("cost") or 0
    store.add_spend("image", m, cost, cid, "Picture · " + prompt[:80])
    return data.get("data") or [], {"model": m, "cost": cost}


_ctx_cache: dict = {}


async def context_length(model: str) -> int:
    """Real context window from OpenRouter's public model list (cached), so sub-agents budget correctly."""
    if model not in _ctx_cache:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                for m in (await c.get(f"{OPENROUTER}/models")).json().get("data", []):
                    _ctx_cache[m["id"]] = int(m.get("context_length") or 128000)
        except Exception:
            pass
    return _ctx_cache.get(model, 128000)


MUSIC_MODEL = "google/lyria-3-clip-preview"   # ~30 s instrumental clip, $0.04


async def music(store, prompt: str, cid=None, label=None):
    """Background music via Lyria (audio comes back as a stream of base64 chunks). Returns (mp3 bytes, cost)."""
    import base64
    k = key(store)
    body = {"model": MUSIC_MODEL, "messages": [{"role": "user", "content": prompt[:1000]}], "modalities": ["text", "audio"],
            "audio": {"format": "wav"}, "stream": True, "usage": {"include": True}}
    chunks, cost = [], 0.0
    async with httpx.AsyncClient(timeout=240) as c:
        async with c.stream("POST", f"{OPENROUTER}/chat/completions", headers=_headers(k), json=body) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"music model error {r.status_code}")
            async for line in r.aiter_lines():
                if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                    continue
                d = json.loads(line[6:])
                if d.get("error"):
                    raise RuntimeError(broker.scrub(str(d["error"])[:200], k))
                cost = (d.get("usage") or {}).get("cost") or cost
                for ch in d.get("choices", []):
                    a = (ch.get("delta") or {}).get("audio") or {}
                    if a.get("data"):
                        chunks.append(a["data"])
    if not chunks:
        raise RuntimeError("the music model returned no audio")
    store.add_spend("music", MUSIC_MODEL, cost, cid, label or "Music")
    return base64.b64decode("".join(chunks)), float(cost)
