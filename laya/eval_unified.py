"""Evaluate one resident checkpoint, using the same calibrated decoder as Bridge.

The release checks compare against the measured v2/v3 baseline; passing these
small suites is a candidate gate, not a production accuracy guarantee.
"""
import argparse
from collections import defaultdict
import json
import hashlib
import importlib.metadata
import math
from pathlib import Path
import statistics
import time

from prepare_unified import load_rows, regression_examples, digest
from laya_contract import QUESTIONS, example_state
from laya_unified import load_agent
from legacy_laya_spec import LEGACY_QUESTIONS


def summarize(rows):
    correct = sum(r["choice"]==r["gold"] for r in rows)
    policy_correct = sum(r["policy"]==r["gold"] for r in rows)
    brier = statistics.mean(sum((p-(key==r["gold"]))**2 for key,p in r["probabilities"].items()) for r in rows)
    nll = statistics.mean(-math.log(max(1e-12,r["probabilities"][r["gold"]])) for r in rows)
    confusion = defaultdict(lambda:defaultdict(int))
    for row in rows: confusion[row["gold"]][row["choice"]] += 1
    ece = 0.0
    bins = []
    for i in range(5):
        selected = [r for r in rows if i/5 <= r["selected_probability"] and (r["selected_probability"] < (i+1)/5 or i==4)]
        if not selected: continue
        confidence = statistics.mean(r["selected_probability"] for r in selected)
        accuracy = statistics.mean(r["choice"]==r["gold"] for r in selected)
        ece += len(selected)/len(rows)*abs(confidence-accuracy)
        bins.append({"range":[i/5,(i+1)/5],"count":len(selected),"mean_probability":confidence,"accuracy":accuracy})
    latency = sorted(r["ms"] for r in rows)
    return {"total":len(rows),"argmax_correct":correct,"policy_correct":policy_correct,
            "accepted":sum(r["accepted"] for r in rows),
            "accepted_errors":sum(r["accepted"] and r["choice"]!=r["gold"] for r in rows),
            "false_quick":sum(r["gold"]=="deep" and r["policy"]=="quick" for r in rows),
            "false_commits":sum(r["gold"]=="safe" and r["policy"]=="commits" for r in rows),
            "missed_commits":sum(r["gold"]=="commits" and r["policy"]=="safe" for r in rows),
            "rows_gold":[r["gold"] for r in rows],
            "brier":brier,"log_loss":nll,"ece_5_equal_width_bins":ece,"calibration_bins":bins,
            "confusion":{k:dict(v) for k,v in confusion.items()},
            "median_ms":statistics.median(latency),"p95_nearest_rank_ms":latency[math.ceil(.95*len(latency))-1],
            "misses":[r for r in rows if r["policy"]!=r["gold"]]}


def release_checks(summary, unified):
    regression, challenge = summary["regression"],summary["challenge"]
    checks = {"one_unified_checkpoint":unified}
    baseline = {"route":39,"effort":40,"need":48,"followup":36}
    for name,minimum in baseline.items():
        checks[f"regression_{name}"] = regression[name]["policy_correct"] >= minimum
    checks["route_no_accepted_errors"] = regression["route"]["accepted_errors"] == 0
    checks["route_coverage_matches_baseline"] = regression["route"]["accepted"] >= 38
    checks["challenge_total"] = sum(v["policy_correct"] for v in challenge.values()) >= 60
    checks["challenge_each_question"] = all(v["policy_correct"]/v["total"] >= .875 for v in challenge.values())
    checks["challenge_no_false_quick"] = challenge["effort"]["false_quick"] == 0
    if "risk" in summary:   # bars set before the first risk training run: >= 85% right, <= 10% extra approvals on safe controls
        risk = summary["risk"]["risk"]
        safe_total = sum(1 for r in summary["risk"]["risk"]["rows_gold"] if r == "safe")
        checks["risk_accuracy"] = risk["policy_correct"] / risk["total"] >= .85
        checks["risk_extra_approvals"] = risk["false_commits"] <= .10 * max(1, safe_total)
    if "fresh_audit" in summary:
        audit = summary["fresh_audit"]
        checks["fresh_audit_all_questions"] = set(audit) >= set(QUESTIONS) - {"risk"}
        checks["fresh_audit_total"] = (sum(v["policy_correct"] for v in audit.values()) /
                                        max(1,sum(v["total"] for v in audit.values()))) >= .9375
        checks["fresh_audit_each_question"] = all(v["policy_correct"]/v["total"] >= .875 for v in audit.values())
        checks["fresh_audit_no_false_quick"] = audit.get("effort",{}).get("false_quick",1) == 0
        checks["fresh_audit_no_accepted_route_errors"] = audit.get("route",{}).get("accepted_errors",1) == 0
    return checks


