"""Build Clara's Google Play videos from raw phone screen recordings.

    python tools/play_videos.py <clips_dir> <out_dir>

<clips_dir> holds `adb shell screenrecord` captures (1080x2400). The cut list below names the clip, start and end second,
speed-up, and caption for each shot. Needs ffmpeg (imageio-ffmpeg) and Pillow. Fonts come from the Clara install
(~/.local/share/clara/fonts) and the logo from brand/.
"""
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.expanduser(os.environ.get("CLARA_FONTS", "~/.local/share/clara/fonts"))
LOGO = os.path.join(ROOT, "brand", "clara-logo.png")
FPS = 30
PHONE_CROP = "crop=1080:2160:0:120"   # drop the status bar and navigation bar (also keeps personal icons out)

TEXT = (255, 255, 255)
SOFT = (205, 200, 255)
ACCENT = (110, 200, 255)


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def glow_bg(w, h):
    g = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(g)
    d.ellipse((-w // 4, h // 6, w // 2, h + h // 4), fill=(55, 25, 130))
    d.ellipse((w // 2, -h // 3, w + w // 4, h // 2), fill=(20, 40, 120))
    return Image.blend(Image.new("RGB", (w, h)), g.filter(ImageFilter.GaussianBlur(min(w, h) // 5)), 0.6)


def wrap(draw, text, f, width):
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            test = (line + " " + word).strip()
            if draw.textlength(test, font=f) <= width:
                line = test
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def text_block(draw, xy, text, f, fill, width, spacing=1.25, align="left"):
    x, y = xy
    for line in wrap(draw, text, f, width):
        lx = x if align == "left" else x + (width - draw.textlength(line, font=f)) / 2
        draw.text((lx, y), line, font=f, fill=fill)
        y += int(f.size * spacing)
    return y


def card(w, h, title, sub, foot=None):
    """A still title or end card."""
    im = glow_bg(w, h)
    logo = Image.open(LOGO).convert("RGB")
    s = int(min(w, h) * 0.38)
    top = int(h * (0.08 if w > h else 0.2))
    layer = Image.new("RGB", (w, h))
    layer.paste(logo.resize((s, s), Image.LANCZOS), ((w - s) // 2, top))
    from PIL import ImageChops
    im = ImageChops.lighter(im, layer)
    d = ImageDraw.Draw(im)
    y = top + s + int(h * 0.03)
    y = text_block(d, (int(w * 0.08), y), title, font("Poppins-ExtraBold.ttf", int(min(h * 0.075, w * 0.075))), TEXT, int(w * 0.84), align="center")
    y = text_block(d, (int(w * 0.1), y + int(h * 0.01)), sub, font("Poppins-SemiBold.ttf", int(min(h * 0.035, w * 0.042))), SOFT, int(w * 0.8), align="center")
    if foot:
        text_block(d, (int(w * 0.1), y + int(h * 0.03)), foot, font("Poppins-SemiBold.ttf", int(min(h * 0.026, w * 0.034))), ACCENT, int(w * 0.8), align="center")
    return im


def frame_landscape(caption, sub=""):
    """1920x1080 background with the caption on the left; the phone goes on the right."""
    im = glow_bg(1920, 1080)
    d = ImageDraw.Draw(im)
    y = text_block(d, (130, 330), caption, font("Poppins-ExtraBold.ttf", 76), TEXT, 1000)
    if sub:
        text_block(d, (130, y + 24), sub, font("Poppins-SemiBold.ttf", 38), SOFT, 980)
    return im


def frame_portrait(caption):
    """1080x1920 background with a caption band on top; the phone sits below it."""
    im = glow_bg(1080, 1920)
    d = ImageDraw.Draw(im)
    f = font("Poppins-ExtraBold.ttf", 52)
    lines = wrap(d, caption, f, 980)
    y = 120 - len(lines) * 32
    for line in lines:
        d.text(((1080 - d.textlength(line, font=f)) / 2, y), line, font=f, fill=TEXT)
        y += 66
    return im


def rounded_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


def run(args):
    subprocess.run([FF, "-loglevel", "error", "-y", *args], check=True)


def still(png, seconds, out):
    run(["-framerate", str(FPS), "-loop", "1", "-t", str(seconds), "-i", png, "-f", "lavfi", "-t", str(seconds), "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", f"fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.4,fade=t=out:st={seconds - 0.4}:d=0.4",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-shortest", out])


def duration(path):
    err = subprocess.run([FF, "-i", path], capture_output=True, text=True).stderr
    h, m, s = err.split("Duration: ")[1].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def shot(clip, start, end, speed, bg_png, mask_png, layout, out):
    """One phone shot: trim, speed up, crop, scale, round the corners, place on the background."""
    end = min(end, duration(clip))
    if layout == "landscape":
        pw, ph, px, py = 480, 960, 1310, 60
    else:
        pw, ph, px, py = 840, 1680, 120, 220
    dur = (end - start) / speed
    vf = (f"[0:v]trim={start}:{end},setpts=(PTS-STARTPTS)/{speed},fps={FPS},{PHONE_CROP},scale={pw}:{ph},format=rgba[p];"
          f"[2:v]format=gray,scale={pw}:{ph}[m];[p][m]alphamerge[pm];"
          f"[1:v][pm]overlay={px}:{py}:shortest=1,fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.3,fade=t=out:st={max(dur - 0.3, 0)}:d=0.3[v]")
    run(["-i", clip, "-framerate", str(FPS), "-loop", "1", "-i", bg_png, "-framerate", str(FPS), "-loop", "1", "-i", mask_png, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-filter_complex", vf, "-map", "[v]", "-map", "3:a", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", out])


def build(name, layout, intro, shots, outro, clips, out_dir, tmp):
    w, h = (1920, 1080) if layout == "landscape" else (1080, 1920)
    parts = []
    mask = os.path.join(tmp, f"mask-{layout}.png")
    pw, ph = (480, 960) if layout == "landscape" else (840, 1680)
    rounded_mask(pw, ph, 44 if layout == "landscape" else 60).save(mask)
    for i, (title, sub, foot, secs) in enumerate([intro, outro]):
        p = os.path.join(tmp, f"{name}-card{i}.png")
        card(w, h, title, sub, foot).save(p)
        v = os.path.join(tmp, f"{name}-card{i}.mp4")
        still(p, secs, v)
        parts.append(v)
    intro_v, outro_v = parts
    parts = [intro_v]
    for i, s in enumerate(shots):
        clip, start, end, speed, caption = s[:5]
        sub = s[5] if len(s) > 5 else ""
        bg = os.path.join(tmp, f"{name}-bg{i}.png")
        (frame_landscape(caption, sub) if layout == "landscape" else frame_portrait(caption)).save(bg)
        v = os.path.join(tmp, f"{name}-shot{i}.mp4")
        shot(os.path.join(clips, clip), start, end, speed, bg, mask, layout, v)
        parts.append(v)
    parts.append(outro_v)
    lst = os.path.join(tmp, f"{name}.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    out = os.path.join(out_dir, f"{name}.mp4")
    run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    print(out)


END = ("Clara", "Free and open source", "Needs a Linux PC with an NVIDIA GPU (12 GB+)\nclara.thewiderlens.info")

VIDEOS = {
    # 1. Store listing promo (landscape, for YouTube)
    "clara-promo": ("landscape",
        ("Meet Clara", "Your private AI assistant, running on your own PC", None, 3.0),
        [
            ("clip1.mp4", 1.0, 15.0, 1.6, "Ask her anything", "Answers in seconds, from the GPU in your own computer."),
            ("clip2.mp4", 1.0, 36.0, 4.5, "She does real work", "Research, files, code, a browser of her own."),
            ("clip2b.mp4", 2.0, 12.0, 1.4, "And brings back the answer", "Nothing you ask leaves your PC."),
            ("clip3.mp4", 3.0, 30.0, 2.5, "You approve anything risky", "Sending, deleting, buying and installing ask you first."),
            ("clip1.mp4", 40.5, 52.0, 1.6, "Reminders and routines", "Delivered to your phone."),
            ("clip2.mp4", 53.0, 58.0, 1.0, "Connect your accounts", "Gmail, Calendar, Spotify, Notion and more. Your logins stay on your PC."),
        ],
        END + (4.0,)),
    # 2. Reviewer demo (portrait): how the app works with the user's own PC
    "clara-reviewer-demo": ("portrait",
        ("Clara: how it works", "The phone app for a self-hosted AI assistant. Clara runs on the user's own Linux PC; this app pairs with it.", None, 5.0),
        [
            ("pair.mp4", 0.0, 99.0, 1.0, "1. Pair with the PC using the code from 'clara pair'"),
            ("clip1.mp4", 0.0, 20.0, 1.0, "2. Chat: replies come from the PC"),
            ("clip2.mp4", 0.0, 36.0, 2.0, "3. Tasks: Clara works on her own sandboxed computer"),
            ("clip2b.mp4", 0.0, 13.0, 1.0, "…and reports back"),
            ("clip3.mp4", 0.0, 38.0, 1.0, "4. Risky actions need the user's approval"),
            ("clip1.mp4", 36.0, 56.0, 1.0, "5. Reminders are scheduled on the PC"),
        ],
        END + (4.0,)),
    # 3. Foreground service declaration (portrait)
    "clara-foreground-service": ("portrait",
        ("Why Clara uses a foreground service", "Type: remote messaging. It keeps a live link to the user's own PC so replies and approval requests arrive at once.", None, 5.0),
        [
            ("fgs.mp4", 0.0, 99.0, 1.0, "The persistent notification while paired"),
            ("clip3.mp4", 8.0, 30.0, 1.0, "An approval request arrives as a notification"),
        ],
        ("Clara", "The service runs only while the phone is paired.", None, 4.0)),
}


class _Keep:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        os.makedirs(self.path, exist_ok=True)
        return self.path

    def __exit__(self, *a):
        return False


def main():
    clips, out_dir = sys.argv[1], sys.argv[2]
    only = sys.argv[3:]
    os.makedirs(out_dir, exist_ok=True)
    keep = os.environ.get("CLARA_VIDEO_TMP")   # set to keep the intermediate files
    with (tempfile.TemporaryDirectory() if not keep else _Keep(keep)) as tmp:
        for name, (layout, intro, shots, outro) in VIDEOS.items():
            if only and name not in only:
                continue
            build(name, layout, intro, shots, outro, clips, out_dir, tmp)


if __name__ == "__main__":
    main()
