"""Generate diverse labeled router examples with local Bonsai (no thinking)."""
import json, random, urllib.request, re, sys
URL = "http://127.0.0.1:8080/v1/chat/completions"
DEF = {
 "chat": "casual talk, greetings, thanks, feelings, jokes, opinions, advice, explanations, math, definitions, writing/brainstorming help — anything answerable from general knowledge with NO tools, files, internet, live data, or actions",
 "task": "do something NOW that needs the computer, files, apps, terminal, browser, web search, live/current info (weather, news, prices, scores), email/messages, shopping, booking, or installing/running software",
 "schedule": "create, change, cancel, or list reminders, alarms, timers, or recurring/future scheduled jobs (including 'every day check X and tell me')",
}
STYLES = ["short lowercase text message with typos", "polite full sentence", "casual slang", "very terse (2-4 words)",
          "long rambling message with context", "voice-dictated style with no punctuation", "question form", "command form"]
TOPICS = ["money", "health and fitness", "food and cooking", "travel", "family", "work", "school", "cars", "gaming", "music",
          "tech and PCs", "home and chores", "shopping", "pets", "relationships", "news and sports", "coding", "entertainment"]
def ask(label, style, topic, n=10):
    prompt = (f"Write {n} different messages a user might send to their personal AI assistant.\n"
              f"Every message must belong to category '{label}': {DEF[label]}.\nStyle: {style}. Topic area: {topic}.\n"
              "Make them realistic and varied. Output ONLY a JSON array of strings.")
    body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": 1500, "temperature": 1.0,
            "chat_template_kwargs": {"enable_thinking": False}}
    r = json.load(urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=300))
    txt = r["choices"][0]["message"]["content"]
    m = re.search(r"\[.*\]", txt, re.S)
    try: return [s.strip() for s in json.loads(m.group(0)) if isinstance(s, str) and 1 < len(s) < 300]
    except Exception: return []
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
out = open(sys.argv[1], "a")
for i in range(int(sys.argv[3]) if len(sys.argv) > 3 else 36):
    label = ["chat", "task", "schedule"][i % 3]
    items = []
    for _ in range(3):
        items = ask(label, random.choice(STYLES), random.choice(TOPICS))
        if items: break
    for s in items:
        out.write(json.dumps({"text": s, "label": label}) + "\n"); out.flush()
    print(i, label, flush=True)
