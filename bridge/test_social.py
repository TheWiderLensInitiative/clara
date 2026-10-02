"""Social posting against tools/fake_services.py (start it first: python tools/fake_services.py, port 8798;
it needs bridge/requirements-dev.txt on top of the Bridge requirements).

    CLARA_DATA_DIR=$(mktemp -d) python bridge/test_social.py
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

FAKE = "http://127.0.0.1:8798"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("CLARA_DATA_DIR", tempfile.mkdtemp())
os.environ["CLARA_DB"] = os.path.join(os.environ["CLARA_DATA_DIR"], "test.db")

import broker       # noqa: E402
import connectors   # noqa: E402
from store import Store  # noqa: E402

TOKEN = "EA" + "A" * 70
store = Store()
connectors.X_API, connectors.GRAPH = FAKE + "/2", FAKE + "/v23.0"
for pid in ("x", "meta"):
    connectors.PROVIDERS[pid]["hosts"] = ["127.0.0.1:8798"]
store.save_connector("x", tokens=broker.seal(json.dumps({"access_token": TOKEN, "refresh_token": "r", "expires_at": time.time() + 3600})),
                     account="TheWiderLens")
store.save_connector("meta", tokens=broker.seal(json.dumps({"page_id": "12345", "token": TOKEN, "ig_user_id": "67890"})),
                     account="The Wider Lens")

video = Path(tempfile.mkdtemp()) / "reel.mp4"
video.write_bytes(os.urandom(9 * 1024 * 1024 + 123))   # three chunks for X


async def main():
    r = await connectors.x_post(store, ["Meet Clara 🟣", "She runs on your own PC."], video)
    assert r["url"].startswith("https://x.com/TheWiderLens/status/") and len(r["ids"]) == 2, r
    r = await connectors.facebook_post(store, "Clara is here")
    assert r["id"] == "12345_777", r
    r = await connectors.facebook_post(store, "The reel", video)
    assert r["url"].endswith("/reel/555"), r
    r = await connectors.instagram_post(store, "The reel", video)
    assert "instagram.com/reel/888" in r["url"], r
    link, sub = connectors.reddit_submit_link("r/LocalLLaMA", "I built Clara", "Line one\nline two")
    assert sub == "LocalLLaMA" and "selftext=true" in link and "title=I%20built%20Clara" in link, link
    log = httpx.get(FAKE + "/_social").json()
    kinds = [p[0] for p in log["posts"]]
    assert kinds == ["x", "x", "fb", "fb-reel", "ig"], kinds
    x1, x2 = log["posts"][0][1], log["posts"][1][1]
    assert x1["media"]["media_ids"] and x2["reply"]["in_reply_to_tweet_id"], (x1, x2)
    print("social posting: all checks passed")


asyncio.run(main())
