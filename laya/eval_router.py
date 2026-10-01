"""Evaluate a Laya checkpoint on the hand-labeled test set. usage: eval_router.py <model_dir|base> [device]"""
import sys, time, laya
from router_spec import QUESTION, state
from eval_set import EVAL
path = sys.argv[1]; dev = sys.argv[2] if len(sys.argv) > 2 else "cpu"
agent = laya.Agent("convaiinnovations/laya" if path == "base" else path, device=dev)
ok, lat, rows = 0, [], []
for text, gold in EVAL:
    t = time.perf_counter(); a = agent.predict(state(text), {"route": QUESTION})["answers"]["route"]; lat.append((time.perf_counter() - t) * 1000)
    pred, conf = a["choice"], a.get("confidence", 0.0); ok += pred == gold; rows.append((pred == gold, conf, gold, pred, text))
for hit, conf, gold, pred, text in sorted(rows, key=lambda r: r[1]):
    if not hit or conf < 0.5: print(f"  {'ok  ' if hit else 'MISS'} conf={conf:.2f} {gold:>8} -> {pred:<8} {text}")
print(f"accuracy {ok}/{len(EVAL)} = {ok/len(EVAL):.0%}  median {sorted(lat)[len(lat)//2]:.0f} ms on {dev}")
for th in (0.3, 0.5, 0.7):
    kept = [r for r in rows if r[1] >= th]
    print(f"  conf>={th}: keeps {len(kept)}/{len(rows)}, accuracy among kept {sum(r[0] for r in kept)/max(1,len(kept)):.0%}")
