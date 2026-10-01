"""Clara's social videos: a vertical reel/short and a landscape full video, narrated by Clara's own voice.

    CLARA_DATA_DIR=~/.local/share/clara ~/.local/share/clara/venv/bin/python tools/social_videos.py <clips_dir> <out_dir> [reel] [full]

<clips_dir> holds phone screen recordings (1080x2400 portrait, or 2400x1080 landscape for the takeover view). Each scene
below has a narration line; its footage is trimmed and sped up or slowed to match how long Clara takes to say it.
Captions are burned in (most people watch muted), with a soft synthesized pad underneath. Needs the Clara Bridge
venv (Kokoro voice, imageio-ffmpeg, Pillow, numpy) and ~/clara/bridge for voice.py.
"""
import io
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser(os.environ.get("CLARA_BRIDGE_DIR", "~/clara/bridge")))
import play_videos as pv   # backgrounds, cards, fonts, rounded masks
import voice                # Clara's Kokoro voice

FF, FPS, SR = pv.FF, 30, 24000
VOICE = os.environ.get("CLARA_PROMO_VOICE", "af_heart")
URL_SAID = "clara dot the wider lens dot info, slash beta"
URL_SHOWN = "clara.thewiderlens.info/beta"


def run(args):
    subprocess.run([FF, "-loglevel", "error", "-y", *args], check=True)


def duration(path):
    return pv.duration(path)


