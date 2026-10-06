"""Single-GPU fine-tune of Laya for Clara's router (adapted from Laya's 2xT4 RLCD notebook).
usage: train_router.py train.jsonl out_dir"""
import os, sys, json, random, time
import torch
from huggingface_hub import snapshot_download
from safetensors.torch import load_file, save_file
from transformers import AutoTokenizer
from laya.agent import _fix_tokenizer_config
from laya.common import build_model, build_sequence, render_options, proper_reward, QTYPES
from router_spec import QUESTION, state
from effort_spec import EFFORT_Q
from need_spec import NEED_Q
from followup_spec import FOLLOWUP_Q, followup_state

EPOCHS, MICRO_BATCH, GRAD_ACCUM, GROUP_SIZE = 3, 8, 4, 4
LR_ENCODER, LR_HEAD, SIGMA_START, SIGMA_END, SMOOTH = 2.5e-5, 1.0e-4, 0.4, 0.1, 0.05

def collate(items, pad_id):
    n, L = len(items), max(len(it["ids"]) for it in items); kmax = max(len(it["markers"]) for it in items)
    ids = torch.full((n, L), pad_id, dtype=torch.long); att = torch.zeros((n, L), dtype=torch.long)
    mpos = torch.zeros((n, kmax), dtype=torch.long); mmask = torch.zeros((n, kmax), dtype=torch.bool); tgt = torch.zeros((n, kmax))
    for i, it in enumerate(items):
        ids[i, :len(it["ids"])] = torch.tensor(it["ids"]); att[i, :len(it["ids"])] = 1; k = len(it["markers"])
        mpos[i, :k] = torch.tensor(it["markers"]); mmask[i, :k] = True; tgt[i, :k] = torch.tensor(it["target"])
    return ids, att, mpos, mmask, tgt, torch.tensor([it["qtype"] for it in items])

def fit_temp(sel):
    kmax = max(len(z) for z, _ in sel); Z = torch.full((len(sel), kmax), -1e4); T = torch.zeros((len(sel), kmax))
    for i, (z, t) in enumerate(sel): Z[i, :len(z)] = torch.tensor(z); T[i, :len(t)] = torch.tensor(t)
    lt = torch.zeros(1, requires_grad=True); opt = torch.optim.LBFGS([lt], lr=0.1, max_iter=100)
    def closure():
        opt.zero_grad(); loss = -(T * torch.log_softmax(Z / lt.exp(), -1)).sum(-1).mean(); loss.backward(); return loss
    opt.step(closure); return float(torch.clamp(lt.exp(), 0.1, 10.0))

