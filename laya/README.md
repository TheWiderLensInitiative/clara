# Training laya-for-clara

## Current model: laya-clara-unified (2026-10-04)

Clara serves **one `laya-clara-unified` checkpoint** for route, effort, need and
follow-up. It is installed locally on the project PC; Hugging Face still has the
previous model, so a fresh installation downloads that one until a separately
validated release is published. Results of the selected run:

- Established regressions: route **40/40**, effort **40/40**, need **50/50**,
  follow-up **36/36**; all 40 routes accepted correctly.
- Development challenge: **64/64**; 15/16 route decisions accepted, all correct.
- First evaluation of the frozen final audit: **64/64 top choices**, **63/64
  threshold decisions**. One specified calendar edit was conservatively sent to
  deep mode at P(quick)=0.7854, below the unchanged 0.8 threshold. There were no
  false-quick decisions or accepted wrong routes.
- A separate fresh check written afterwards (`unified_fresh_check.json`, 48 unseen
  messages, 12 per question; keep out of training,
  run through the Bridge's serving path) scored 48/48, with every route decided
  by Laya alone.
- **81** software tests, tiny training/resume/export/reload checks, installer
  recovery fixtures and isolated app-dispatch cases passed. Dispatch checks used
  the real checkpoint with temporary storage and stubbed external execution; they
  do not establish success on connected-account workflows.

The final continuation used 2,977 training examples, 602 development examples and
600 calibration examples, with balanced coverage of all four questions and a
training-only preservation penalty for route, effort and need. Epoch two was
selected by development log loss and calibrated in CPU serving precision.
These are small synthetic/assistant-reviewed suites, not a production accuracy
guarantee. The established suites informed development; only the separate final
audit was unused before this candidate's final evaluation. That audit is now
consumed: a future release needs another fresh audit for a new independent claim.
Personal conversations were not used for training. Each candidate's evaluation,
manifest and deployment records stay with the training run, outside the repository.

## One unified Clara model

The architecture is **one resident checkpoint for route, effort, need and follow-up**.
The v2/v3 results below are the historical baseline to match, not the architecture
required for the next model. The Bridge reuses its primary agent for all four
questions when that checkpoint declares all four capabilities.

The unified pipeline preserves the existing `train_router.py` work:

- `prepare_unified.py`: validate labels; deduplicate model inputs; group explicit
  contrast pairs and repeated inputs across question types; write fixed, hashed
  training/development/calibration splits. Explicitly exclude known test groups.
  Legacy examples lack semantic-family metadata, so near-duplicates still need review.
- `unified_contrasts.jsonl`: 224 agent-authored synthetic examples with pair IDs.
  They are not human-adjudicated examples or personal-chat data.
- `unified_boundaries.jsonl`: 192 additional synthetic examples, including short
  tasks requiring judgment, long single-action requests, contextual follow-ups,
  and reasoning over supplied information. Related pairs stay in one split.
- `need_label_review.json`: source-pinned review of all 36 legacy `need/other`
  examples: 10 explicit label corrections and 21 ambiguous examples excluded.
  This is an assistant review, not human adjudication; other categories still
  need a complete label audit. Raw training files remain unchanged.
- `label_review.json`: extends that review with four clear effort-label
  corrections: 14 corrections and 21
  exclusions in total, with the original source hash and a reason per decision.
- `label_review_v2.json`: earlier review, also checking short email/calendar
  examples that conflated provider reservations, personal calendar entries and
  unspecified communication channels. In total: 18 corrections and 42 exclusions.
- `label_review_v3.json`: additionally checks legacy quick and
  short effort examples. It records 22 corrections and 49 exclusions. This is
  still assistant adjudication, not a complete independent dataset review.
- `label_review_v4.json`: current review, excluding eight further malformed
  follow-up examples that contained generated `continue:` labels inside the
  message. Cumulative total: 22 label corrections and 57 exclusions.
- `unified_effort_boundaries.jsonl`: 64 regression-informed examples contrasting
  specified lookups/actions with inspection, selection and judgment. The older
  suites now serve as development regressions; they are not an independent
  estimate of the generalization gained from these examples.
- `unified_need_boundaries.jsonl`: 64 intent contrasts, especially making a
  provider reservation versus recording an already-confirmed event in a calendar.
  Reservation examples intentionally work without a browser keyword or site name.
- `unified_implicit_boundaries.jsonl`: 240 paired examples for judgment implied
  by the goal or object, direct resource-usage lookups, posting existing media
  versus creating it, local file retrieval versus personal memory, travel
  planning versus reservations, and reactions versus task refinements. These
  are regression-informed development data, not fresh evaluation examples.
- `unified_continuation_pairs.jsonl`: 128 further paired examples for selecting
  important records versus copying named folders, and questions about previous
  options when the assistant did not end with an offer or question.
- `unified_interruptions.jsonl`: 64 pairs contrasting short pauses/rejections
  with complete new requests that happen to begin with words such as "wait".
- `unified_challenge.jsonl`: 64 separate challenge cases. Keep these out of training.
- `unified_final_audit.jsonl`: 64 additional cases frozen after diagnosing the
  initial candidates, before curated training. Run this once a candidate passes
  the existing suites; do not use its failures to tune that same release.
- `train_unified.py`: start from an original base checkpoint, balance task sampling
  while visiting every source example each epoch, then add weighted examples to
  equalize task counts. The earlier replacement-only sampler could miss examples.
  Select the epoch on development results and fit one temperature per question on
  untouched calibration examples using CPU FP32 serving precision. The initial
  CE/RLCD comparison uses the same original data split and three-epoch budget.
  With `--average-checkpoints`, also compare averages of training snapshots on
  development data. Export one selected weight file; no inference ensemble is used.
  `--resume-candidate` permits continued training of a recorded unified candidate
  only after checking its weights, input definitions, original split files, and
  all recorded ancestor training states against the new holdouts. Unknown legacy
  checkpoints remain disallowed. The parent is also a development-selection
  candidate, so continued training need not replace a better parent checkpoint.
  `--selection-metric log_loss` selects by probability quality directly; the
  default `accuracy` retains the original selection rule.
  Optional `--distill-weight 4` caches the verified parent's predictions on
  training examples for `--distill-questions route effort need`. A KL penalty
  preserves those behaviors while teaching follow-ups. Its source checkpoint,
  target hash, task names, weight and temperature are recorded. The parent is
  used only to prepare training targets; serving still loads one model.
- `eval_unified.py`: load exactly one agent through the Bridge decoder; evaluate
  all 166 existing plus 64 new cases, thresholds, fallback coverage, calibration
  and CPU latency. It does not call Bonsai, tools or connected accounts.
- `reselect_unified.py`: optional export of saved training snapshots using minimum
  mean per-question development log loss. It records the alternative selection
  rule and recalibrates the selected weights. This uses development results only;
  the release and fresh-audit gates still apply without changes.
- `test_unified.py`: offline tests for grouping, manifests, calibration and
  single-load serving behavior.

The four `clara_temperature_by_question` scalars calibrate one shared model.
The optional preservation penalty adapts teacher-distribution matching from
[knowledge distillation](https://arxiv.org/abs/1503.02531) and the motivation of
[Learning without Forgetting](https://arxiv.org/abs/1606.09282). Clara also replays
its existing training examples; this is an application-specific variation, not
a reproduction of either paper or a guarantee against regressions.
Question descriptions are compact enough to survive Laya's option-token limits.
The previous need descriptions were cut to 21 tokens per option, hiding several
category distinctions. The current effort and follow-up descriptions also fit
fully within the upstream 48-token per-option limit.
The Bridge validates question definitions and answer order against their saved
hashes, and applies the temperatures without mutating shared state. Answer order
can change predictions even when the labels and descriptions are unchanged.
Unified routing uses selected-answer probability with a
candidate default threshold of 0.9; legacy checkpoints retain the entropy gate.
`CLARA_ROUTER_THRESHOLD` overrides the default, so evaluate any override explicitly.
CPU serving uses four intra-op threads, matching the evaluator; set
`CLARA_LAYA_THREADS` to benchmark a different thread budget on another machine.

Confident need predictions now accompany the Hermes handoff as category-specific
tool guidance, including non-browser tasks. Low-confidence or unknown categories
retain the general-agent path. These hints do not grant access, change spending
limits, bypass approval, or force the agent to follow an incorrect classification.
Existing connector availability instructions and browser fast-lane behavior remain
in effect. Isolated Bridge tests verify dispatch and the actual Hermes payload.

Run from the repository root, choosing fresh output directories:

```bash
python laya/prepare_unified.py \
  --input laya/train_v3.jsonl --input laya/unified_contrasts.jsonl \
  --input laya/unified_boundaries.jsonl --input laya/unified_effort_boundaries.jsonl \
  --input laya/unified_need_boundaries.jsonl --input laya/unified_implicit_boundaries.jsonl \
  --input laya/unified_continuation_pairs.jsonl \
  --input laya/unified_interruptions.jsonl --review laya/label_review_v4.json \
  --held-out laya/unified_challenge.jsonl --held-out laya/unified_final_audit.jsonl \
  --exclude-held-out \
  --output /path/to/run/splits

python laya/train_unified.py --base /path/to/original-laya-snapshot \
  --splits /path/to/run/splits --output /path/to/run/candidate-ce --preflight

# CUDA training environment and at least 9 GiB free VRAM. This does not stop services.
python laya/train_unified.py --base /path/to/original-laya-snapshot \
  --splits /path/to/run/splits --output /path/to/run/candidate-ce --loss ce \
  --epochs 4 --average-checkpoints

# Optional continuation of a recorded candidate with expanded, still-disjoint data.
python laya/train_unified.py --base /path/to/prior/candidate --resume-candidate \
  --splits /path/to/new-run/splits --output /path/to/new-run/candidate-refined \
  --epochs 2 --average-checkpoints --selection-metric log_loss \
  --encoder-lr 4e-6 --head-lr 1.5e-5

# Evaluate in the pinned CPU Bridge environment used for serving.
python laya/eval_unified.py --model /path/to/run/candidate-ce \
  --report /path/to/run/candidate-ce-evaluation.json

# Optional probability-focused selection from a completed run with saved epochs.
python laya/reselect_unified.py --source /path/to/run/candidate-refined \
  --output /path/to/run/candidate-probability

# Final audit after the development/regression gates pass.
python laya/eval_unified.py --model /path/to/run/candidate-ce \
  --audit laya/unified_final_audit.jsonl --report /path/to/run/final-evaluation.json

PYTHONPATH=laya:bridge python -m unittest test_unified -v
```

Keep CUDA training dependencies separate from the CPU Bridge environment. Use
Laya, Transformers, NumPy, Hugging Face Hub and Safetensors versions matching
`bridge/requirements.txt`, and CUDA PyTorch compatible with the host driver.
Each candidate records the actual versions, base/data hashes, seed, arguments,
selected epoch and temperatures in `clara_training_manifest.json`.
Training source snapshots are archived with the candidate. Optional epoch files
are stored in a separate sibling directory; only the selected checkpoint is served.

The evaluator exits nonzero unless the candidate matches the recorded baseline
on all four original suites, retains routing coverage without accepted route
mistakes, and meets the challenge checks. These small suites are a first gate,
not proof of production accuracy. Also run Bridge regressions and representative
end-to-end workflows. After validation, point `CLARA_ROUTER_MODEL` to the unified
candidate: no secondary model is loaded. Training/evaluation never install,
upload, replace or delete production checkpoints, and never stop services.

## Historical training path

The router that answers Clara's front-door questions: **route** (`chat` / `task` / `schedule`), **effort**
(`quick` / `deep`), **need** (what kind of help a task needs: `browser`, `search`, `email_calendar`, `apps`, `computer`,
`create`, `memory`, `other`; asked after task routing) and **followup** (`continue` / `new`: does a message continue
Clara's last task? It also sees her last reply). The trained model is on Hugging Face as `TheWiderLensInitiative/laya-for-clara`; `install.sh`
downloads it. You only need this folder to improve it.

| File | What it is |
|---|---|
| `router_spec.py`, `effort_spec.py`, `need_spec.py`, `followup_spec.py` | The questions, exactly as used at runtime (training and runtime must match; the Bridge keeps identical copies) |
| `train.jsonl`, `hard.jsonl` | Route examples (synthetic, from `gen_data.py`, plus hand-written hard cases) |
| `train_v2.jsonl` | The combined training file: route + effort examples, each tagged with its `question` |
| `effort_eval.jsonl`, `need_eval.jsonl`, `followup_eval.jsonl`, `eval_set.py` | Held-out, hand-labeled test sets |
| `gen_data.py`, `gen_effort.py`, `gen_need.py`, `gen_followup.py` | Generate more examples with your local Bonsai (thinking off) |
| `eval_all.py` | Score a checkpoint on all four questions |
| `train_router.py` | Fine-tune (Laya's recipe), then calibrate temperatures |
| `eval_router.py`, `zero_shot.py` | Evaluate a checkpoint |

## Retrain

Needs a CUDA PyTorch (not the CPU one the Bridge uses) and ~8 GB of GPU memory, so stop the model first:

```bash
clara stop
python train_router.py train_v2.jsonl out/laya-for-clara     # ~4 minutes on an RTX 3060
python eval_router.py out/laya-for-clara
clara start
```

Then point the Bridge at it with `CLARA_ROUTER_MODEL=/path/to/out/laya-for-clara`.

## v3: need + followup (2026-10-02)

`train_v3.jsonl` = `train_v2.jsonl` + `need_train.jsonl` (892, from `gen_need.py`, filtered) + `followup_train.jsonl`
(699, from `gen_followup.py`, filtered). Trained in 8 minutes; `eval_all.py` on the held-out sets:

| question | v2 | v3 |
|---|---|---|
| route | 39/40 | 40/40 |
| effort (Bridge rule, P(quick) ≥ 0.8) | 40/40 | 38/40 |
| need | 35/50 (never trained) | 48/50 |
| followup | 25/36 (never trained) | 36/36 |

The old v3 route probabilities clustered around 0.79–0.83. The cause was a bug in
`train_router.py`: a comment swallowed `cfg.pop("temperature_by_options")`, so the base
model's per-option-count temperatures (≈1.9 for two options, ≈1.8 for three) overrode
the fitted one. Removing them restored ≈0.95 probabilities, and the line is fixed. Even
then, effort had genuine decision errors that temperature scaling alone could not fix. This led to an earlier
v2-plus-v3 proposal. That proposal is superseded by the unified pipeline above.
The secondary-model loader has been removed. A primary checkpoint declaring all
four questions reuses the same agent object. An older primary checkpoint uses
the app's existing fallback rules for missing capabilities, never another Laya.
`bridge/legacy_laya_spec.py` preserves the original input definitions for legacy
weights; the compact unified questions apply only to unified checkpoints.
