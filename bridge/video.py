"""Clara's video pipeline: cloud video models via OpenRouter, finished on this PC with ffmpeg.

One request can be a single clip or a short multi-shot video:
  shots (each a prompt, optional length, optional still image to animate)
  -> every shot rendered by the user's chosen video model (in parallel)
  -> clips normalized and joined, optional narration in Clara's own (Kokoro) voice mixed over them
  -> final .mp4 + a poster frame in the workspace, delivered to the chat.
The user approves the estimated cost on their phone first; the exact cost OpenRouter reports is recorded.
"""
import asyncio
import base64
import mimetypes
import re
import subprocess
import time
from pathlib import Path

import httpx

OPENROUTER = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/veo-3.1-lite"
POLL_SECONDS = 15
MAX_WAIT = 20 * 60
RES_PIXELS = {"480p": (854, 480), "720p": (1280, 720), "768p": (1366, 768), "1080p": (1920, 1080), "2K": (2560, 1440), "4K": (3840, 2160)}

_models_cache: dict = {"at": 0.0, "data": []}


async def models(force=False) -> list:
    """OpenRouter's video models with durations, resolutions and price SKUs (cached for an hour)."""
    if force or time.time() - _models_cache["at"] > 3600 or not _models_cache["data"]:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{OPENROUTER}/videos/models")
        _models_cache.update(at=time.time(), data=r.json().get("data", []))
    return _models_cache["data"]


async def model_info(model_id: str) -> dict | None:
    return next((m for m in await models() if m["id"] == model_id or m.get("canonical_slug") == model_id), None)


# --- prices: OpenRouter lists them in several units; turn them into dollars per second ---------------
def _dims(resolution: str, aspect: str) -> tuple[int, int]:
    w, h = RES_PIXELS.get(resolution, (1280, 720))
    if aspect in ("9:16", "3:4", "2:3", "9:21"):
        w, h = h, w
    elif aspect == "1:1":
        w = h
    return w, h


def dollars_per_second(info: dict, resolution: str, audio: bool, aspect: str = "16:9", image_input=False) -> float | None:
    skus = {k: float(v) for k, v in (info.get("pricing_skus") or {}).items() if re.fullmatch(r"[0-9.eE-]+", str(v))}
    if not skus:
        return None
    res = resolution.lower()

    def pick(cands):
        """Best-matching SKU name among candidates, preferring ones that mention our resolution / audio / mode."""
        def score(k):
            s = 0
            if res in k.lower(): s += 4
            elif re.search(r"\d+p|[24]k", k.lower()): s -= 4           # a different resolution
            if ("without_audio" in k) == (not audio): s += 2
            elif "audio" in k: s -= 2
            if image_input and "image_to_video" in k: s += 1
            if not image_input and "text_to_video" in k: s += 1
            if "video_input" in k or "continuation" in k or "reference" in k: s -= 6
            return s
        return max(cands, key=score) if cands else None

    per_sec = [k for k in skus if "second" in k and "image_input" not in k and "megapixel" not in k and "minimum" not in k]
    if per_sec:
        k = pick(per_sec)
        return skus[k] / (100 if "cents" in k else 1)
    tokens = [k for k in skus if k.startswith("video_tokens")]
    if tokens:   # ByteDance Seedance: billed per video token ≈ width*height*fps/1024 per second
        w, h = _dims(resolution, aspect)
        return skus[pick(tokens)] * (w * h * 24 / 1024)
    return None


