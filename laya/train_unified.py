"""Train one Clara checkpoint on four balanced tasks, then calibrate each task.

Uses an explicit local base checkpoint and fixed, hashed data splits. Writes a
new candidate directory; it never installs a model or stops a running service.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import random
import shutil
import sys
import tempfile
import time

from prepare_unified import assert_disjoint, state_key
from laya_contract import QUESTIONS, example_state, schema_hash, ordered_schema_hash


def read_splits(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    splits = {}
    for name in ("train", "dev", "calibration"):
        content = (folder / f"{name}.jsonl").read_bytes()
        if hashlib.sha256(content).hexdigest() != manifest["split_sha256"][name]:
            raise ValueError(f"Split changed after preparation: {name}")
        splits[name] = [json.loads(line) for line in content.splitlines() if line.strip()]
        if not splits[name]:
            raise ValueError(f"Empty split: {name}")
    assert_disjoint(splits)
    for name in QUESTIONS:
        if manifest["question_hashes"].get(name) != schema_hash(name):
            raise ValueError(f"Question schema changed: {name}")
        for split, rows in splits.items():
            labels = {r["label"] for r in rows if r["question"] == name}
            if labels != set(QUESTIONS[name]["criteria"]):
                raise ValueError(f"{split} must include every class for {name}")
    return splits, manifest


def balanced_epoch(items, seed):
    """Visit every example, then top up each task to the largest task's size."""
    rng = random.Random(seed)
    tasks = defaultdict(list)
    for item in items:
        tasks[item["question"]].append(item)
    names = sorted(tasks)
    per_task = max(map(len,tasks.values()))
    sampled = []
    for name in names:
        rows = tasks[name]
        counts = Counter(x["label"] for x in rows)
        sampled.extend(rows)
        sampled.extend(rng.choices(rows, weights=[1 / math.sqrt(counts[x["label"]]) for x in rows], k=per_task-len(rows)))
    rng.shuffle(sampled)
    return sampled


def validate_resume(base, cfg, splits, data_manifest):
    """Resume our recorded candidate only when all prior training stays out of holdouts."""
    record_path = base / "clara_training_manifest.json"
    if not record_path.exists():
        raise ValueError("Resume requires a unified training manifest; legacy Clara exposure is unknown")
    record = json.loads(record_path.read_text())
    if file_hash(base / "model.safetensors") != record.get("candidate_weights_sha256"):
        raise ValueError("Parent candidate weights changed")
    if set(cfg.get("questions") or []) != set(QUESTIONS) or \
       cfg.get("clara_question_hashes") != {q:schema_hash(q) for q in QUESTIONS} or \
       cfg.get("clara_ordered_question_hashes") != {q:ordered_schema_hash(q) for q in QUESTIONS}:
        raise ValueError("Resume requires the same trained questions and answer order")
    previous, previous_manifest = read_splits(Path(record["arguments"]["splits"]))
    if previous_manifest != record["data"]:
        raise ValueError("Parent split manifest changed")
    seen = {state_key(r) for r in previous["train"]}
    seen.update((record.get("resume_validation") or {}).get("ancestor_training_state_hashes", []))
    held_out = {state_key(r) for name in ("dev","calibration") for r in splits[name]}
    held_out.update(data_manifest.get("held_out_state_hashes", []))
    if seen & held_out:
        raise ValueError("Previously trained inputs overlap the new holdouts")
    return {"parent":str(base.resolve()),"parent_manifest_sha256":file_hash(record_path),
            "parent_configuration_sha256":file_hash(base / "rl_agent_config.json"),
            "ancestor_training_state_hashes":sorted(seen),
            "validation":"Verified recorded weights, schemas, prior split files and disjoint prior-training/holdout states"}


def fit_temperature(rows):
    """Bounded log-loss search on hard, held-out labels; runtime range [.5, 5]."""
    import numpy as np
    z = np.array([row["logits"] for row in rows], dtype=np.float64)
    y = np.array([row["gold"] for row in rows])
    best = (float("inf"), 1.0)
    for temp in np.geomspace(.5, 5.0, 401):
        scaled = z / temp
        scaled -= scaled.max(axis=1, keepdims=True)
        loss = float((np.log(np.exp(scaled).sum(axis=1)) - scaled[np.arange(len(y)), y]).mean())
        best = min(best, (loss, float(temp)))
    return best[1]


