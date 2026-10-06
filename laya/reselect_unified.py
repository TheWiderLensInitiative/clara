"""Export a saved training checkpoint selected by development log loss.

Selection uses recorded development results only. The chosen weights are calibrated
again on the original calibration split; no release or final-audit labels are read.
Requires a completed run with --average-checkpoints and its saved epoch files.
"""
import argparse
import importlib.metadata
import json
import math
from pathlib import Path
import shutil
import time

from train_unified import read_splits, validate_resume, tokenize, evaluate, fit_temperature, file_hash
from laya_contract import QUESTIONS


def select_checkpoint(history, expected_counts):
    choices=[]
    for row in history:
        dev=row['dev']
        if set(dev)!=set(QUESTIONS) or {q:s['total'] for q,s in dev.items()}!=expected_counts:
            raise ValueError('Development history does not match the recorded split')
        if any(not math.isfinite(s['log_loss']) or s['log_loss']<0 or
               not math.isfinite(s['accuracy']) or not 0<=s['accuracy']<=1 for s in dev.values()):
            raise ValueError('Development scores must be finite valid metrics')
        if 'checkpoint_average' in row:
            name='average-'+'-'.join(map(str,row['checkpoint_average']))
        elif row.get('checkpoint')=='parent':
            name='parent'
        else:
            name=f"epoch-{row['epoch']}"
        mean_loss=sum(s['log_loss'] for s in dev.values())/len(dev)
        mean_accuracy=sum(s['accuracy'] for s in dev.values())/len(dev)
        choices.append({'name':name,'mean_log_loss':mean_loss,'mean_accuracy':mean_accuracy,
                        'epoch':row.get('epoch')})
    if not choices:
        raise ValueError('No development checkpoints available')
    selected=min(choices,key=lambda x:(x['mean_log_loss'],-x['mean_accuracy'],x['name']))
    return selected,choices


def main(args):
    import torch
    from transformers import AutoTokenizer
    from safetensors.torch import load_file
    from laya.common import build_model
    if args.output.exists():
        raise ValueError(f'Refusing to overwrite candidate: {args.output}')
    torch.set_num_threads(args.threads);torch.set_num_interop_threads(1)
    source=args.source.resolve()
    record_path=source/'clara_training_manifest.json'
    record=json.loads(record_path.read_text())
    cfg=json.loads((source/'rl_agent_config.json').read_text())
    splits,data=read_splits(Path(record['arguments']['splits']))
    validate_resume(source,cfg,splits,data)
    if not record['arguments'].get('average_checkpoints'):
        raise ValueError('Source run must preserve all epoch files with --average-checkpoints')
    selected,choices=select_checkpoint(record['history'],
                                      {q:sum(r['question']==q for r in splits['dev']) for q in QUESTIONS})
    if selected['name']=='parent':
        weights=Path(record['base_path'])/'model.safetensors'
        if file_hash(weights)!=record['base_weights_sha256']:
            raise ValueError('Parent weights changed since training')
    else:
        weights=source.with_name(source.name+'-epochs')/(selected['name']+'.safetensors')
    selected_hash=file_hash(weights)
    print(json.dumps({'selected':selected,'choices':choices}),flush=True)
    tok=AutoTokenizer.from_pretrained(source/'tokenizer',local_files_only=True)
    rows=tokenize(splits,tok,cfg)
    model=build_model(cfg,encoder_dir=str(source/'encoder'),pretrained=False)
    model.load_state_dict(load_file(str(weights)),strict=True)
    model.encoder.config.reference_compile=False
    started=time.monotonic()
    predictions,calibration=evaluate(model,rows['calibration'],tok,torch.device('cpu'),args.batch_size,
                                     progress='reselection calibration')
    temperatures={q:fit_temperature(examples) for q,examples in predictions.items()}
    cfg.update(temperature=[1.,1.,1.],clara_temperature_by_question=temperatures)
    cfg.pop('temperature_by_options',None)
    args.output.mkdir(parents=True)
    shutil.copy2(weights,args.output/'model.safetensors')
    if file_hash(args.output/'model.safetensors')!=selected_hash:
        raise ValueError('Selected weights changed during export')
    for folder in ('encoder','tokenizer','training_source'):
        shutil.copytree(source/folder,args.output/folder)
    shutil.copy2(source/'training_history.json',args.output/'training_history.json')
    shutil.copy2(__file__,args.output/'training_source/reselect_unified.py')
    (args.output/'rl_agent_config.json').write_text(json.dumps(cfg,indent=2)+'\n')
    record.update(best_epoch=selected['epoch'],selected_checkpoint=selected['name'],
                  candidate_weights_sha256=selected_hash,calibration_before_scaling=calibration,
                  temperatures=temperatures,
                  deployment_status='candidate; must pass eval_unified.py and full app checks before installation')
    record['post_training_selection']={
        'source_candidate':str(source),'source_manifest_sha256':file_hash(record_path),
        'source_weights':str(weights),'selection_rule':'Minimum mean per-question development log loss; ties use mean accuracy then checkpoint name',
        'selected':selected,'choices':choices,'exporter_sha256':file_hash(Path(__file__)),
        'calibration_elapsed_seconds':time.monotonic()-started,
        'runtime_versions':{p:importlib.metadata.version(p) for p in ('laya','torch','transformers')},
        'arguments':{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
        'limits':'Alternative development-selection rule. No release or fresh-audit labels were used to choose between saved epochs.'}
    (args.output/'clara_training_manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'candidate':str(args.output),'selected':selected['name'],'temperatures':temperatures}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--threads',type=int,default=4)
    parser.add_argument('--batch-size',type=int,default=4)
    main(parser.parse_args())
