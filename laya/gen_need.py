"""Generate 'what kind of help' task examples with local Bonsai (no thinking).
usage: gen_need.py out.jsonl [seed] [rounds]   (each round = one label x style x topic, ~12 examples)"""
import json, random, re, sys
sys.path.insert(0, "."); from need_spec import NEEDS
from gen_effort import llm, STYLES, TOPICS

HINTS = {   # what makes each label different from its neighbours, so the examples teach the boundary
    "browser": "Name a real site or web app (Amazon, OpenTable, Ticketmaster, Google Groups, a bank, a utility, Etsy, Craigslist, "
               "a school portal...) OR clearly need clicking through a site. Never just a question that a web search answers.",
    "search": "Questions or research answered by reading the web. Never doing something on a site (no booking, buying, posting, signing in).",
    "email_calendar": "Only the user's own email or calendar.",
    "apps": "Only connected apps and devices: Spotify, smart lights, thermostat, Notion, Todoist, GitHub, Slack, Discord, Telegram, "
            "Dropbox, OneDrive, posting to X/Instagram/Facebook, YouTube upload.",
    "computer": "Only the user's own PC: files, folders, disk, programs, terminal, system info.",
    "create": "Making a picture, logo, video, or code/script/app/website, or fixing a bug.",
    "memory": "Asking the assistant to remember, forget, or recall something about the user.",
    "other": "Tasks that fit none of the others: plans, conversions, calculations on the user's data, organizing ideas.",
}


def ask(label, style, topic, n=12):
    others = "; ".join(f"'{k}'" for k in NEEDS if k != label)
    prompt = (f"Write {n} different requests a user might send to their personal AI assistant, which can use their computer, "
              f"browser, email, calendar, connected apps and smart home.\nEvery request must need '{label}': {NEEDS[label]}\n"
              f"{HINTS[label]}\nNone may fit better under {others}.\nStyle: {style}. Loosely related to: {topic} "
              "(ignore the topic if it doesn't fit).\nMake them realistic and varied. Output ONLY a JSON array of strings.")
    m = re.search(r"\[.*\]", llm(prompt), re.S)
    try:
        return [s.strip() for s in json.loads(m.group(0)) if isinstance(s, str) and 3 < len(s) < 300]
    except Exception:
        return []


if __name__ == "__main__":
    random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    held_out = {json.loads(l)["text"].lower() for l in open("need_eval.jsonl")}
    out, seen, kept = open(sys.argv[1], "a"), set(), 0
    labels = list(NEEDS)
    for i in range(int(sys.argv[3]) if len(sys.argv) > 3 else 96):
        label = labels[i % len(labels)]
        for s in ask(label, random.choice(STYLES), random.choice(TOPICS)):
            key = s.lower()
            if key in seen or key in held_out:
                continue
            seen.add(key)
            out.write(json.dumps({"text": s, "label": label, "question": "need"}) + "\n"); out.flush(); kept += 1
        print(i, label, "kept", kept, flush=True)