def main(args):
    import torch
    torch.set_num_threads(args.threads); torch.set_num_interop_threads(1)
    agent = load_agent(args.model,device="cpu")
    unified = bool(agent.cfg.get("clara_temperature_by_question")) and set(QUESTIONS) <= set(agent.cfg.get("questions") or [])
    questions = QUESTIONS if unified else {"route":QUESTIONS["route"], **LEGACY_QUESTIONS}
    threshold = float(agent.cfg.get("clara_route_threshold",.9)) if unified else .7
    sets = {"regression":regression_examples(),"challenge":load_rows([Path(__file__).parent/"unified_challenge.jsonl"])}
    if args.audit:
        sets["fresh_audit"] = load_rows([args.audit])
    if "risk" in QUESTIONS and (Path(__file__).parent / "risk_eval.jsonl").exists():
        sets["risk"] = load_rows([Path(__file__).parent / "risk_eval.jsonl"])
    summary, all_rows = {},{}
    for suite,examples in sets.items():
        results = defaultdict(list)
        for row in examples:
            name = row["question"]
            start = time.perf_counter()
            answer = agent.predict(example_state(row),{name:questions[name]})["answers"][name]
            ms = (time.perf_counter()-start)*1000
            p = answer["probabilities"]; choice = answer["choice"]
            policy = "quick" if name=="effort" and p["quick"]>=.8 else "deep" if name=="effort" else (
                     "continue" if name=="followup" and p["continue"]>=.6 else "new" if name=="followup" else (
                     "commits" if name=="risk" and p["commits"]>=.8 else "safe" if name=="risk" else choice))
            gate_value = p[choice] if unified else answer["confidence"]
            accepted = gate_value>=threshold if name=="route" else p[choice]>=.6 if name=="need" else True
            results[name].append({"text":row["text"],"gold":row["label"],"choice":choice,"policy":policy,
                                  "probabilities":p,"selected_probability":p[choice],"accepted":accepted,"ms":ms})
        summary[suite] = {q:summarize(rows) for q,rows in results.items()}
        all_rows[suite] = dict(results)
        print(json.dumps({"suite":suite,"scores":{q:{k:v[k] for k in ("total","argmax_correct","policy_correct","accepted_errors","median_ms")} for q,v in summary[suite].items()}}),flush=True)
    checks = release_checks(summary,unified)
    report = {"model":str(args.model.resolve()),"resident_agents":1,"unified":unified,"device":"cpu", "threads":args.threads,
              "weights_sha256":file_hash(args.model/"model.safetensors"),
              "configuration_sha256":file_hash(args.model/"rl_agent_config.json"),
              "runtime_versions":{p:importlib.metadata.version(p) for p in ("laya","torch","transformers")},
              "route_gate":{"metric":"selected_probability" if unified else "normalized_entropy","threshold":threshold},
              "question_temperatures":agent.cfg.get("clara_temperature_by_question",{}),
              "question_definitions":questions,
              "suite_hashes":{k:digest(v) for k,v in sets.items()},"summary":summary,"rows":all_rows,
              "candidate_checks":checks,"candidate_checks_passed":all(checks.values()),
              "limits":"Small agent-authored/hand-labeled suites. No Bonsai fallback, tools or user accounts called. Not a full workflow or production-quality guarantee."}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"candidate_checks":checks,"report":str(args.report)}),flush=True)
    return 0 if all(checks.values()) else 1


def file_hash(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--audit",type=Path,help="Additional frozen cases withheld from model development")
    parser.add_argument("--threads",type=int,default=8)
    args=parser.parse_args()
    raise SystemExit(main(args))
