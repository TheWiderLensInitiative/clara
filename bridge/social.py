"""Social media / ad finishing for Clara's videos. Everything here runs on this PC (no cloud cost):

  captions      word-by-word, the spoken word highlighted in the brand's accent color (TikTok/Reels style)
  hook          big title in the first seconds, to stop the scroll
  callouts      short banners during chosen shots ("50% OFF", "Fresh daily")
  logo          small watermark in a corner
  end card      brand colors, logo, call to action and website
  music         a Lyria clip, ducked under the narration
  formats       one render, re-framed to 9:16 / 1:1 / 16:9 (blurred fill instead of black bars)
  loudness      normalized to -14 LUFS like the platforms expect
"""
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import video

from paths import FONT_DIR
FONTS = {  # name shown in the app -> (file, family name libass sees)
    "Poppins": ("Poppins-ExtraBold.ttf", "Poppins ExtraBold"),
    "Anton": ("Anton-Regular.ttf", "Anton"),
    "Bebas Neue": ("BebasNeue-Regular.ttf", "Bebas Neue"),
}
DEFAULT_BRAND = {"name": "", "tagline": "", "cta": "", "website": "", "primary": "#2F6BFF", "accent": "#FFD23F",
                 "text": "#FFFFFF", "font": "Poppins", "logo": "", "music": "upbeat, modern, positive"}
FORMAT_SIZES = {"9:16": (720, 1280), "1:1": (1080, 1080), "16:9": (1280, 720), "4:5": (864, 1080)}
END_CARD_SECONDS = 2.8


def _hex(c: str, fallback="#FFFFFF") -> tuple[int, int, int]:
    c = (c or fallback).lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return _hex(fallback)


