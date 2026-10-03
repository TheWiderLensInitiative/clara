"""Generate follow-up examples with local Bonsai (no thinking): Clara's last reply after a task, then the user's next message.
usage: gen_followup.py out.jsonl [seed] [rounds]"""
import json, random, re, sys
sys.path.insert(0, "."); from followup_spec import FOLLOWUPS
from gen_effort import llm, STYLES, TOPICS

KINDS = {
    "continue": ["says yes or no to something Clara offered or asked", "corrects or changes what she did (a time, a name, an amount)",
                 "asks for more of the same or the next one", "asks about her result ('which one', 'how much', 'why')",
                 "adds a detail she needs", "a very short reply like 'also', 'that one', 'the second', 'do it', 'nah'"],
    "new": ["thanks or praise only", "a greeting or small talk", "a feeling or a joke", "a brand new request on another subject",
            "an unrelated general-knowledge question", "a new task for a different app or service"],
}


def ask(label, style, topic, n=8):
    kind = random.choice(KINDS[label])
    prompt = (f"Clara is a personal AI assistant that just finished a task for the user (it can use their computer, browser, email, "
              f"calendar, apps and smart home). Write {n} different examples. Each has Clara's last reply (1-3 sentences: a result, "
              f"or a question/offer like 'Want me to...?') and the user's next message.\nIn every example the user's message must be "
              f"'{label}': {FOLLOWUPS[label]}\nThis time the user's message {kind}.\nUser style: {style}. Task area: {topic}.\n"
              'Output ONLY a JSON array of objects like {"clara": "...", "user": "..."}.')
    m = re.search(r"\[.*\]", llm(prompt), re.S)
    try:
        return [(d["clara"].strip(), d["user"].strip()) for d in json.loads(m.group(0))
                if isinstance(d, dict) and isinstance(d.get("clara"), str) and isinstance(d.get("user"), str) and 0 < len(d["user"]) < 300]
    except Exception:
        return []


if __name__ == "__main__":
    random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    held_out = {json.loads(l)["text"].lower() for l in open("followup_eval.jsonl")}
    out, seen, kept = open(sys.argv[1], "a"), set(), 0
    for i in range(int(sys.argv[3]) if len(sys.argv) > 3 else 100):
        label = ["continue", "new"][i % 2]
        for last, text in ask(label, random.choice(STYLES), random.choice(TOPICS)):
            key = (last.lower(), text.lower())
            if key in seen or text.lower() in held_out:
                continue
            seen.add(key)
            out.write(json.dumps({"text": text, "last": last, "label": label, "question": "followup"}) + "\n"); out.flush(); kept += 1
        print(i, label, "kept", kept, flush=True)
