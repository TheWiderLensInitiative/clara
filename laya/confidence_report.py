"""How sure a checkpoint is, per question: the probability of its chosen answer, split by right/wrong.
usage: confidence_report.py <model_dir> [<model_dir> ...]"""
import json, statistics, sys, laya
from router_spec import QUESTION, state
from effort_spec import EFFORT_Q
from need_spec import NEED_Q
from followup_spec import FOLLOWUP_Q, followup_state
from eval_set import EVAL
load = lambda f: [json.loads(l) for l in open(f)]
SETS = {"route": (QUESTION, [(state(t), g) for t, g in EVAL]),
        "effort": (EFFORT_Q, [(state(e["text"]), e["label"]) for e in load("effort_eval.jsonl")]),
        "need": (NEED_Q, [(state(e["text"]), e["label"]) for e in load("need_eval.jsonl")]),
        "followup": (FOLLOWUP_Q, [(followup_state(e["text"], e["last"]), e["label"]) for e in load("followup_eval.jsonl")])}
for path in sys.argv[1:]:
    agent = laya.Agent(path, device="cpu"); print("==", path.rstrip("/").split("/")[-1])
    for name, (q, rows) in SETS.items():
        right, wrong = [], []
        for st, gold in rows:
            a = agent.predict(st, {name: q})["answers"][name]
            (right if a["choice"] == gold else wrong).append(float(a["probabilities"][a["choice"]]))
        print(f"  {name:<9} right {len(right):>2}: P median {statistics.median(right):.2f} min {min(right):.2f} | "
              f"wrong {len(wrong)}: {', '.join(f'{p:.2f}' for p in wrong) or '-'}")