def _ass_color(c: str, alpha=0) -> str:
    r, g, b = _hex(c)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _t(sec: float) -> str:
    sec = max(0.0, sec)
    return f"{int(sec // 3600)}:{int(sec % 3600 // 60):02d}:{sec % 60:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def caption_groups(words, max_words=3, max_chars=16):
    """Chunks of 1-3 words, breaking after punctuation, so captions stay big and readable."""
    groups, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x[0] for x in cur)
        if len(cur) >= max_words or len(text) >= max_chars or re.search(r"[.!?,;:]$", w[0]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def build_ass(size, brand, words=(), hook=None, callouts=(), total=0.0) -> str:
    """One .ass subtitle file with the captions, hook and callouts for a given frame size."""
    w, h = size
    vertical = h > w
    fam = FONTS.get(brand.get("font"), FONTS["Poppins"])[1]
    unit = min(w, h)
    cap_size = int(unit * (0.125 if vertical else 0.095))
    hook_size = int(unit * (0.1 if vertical else 0.085))
    white, accent, primary = brand.get("text") or "#FFFFFF", brand.get("accent") or "#FFD23F", brand.get("primary") or "#2F6BFF"
    styles = [
        # Name, Font, Size, Primary, Secondary, Outline, Back, Bold, Italic, U, S, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Align, ML, MR, MV
        f"Style: Cap,{fam},{cap_size},{_ass_color(white)},{_ass_color(accent)},&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{max(3, cap_size // 12)},2,2,40,40,{int(h * (0.24 if vertical else 0.1))},1",
        f"Style: Hook,{fam},{hook_size},{_ass_color(white)},{_ass_color(white)},{_ass_color(primary)},{_ass_color(primary)},0,0,0,0,100,100,0,0,3,{max(8, hook_size // 5)},0,8,50,50,{int(h * (0.13 if vertical else 0.08))},1",
        f"Style: Callout,{fam},{int(cap_size * 0.8)},{_ass_color('#111111')},{_ass_color('#111111')},{_ass_color(accent)},{_ass_color(accent)},0,0,0,0,100,100,0,0,3,{max(8, cap_size // 5)},0,5,50,50,0,1",
    ]
    events = []
    if hook:
        end = min(2.8, total or 2.8)
        events.append(f"Dialogue: 1,{_t(0.1)},{_t(end)},Hook,,0,0,0,,{{\\fad(150,250)\\t(0,180,\\fscx106\\fscy106)\\t(180,320,\\fscx100\\fscy100)}}{_esc(hook).upper()}")
    for c in callouts:
        events.append(f"Dialogue: 1,{_t(c['start'])},{_t(c['end'])},Callout,,0,0,0,,{{\\fad(120,200)}}{_esc(c['text']).upper()}")
    for g in caption_groups(list(words)):
        g_end = g[-1][2] + 0.05
        for i, (word, start, end) in enumerate(g):
            nxt = g[i + 1][1] if i + 1 < len(g) else g_end
            parts = []
            for j, (wj, _, _) in enumerate(g):
                txt = _esc(wj).upper()
                parts.append(f"{{\\c{_ass_color(accent)}\\fscx108\\fscy108}}{txt}{{\\c{_ass_color(white)}\\fscx100\\fscy100}}" if j == i else txt)
            events.append(f"Dialogue: 0,{_t(start)},{_t(nxt)},Cap,,0,0,0,,{' '.join(parts)}")
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nScaledBorderAndShadow: yes\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            + "\n".join(styles) + "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    return head + "\n".join(events) + "\n"


def _font(brand, px):
    f = FONTS.get(brand.get("font"), FONTS["Poppins"])[0]
    try:
        return ImageFont.truetype(str(FONT_DIR / f), px)
    except Exception:
        return ImageFont.load_default()


def _fit_text(draw, text, brand, max_w, start_px):
    px = start_px
    while px > 18:
        font = _font(brand, px)
        if draw.textlength(text, font=font) <= max_w:
            return font
        px -= 4
    return _font(brand, px)


def end_card(size, brand, out: Path, logo: Path | None, cta: str | None):
    """Brand gradient, logo (or name), call-to-action pill and website."""
    w, h = size
    p, a = _hex(brand.get("primary"), "#2F6BFF"), _hex(brand.get("accent"), "#FFD23F")
    dark = tuple(int(c * 0.35) for c in p)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):          # diagonal-ish gradient: dark primary -> primary
        for x in range(0, w, 4):
            t = min(1.0, (y / h) * 0.75 + (x / w) * 0.25)
            col = tuple(int(dark[i] + (p[i] - dark[i]) * t) for i in range(3))
            for dx in range(4):
                if x + dx < w:
                    px[x + dx, y] = col
    d = ImageDraw.Draw(img)
    unit = min(w, h)
    y = int(h * (0.30 if h > w else 0.22))
    if logo and logo.exists():
        lg = Image.open(logo).convert("RGBA")
        lg.thumbnail((int(w * 0.45), int(h * 0.22)))
        img.paste(lg, ((w - lg.width) // 2, y), lg)
        y += lg.height + int(unit * 0.05)
    elif brand.get("name"):
        f = _fit_text(d, brand["name"], brand, w * 0.85, int(unit * 0.13))
        tw = d.textlength(brand["name"], font=f)
        d.text(((w - tw) / 2, y), brand["name"], font=f, fill=_hex(brand.get("text")))
        y += int(unit * 0.17)
    if brand.get("tagline"):
        f = _fit_text(d, brand["tagline"], brand, w * 0.8, int(unit * 0.05))
        tw = d.textlength(brand["tagline"], font=f)
        d.text(((w - tw) / 2, y), brand["tagline"], font=f, fill=_hex(brand.get("text")))
        y += int(unit * 0.09)
    cta = (cta or brand.get("cta") or "").strip()
    if cta:
        f = _fit_text(d, cta.upper(), brand, w * 0.7, int(unit * 0.07))
        tw = d.textlength(cta.upper(), font=f)
        bh = int(f.size * 1.9)
        bw = int(tw + f.size * 1.6)
        x0 = (w - bw) // 2
        d.rounded_rectangle([x0, y, x0 + bw, y + bh], radius=bh // 2, fill=a)
        d.text(((w - tw) / 2, y + (bh - f.size) / 2 - f.size * 0.12), cta.upper(), font=f, fill=(17, 17, 17))
        y += bh + int(unit * 0.05)
    if brand.get("website"):
        f = _fit_text(d, brand["website"], brand, w * 0.8, int(unit * 0.045))
        tw = d.textlength(brand["website"], font=f)
        d.text(((w - tw) / 2, y), brand["website"], font=f, fill=_hex(brand.get("text")))
    img.save(out, quality=95)


def logo_png(logo: Path, size, out: Path) -> Path:
    """Watermark: logo scaled to ~16% of the frame width, slightly transparent."""
    w, h = size
    lg = Image.open(logo).convert("RGBA")
    lg.thumbnail((int(min(w, h) * 0.18), int(min(w, h) * 0.18)))
    alpha = lg.getchannel("A").point(lambda v: int(v * 0.85))
    lg.putalpha(alpha)
    lg.save(out)
    return out


def reframe_filter(src_size, dst_size) -> str:
    """Crop when the shapes are close; otherwise a blurred, darkened copy fills the frame behind the full picture."""
    (sw, sh), (w, h) = src_size, dst_size
    ratio = max((sw / sh) / (w / h), (w / h) / (sw / sh))
    if ratio < 1.35:
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    return (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=28,eq=brightness=-0.12[bg];"
            f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")


def mix_audio(clean: Path, out: Path, total: float, narration: Path | None, music: Path | None):
    """Clip sound (quieter under a voice) + narration + music ducked under the narration, normalized to -14 LUFS."""
    ins, parts = ["-i", str(clean)], []
    parts.append(f"[0:a]apad,atrim=0:{total:.2f},volume={0.3 if narration else 1.0}[bed]")
    labels = ["[bed]"]
    idx = 1
    if narration:
        ins += ["-i", str(narration)]
        parts.append(f"[{idx}:a]aresample=48000,apad,atrim=0:{total:.2f},asplit=2[vo][key]")
        labels.append("[vo]")
        idx += 1
    if music:
        ins += ["-stream_loop", "-1", "-i", str(music)]
        fade = max(0.0, total - 1.8)
        parts.append(f"[{idx}:a]aresample=48000,atrim=0:{total:.2f},volume=0.35,afade=t=out:st={fade:.2f}:d=1.8[mus]")
        if narration:
            parts.append("[mus][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[ducked]")
            labels.append("[ducked]")
        else:
            labels.append("[mus]")
    elif narration:
        parts.append("[key]anullsink")
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
                 "loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    video._run([*ins, "-filter_complex", ";".join(parts), "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])


def render_format(clean: Path, src_size, dst_size, out: Path, ass: Path, logo: Path | None, card: Path | None,
                  audio: Path, body_seconds: float):
    """Reframe the joined clips, burn captions/hook/callouts, add the logo, append the end card, mux the mixed audio."""
    w, h = dst_size
    ins = ["-i", str(clean)]
    chain = f"[0:v]{reframe_filter(src_size, dst_size)},fps=30,format=yuv420p[v0];"
    last = "v0"
    if logo:
        ins += ["-i", str(logo)]
        m = int(min(w, h) * 0.04)
        chain += f"[{last}][1:v]overlay=W-w-{m}:{m}[v1];"
        last = "v1"
    fonts = str(FONT_DIR)
    chain += f"[{last}]subtitles='{ass}':fontsdir='{fonts}'[body];"
    if card:
        ins += ["-loop", "1", "-t", f"{END_CARD_SECONDS}", "-i", str(card)]
        ci = 2 if logo else 1
        chain += (f"[{ci}:v]scale={w}:{h},setsar=1,fps=30,format=yuv420p[card];"
                  f"[body][card]xfade=transition=fade:duration=0.4:offset={max(0.1, body_seconds - 0.4):.2f}[vout]")
    else:
        chain += "[body]null[vout]"
    chain = chain.replace("[vout]", "[vfinal]") + ";[vfinal]format=yuv420p[vout]"   # overlays/subtitles can switch to 4:4:4, which phones and TikTok reject
    ins += ["-i", str(audio)]
    ai = len([x for x in ins if x == "-i"]) - 1
    video._run([*ins, "-filter_complex", chain, "-map", "[vout]", "-map", f"{ai}:a", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out)])