def selection_score(summary, metric="accuracy"):
    accuracy=sum(x["accuracy"] for x in summary.values())/len(summary)
    negative_loss=-sum(x["log_loss"] for x in summary.values())/len(summary)
    return (negative_loss,accuracy) if metric=="log_loss" else (accuracy,negative_loss)


def average_checkpoints(paths, destination):
    """Average training snapshots into one checkpoint, never a serving ensemble."""
    import torch
    from safetensors.torch import load_file,save_file
    sums, dtypes = {}, {}
    for index,path in enumerate(paths):
        tensors = load_file(str(path))
        if index and set(tensors) != set(sums):
            raise ValueError("Checkpoint keys differ")
        for name,tensor in tensors.items():
            if index == 0:
                dtypes[name] = tensor.dtype
                sums[name] = tensor.float() if tensor.is_floating_point() else tensor.clone()
            elif tensor.dtype != dtypes[name] or tensor.shape != sums[name].shape:
                raise ValueError(f"Checkpoint tensor changed: {name}")
            elif tensor.is_floating_point():
                sums[name].add_(tensor.float())
            elif not torch.equal(tensor,sums[name]):
                raise ValueError(f"Non-floating checkpoint buffer differs: {name}")
        del tensors
    save_file({name:(tensor/len(paths)).to(dtypes[name]).contiguous() if tensor.is_floating_point()
                    else tensor.contiguous() for name,tensor in sums.items()},str(destination))


def tokenize(splits, tok, cfg):
    from laya.common import build_sequence, render_options, QTYPES
    # Distinct labels alone do not prove the category definitions survived.
    for name,spec in QUESTIONS.items():
        q = {"t":"choice","ins":spec["instructions"],"crit":spec["criteria"]}
        _,_,stats = build_sequence(tok,{"message":"budget check"},q,cfg["max_len"],cfg["head_max_len"],return_stats=True)
        cap = min(48,stats["tokens_per_option"]-1) if stats["tokens_per_option"] else 48
        if any(len(tok.encode(" "+option,add_special_tokens=False)) > cap for option in render_options(q)):
            raise ValueError(f"Question criteria are truncated: {name}; shorten definitions before training")
    result = {}
    token_states = {}
    for split, rows in splits.items():
        result[split] = []
        for row in rows:
            name = row["question"]
            spec = QUESTIONS[name]
            q = {"t":"choice", "ins":spec["instructions"], "crit":spec["criteria"]}
            ids, markers, stats = build_sequence(tok, example_state(row), q, cfg["max_len"], cfg["head_max_len"], return_stats=True)
            if len(markers) != len(render_options(q)) or stats["options_distinct"] != len(markers):
                raise ValueError(f"Question options lost during tokenization: {name}")
            key = (name, tuple(ids))
            if key in token_states and token_states[key] != split:
                raise ValueError(f"Token-identical inputs cross splits: {name}")
            token_states[key] = split
            keys = list(spec["criteria"])
            result[split].append({**row, "ids":ids, "markers":markers, "qtype":QTYPES["choice"], "gold":keys.index(row["label"])})
    return result


def collate(rows, pad_id, device, smoothing=0.0):
    import torch
    n, length, options = len(rows), max(len(x["ids"]) for x in rows), max(len(x["markers"]) for x in rows)
    ids = torch.full((n,length),pad_id,dtype=torch.long)
    attention = torch.zeros_like(ids)
    markers = torch.zeros((n,options),dtype=torch.long)
    mask = torch.zeros((n,options),dtype=torch.bool)
    targets = torch.zeros((n,options))
    for i,row in enumerate(rows):
        length,k = len(row["ids"]),len(row["markers"])
        ids[i,:length] = torch.tensor(row["ids"]); attention[i,:length] = 1
        markers[i,:k] = torch.tensor(row["markers"]); mask[i,:k] = True
        targets[i,:k] = smoothing / (k-1); targets[i,row["gold"]] = 1-smoothing
    qt = torch.tensor([row["qtype"] for row in rows])
    return tuple(x.to(device) for x in (ids,attention,markers,mask,qt,targets))


