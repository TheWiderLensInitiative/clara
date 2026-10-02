"""clara-cloud: things Bonsai can't do locally, through the Bridge's OpenRouter gateway (key never visible to Clara).

- generate_image: image generation; results land in the workspace (the user's Library).
- make_video: clips or short multi-shot videos, rendered in the cloud and finished on the PC; delivered to the chat.
- cloud_status: today's spend, the user's cap, and the chosen models.
- suggest_cloud_budget: propose a daily cap; the user accepts or declines on their phone. Clara can never set it.
Heavy coding/reasoning goes through delegate_task, whose sub-agents run on the user's chosen cloud model.
"""
import json
import os
import urllib.error
import urllib.request

BRIDGE = os.environ.get("CLARA_BRIDGE_URL", "http://127.0.0.1:8700")


def _link(path, body=None, timeout=30):
    req = urllib.request.Request(BRIDGE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + os.environ.get("CLARA_LINK_TOKEN", ""), "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


IMAGE_SCHEMA = {
    "name": "generate_image",
    "description": "Generate an image with a cloud image model (via the user's OpenRouter account). Use for pictures, illustrations, "
                   "logos, character art and mockups. Write a detailed prompt (subject, style, colors, composition). The image is saved "
                   "in your workspace and appears in the user's Library; mention the file name in your reply. The user may be asked "
                   "to approve cloud use on their phone first.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Detailed description of the image"},
            "aspect_ratio": {"type": "string", "description": "e.g. 1:1, 16:9, 9:16, 4:3"},
            "name": {"type": "string", "description": "Short file name hint, e.g. clara-character-v2"},
        },
        "required": ["prompt"],
    },
}
VIDEO_SCHEMA = {
    "name": "make_video",
    "description": "Make a video with the user's cloud video model (via their OpenRouter account), finished on the PC. For a simple clip "
                   "pass one shot. For a short story, ad or explainer, plan 2-5 shots (about 4-8 seconds each) that flow together, each "
                   "with a vivid visual prompt (subject, action, camera move, lighting, style) and keep characters/style consistent across "
                   "shots. To animate a still (one you made with generate_image, or a photo the user attached), pass its workspace path "
                   "as that shot's image. Optional narration is spoken over the video in your own voice (about 2.5 words per second of "
                   "video). The user approves the estimated cost on their phone, then it renders in the background and the finished "
                   "video is delivered to their chat automatically: after calling this, just tell them it's on the way and the estimate."
                   ,
    "parameters": {
        "type": "object",
        "properties": {
            "shots": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "object", "properties": {
                "prompt": {"type": "string", "description": "What happens in this shot, visually"},
                "seconds": {"type": "number", "description": "Length of this shot, e.g. 5"},
                "image": {"type": "string", "description": "Optional workspace path of an image to animate, e.g. images/robot.jpg"},
            }, "required": ["prompt"]}},
            "aspect_ratio": {"type": "string", "description": "16:9 (landscape), 9:16 (phone/vertical, reels) or 1:1"},
            "narration": {"type": "string", "description": "Optional voice-over script in your voice"},
            "sound": {"type": "boolean", "description": "Let the model create sound effects/ambience (ignored when narrated). Default true"},
            "title": {"type": "string", "description": "Short title (always set one), used for the file name the user shares"},
            "hook": {"type": "string", "description": "Social/ads: big scroll-stopping title shown for the first ~2.5 s (max ~6 words)"},
            "captions": {"type": "boolean", "description": "Word-by-word captions of the narration (default on for social videos)"},
            "callouts": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string", "description": "2-4 words, e.g. '50% OFF' or 'Fresh daily'"},
                "shot": {"type": "integer", "description": "Shot number (1-based) it appears in"}}, "required": ["text", "shot"]}},
            "brand": {"type": "boolean", "description": "Use the user's brand kit: logo watermark, colors and font"},
            "end_card": {"type": "boolean", "description": "Finish with a branded card: logo, call to action, website"},
            "cta": {"type": "string", "description": "Call to action for the end card, e.g. 'Order today' (default: brand kit's)"},
            "music": {"type": "string", "description": "Background music style, e.g. 'upbeat acoustic pop' (adds $0.04), or 'brand' for the brand kit's style"},
            "formats": {"type": "array", "items": {"type": "string", "enum": ["9:16", "1:1", "16:9", "4:5"]},
                        "description": "Extra versions to export from the same render (free), e.g. ['1:1', '16:9']"},
        },
        "required": ["shots"],
    },
}
SOCIAL_GUIDE = (
    " SOCIAL VIDEOS AND ADS: use aspect 9:16 (TikTok/Reels/Shorts; add formats ['1:1','16:9'] if they post elsewhere), 3-4 shots of "
    "4-6 s (15-25 s total), brand=true and end_card=true when it's for their business (check get_brand_kit first), narration in a "
    "warm, punchy voice with captions, a hook of max 6 words, 1-2 callouts, and music. Recipes: PRODUCT AD = hook (problem or bold "
    "claim) -> product close-up -> product in use / happy customer -> offer + CTA. BEFORE/AFTER = the problem -> the transformation "
    "-> result + CTA. 3 TIPS = hook 'three tips for X' -> one shot per tip with a callout -> CTA. STORY/TESTIMONIAL = relatable "
    "moment -> discovery -> result -> CTA. Keep the same characters, product look and color palette in every shot prompt. "
    "NEVER invent business facts for an ad (opening hours, prices, discounts, addresses, awards, ingredients, guarantees): only use "
    "what the user or the brand kit told you. If an ad needs a fact you don't have, ask the user first or leave it out.")