def narrate(text):
    """(float32 samples at SR, [(word, start, end)], seconds)."""
    wav, words, secs = voice.synthesize_timed(text, voice=VOICE, speed=1.05)
    with wave.open(io.BytesIO(wav)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if w.getframerate() != SR:
            raise SystemExit("unexpected sample rate")
    return a, words, secs


# ── scenes ──────────────────────────────────────────────────────────────────────────────────────────────────
# (clip or None for a card, start, end, headline, sub, narration)
REEL = [
    ("clip1.mp4", 5.0, 15.0, "AI that lives on\nYOUR computer", "",
     "Hi, I'm Clara. An AI assistant that runs on your own computer, not in the cloud."),
    ("browse.mp4", 18.0, 40.0, "Watch her work, live", "",
     "Ask me anything, and watch me research the web, live in the chat."),
    ("help_a.mp4", 0.5, 6.5, "Stuck on a CAPTCHA?", "",
     "Hit a CAPTCHA? I'll ask you to take over."),
    ("help_b.mp4", 0.0, 8.0, "Take over in one tap", "",
     "Solve it, hand it back, and I carry on."),
    ("clip3.mp4", 6.0, 30.0, "Nothing risky without your OK", "",
     "Anything risky, like installing software, waits for your OK."),
    ("voice.mp4", 0.0, 14.0, "Or just talk", "",
     "Or just talk to me, hands-free."),
    (None, 0, 0, "Clara", "Free & open source\nBeta testers wanted\n" + URL_SHOWN,
     "I'm free and open source. Join the beta at " + URL_SAID + "."),
]

FULL = [
    (None, 0, 0, "Meet Clara", "Your private AI assistant, running on your own PC",
     "Meet Clara: a free, private AI assistant that runs on your own PC, with an Android app to talk to her."),
    ("clip1.mp4", 5.0, 15.0, "Private by design", "Her brain, memory and voice run on your hardware.",
     "Most assistants live in someone else's cloud. Clara's brain, her memory and her voice all run on your own computer, "
     "so your chats and files never leave your home."),
    ("setup.mp4", 0.5, 9.0, "One command to set up", "Linux PC + NVIDIA GPU with 12 GB or more",
     "Setting her up takes one command on a Linux PC with an NVIDIA graphics card."),
    ("pair.mp4", 1.0, 16.0, "Pair your phone", "Scan the QR code, enter the pairing code",
     "The installer shows a QR code to get the app, and a pairing code. Enter it, and you're connected."),
    ("clip1.mp4", 12.0, 30.0, "Ask her anything", "Answers come straight from your own GPU",
     "Ask her anything. Everyday questions get quick answers, straight from your own graphics card."),
    ("browse.mp4", 18.0, 60.0, "She does real work", "Her own sandboxed computer and browser",
     "For real work, she uses her own sandboxed computer. You can watch her browse the web, live, right in the chat."),
    ("clip2b.mp4", 1.0, 13.0, "And brings back the answer", "",
     "Then she brings back the answer."),
    ("help_a.mp4", 0.5, 6.5, "She asks for help", "CAPTCHAs, sign-ins, 'are you human' checks",
     "If she hits a CAPTCHA, or a sign-in only you can do, she asks for your help."),
    ("help_b.mp4", 0.0, 8.0, "Take over in one tap", "Full screen, pinch to zoom, hand it back",
     "Take over her browser in one tap, solve it, and hand it back. She carries on from there."),
    ("clip3.mp4", 4.0, 38.0, "You stay in control", "Risky actions always ask first",
     "Sending, deleting, buying or installing always asks you first, with a preview. Deny it, and nothing happens."),
    ("clip1.mp4", 36.0, 56.0, "Reminders and routines", "Delivered to your phone",
     "Reminders and scheduled jobs are delivered straight to your phone."),
    ("voice.mp4", 0.0, 30.0, "Hands-free voice", "Her voice is generated on your PC",
     "And voice mode lets you talk to her hands-free, with a voice that's generated on your own PC."),
    (None, 0, 0, "Connects to your accounts", "Gmail, Calendar, Spotify, Notion, GitHub and more.\nPasswords stay on your phone.",
     "She connects to Gmail, Calendar, Spotify, Notion and more, and your passwords stay on your phone."),
    (None, 0, 0, "Join the beta", "Free & open source\n" + URL_SHOWN,
     "Clara is free and open source. We're looking for beta testers to bring her to Google Play. "
     "Join at " + URL_SAID + "."),
]

CREDIT = "Created by DevIgnite × The Wider Lens Initiative Project"


# ── pictures ────────────────────────────────────────────────────────────────────────────────────────────────
def headline_bg(w, h, title, sub, layout, wide_clip=False):
    im = pv.glow_bg(w, h)
    d = ImageDraw.Draw(im)
    if layout == "landscape" and wide_clip:
        f = pv.font("Poppins-ExtraBold.ttf", 64)
        d.text(((w - d.textlength(title, font=f)) / 2, 40), title, font=f, fill=pv.TEXT)
        if sub:
            g = pv.font("Poppins-SemiBold.ttf", 32)
            d.text(((w - d.textlength(sub, font=g)) / 2, 122), sub, font=g, fill=pv.SOFT)
        return im
    if layout == "vertical":
        f = pv.font("Poppins-ExtraBold.ttf", 70)
        lines = [ln for part in title.split("\n") for ln in pv.wrap(d, part, f, w - 120)]
        y = 70 if len(lines) > 1 else 110
        for line in lines:
            d.text(((w - d.textlength(line, font=f)) / 2, y), line, font=f, fill=pv.TEXT)
            y += 84
    else:
        y = pv.text_block(d, (110, 300), title, pv.font("Poppins-ExtraBold.ttf", 72), pv.TEXT, 1100)
        if sub:
            pv.text_block(d, (110, y + 20), sub, pv.font("Poppins-SemiBold.ttf", 36), pv.SOFT, 1060)
    return im


def end_card(w, h, title, sub):
    im = pv.card(w, h, title, sub.split("\n")[0], "\n".join(sub.split("\n")[1:]) or None)
    d = ImageDraw.Draw(im)
    f = pv.font("Poppins-SemiBold.ttf", int(min(w, h) * 0.026))
    d.text(((w - d.textlength(CREDIT, font=f)) / 2, h - int(h * 0.07)), CREDIT, font=f, fill=pv.SOFT)
    return im


def boxes(layout, landscape_clip):
    """(canvas w, h), (clip box x, y, w, h)."""
    if layout == "vertical":
        if landscape_clip:
            return (1080, 1920), (40, 520, 1000, 464)
        return (1080, 1920), (170, 330, 740, 1480)
    if landscape_clip:
        return (1920, 1080), (310, 190, 1300, 603)
    return (1920, 1080), (1290, 60, 480, 960)


# ── scenes → video parts ────────────────────────────────────────────────────────────────────────────────────
def scene_video(i, sc, secs, layout, clips, tmp):
    clip, start, end, title, sub, _ = sc
    out = os.path.join(tmp, f"{layout}-{i:02d}.mp4")
    if clip is None:
        (w, h), _ = boxes(layout, False)
        png = os.path.join(tmp, f"{layout}-{i:02d}.png")
        end_card(w, h, title, sub).save(png)
        run(["-framerate", str(FPS), "-loop", "1", "-t", f"{secs:.3f}", "-i", png,
             "-vf", f"fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.35", "-c:v", "libx264", "-crf", "20", "-an", out])
        return out
    src = os.path.join(clips, clip)
    end = min(end, duration(src))
    probe = subprocess.run([FF, "-i", src], capture_output=True, text=True).stderr
    landscape = " 2400x1080" in probe
    (w, h), (bx, by, bw, bh) = boxes(layout, landscape)
    bg = os.path.join(tmp, f"{layout}-{i:02d}-bg.png")
    headline_bg(w, h, title, sub if layout == "landscape" else "", layout, wide_clip=landscape).save(bg)
    mask = os.path.join(tmp, f"{layout}-{i:02d}-mask.png")
    pv.rounded_mask(bw, bh, 40).save(mask)
    speed = max(0.6, min(4.0, (end - start) / secs))
    crop = "crop=2200:1020:100:60" if landscape else "crop=1080:2160:0:120"
    vf = (f"[0:v]trim={start}:{end},setpts=(PTS-STARTPTS)/{speed},fps={FPS},{crop},scale={bw}:{bh},"
          f"tpad=stop_mode=clone:stop_duration=30,format=rgba[p];"
          f"[2:v]format=gray,scale={bw}:{bh}[m];[p][m]alphamerge[pm];"
          f"[1:v][pm]overlay={bx}:{by}:shortest=1,fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.25[v]")
    run(["-i", src, "-framerate", str(FPS), "-loop", "1", "-i", bg, "-framerate", str(FPS), "-loop", "1", "-i", mask,
         "-filter_complex", vf, "-map", "[v]", "-t", f"{secs:.3f}", "-c:v", "libx264", "-crf", "20", "-an", out])
    return out


# ── sound ───────────────────────────────────────────────────────────────────────────────────────────────────
def pad(seconds):
    """A soft, slow chord pad (C, Am, F, G), well under the voice."""
    t = np.arange(int(seconds * SR)) / SR
    chords = [(261.63, 329.63, 392.00), (220.00, 261.63, 329.63), (174.61, 220.00, 261.63), (196.00, 246.94, 293.66)]
    bar = 4.0
    out = np.zeros_like(t)
    for k, chord in enumerate(chords * int(seconds // (bar * 4) + 2)):
        s0 = k * bar
        if s0 > seconds:
            break
        idx = (t >= s0) & (t < s0 + bar + 1.5)
        tt = t[idx] - s0
        env = np.minimum(1, tt / 1.2) * np.exp(-np.maximum(0, tt - bar) * 2.5)
        for f in chord:
            out[idx] += env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2 * tt) + 0.5 * np.sin(2 * np.pi * f / 2 * tt))
    out /= max(1e-6, np.abs(out).max())
    fade = np.minimum(1, np.minimum(t / 2, (seconds - t) / 2))
    return out * fade * 0.08


def ass_time(s):
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def captions(words_at, layout, path):
    """Burned-in captions: about four words at a time, the spoken word highlighted."""
    w, h = (1080, 1920) if layout == "vertical" else (1920, 1080)
    size, margin = (64, 150) if layout == "vertical" else (50, 150)
    align, margin_l, margin_r = (2, 60, 60) if layout == "vertical" else (1, 110, 900)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,Poppins ExtraBold,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,3,10,0,{align},{margin_l},{margin_r},{margin},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for chunk_start in range(0, len(words_at), 4):
        chunk = words_at[chunk_start:chunk_start + 4]
        for j, (word, s, e) in enumerate(chunk):
            text = " ".join(("{\\c&HFFE138&}" + wd + "{\\c&HFFFFFF&}") if k == j else wd for k, (wd, _, _) in enumerate(chunk))
            end = chunk[j + 1][1] if j + 1 < len(chunk) else e
            lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(end)},Cap,,0,0,0,,{text}")
    open(path, "w").write("\n".join(lines) + "\n")


