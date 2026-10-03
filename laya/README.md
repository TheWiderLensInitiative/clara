# Training laya-for-clara

The router that answers Clara's front-door questions: **route** (`chat` / `task` / `schedule`), **effort**
(`quick` / `deep`), **need** (what kind of help a task needs: `browser`, `search`, `email_calendar`, `apps`, `computer`,
`create`, `memory`, `other`; asked in the same call as route) and **followup** (`continue` / `new`: does a message continue
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

v3 picks the right answer but its probabilities are squeezed: every route answer sits at 0.79-0.83 and quick/deep
overlap, so it can't say "unsure". Tripling the effort examples didn't fix it (and made need/followup worse), so the
likely cause is the single calibration temperature shared by all choice questions. **The Bridge therefore runs both:**
v2 (`laya-for-clara`) for route + effort, and v3 (`laya-for-clara-v3`, `CLARA_NEED_MODEL`) for need (tasks only, +0.4 s)
and followup. Without a v3 folder the Bridge falls back to its keyword rules. Install a v3 build by copying the
training output to `$CLARA_DATA_DIR/laya-for-clara-v3`; `train_router.py` writes `"questions"` into its config and the
Bridge only uses need/followup from a model that lists them. Next try: per-question temperatures.