VIDEO_SCHEMA["description"] += SOCIAL_GUIDE
BRAND_GET_SCHEMA = {
    "name": "get_brand_kit",
    "description": "Read the user's brand kit (business name, tagline, call to action, website, colors, font, music style, whether a "
                   "logo is set) before making ads or branded videos.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}
BRAND_SET_SCHEMA = {
    "name": "update_brand_kit",
    "description": "Fill in or change the user's brand kit when they tell you about their business (name, tagline, call to action, "
                   "website, colors as #RRGGBB, font: Poppins | Anton | Bebas Neue, music style). The logo is added by the user in "
                   "the app (Clara menu -> Brand kit).",
    "parameters": {"type": "object", "properties": {k: {"type": "string"} for k in
                   ("name", "tagline", "cta", "website", "primary", "accent", "text", "font", "music")}, "required": []},
}
RESTYLE_SCHEMA = {
    "name": "restyle_yourself",
    "description": "Change how you (Clara) look in the user's app: your animated character. Use it when the user asks you to change "
                   "your look, colors, outfit or vibe (e.g. 'make yourself purple', 'wear sunglasses', 'look cozy for winter'). Only pass the "
                   "fields you're changing. Colors are hex like #FF8800 (body: 2-4 colors for your gradient). Shapes: round, tall, wide, blob, "
                   "square. Hair: curl (your logo curl), tuft, antenna, spikes, bun, none. Eyes: round, big, sparkle, sleepy, dots. Up to 3 "
                   "accessories: glasses, sunglasses, bow, cat_ears, bunny_ears, crown, beanie, flower, scarf (accessory_color colors them). "
                   "Presets you can copy: Original, Sunset, Mint, Kitty, Robot, Cozy, Royal, Cool. Give the look a short name. It shows "
                   "instantly and the user can undo it with one tap, so no need to ask first when they asked for a change.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}, "body": {"type": "array", "items": {"type": "string"}}, "shape": {"type": "string"},
        "hair": {"type": "string"}, "hair_colors": {"type": "array", "items": {"type": "string"}}, "eyes": {"type": "string"},
        "eye_color": {"type": "string"}, "cheeks": {"type": "string", "description": "hex, or 'none'"},
        "halo": {"type": "array", "items": {"type": "string"}}, "headphone_accents": {"type": "array", "items": {"type": "string"}},
        "accessories": {"type": "array", "items": {"type": "string"}}, "accessory_color": {"type": "string"},
        "preset": {"type": "string", "description": "start from a preset, then apply the other fields"},
        "note": {"type": "string", "description": "one short line to the user about the new look"},
    }, "required": []},
}
STATUS_SCHEMA = {
    "name": "cloud_status",
    "description": "Check cloud AI usage: dollars spent today, the user's daily cap (if any), and which cloud models are selected.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}
BUDGET_SCHEMA = {
    "name": "suggest_cloud_budget",
    "description": "Suggest a daily cloud spending cap to the user, with a short reason (e.g. after a big coding task, or when the cap "
                   "was hit). The user accepts or declines on their phone; you cannot set or change the cap yourself.",
    "parameters": {"type": "object", "properties": {"amount": {"type": "number", "description": "Dollars per day"},
                                                    "reason": {"type": "string"}}, "required": ["amount", "reason"]},
}


def handle_image(args, session_id=None, **_):
    a = args or {}
    import hermes_plugins.clara_guardian as guardian
    body = {"prompt": a.get("prompt", ""), "aspect_ratio": a.get("aspect_ratio"), "name": a.get("name"), "conversation_id": session_id}
    try:   # may wait on the user's OK for cloud use, for as long as they need
        res = guardian.patient(lambda: _link("/internal/cloud/image", body, timeout=None))
        return json.dumps({"error": "The user stopped this task."} if res is guardian.STOPPED else res)
    except Exception as e:
        return json.dumps({"error": f"Couldn't reach the Clara Bridge: {type(e).__name__}"})


def handle_video(args, session_id=None, **_):
    a = args or {}
    body = {"shots": [{"prompt": str(sh.get("prompt", "")), "seconds": sh.get("seconds"), "image": sh.get("image")}
                      for sh in (a.get("shots") or []) if isinstance(sh, dict)],
            "aspect_ratio": a.get("aspect_ratio") or "16:9", "narration": a.get("narration"), "sound": a.get("sound", True) is not False,
            "title": a.get("title"), "conversation_id": session_id,
            "hook": a.get("hook"), "captions": a.get("captions"), "brand": bool(a.get("brand")), "end_card": bool(a.get("end_card")),
            "cta": a.get("cta"), "music": a.get("music"), "formats": [f for f in (a.get("formats") or []) if isinstance(f, str)],
            "callouts": [{"text": str(c.get("text", "")), "shot": int(c.get("shot") or 1)} for c in (a.get("callouts") or []) if isinstance(c, dict)]}
    import hermes_plugins.clara_guardian as guardian
    try:   # waits only for the user's OK on the phone, for as long as they need
        res = guardian.patient(lambda: _link("/internal/cloud/video", body, timeout=None))
        return json.dumps({"error": "The user stopped this task."} if res is guardian.STOPPED else res)
    except urllib.error.HTTPError as e:
        return json.dumps({"error": e.read().decode(errors="replace")[:300]})
    except Exception as e:
        return json.dumps({"error": f"Couldn't reach the Clara Bridge: {type(e).__name__}"})


def handle_brand_get(args, **_):
    try:
        return json.dumps(_link("/internal/brand"))
    except Exception as e:
        return json.dumps({"error": f"Couldn't reach the Clara Bridge: {type(e).__name__}"})


def handle_brand_set(args, **_):
    try:
        return json.dumps(_link("/internal/brand", {k: v for k, v in (args or {}).items() if v}))
    except urllib.error.HTTPError as e:
        return json.dumps({"error": e.read().decode(errors="replace")[:300]})
    except Exception as e:
        return json.dumps({"error": f"Couldn't reach the Clara Bridge: {type(e).__name__}"})


PRESET_NAMES = ["Original", "Sunset", "Mint", "Kitty", "Robot", "Cozy", "Royal", "Cool"]


def handle_restyle(args, **_):
    a = dict(args or {})
    note = a.pop("note", None)
    base = {}
    if a.get("preset"):
        p = str(a.pop("preset"))
        if p not in PRESET_NAMES:
            return json.dumps({"error": f"unknown preset; choose from {', '.join(PRESET_NAMES)}"})
        base = {"preset": p}
    try:
        return json.dumps(_link("/internal/character", {"style": {**a, **({"_preset": base["preset"]} if base else {})}, "note": note}))
    except Exception as e:
        return json.dumps({"error": f"Couldn't reach the Clara Bridge: {type(e).__name__}"})


def handle_status(args, **_):
    try:
        return json.dumps(_link("/internal/cloud/status"))
    except Exception as e:
        return json.dumps({"error": f"Couldn't reach the Clara Bridge: {type(e).__name__}"})


def handle_budget(args, **_):
    a = args or {}
    try:
        return json.dumps(_link("/internal/cloud/suggest-budget", {"amount": float(a.get("amount", 0)), "reason": str(a.get("reason", ""))}))
    except Exception as e:
        return json.dumps({"error": f"Couldn't reach the Clara Bridge: {type(e).__name__}"})


def register(ctx) -> None:
    ctx.register_tool(name="generate_image", toolset="clara_cloud", schema=IMAGE_SCHEMA, handler=handle_image, emoji="🎨")
    ctx.register_tool(name="make_video", toolset="clara_cloud", schema=VIDEO_SCHEMA, handler=handle_video, emoji="🎬")
    ctx.register_tool(name="get_brand_kit", toolset="clara_cloud", schema=BRAND_GET_SCHEMA, handler=handle_brand_get, emoji="🏷️")
    ctx.register_tool(name="update_brand_kit", toolset="clara_cloud", schema=BRAND_SET_SCHEMA, handler=handle_brand_set, emoji="🏷️")
    ctx.register_tool(name="restyle_yourself", toolset="clara_cloud", schema=RESTYLE_SCHEMA, handler=handle_restyle, emoji="✨")
    ctx.register_tool(name="cloud_status", toolset="clara_cloud", schema=STATUS_SCHEMA, handler=handle_status, emoji="☁️")
    ctx.register_tool(name="suggest_cloud_budget", toolset="clara_cloud", schema=BUDGET_SCHEMA, handler=handle_budget, emoji="💰")
