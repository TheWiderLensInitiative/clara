"""Validate, deduplicate and group Clara examples before making fixed splits.

Existing data has no semantic-family provenance: exact state identities are
grouped automatically; new data should also supply scenario_id/pair_id/group_id.
No model-generated labels or user conversations are collected by this script.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
from laya_contract import QUESTIONS, example_state, schema_hash


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def norm(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def state_key(row):
    st = example_state(row)
    return digest({k: norm(v) for k, v in st.items()})


def load_rows(paths):
    rows = []
    for path in paths:
        for number, line in enumerate(Path(path).read_text().splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            name = row.setdefault("question", "route")
            if name not in QUESTIONS or row.get("label") not in QUESTIONS[name]["criteria"]:
                raise ValueError(f"{path}:{number}: unknown question or label")
            if not isinstance(row.get("text"), str) or not row["text"].strip():
                raise ValueError(f"{path}:{number}: missing text")
            if name == "followup" and (not isinstance(row.get("last"), str) or not row["last"].strip()):
                raise ValueError(f"{path}:{number}: follow-up needs assistant context")
            for field in ("group_id", "pair_id", "scenario_id", "conversation_id"):
                if field in row and (not isinstance(row[field], str) or not row[field]):
                    raise ValueError(f"{path}:{number}: invalid {field}")
            row["source_file"] = Path(path).name
            rows.append(row)
    return rows


def split_rows(rows, seed=20261003):
    parents = {}
    def find(x):
        parents.setdefault(x, x)
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parents[max(a,b)] = min(a,b)
    unique = {}
    for row in rows:
        sk = state_key(row)
        for field in ("group_id", "pair_id", "scenario_id", "conversation_id"):
            if row.get(field):
                union(sk, f"{field}:{row[field]}")
        find(sk)
        key = (row["question"], sk)
        if key in unique and unique[key]["label"] != row["label"]:
            raise ValueError(f"Conflicting labels for {row['question']}: {row['text']!r}")
        unique.setdefault(key, dict(row))
    splits = {"train": [], "dev": [], "calibration": []}
    for (_, sk), row in sorted(unique.items()):
        group = find(sk)
        value = int(digest([seed, group])[:16], 16) / 2**64
        split = "train" if value < .70 else "dev" if value < .85 else "calibration"
        row["split_group"] = digest(group)
        splits[split].append(row)
    return splits


def assert_disjoint(splits):
    seen_groups, seen_states = {}, {}
    for name, rows in splits.items():
        for row in rows:
            for key, seen in ((row["split_group"], seen_groups), (state_key(row), seen_states)):
                if key in seen and seen[key] != name:
                    raise ValueError(f"Data leakage between {seen[key]} and {name}")
                seen[key] = name


def apply_review(rows, review, paths):
    """Apply explicit, source-pinned label reviews without editing raw examples."""
    notes = json.loads(Path(review).read_text())
    sources = {Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    for name, expected in notes["source_sha256"].items():
        if sources.get(name) != expected:
            raise ValueError(f"Reviewed source changed or is missing: {name}")
    decisions = {}
    for item in notes["decisions"]:
        key = (item["question"],state_key(item))
        if key in decisions or not item.get("reason") or item["action"] not in ("drop","relabel"):
            raise ValueError("Invalid or repeated review decision")
        if item["action"] == "relabel" and item.get("label") not in QUESTIONS[item["question"]]["criteria"]:
            raise ValueError("Review uses an unknown replacement label")
        decisions[key] = item
    output, matched, changes = [], set(), Counter()
    for row in rows:
        key = (row["question"],state_key(row))
        item = decisions.get(key)
        if item is None:
            output.append(row)
            continue
        if row["label"] != item["old_label"]:
            raise ValueError("Reviewed label changed; review it again")
        matched.add(key); changes[item["action"]] += 1
        if item["action"] == "relabel":
            output.append({**row,"label":item["label"],"label_review":Path(review).name})
    if matched != set(decisions):
        raise ValueError("Review contains an example missing from the inputs")
    return output, dict(changes)


def prepare(paths, output, seed=20261003, excluded=(), exclude_held_out=False, review=None):
    rows = load_rows(paths)
    review_changes = {}
    if review is not None:
        rows, review_changes = apply_review(rows, review, paths)
    splits = split_rows(rows, seed)
    assert_disjoint(splits)
    # Reject test contamination rather than silently moving or discarding it.
    held_out = {state_key(row) for row in excluded}
    overlap = [r for group in splits.values() for r in group if state_key(r) in held_out]
    excluded_groups = {r["split_group"] for r in overlap}
    removed = [r for group in splits.values() for r in group if r["split_group"] in excluded_groups]
    if overlap and not exclude_held_out:
        raise ValueError(f"Training source contains {len(overlap)} held-out inputs")
    if exclude_held_out:
        splits = {name:[r for r in group if r["split_group"] not in excluded_groups] for name,group in splits.items()}
    expected = {f"{q}/{r['label']}" for r in rows for q in [r["question"]]}
    counts = {name: dict(sorted(Counter(f"{r['question']}/{r['label']}" for r in group).items())) for name, group in splits.items()}
    for name in splits:
        missing = expected - set(counts[name])
        if missing:
            raise ValueError(f"{name} lacks classes {sorted(missing)}; collect more grouped examples")
    output = Path(output)
    if output.exists():
        raise ValueError(f"Refusing to overwrite split directory: {output}")
    output.mkdir(parents=True)
    files = {}
    for name, group in splits.items():
        content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in group)
        (output / f"{name}.jsonl").write_text(content)
        files[name] = hashlib.sha256(content.encode()).hexdigest()
    manifest = {"format":1,"seed":seed,"source_rows":len(rows),"unique_rows":sum(map(len,splits.values())),
                "review_sha256":hashlib.sha256(Path(review).read_bytes()).hexdigest() if review else None,
                "review_changes":review_changes,
                "held_out_groups_removed":len(excluded_groups),"held_out_rows_removed":len(removed),
                "held_out_state_hashes":sorted(held_out),
                "split_rows":{k:len(v) for k,v in splits.items()},"class_counts":counts,"split_sha256":files,
                "input_sha256":{str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},
                "question_hashes":{q:schema_hash(q) for q in QUESTIONS},
                "grouping":"Exact normalized model state plus declared group/pair/scenario/conversation IDs. Legacy semantic families are unknown."}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def regression_examples():
    from eval_set import EVAL
    result = [{"question":"route","text":text,"label":label} for text,label in EVAL]
    for q in ("effort","need","followup"):
        for line in (Path(__file__).parent / f"{q}_eval.jsonl").read_text().splitlines():
            row = json.loads(line); row["question"] = q; result.append(row)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--held-out", type=Path, action="append", default=[])
    parser.add_argument("--exclude-held-out", action="store_true", help="Explicitly remove entire groups that overlap held-out inputs")
    parser.add_argument("--review", type=Path, help="Explicit source-pinned label corrections and ambiguous-example exclusions")
    args = parser.parse_args()
    report = prepare(args.input, args.output, args.seed, regression_examples() + load_rows(args.held_out), args.exclude_held_out, args.review)
    print(json.dumps({k:v for k,v in report.items() if k != "held_out_state_hashes"}, indent=2))
