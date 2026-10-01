"""Stand-ins for connector tests (port 8798): a Home Assistant, and a Spotify-like OAuth service (PKCE, no secret)."""
import base64, hashlib, secrets, time
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, Response
import uvicorn
app = FastAPI()
HA_TOKEN = "ha-" + "x" * 60
lights = {"light.kitchen": "off"}
codes, tokens, refresh, log = {}, {}, {}, []

def ha(req):
    if req.headers.get("authorization") != f"Bearer {HA_TOKEN}": raise HTTPException(401)
@app.get("/api/config")
def cfg(request: Request): ha(request); return {"location_name": "Home", "version": "2026.9"}
@app.get("/api/states")
def states(request: Request): ha(request); return [{"entity_id": k, "state": v} for k, v in lights.items()]
@app.post("/api/services/light/{svc}")
async def light(svc: str, request: Request):
    ha(request); d = await request.json(); lights[d["entity_id"]] = "on" if svc == "turn_on" else "off"; log.append(("light", svc, d)); return [{"entity_id": d["entity_id"], "state": lights[d["entity_id"]]}]

CLIENT = "0123456789abcdef0123456789abcdef"
@app.get("/authorize")
def authorize(client_id: str, redirect_uri: str, state: str, code_challenge: str, code_challenge_method: str, response_type: str, scope: str):
    assert client_id == CLIENT and code_challenge_method == "S256"
    code = secrets.token_urlsafe(8); codes[code] = (code_challenge, redirect_uri)
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}")
@app.post("/api/token")
def token(grant_type: str = Form(...), client_id: str = Form(...), code: str = Form(None), code_verifier: str = Form(None),
          redirect_uri: str = Form(None), refresh_token: str = Form(None), client_secret: str = Form(None)):
    if client_id != CLIENT or client_secret: raise HTTPException(400, "public client: no secret expected")
    if grant_type == "authorization_code":
        chal, ru = codes.pop(code)
        assert base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode() == chal and ru == redirect_uri
    elif refresh_token not in refresh: return {"error": "invalid_grant"}
    at, rt = "at-" + secrets.token_hex(6), "rt-" + secrets.token_hex(6)
    tokens[at] = time.time() + 3600; refresh[rt] = 1
    return {"access_token": at, "refresh_token": rt, "expires_in": 3600, "scope": "x"}
def sp(req):
    if tokens.get(req.headers.get("authorization", "")[7:], 0) < time.time(): raise HTTPException(401)
@app.get("/v1/me")
def me(request: Request): sp(request); return {"display_name": "Test Listener", "email": "listener@example.com"}
@app.get("/v1/search")
def search(request: Request, q: str, type: str): sp(request); return {"tracks": {"items": [{"name": "Clair de Lune", "uri": "spotify:track:1", "echo": request.headers.get("authorization")}]}}
@app.put("/v1/me/player/play")
async def play(request: Request): sp(request); log.append(("play", await request.json())); return Response(status_code=204)
@app.get("/v1/cover")
def cover(request: Request): sp(request); return Response(b"\x89PNG\r\n\x1a\n" + b"0" * 100, media_type="image/png")
# --- X API v2 (posts, chunked media upload) and Meta Graph (Page, Reels, Instagram resumable) ---------------------
SOCIAL_TOKEN = "EA" + "A" * 70
media, posts = {}, []
def social_auth(req):
    if req.headers.get("authorization") not in (f"Bearer {SOCIAL_TOKEN}", f"OAuth {SOCIAL_TOKEN}"): raise HTTPException(401)
@app.post("/2/media/upload/initialize")
async def x_init(request: Request):
    social_auth(request); d = await request.json(); mid = str(len(media) + 100)
    media[mid] = {"total": d["total_bytes"], "got": 0, "polls": 0}; return {"data": {"id": mid}}
@app.post("/2/media/upload/{mid}/append")
async def x_append(mid: str, request: Request):
    social_auth(request); form = await request.form(); media[mid]["got"] += len(await form["media"].read()); return Response(status_code=204)
@app.post("/2/media/upload/{mid}/finalize")
def x_final(mid: str, request: Request):
    social_auth(request); m = media[mid]
    if m["got"] != m["total"]: raise HTTPException(400, f"got {m['got']} of {m['total']}")
    return {"data": {"id": mid, "processing_info": {"state": "pending", "check_after_secs": 1}}}
@app.get("/2/media/upload")
def x_status(command: str, media_id: str, request: Request):
    social_auth(request); media[media_id]["polls"] += 1
    return {"data": {"id": media_id, "processing_info": {"state": "succeeded" if media[media_id]["polls"] > 1 else "in_progress", "check_after_secs": 1}}}
@app.post("/2/tweets")
async def x_tweet(request: Request):
    social_auth(request); d = await request.json(); pid = str(9000 + len(posts)); posts.append(("x", d)); return {"data": {"id": pid, "text": d["text"]}}
@app.get("/2/users/me")
def x_me(request: Request): social_auth(request); return {"data": {"id": "1", "username": "TheWiderLens"}}
@app.get("/v23.0/{node}")
def graph_get(node: str, request: Request, fields: str = ""):
    social_auth(request)
    if fields == "status_code": return {"status_code": "FINISHED", "id": node}
    if fields == "permalink": return {"permalink": f"https://www.instagram.com/reel/{node}/"}
    return {"id": node, "name": "The Wider Lens"}
@app.post("/v23.0/{page}/feed")
async def fb_feed(page: str, request: Request):
    social_auth(request); posts.append(("fb", await request.json())); return {"id": f"{page}_777"}
@app.post("/v23.0/{page}/video_reels")
async def fb_reels(page: str, request: Request, upload_phase: str = None, video_id: str = None, description: str = ""):
    social_auth(request)
    phase = upload_phase or (await request.json()).get("upload_phase")
    if phase == "start": return {"video_id": "555", "upload_url": "http://127.0.0.1:8798/video-upload/v23.0/555"}
    assert media.get("rup-555", {}).get("got"), "finish before upload"
    posts.append(("fb-reel", {"video_id": video_id, "description": description})); return {"success": True}
@app.post("/video-upload/v23.0/{vid}")
@app.post("/ig-api-upload/v23.0/{vid}")
async def rupload(vid: str, request: Request):
    social_auth(request); body = await request.body()
    assert request.headers.get("authorization", "").startswith("OAuth ") and int(request.headers["file_size"]) == len(body)
    media[f"rup-{vid}"] = {"got": len(body)}; return {"success": True}
@app.post("/v23.0/{ig}/media")
def ig_media(ig: str, request: Request, media_type: str, upload_type: str, caption: str = ""):
    social_auth(request); assert media_type == "REELS" and upload_type == "resumable"
    return {"id": "777", "uri": "http://127.0.0.1:8798/ig-api-upload/v23.0/777"}
@app.post("/v23.0/{ig}/media_publish")
def ig_publish(ig: str, request: Request, creation_id: str):
    social_auth(request); assert media.get(f"rup-{creation_id}", {}).get("got"); posts.append(("ig", creation_id)); return {"id": "888"}
@app.get("/_social")
def social_log(): return {"posts": posts, "media": media}
@app.get("/_log")
def getlog(): return {"log": log, "lights": lights}
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8798, log_level="warning")
