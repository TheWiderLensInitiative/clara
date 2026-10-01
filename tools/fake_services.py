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
@app.get("/_log")
def getlog(): return {"log": log, "lights": lights}
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8798, log_level="warning")
