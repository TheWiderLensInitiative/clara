"""Generate quick/deep task examples with local Bonsai (no thinking), then keep only ones a second, thinking pass agrees with."""
import json, random, urllib.request, re, sys
sys.path.insert(0, "."); from effort_spec import EFFORTS
URL = "http://127.0.0.1:8080/v1/chat/completions"
STYLES = ["short lowercase text message with typos", "polite full sentence", "casual slang", "very terse (2-5 words)",
          "long rambling message with context", "voice-dictated style with no punctuation", "question form", "command form"]
TOPICS = ["email and inbox", "calendar and meetings", "smart home lights and thermostat", "music and spotify", "the user's PC and files",
          "shopping and prices", "travel", "money and bills", "work documents", "school", "cars", "gaming", "news and sports",
          "cooking and groceries", "health and fitness", "coding and github", "social media and videos", "notes and to-do lists",
          "messaging friends on telegram, slack or discord", "weather and local places"]
def llm(prompt, think=False, max_tokens=1500, temp=1.0):
    body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": temp, "id_slot": 1,
            "chat_template_kwargs": {"enable_thinking": think}}
    r = json.load(urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=600))
    return r["choices"][0]["message"]["content"]
def ask(label, style, topic, n=10):
    other = "deep" if label == "quick" else "quick"
    prompt = (f"Write {n} different requests a user might send to their personal AI assistant, which can use their computer, "
              f"email, calendar, browser, apps and smart home.\nEvery request must be '{label}': {EFFORTS[label]}\n"
              f"None may be '{other}': {EFFORTS[other]}\nStyle: {style}. Topic area: {topic}.\n"
              "Make them realistic and varied. Output ONLY a JSON array of strings.")
    m = re.search(r"\[.*\]", llm(prompt), re.S)
    try: return [s.strip() for s in json.loads(m.group(0)) if isinstance(s, str) and 3 < len(s) < 300]
    except Exception: return []
def check(text):
    prompt = (f"A personal AI assistant got this request: {text!r}\nIs it 'quick' ({EFFORTS['quick']}) or 'deep' ({EFFORTS['deep']})? "
              "Answer with one word: quick or deep.")
    w = llm(prompt, think=False, max_tokens=5, temp=0).strip().lower().strip(".")
    return w if w in EFFORTS else None
if __name__ == "__main__":
    random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    out = open(sys.argv[1], "a"); kept = dropped = 0
    for i in range(int(sys.argv[3]) if len(sys.argv) > 3 else 60):
        label = ["quick", "deep"][i % 2]
        items = ask(label, random.choice(STYLES), random.choice(TOPICS), n=14)
        for s in items:
            if True:   # the no-thinking checker shares the quick-bias we're training away, so labels come from the generator
                out.write(json.dumps({"text": s, "label": label}) + "\n"); out.flush(); kept += 1
            else:
                dropped += 1
        print(i, label, "kept", kept, "dropped", dropped, flush=True)
