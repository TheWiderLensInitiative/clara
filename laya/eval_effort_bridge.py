"""Effort as the Bridge decides it: quick only if P(quick) >= CLARA_QUICK_MIN_CONF (0.8). usage: eval_effort_bridge.py <model_dir>"""
import json, sys, laya
from router_spec import state
from effort_spec import EFFORT_Q
agent = laya.Agent(sys.argv[1], device="cpu")
ok = 0
rows = [json.loads(l) for l in open("effort_eval.jsonl")]
for e in rows:
    p = float(agent.predict(state(e["text"]), {"effort": EFFORT_Q})["answers"]["effort"]["probabilities"]["quick"])
    pick = "quick" if p >= 0.8 else "deep"; ok += pick == e["label"]
    if pick != e["label"] or 0.5 < p < 0.8:
        print(f"  {'MISS' if pick != e['label'] else 'ok  '} P(quick)={p:.2f} gold={e['label']:<5} -> {pick:<5} {e['text'][:70]}")
print(f"bridge rule: {ok}/{len(rows)}")