def fit_duration(info: dict, seconds: float) -> int:
    allowed = sorted(info.get("supported_durations") or [])
    if not allowed:
        return int(max(2, min(10, round(seconds or 5))))
    want = seconds or allowed[len(allowed) // 2]
    return min(allowed, key=lambda d: (abs(d - want), -d))


def fit_resolution(info: dict, wanted: str = "720p") -> str:
    allowed = info.get("supported_resolutions") or []
    if not allowed or wanted in allowed:
        return wanted
    order = ["720p", "768p", "1080p", "480p", "2K", "1K", "4K"]
    return next((r for r in order if r in allowed), allowed[0])


def fit_aspect(info: dict, wanted: str) -> str | None:
    allowed = info.get("supported_aspect_ratios")
    if not allowed:
        return wanted
    return wanted if wanted in allowed else ("16:9" if "16:9" in allowed else allowed[0])


# --- OpenRouter calls ---------------------------------------------------------------------------------
def _headers(k):
    return {"Authorization": f"Bearer {k}", "HTTP-Referer": "https://clara.local", "X-Title": "Clara"}


def image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


async def submit(key: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{OPENROUTER}/videos", headers=_headers(key), json=body)
    try:
        data = r.json()
    except Exception:
        data = {"error": {"message": r.text[:300]}}
    if r.status_code >= 400 or "id" not in data:
        msg = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else data.get("error")
        raise RuntimeError(str(msg or f"HTTP {r.status_code}")[:300].replace(key, "[key]"))
    return data


async def poll(key: str, job_id: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{OPENROUTER}/videos/{job_id}", headers=_headers(key))
    return r.json()


async def download(key: str, url: str, dest: Path, tries=5):
    """Fetch a finished clip. Right after a job completes the file can briefly stall or 404, so retry with backoff."""
    last = None
    for attempt in range(tries):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60), follow_redirects=True) as c:
                async with c.stream("GET", url, headers=_headers(key) if url.startswith(OPENROUTER) else None) as r:
                    r.raise_for_status()
                    tmp = dest.with_suffix(".part")
                    with tmp.open("wb") as f:
                        async for chunk in r.aiter_bytes():
                            f.write(chunk)
            if tmp.stat().st_size < 1000:
                raise RuntimeError("empty download")
            tmp.replace(dest)
            return
        except Exception as e:
            last = e
            await asyncio.sleep(5 * (attempt + 1))
    raise RuntimeError(f"couldn't download the clip ({type(last).__name__}: {str(last)[:120]})")


# --- finishing on this PC --------------------------------------------------------------------------------
def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list, timeout=600):
    p = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg: " + p.stderr.strip()[-400:])


def has_audio(path: Path) -> bool:
    p = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return "Audio:" in p.stderr


def dimensions(path: Path) -> tuple[int, int] | None:
    p = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", p.stderr)
    return (int(m[1]), int(m[2])) if m else None


def duration(path: Path) -> float:
    p = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def finish(clips: list[Path], out: Path, size: tuple[int, int], narration_wav: Path | None = None):
    """Normalize every clip (size, 30 fps, stereo AAC; silence where a clip has no sound), join them, and mix narration."""
    w, h = size
    parts = []
    for i, c in enumerate(clips):
        n = out.parent / f".part{i}.mp4"
        d = dimensions(c)
        close = d and abs((d[0] / d[1]) / (w / h) - 1) < 0.35
        fit = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}" if close    # similar shape: fill the frame
               else f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=28,eq=brightness=-0.12[bg];"
                    f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")  # blurred fill, no black bars
        vf = f"{fit},setsar=1,fps=30,format=yuv420p"
        if has_audio(c):
            _run(["-i", str(c), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                  "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", str(n)])
        else:
            _run(["-i", str(c), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "20", "-c:a", "aac", "-shortest", str(n)])
        parts.append(n)
    joined = out.parent / ".joined.mp4"
    listing = out.parent / ".list.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
    _run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)])
    if narration_wav:
        # the clips' own sound drops to 25% under Clara's voice; video length stays the same
        _run(["-i", str(joined), "-i", str(narration_wav), "-filter_complex",
              "[0:a]volume=0.25[bg];[1:a]aresample=48000,apad[vo];[bg][vo]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]",
              "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(out)])
    else:
        joined.replace(out)
    for p in parts + [joined, listing]:
        p.unlink(missing_ok=True)


def poster(video: Path, jpg: Path):
    _run(["-ss", "0.5", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(jpg)])