def main(train_path, out_dir):
    model_dir = snapshot_download("convaiinnovations/laya"); _fix_tokenizer_config(model_dir)
    tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, "tokenizer"))
    cfg = json.load(open(os.path.join(model_dir, "rl_agent_config.json")))
    # four questions share the model: route (chat/task/schedule), effort (quick/deep), need (what kind of help) and
    # followup (continue/new, which also sees Clara's last reply); each line says which (default route)
    specs = {"route": QUESTION, "effort": EFFORT_Q, "need": NEED_Q, "followup": FOLLOWUP_Q}
    items = []
    for line in open(train_path):
        ex = json.loads(line); spec = specs[ex.get("question", "route")]
        keys = list(spec["criteria"]); q = {"t": "choice", "ins": spec["instructions"], "crit": spec["criteria"]}
        tgt = [SMOOTH / (len(keys) - 1)] * len(keys); tgt[keys.index(ex["label"])] = 1 - SMOOTH
        st = followup_state(ex["text"], ex.get("last")) if ex.get("question") == "followup" else state(ex["text"])
        seq, markers = build_sequence(tok, st, q, cfg["max_len"], cfg["head_max_len"])
        if len(markers) == len(render_options(q)): items.append({"ids": seq, "markers": markers, "qtype": QTYPES["choice"], "target": tgt})
    random.Random(20260922).shuffle(items); n_cal = max(30, len(items) // 10)
    calib, train = items[:n_cal], items[n_cal:]
    print(f"{len(train)} train / {len(calib)} calibration items", flush=True)

    dev = torch.device("cuda"); model = build_model(cfg, encoder_dir=os.path.join(model_dir, "encoder"))
    model.load_state_dict(load_file(os.path.join(model_dir, "model.safetensors")), strict=True)
    model.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False}); model.head_checkpointing = True
    model.to(dev).train()
    enc = [p for n, p in model.named_parameters() if "encoder." in n]; head = [p for n, p in model.named_parameters() if "encoder." not in n]
    opt = torch.optim.AdamW([{"params": enc, "lr": LR_ENCODER}, {"params": head, "lr": LR_HEAD}], weight_decay=0.01)
    total = max(1, (len(train) // (MICRO_BATCH * GRAD_ACCUM)) * EPOCHS)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=total, eta_min=1e-6); scaler = torch.amp.GradScaler("cuda")
    t0 = time.time()
    for ep in range(EPOCHS):
        random.Random(42 + ep).shuffle(train); sigma = SIGMA_START + (SIGMA_END - SIGMA_START) * ep / max(1, EPOCHS - 1)
        tot, nb = 0.0, 0; opt.zero_grad(set_to_none=True)
        for b in range(0, len(train), MICRO_BATCH):
            ids, att, mpos, mmask, tgt, qt = [x.to(dev) for x in collate(train[b:b + MICRO_BATCH], tok.pad_token_id)]
            with torch.autocast("cuda", dtype=torch.float16):
                logits, act = model(ids, att, mpos, mmask, qt)
            logits = logits.float(); k = mmask.sum(-1, keepdim=True).float()
            eps = torch.randn((GROUP_SIZE,) + logits.shape, device=dev) * sigma * mmask; eps = (eps - eps.sum(-1, keepdim=True) / k) * mmask
            z = logits.detach().unsqueeze(0) + eps; qd = torch.softmax(z.masked_fill(~mmask, -1e4), -1)
            with torch.no_grad():
                r = proper_reward(qd, tgt.unsqueeze(0), qt, mmask, w_sph=0.75, w_rps=1.0); adv = r - r.mean(0, keepdim=True); adv = adv / (adv.std() + 1e-6)
            logp = -(((z - logits.unsqueeze(0)) ** 2) * mmask).sum(-1) / (2 * sigma ** 2)
            loss_ce = -(tgt * torch.log_softmax(logits.masked_fill(~mmask, -1e4), -1)).sum(-1).mean()
            loss = (-(adv * logp).mean() + loss_ce) / GRAD_ACCUM + 0.0 * act.sum()
            scaler.scale(loss).backward(); nb += 1; tot += loss.item() * GRAD_ACCUM
            if nb % GRAD_ACCUM == 0 or b + MICRO_BATCH >= len(train):
                scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt); scaler.update(); sched.step(); opt.zero_grad(set_to_none=True)
        print(f"epoch {ep+1}/{EPOCHS} loss {tot/nb:.4f}  {time.time()-t0:.0f}s  peak VRAM {torch.cuda.max_memory_allocated()/2**30:.1f} GiB", flush=True)

    model.eval(); del opt, scaler; torch.cuda.empty_cache(); preds = []
    with torch.no_grad():
        for b in range(0, len(calib), 16):
            chunk = calib[b:b + 16]; ids, att, mpos, mmask, tgt, qt = [x.to(dev) for x in collate(chunk, tok.pad_token_id)]
            with torch.autocast("cuda", dtype=torch.float16):
                l, _ = model(ids, att, mpos, mmask, qt)
            for i, it in enumerate(chunk): preds.append((l[i, :len(it["markers"])].float().cpu().tolist(), it["target"]))
    temps = list(cfg.get("temperature", [1.2, 1.2, 1.2])) if isinstance(cfg.get("temperature"), list) else [1.2, 1.2, 1.2]
    temps[QTYPES["choice"]] = fit_temp(preds); print("calibrated temperatures", temps)
    os.makedirs(out_dir, exist_ok=True)
    save_file({k: v.half().contiguous().cpu() for k, v in model.state_dict().items()}, os.path.join(out_dir, "model.safetensors"))
    model.encoder.config.save_pretrained(os.path.join(out_dir, "encoder")); tok.save_pretrained(os.path.join(out_dir, "tokenizer"))
    # questions: what this checkpoint was trained on (the Bridge checks it). The base model's per-option-count
    # temperatures must go: they override the one fitted above and squeeze 2- and 3-option answers toward 0.8.
    cfg.update(fine_tuned=True, model_name="laya-clara-router-v3", temperature=temps, questions=sorted(specs))
    cfg.pop("temperature_by_options", None)
    json.dump(cfg, open(os.path.join(out_dir, "rl_agent_config.json"), "w"), indent=2); print("saved", out_dir)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
