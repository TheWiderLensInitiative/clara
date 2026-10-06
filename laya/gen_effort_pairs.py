"""Contrast pairs for quick/deep on the same subject: going through many things and judging them is deep, one lookup or
one action is quick. v3 learned "inbox"/"repo"/"documents" = quick from the need data; these teach the difference.
usage: gen_effort_pairs.py out.jsonl [seed] [rounds]"""
import json, random, re, sys
sys.path.insert(0, ".")
from gen_effort import llm, STYLES

SUBJECTS = ["email inbox", "calendar", "github repositories and issues", "documents and files on the PC", "photos", "Dropbox files",
            "Notion pages", "Todoist tasks", "Slack messages", "bank and card transactions", "bills and subscriptions",
            "smart home devices and routines", "Spotify playlists", "browser bookmarks", "downloads folder", "receipts",
            "news sites", "online orders", "contacts", "YouTube channel videos", "social media posts and comments", "notes"]


def pairs(subject, style, n=6):
    prompt = (f"About the user's {subject}, write {n} pairs of requests to a personal AI assistant.\n"
              "In each pair, 'deep' asks it to go through, review, sort, back up, audit or clean up MANY items and use judgment "
              "(decide which ones matter, need a reply, need fixing, are duplicates, what to keep, then report or act). "
              "'quick' asks for ONE simple lookup or ONE action on the same subject (show, open, count, read one, add one, "
              "turn on, play) with no judgment.\n"
              f"Style: {style}. Vary the wording; don't always start with 'go through'.\n"
              'Output ONLY a JSON array of objects like {"deep": "...", "quick": "..."}.')
    m = re.search(r"\[.*\]", llm(prompt), re.S)
    try:
        return [(d["deep"].strip(), d["quick"].strip()) for d in json.loads(m.group(0))
                if isinstance(d, dict) and isinstance(d.get("deep"), str) and isinstance(d.get("quick"), str)]
    except Exception:
        return []


if __name__ == "__main__":
    random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    held_out = {json.loads(l)["text"].lower() for l in open("effort_eval.jsonl")}
    out, seen, kept = open(sys.argv[1], "a"), set(), 0
    for i in range(int(sys.argv[3]) if len(sys.argv) > 3 else 44):
        for deep, quick in pairs(SUBJECTS[i % len(SUBJECTS)], random.choice(STYLES)):
            for text, label in ((deep, "deep"), (quick, "quick")):
                if 3 < len(text) < 300 and text.lower() not in seen and text.lower() not in held_out:
                    seen.add(text.lower())
                    out.write(json.dumps({"text": text, "label": label, "question": "effort"}) + "\n"); kept += 1
        out.flush()
        print(i, SUBJECTS[i % len(SUBJECTS)], "kept", kept, flush=True)