def evaluate(model, rows, tok, device, batch_size, progress=None):
    import torch
    from contextlib import nullcontext
    model.eval()
    predictions = defaultdict(list)
    with torch.inference_mode():
        for start in range(0,len(rows),batch_size):
            chunk = rows[start:start+batch_size]
            ids,att,markers,mask,qt,_ = collate(chunk,tok.pad_token_id,device)
            context = torch.autocast("cuda",dtype=torch.float16) if device.type == "cuda" else nullcontext()
            with context:
                logits,_ = model(ids,att,markers,mask,qt)
            for row,z in zip(chunk,logits.float().cpu()):
                predictions[row["question"]].append({"gold":row["gold"], "logits":z[:len(row["markers"])].tolist()})
            if progress and (start // batch_size) % 16 == 0:
                print(f"{progress} examples={min(start+len(chunk),len(rows))}/{len(rows)}",flush=True)
    summary = {}
    for name,examples in predictions.items():
        z = torch.tensor([r["logits"] for r in examples]); y = torch.tensor([r["gold"] for r in examples])
        summary[name] = {"correct":int((z.argmax(-1)==y).sum()),"total":len(examples),
                         "accuracy":float((z.argmax(-1)==y).float().mean()),
                         "log_loss":float(torch.nn.functional.cross_entropy(z,y))}
    return dict(predictions),summary


def cache_replay_logits(model, rows, questions, tok, device, batch_size):
    """Keep the parent's training-only predictions for tasks being preserved."""
    selected = [r for r in rows if r["question"] in questions]
    predictions, _ = evaluate(model,selected,tok,device,batch_size,progress="replay targets")
    by_question = {q:iter(values) for q,values in predictions.items()}
    for row in selected:
        row["teacher_logits"] = next(by_question[row["question"]])["logits"]
    encoded = json.dumps([r["teacher_logits"] for r in selected],separators=(",",":"))
    return {"examples":len(selected),"questions":sorted(questions),
            "logits_sha256":hashlib.sha256(encoded.encode()).hexdigest(),
            "source":"Verified parent predictions on training inputs only"}


def replay_kl(logits, rows, temperature):
    """Per-example KL(parent || student), with no target for newly learned tasks."""
    import torch
    selected = [i for i,r in enumerate(rows) if "teacher_logits" in r]
    result = logits.new_zeros(len(rows))
    if not selected:
        return result
    index = torch.tensor(selected,device=logits.device)
    teacher = logits.new_full((len(selected),logits.shape[-1]),-1e4)
    for j,i in enumerate(selected):
        values = rows[i]["teacher_logits"]
        teacher[j,:len(values)] = logits.new_tensor(values)
    values = torch.nn.functional.kl_div(
        torch.log_softmax(logits[index]/temperature,-1),
        torch.softmax(teacher/temperature,-1),reduction="none").sum(-1) * temperature**2
    return result.index_copy(0,index,values)


def main(args):
    import numpy as np
    import torch
    from transformers import AutoTokenizer
    from safetensors.torch import load_file,save_file
    from laya.agent import _fix_tokenizer_config
    from laya.common import build_model, proper_reward
    from contextlib import nullcontext
    if args.output.exists():
        raise ValueError(f"Refusing to overwrite candidate directory: {args.output}")
    if args.distill_weight and not args.resume_candidate:
        raise ValueError("Replay distillation requires a verified parent candidate")
    splits,data_manifest = read_splits(args.splits)
    cfg = json.loads((args.base / "rl_agent_config.json").read_text())
    resume_validation = None
    if args.resume_candidate:
        resume_validation = validate_resume(args.base,cfg,splits,data_manifest)
    elif cfg.get("questions") or "clara" in str(cfg.get("model_name", "")).lower():
        raise ValueError("Use the original base checkpoint: Clara checkpoints may already have seen these holdouts")
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(args.seed)
    with tempfile.TemporaryDirectory(prefix="clara-train-metadata-") as temporary:
        metadata = Path(temporary)
        for name in ("tokenizer", "encoder"):
            shutil.copytree(args.base / name,metadata / name)
        _fix_tokenizer_config(str(metadata))
        tok = AutoTokenizer.from_pretrained(str(metadata / "tokenizer"),local_files_only=True)
        items = tokenize(splits,tok,cfg)
        print(json.dumps({"preflight":"passed", "split_rows":{k:len(v) for k,v in items.items()},
                          "cuda_available":torch.cuda.is_available(), "tasks":list(QUESTIONS),
                          "base":str(args.base.resolve())}),flush=True)
        if args.preflight:
            return
        device = torch.device(args.device)
        if device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA training environment required; the Bridge environment intentionally uses CPU Torch")
        if device.type == "cuda" and torch.cuda.mem_get_info()[0] < 9 * 2**30:
            raise RuntimeError("Training needs at least 9 GiB free VRAM; free the GPU before starting this run")
        model = build_model(cfg,encoder_dir=str(metadata / "encoder"),pretrained=False)
        model.load_state_dict(load_file(str(args.base / "model.safetensors")),strict=True)
        model.encoder.config.reference_compile = False
        model.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant":False})
        model.head_checkpointing = True
        model.to(device)
        replay = None
        if args.distill_weight:
            replay = cache_replay_logits(model,items["train"],args.distill_questions,tok,device,args.micro_batch)
            replay.update(weight=args.distill_weight,temperature=args.distill_temperature,
                          parent_weights_sha256=file_hash(args.base / "model.safetensors"))
            print(json.dumps({"replay_distillation":replay}),flush=True)
        groups = [{"params":[p for n,p in model.named_parameters() if n.startswith("encoder.")],"lr":args.encoder_lr},
                  {"params":[p for n,p in model.named_parameters() if not n.startswith("encoder.")],"lr":args.head_lr}]
        optimizer = torch.optim.AdamW(groups,weight_decay=.01)
        epoch_size = len(balanced_epoch(items["train"],args.seed))
        steps = math.ceil(epoch_size / (args.micro_batch*args.accumulation)) * args.epochs
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=steps,eta_min=1e-6)
        scaler = torch.amp.GradScaler("cuda",enabled=device.type=="cuda")
        args.output.mkdir(parents=True)
        checkpoint_dir = args.output.with_name(args.output.name+"-epochs")
        if args.average_checkpoints:
            checkpoint_dir.mkdir(exist_ok=False)
        source_dir = args.output / "training_source"
        source_dir.mkdir()
        root = Path(__file__).resolve().parents[1]
        source_files = ["laya/train_unified.py","laya/prepare_unified.py","bridge/laya_contract.py",
                        "bridge/laya_unified.py"] + [f"bridge/{name}_spec.py" for name in ("router","effort","need","followup")]
        source_hashes = {}
        for relative in source_files:
            source = root / relative
            shutil.copy2(source,source_dir / source.name)
            source_hashes[relative] = file_hash(source_dir / source.name)
        (source_dir / "source_sha256.json").write_text(json.dumps(source_hashes,indent=2)+"\n")
        best,history = None,[]
        started = time.monotonic()
        if resume_validation:
            _,dev = evaluate(model,items["dev"],tok,device,args.micro_batch)
            best = selection_score(dev,args.selection_metric); best_epoch = None; selected_checkpoint = "parent"
            shutil.copy2(args.base / "model.safetensors",args.output / "model.safetensors")
            history.append({"checkpoint":"parent","dev":dev,"selection_score":best})
            print(json.dumps(history[-1]),flush=True)
        for epoch in range(args.epochs):
            model.train()
            rows = balanced_epoch(items["train"],args.seed+epoch)
            loss_sum = 0.0
            skipped_updates = 0
            for group_start in range(0,len(rows),args.micro_batch*args.accumulation):
                group = rows[group_start:group_start+args.micro_batch*args.accumulation]
                optimizer.zero_grad(set_to_none=True)
                for start in range(0,len(group),args.micro_batch):
                    chunk = group[start:start+args.micro_batch]
                    ids,att,markers,mask,qt,target = collate(chunk,tok.pad_token_id,device,args.smoothing)
                    context = torch.autocast("cuda",dtype=torch.float16) if device.type=="cuda" else nullcontext()
                    with context:
                        logits,act = model(ids,att,markers,mask,qt)
                    logits = logits.float().masked_fill(~mask,-1e4)
                    losses = -(target * torch.log_softmax(logits,-1)).sum(-1)
                    if args.distill_weight:
                        losses = losses + args.distill_weight * replay_kl(logits,chunk,args.distill_temperature)
                    if args.loss == "rlcd":
                        sigma = .4 - .3 * epoch / max(1,args.epochs-1)
                        k = mask.sum(-1,keepdim=True)
                        noise = torch.randn((4,)+logits.shape,device=device) * sigma * mask
                        noise = (noise-noise.sum(-1,keepdim=True)/k)*mask
                        z = logits.detach().unsqueeze(0)+noise
                        with torch.no_grad():
                            qd = torch.softmax(z.masked_fill(~mask,-1e4),-1)
                            reward = proper_reward(qd,target.unsqueeze(0),qt,mask,w_sph=.75,w_rps=1.0)
                            advantage = reward-reward.mean(0,keepdim=True)
                            advantage = advantage/(advantage.std()+1e-6)
                        logp = -(((z-logits.unsqueeze(0))**2)*mask).sum(-1)/(2*sigma**2)
                        losses = losses-(advantage*logp).mean(0)
                    loss = losses.sum()/len(group) + 0.0*act.sum()
                    if not torch.isfinite(loss): raise RuntimeError("Non-finite training loss")
                    scaler.scale(loss).backward(); loss_sum += float(losses.detach().sum())
                scaler.unscale_(optimizer); torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
                previous_scale = scaler.get_scale()
                scaler.step(optimizer); scaler.update()
                if scaler.get_scale() >= previous_scale:
                    scheduler.step()
                else:
                    skipped_updates += 1
                if group_start % (args.micro_batch*args.accumulation*10) == 0:
                    print(f"epoch={epoch+1} examples={min(group_start+len(group),len(rows))}/{len(rows)} elapsed={time.monotonic()-started:.0f}s",flush=True)
            _,dev = evaluate(model,items["dev"],tok,device,args.micro_batch)
            score = selection_score(dev,args.selection_metric)
            history.append({"epoch":epoch+1,"train_loss":loss_sum/len(rows),"skipped_updates":skipped_updates,
                            "dev":dev,"selection_score":score})
            print(json.dumps(history[-1]),flush=True)
            improved = best is None or score > best
            if improved or args.average_checkpoints:
                exported = {k:(v.detach().half() if v.is_floating_point() else v.detach()).cpu().contiguous()
                            for k,v in model.state_dict().items()}
                if args.average_checkpoints:
                    save_file(exported,str(checkpoint_dir / f"epoch-{epoch+1}.safetensors"))
                if improved:
                    best = score; best_epoch = epoch+1; selected_checkpoint = f"epoch-{epoch+1}"
                    save_file(exported,str(args.output / "model.safetensors"))
                del exported
            (args.output / "training_history.json").write_text(json.dumps(history,indent=2)+"\n")
        model.zero_grad(set_to_none=True)
        # The scheduler retains the optimizer and its GPU state; release both.
        del optimizer,scheduler,scaler,groups,loss,losses,logits,act,ids,att,markers,mask,qt,target
        if device.type=="cuda": torch.cuda.empty_cache()
        if args.average_checkpoints:
            choices = [tuple(range(1,args.epochs+1)),tuple(range(max(1,args.epochs-1),args.epochs+1))]
            for epochs in dict.fromkeys(choices):
                if len(epochs)<2: continue
                name = "average-"+"-".join(map(str,epochs))
                path = checkpoint_dir / f"{name}.safetensors"
                average_checkpoints([checkpoint_dir/f"epoch-{epoch}.safetensors" for epoch in epochs],path)
                model.load_state_dict(load_file(str(path)),strict=True)
                _,dev = evaluate(model,items["dev"],tok,device,args.micro_batch)
                score = selection_score(dev,args.selection_metric)
                history.append({"checkpoint_average":list(epochs),"dev":dev,"selection_score":score})
                print(json.dumps(history[-1]),flush=True)
                if score > best:
                    best = score; best_epoch = None; selected_checkpoint = name
                    shutil.copy2(path,args.output / "model.safetensors")
            (args.output / "training_history.json").write_text(json.dumps(history,indent=2)+"\n")
        model.load_state_dict(load_file(str(args.output / "model.safetensors")),strict=True)
        # Fit the exported fp16 weights loaded as CPU fp32, exactly as Bridge serves them.
        model.to("cpu")
        if device.type=="cuda": torch.cuda.empty_cache()
        print("Fitting per-question calibration on the CPU serving precision",flush=True)
        predictions,calibration = evaluate(model,items["calibration"],tok,torch.device("cpu"),args.micro_batch,
                                           progress="calibration")
        temperatures = {name:fit_temperature(rows) for name,rows in predictions.items()}
        trained = sorted({r["question"] for r in items["train"]})
        cfg.update(model_name="laya-clara-unified",fine_tuned=True,questions=trained,temperature=[1.0,1.0,1.0],
                   clara_temperature_by_question=temperatures,clara_question_hashes={q:schema_hash(q) for q in trained},
                   clara_ordered_question_hashes={q:ordered_schema_hash(q) for q in trained},
                   clara_route_threshold=.9)
        cfg.pop("temperature_by_options",None)
        cfg.pop("training",None)
        model.encoder.config.save_pretrained(args.output / "encoder")
        tok.save_pretrained(args.output / "tokenizer")
        (args.output / "rl_agent_config.json").write_text(json.dumps(cfg,indent=2)+"\n")
        manifest = {"format":1,"best_epoch":best_epoch,"selected_checkpoint":selected_checkpoint,"base_path":str(args.base.resolve()),
                    "resume_validation":resume_validation,"replay_distillation":replay,
                    "trainer_sha256":source_hashes["laya/train_unified.py"],"training_source_sha256":source_hashes,
                    "base_config_sha256":hashlib.sha256((args.base / "rl_agent_config.json").read_bytes()).hexdigest(),
                    "base_weights_sha256":file_hash(args.base / "model.safetensors"),"data":data_manifest,
                    "arguments":{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
                    "versions":{p:importlib.metadata.version(p) for p in ("laya","torch","transformers","numpy","safetensors")},
                    "history":history,"calibration_before_scaling":calibration,"temperatures":temperatures,
                    "elapsed_seconds":time.monotonic()-started,"candidate_weights_sha256":file_hash(args.output / "model.safetensors"),
                    "deployment_status":"candidate; must pass eval_unified.py and full app checks before installation"}
        (args.output / "clara_training_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        print(json.dumps({"candidate":str(args.output),"selected_checkpoint":selected_checkpoint,
                          "best_epoch":best_epoch,"temperatures":temperatures}),flush=True)


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle,"sha256").hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base",type=Path,required=True)
    parser.add_argument("--resume-candidate",action="store_true",help="Continue a recorded unified candidate after checking prior-training/holdout separation")
    parser.add_argument("--selection-metric",choices=["accuracy","log_loss"],default="accuracy",
                        help="Primary mean per-question development metric; the other breaks ties")
    parser.add_argument("--distill-weight",type=float,default=0.0,
                        help="Parent-to-student KL weight on training examples for preserved tasks")
    parser.add_argument("--distill-questions",nargs="+",choices=list(QUESTIONS),default=["route","effort","need"])
    parser.add_argument("--distill-temperature",type=float,default=2.0)
    parser.add_argument("--splits",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--preflight",action="store_true")
    parser.add_argument("--device",choices=["cuda","cpu"],default="cuda")
    parser.add_argument("--loss",choices=["ce","rlcd"],default="ce")
    parser.add_argument("--epochs",type=int,default=3)
    parser.add_argument("--average-checkpoints",action="store_true",help="Also select between epoch averages using development data only")
    parser.add_argument("--micro-batch",type=int,default=4)
    parser.add_argument("--accumulation",type=int,default=8)
    parser.add_argument("--encoder-lr",type=float,default=2.5e-5)
    parser.add_argument("--head-lr",type=float,default=1e-4)
    parser.add_argument("--smoothing",type=float,default=.02)
    parser.add_argument("--seed",type=int,default=20261003)
    parser.add_argument("--threads",type=int,default=4)
    args = parser.parse_args()
    if min(args.epochs,args.micro_batch,args.accumulation,args.threads) < 1 or not 0 <= args.smoothing < 1:
        parser.error("positive counts and smoothing in [0, 1) are required")
    if not math.isfinite(args.distill_weight) or args.distill_weight < 0 or not math.isfinite(args.distill_temperature) or args.distill_temperature <= 0:
        parser.error("distillation weight must be finite and nonnegative; temperature must be finite and positive")
    main(args)
