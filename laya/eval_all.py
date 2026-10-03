"""Evaluate a Laya checkpoint on all four of Clara's questions (held-out, hand-labeled sets).
usage: eval_all.py <model_dir|base> [device]"""
import json, sys, time, laya
from router_spec import QUESTION, state
from effort_spec import EFFORT_Q
from need_spec import NEED_Q
from followup_spec import FOLLOWUP_Q, followup_state
from eval_set import EVAL

path = sys.argv[1]; dev = sys.argv[2] if len(sys.argv) > 2 else "cpu"
agent = laya.Agent("convaiinnovations/laya" if path == "base" else path, device=dev)
load = lambda f: [json.loads(l) for l in open(f)]
sets = {
    "route": [(state(t), g) for t, g in EVAL],
    "effort": [(state(e["text"]), e["label"]) for e in load("effort_eval.jsonl")],
    "need": [(state(e["text"]), e["label"]) for e in load("need_eval.jsonl")],
    "followup": [(followup_state(e["text"], e["last"]), e["label"]) for e in load("followup_eval.jsonl")],
}
questions = {"route": QUESTION, "effort": EFFORT_Q, "need": NEED_Q, "followup": FOLLOWUP_Q}
summary = {}
for name, rows in sets.items():
    ok, misses, lat = 0, [], []
    for st, gold in rows:
        t = time.perf_counter(); a = agent.predict(st, {name: questions[name]})["answers"][name]; lat.append((time.perf_counter() - t) * 1000)
        ok += a["choice"] == gold
        if a["choice"] != gold:
            misses.append(f"    MISS {gold:>14} -> {a['choice']:<14} {st['message'][:70]}")
    summary[name] = f"{ok}/{len(rows)} = {ok/len(rows):.0%}"
    print(f"{name}: {summary[name]}  median {sorted(lat)[len(lat)//2]:.0f} ms"); print("\n".join(misses[:12]))
# the Bridge asks route + need together: one call
t = time.perf_counter()
for st, _ in sets["need"][:20]:
    agent.predict(st, {"route": QUESTION, "need": NEED_Q})
print(f"route+need in one call: {(time.perf_counter() - t) * 1000 / 20:.0f} ms each")
print("SUMMARY", json.dumps(summary))
