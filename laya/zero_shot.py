import time, collections
from laya import LayaRouter
from eval_set import EVAL
CRITERIA = {
    "chat": "Casual conversation, feelings, jokes, advice, explanations, writing help, or questions answerable from general knowledge. No tools, files, internet, or live data needed.",
    "task": "Do something now using the computer, files, apps, the web browser, web search, live or current information, email, shopping, or booking.",
    "schedule": "Create, change, cancel, or list a reminder, alarm, or recurring or future scheduled job.",
}
t0 = time.time(); r = LayaRouter(criteria=CRITERIA, instructions="Which route should handle this message to a personal assistant?"); print(f"load {time.time()-t0:.1f}s")
ok = 0; conf = collections.defaultdict(list); lat = []
for text, gold in EVAL:
    t = time.time(); d = r.invoke(text) if hasattr(r, "invoke") else r(text); lat.append((time.time()-t)*1000)
    route = getattr(d, "route", d if isinstance(d, str) else getattr(d, "choice", str(d)))
    c = getattr(d, "confidence", None); hit = route == gold; ok += hit; conf[hit].append(c or 0)
    if not hit: print(f"  MISS {gold:>8} -> {route:<8} conf={c}  {text}")
print(f"accuracy {ok}/{len(EVAL)} = {ok/len(EVAL):.0%}   median latency {sorted(lat)[len(lat)//2]:.0f} ms (CPU)")
print("mean conf right %.2f wrong %.2f" % (sum(conf[True])/max(1,len(conf[True])), sum(conf[False])/max(1,len(conf[False]))))