def collapse_url(words):
    """Captions show the web address itself where Clara spells it out."""
    said = URL_SAID.replace(",", "").split()
    flat = [w.lower().strip(".,") for w, _, _ in words]
    for i in range(len(flat) - len(said) + 1):
        if flat[i:i + len(said)] == said:
            return words[:i] + [(URL_SHOWN, words[i][1], words[i + len(said) - 1][2])] + words[i + len(said):]
    return words


# ── assembly ────────────────────────────────────────────────────────────────────────────────────────────────
def build(name, scenes, layout, clips, out_dir, tmp):
    parts, voice_track, words_at, t = [], [], [], 0.0
    lead, tail = 0.35, 0.55
    for i, sc in enumerate(scenes):
        audio, words, secs = narrate(sc[5])
        length = lead + secs + tail + (1.2 if i == len(scenes) - 1 else 0)
        parts.append(scene_video(i, sc, length, layout, clips, tmp))
        voice_track.append((t + lead, audio))
        words_at += [(wd, t + lead + s, t + lead + e) for wd, s, e in collapse_url(words)]
        t += length
        print(f"  {name} scene {i + 1}/{len(scenes)}: {length:.1f}s", flush=True)
    total = t
    music = os.environ.get(f"CLARA_PROMO_MUSIC_{name.split('-')[-1].upper()}")   # e.g. CLARA_PROMO_MUSIC_REEL=track.wav
    mix = np.zeros(int(total * SR)) if music else pad(total)
    for start, a in voice_track:
        i0 = int(start * SR)
        mix[i0:i0 + len(a)] += a[: max(0, len(mix) - i0)]
    mix = np.clip(mix, -1, 1)
    wav = os.path.join(tmp, f"{name}.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    lst = os.path.join(tmp, f"{name}.txt")
    open(lst, "w").writelines(f"file '{p}'\n" for p in parts)
    silent = os.path.join(tmp, f"{name}-silent.mp4")
    run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent])
    ass = os.path.join(tmp, f"{name}.ass")
    captions(words_at, layout, ass)
    out = os.path.join(out_dir, f"{name}.mp4")
    # Three separate steps. Doing captions and the audio mix in one ffmpeg graph made it drop chunks of audio
    # (the "skips"), so: captions onto the picture, the sound on its own, then join them without re-encoding the video.
    captioned = os.path.join(tmp, f"{name}-captioned.mp4")
    run(["-i", silent, "-vf", f"subtitles={ass}:fontsdir={pv.FONTS}", "-an",
         "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p", captioned])
    mixed = os.path.join(tmp, f"{name}-mix.wav")
    if music:
        # music under the voice, ducked while Clara speaks (sidechain), faded at both ends, then loudness for social
        fc = (f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.2f},asetpts=PTS-STARTPTS,"
              f"afade=t=in:d=0.8,afade=t=out:st={max(0, total - 2.5):.2f}:d=2.5,volume=0.55[m];"
              f"[0:a]aresample=48000,aformat=channel_layouts=stereo,asplit=2[v1][v2];"
              f"[m][v1]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=450:makeup=1[md];"
              f"[md][v2]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
        run(["-i", wav, "-i", music, "-filter_complex", fc, "-map", "[a]", "-c:a", "pcm_s16le", mixed])
    else:
        run(["-i", wav, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000", "-c:a", "pcm_s16le", mixed])
    run(["-i", captioned, "-i", mixed, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-movflags", "+faststart", out])
    # never ship a video whose sound is shorter than its picture
    a_len, v_len = duration(mixed), duration(captioned)
    if abs(a_len - v_len) > 0.3:
        raise SystemExit(f"{name}: audio {a_len:.2f}s vs video {v_len:.2f}s")
    print(out, f"{total:.1f}s")


def main():
    clips, out_dir = sys.argv[1], sys.argv[2]
    which = sys.argv[3:] or ["reel", "full"]
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        if "reel" in which:
            build("clara-reel", REEL, "vertical", clips, out_dir, tmp)
        if "full" in which:
            build("clara-full", FULL, "landscape", clips, out_dir, tmp)


if __name__ == "__main__":
    main()
