# Training laya-for-clara

The router that answers two questions for every message: **route** (`chat` / `task` / `schedule`) and **effort**
(`quick` / `deep`). The trained model is on Hugging Face as `TheWiderLensInitiative/laya-for-clara`; `install.sh`
downloads it. You only need this folder to improve it.

| File | What it is |
|---|---|
| `router_spec.py`, `effort_spec.py` | The two questions, exactly as used at runtime (training and runtime must match) |
| `train.jsonl`, `hard.jsonl` | Route examples (synthetic, from `gen_data.py`, plus hand-written hard cases) |
| `train_v2.jsonl` | The combined training file: route + effort examples, each tagged with its `question` |
| `effort_eval.jsonl`, `eval_set.py` | Held-out, hand-labeled test sets |
| `gen_data.py`, `gen_effort.py` | Generate more examples with your local Bonsai (thinking off) |
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
