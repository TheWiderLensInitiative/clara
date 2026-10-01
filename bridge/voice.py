"""Clara's speaking voice: Kokoro (82M, ONNX) on the CPU, so the GPU stays with Bonsai."""
import io
import re
import threading
from pathlib import Path

import soundfile as sf

from paths import VOICE_DIR as MODEL_DIR
VOICES = {  # the natural-sounding American/British English voices
    "af_heart": "Heart", "af_bella": "Bella", "af_nicole": "Nicole", "af_aoede": "Aoede", "af_kore": "Kore",
    "af_sarah": "Sarah", "af_nova": "Nova", "af_sky": "Sky", "bf_emma": "Emma (British)", "bf_isabella": "Isabella (British)",
    "am_michael": "Michael", "am_fenrir": "Fenrir", "bm_george": "George (British)",
}
DEFAULT_VOICE = "af_heart"

_kokoro = None
_lock = threading.Lock()


def _engine():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(MODEL_DIR / "kokoro-v1.0.onnx"), str(MODEL_DIR / "voices-v1.0.bin"))
    return _kokoro


EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍⬀-⯿]")


def speakable(text: str) -> str:
    """Markdown and chat decoration read aloud sounds robotic; turn a reply into plain spoken text."""
    t = re.sub(r"```.*?```", " I put the code in the chat. ", text, flags=re.S)
    t = re.sub(r"(?m)^\s*MEDIA:\S+\s*$", "", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", t)          # [label](url) -> label
    t = re.sub(r"https?://\S+", "the link in the chat", t)
    t = re.sub(r"(/var/lib/clara/workspace/|~/)\S+", "the file", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"[*_#>]+", "", t)
    t = re.sub(r"(?m)^\s*[-•☐☑]\s*(\[[ xX]\]\s*)?", "", t)             # bullets / checkboxes
    t = re.sub(r"(?m)^\s*(\d+)\.\s+", r"\1: ", t)
    t = EMOJI.sub("", t)
    t = re.sub(r"\s*—\s*", ", ", t)
    parts = [ln.strip() for ln in t.split("\n") if ln.strip()]
    t = ""
    for ln in parts:  # join lines so list items get a pause instead of running together
        t += (ln if not t else (" " if t[-1] in ".!?:,;" else ", ") + ln)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"([.!?,])\s*\.", r"\1", t)
    return t


def synthesize(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.05) -> bytes:
    """WAV (24 kHz mono 16-bit) for one chunk of speech."""
    voice = voice if voice in VOICES else DEFAULT_VOICE
    with _lock:
        samples, sr = _engine().create(text[:1500], voice=voice, speed=max(0.7, min(1.4, speed)), lang="en-gb" if voice[0] == "b" else "en-us")
    buf = io.BytesIO()
    sf.write(buf, samples, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _syllables(word: str) -> int:
    return max(1, len(re.findall(r"[aeiouy]+", word.lower())) + (1 if re.search(r"\d", word) else 0))


def synthesize_timed(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.05, gap: float = 0.18):
    """Narration with word timings for captions. Kokoro gives no timestamps, so each sentence is spoken on its own,
    measured, and its words spread across it by syllable count. Returns (wav bytes, [(word, start, end)], seconds)."""
    import numpy as np
    voice = voice if voice in VOICES else DEFAULT_VOICE
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", speakable(text)) if s.strip()]
    pieces, words, t, sr = [], [], 0.0, 24000
    for s in sentences:
        with _lock:
            samples, sr = _engine().create(s[:1000], voice=voice, speed=max(0.7, min(1.4, speed)), lang="en-gb" if voice[0] == "b" else "en-us")
        # trim leading/trailing near-silence so the timing lines up with the speech
        loud = np.where(np.abs(samples) > 0.02)[0]
        if len(loud):
            samples = samples[max(0, loud[0] - int(0.03 * sr)): loud[-1] + int(0.06 * sr)]
        dur = len(samples) / sr
        ws = s.split()
        weights = [_syllables(w) for w in ws]
        total = sum(weights) or 1
        cursor = t
        for w, wt in zip(ws, weights):
            span = dur * wt / total
            words.append((w, cursor, cursor + span))
            cursor += span
        pieces += [samples, np.zeros(int(gap * sr), dtype=samples.dtype)]
        t += dur + gap
    audio = np.concatenate(pieces) if pieces else np.zeros(sr // 2, dtype="float32")
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue(), words, len(audio) / sr
