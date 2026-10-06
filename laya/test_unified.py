"""Offline invariants for training splits and the single-checkpoint serving path."""
from collections import Counter
import importlib.util
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from prepare_unified import split_rows, assert_disjoint, state_key, prepare, apply_review, load_rows
from train_unified import balanced_epoch, fit_temperature, collate, read_splits, tokenize, average_checkpoints, validate_resume
from laya_contract import QUESTIONS, schema_hash, ordered_schema_hash, example_state
from laya_unified import agent_class


def isolated_router(folder):
    """Import the router without caching production paths ahead of another suite."""
    spec = importlib.util.spec_from_file_location("_unified_test_router", Path(__file__).resolve().parents[1]/"bridge/router.py")
    module = importlib.util.module_from_spec(spec)
    paths = SimpleNamespace(ROUTER_MODEL=folder, NEED_MODEL=folder/"legacy-secondary")
    with patch.dict(sys.modules,{"paths":paths, spec.name:module}):
        spec.loader.exec_module(module)
    return module


class DataTests(unittest.TestCase):
    def test_resume_verifies_parent_weights_and_all_prior_training_exposure(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);folder=base/'splits';folder.mkdir()
            cfg={'questions':list(QUESTIONS),'clara_question_hashes':{q:schema_hash(q) for q in QUESTIONS},
                 'clara_ordered_question_hashes':{q:ordered_schema_hash(q) for q in QUESTIONS}}
            (base/'rl_agent_config.json').write_text(json.dumps(cfg))
            (base/'model.safetensors').write_bytes(b'fixture weights')
            data={'question_hashes':cfg['clara_question_hashes'],'split_sha256':{}}
            prior={}
            for split in ('train','dev','calibration'):
                prior[split]=[{'question':q,'label':label,'text':f'{split}-{q}-{label}',
                               'last':f'{split} context','split_group':f'{split}-{q}-{label}'}
                              for q,spec in QUESTIONS.items() for label in spec['criteria']]
                content=''.join(json.dumps(r)+'\n' for r in prior[split])
                (folder/f'{split}.jsonl').write_text(content)
                data['split_sha256'][split]=hashlib.sha256(content.encode()).hexdigest()
            (folder/'manifest.json').write_text(json.dumps(data))
            record={'arguments':{'splits':str(folder)},'data':data,
                    'candidate_weights_sha256':hashlib.sha256(b'fixture weights').hexdigest()}
            record_path=base/'clara_training_manifest.json'
            record_path.write_text(json.dumps(record))
            result=validate_resume(base,cfg,prior,{})
            self.assertEqual(set(result['ancestor_training_state_hashes']),{state_key(r) for r in prior['train']})
            moved={**prior,'dev':[prior['train'][0]]}
            with self.assertRaisesRegex(ValueError,'Previously trained inputs'):
                validate_resume(base,cfg,moved,{})
            record['resume_validation']={'ancestor_training_state_hashes':[state_key(prior['dev'][0])]}
            record_path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'Previously trained inputs'):
                validate_resume(base,cfg,prior,{})
            record.pop('resume_validation');record_path.write_text(json.dumps(record))
            (folder/'manifest.json').write_text(json.dumps({**data,'changed':True}))
            with self.assertRaisesRegex(ValueError,'Parent split manifest changed'):
                validate_resume(base,cfg,prior,{})
            (folder/'manifest.json').write_text(json.dumps(data))
            (base/'model.safetensors').write_bytes(b'changed weights')
            with self.assertRaisesRegex(ValueError,'Parent candidate weights changed'):
                validate_resume(base,cfg,prior,{})

    def test_duplicates_cross_questions_and_transitive_pairs_stay_together(self):
        rows = [
            {"question":"route","text":" Open inbox ","label":"task","pair_id":"a"},
            {"question":"route","text":"open inbox","label":"task","pair_id":"b"},
            {"question":"need","text":"OPEN INBOX","label":"email_calendar"},
            {"question":"effort","text":"review inbox","label":"deep","pair_id":"b"},
            {"question":"effort","text":"check inbox","label":"quick","pair_id":"a"},
        ]
        splits = split_rows(rows)
        assert_disjoint(splits)
        nonempty = [r for r in splits.values() if r]
        self.assertEqual(len(nonempty),1)
        self.assertEqual(len(nonempty[0]),4)

    def test_conflicting_labels_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"Conflicting"):
            split_rows([{"question":"route","text":"hello","label":"chat"},
                        {"question":"route","text":"HELLO","label":"task"}])

    def test_followup_identity_uses_the_runtime_context_window(self):
        a={"question":"followup","text":"yes","last":"a"*700+"b"*600}
        b={**a,"last":"b"*600}
        self.assertEqual(state_key(a),state_key(b))
        self.assertNotEqual(state_key(a),state_key({**a,"last":"different question"}))

    def test_manifest_rejects_changed_data(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            for name in ("train","dev","calibration"):(p/f"{name}.jsonl").write_text('{}\n')
            (p/'manifest.json').write_text(json.dumps({"split_sha256":{"train":"wrong"}}))
            with self.assertRaisesRegex(ValueError,"changed"):
                read_splits(p)

    def test_sampling_keeps_equal_task_counts_and_is_reproducible(self):
        rows=[{"question":q,"label":str(i%2),"id":i} for q,n in [("route",80),("effort",4),("need",20),("followup",8)] for i in range(n)]
        a=balanced_epoch(rows,12)
        self.assertEqual(a,balanced_epoch(rows,12))
        self.assertEqual(len(set(Counter(r['question'] for r in a).values())),1)
        self.assertEqual({(r['question'],r['id']) for r in a},{(r['question'],r['id']) for r in rows})
        self.assertNotEqual(a,balanced_epoch(rows,13))

    def test_shuffling_input_does_not_change_split_membership(self):
        rows=[{"question":"route","text":f"request {i}","label":"task","pair_id":str(i//2)} for i in range(50)]
        a=split_rows(rows); random.Random(7).shuffle(rows); b=split_rows(rows)
        self.assertEqual({k:{r['text'] for r in v} for k,v in a.items()},
                         {k:{r['text'] for r in v} for k,v in b.items()})

    def test_review_is_explicit_and_pinned_to_the_original_source(self):
        with tempfile.TemporaryDirectory() as td:
            source, review = Path(td)/'source.jsonl', Path(td)/'review.json'
            rows=[{'question':'need','text':'open my task app','label':'other'},
                  {'question':'need','text':'do several unspecified things','label':'other'},
                  {'question':'need','text':'convert supplied units','label':'other'}]
            source.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            original = source.read_bytes()
            notes={'source_sha256':{source.name:hashlib.sha256(original).hexdigest()},'decisions':[
                {**rows[0],'old_label':'other','label':'apps','action':'relabel','reason':'Explicit connected app'},
                {**rows[1],'old_label':'other','action':'drop','reason':'Ambiguous'}]}
            review.write_text(json.dumps(notes))
            corrected, changes=apply_review(load_rows([source]),review,[source])
            self.assertEqual([r['label'] for r in corrected],['apps','other'])
            self.assertEqual(changes,{'relabel':1,'drop':1})
            self.assertEqual(source.read_bytes(),original)
            source.write_bytes(original+b'\n')
            with self.assertRaisesRegex(ValueError,'source changed'):
                apply_review(load_rows([source]),review,[source])


class CalibrationTests(unittest.TestCase):
    def test_replay_distillation_preserves_parent_choices_without_training_new_tasks(self):
        import torch
        from train_unified import replay_kl
        rows=[{'teacher_logits':[3.,-1.]},{}, {'teacher_logits':[-2.,2.,0.]}]
        z=torch.tensor([[-1.,3.,-1e4],[1.,-1.,-1e4],[2.,-2.,0.]],requires_grad=True)
        loss=replay_kl(z,rows,2.)
        self.assertEqual(float(loss[1].detach()),0.)
        self.assertTrue(torch.isfinite(loss).all())
        loss.sum().backward()
        self.assertLess(float(z.grad[0,0]),0.)
        self.assertGreater(float(z.grad[0,1]),0.)
        self.assertEqual(float(z.grad[0,2]),0.)
        self.assertTrue(torch.equal(z.grad[1],torch.zeros(3)))
        self.assertLess(float(z.grad[2,1]),0.)
        same=torch.tensor([[3.,-1.,-1e4],[1.,-1.,-1e4],[-2.,2.,0.]])
        self.assertTrue(torch.allclose(replay_kl(same,rows,2.),torch.zeros(3),atol=1e-6))

    def test_replay_targets_are_cached_only_for_requested_training_tasks(self):
        from train_unified import cache_replay_logits
        rows=[{'question':'effort'},{'question':'followup'},{'question':'route'},{'question':'effort'}]
        expected={'effort':[{'logits':[2.,1.]},{'logits':[4.,3.]}],
                  'route':[{'logits':[1.,2.,3.]}]}
        with patch('train_unified.evaluate',return_value=(expected,{})) as evaluate:
            result=cache_replay_logits(None,rows,['effort','route'],None,None,2)
        self.assertEqual(evaluate.call_args.args[1],[rows[0],rows[2],rows[3]])
        self.assertNotIn('teacher_logits',rows[1])
        self.assertEqual(rows[3]['teacher_logits'],[4.,3.])
        self.assertEqual(result['examples'],3)
        self.assertEqual(len(result['logits_sha256']),64)

    def test_probability_selection_uses_only_valid_matching_development_scores(self):
        from reselect_unified import select_checkpoint
        counts={q:100 for q in QUESTIONS}
        def scores(accuracy,loss):
            return {q:{'total':100,'accuracy':accuracy,'log_loss':loss} for q in QUESTIONS}
        history=[{'checkpoint':'parent','dev':scores(.99,.3)},
                 {'epoch':1,'dev':scores(.97,.2)},
                 {'checkpoint_average':[1,2],'dev':scores(.98,.2)}]
        chosen,_=select_checkpoint(history,counts)
        self.assertEqual(chosen['name'],'average-1-2')
        with self.assertRaisesRegex(ValueError,'recorded split'):
            select_checkpoint(history,{**counts,'effort':99})
        with self.assertRaisesRegex(ValueError,'finite'):
            select_checkpoint([{'epoch':1,'dev':scores(.99,float('nan'))}],counts)

    def test_training_and_runtime_encode_and_pad_the_same_inputs(self):
        import laya
        import torch
        from laya.common import render_options, collate_items
        from tokenizers import Tokenizer, models, pre_tokenizers
        from transformers import PreTrainedTokenizerFast
        internal={q:laya.Agent._to_internal(spec) for q,spec in QUESTIONS.items()}
        words=set('choice question: budget check'.split())
        for q in internal.values():
            words.update(q['ins'].split())
            for option in render_options(q):words.update(option.split())
        specials=['[UNK]','[PAD]','[CLS]','[SEP]','[MASK]']
        vocab={word:i for i,word in enumerate(specials+sorted(words-set(specials)))}
        backend=Tokenizer(models.WordLevel(vocab,unk_token='[UNK]'))
        backend.pre_tokenizer=pre_tokenizers.WhitespaceSplit()
        tok=PreTrainedTokenizerFast(tokenizer_object=backend,unk_token='[UNK]',pad_token='[PAD]',
                                   cls_token='[CLS]',sep_token='[SEP]',mask_token='[MASK]')
        runtime=laya.Agent.__new__(laya.Agent)
        runtime.tok=tok;runtime.cfg={'max_len':512,'head_max_len':256}
        rows=[{'question':q,'label':next(iter(spec['criteria'])),
               'text':('Literal [MASK], café and a "quoted" phrase.' if i%2 else 'many words '*800),
               'last':'Older context '*100+'The two results are ready.'}
              for i,(q,spec) in enumerate(QUESTIONS.items())]
        trained=tokenize({'train':rows},tok,runtime.cfg)['train']
        encoded=[runtime._encode_state(example_state(row),[row['question']],internal) for row in rows]
        for training,serving in zip(trained,encoded):
            self.assertEqual(training['ids'],serving[0]['ids'])
            self.assertEqual(training['markers'],serving[0]['markers'])
        self.assertEqual(len(trained[0]['ids']),512)
        batch=collate(trained,tok.pad_token_id,torch.device('cpu'))
        serving_batch=collate_items(encoded,tok.pad_token_id)
        for tensor,key in zip(batch,('input_ids','attention_mask','marker_pos','marker_mask','qtype')):
            self.assertTrue(torch.equal(tensor,serving_batch[key]),key)

    def test_checkpoint_average_keeps_integer_buffers_and_input_files(self):
        import torch
        from safetensors.torch import save_file,load_file
        with tempfile.TemporaryDirectory() as td:
            a,b,out=[Path(td)/name for name in ('a.safetensors','b.safetensors','mean.safetensors')]
            save_file({'weight':torch.tensor([2.,4.],dtype=torch.float16),'index':torch.tensor([1,2])},str(a))
            save_file({'weight':torch.tensor([4.,8.],dtype=torch.float16),'index':torch.tensor([1,2])},str(b))
            original=a.read_bytes()
            average_checkpoints([a,b],out)
            tensors=load_file(str(out))
            self.assertTrue(torch.equal(tensors['weight'],torch.tensor([3.,6.],dtype=torch.float16)))
            self.assertEqual(tensors['index'].dtype,torch.int64)
            self.assertEqual(a.read_bytes(),original)
            save_file({'weight':torch.tensor([4.,8.],dtype=torch.float16),'index':torch.tensor([1,3])},str(b))
            with self.assertRaisesRegex(ValueError,'buffer differs'):
                average_checkpoints([a,b],Path(td)/'invalid.safetensors')

    def test_training_rejects_distinct_but_truncated_criteria(self):
        tok=SimpleNamespace(encode=lambda *args,**kwargs:list(range(49)))
        # Upstream can report distinct options even though its hard cap cut them.
        with patch('laya.common.build_sequence',return_value=([],[],{'tokens_per_option':None})):
            with self.assertRaisesRegex(ValueError,'criteria are truncated'):
                tokenize({},tok,{'max_len':512,'head_max_len':192})

    def test_temperature_softens_wrong_overconfidence(self):
        rows=[{"logits":[0.,10.],"gold":i%2} for i in range(20)]
        self.assertEqual(fit_temperature(rows),5.0)

    def test_smoothing_does_not_assign_mass_to_padded_options(self):
        import torch
        rows=[{"ids":[1,2],"markers":[0,1],"qtype":0,"gold":1},
              {"ids":[1,2,3],"markers":[0,1,2],"qtype":0,"gold":2}]
        *_,target=collate(rows,0,torch.device('cpu'),.05)
        self.assertEqual(float(target[0,2]),0)
        self.assertTrue(torch.allclose(target.sum(-1),torch.ones(2)))

    def test_per_question_decoding_preserves_logits_and_respects_offsets(self):
        import numpy as np
        import laya
        cls=agent_class(laya.Agent)
        agent=cls.__new__(cls)
        agent.question_temperatures={'effort':.5,'followup':2.0}
        agent.temperature=[1.05,1.,1.]
        agent.temperature_by_options={'choice:2':1.9}
        agent.lang_temperatures={}
        logits=np.array([[100.,-100.],[0.,4.],[0.,4.]],dtype=np.float32)
        original=logits.copy()
        ids=['effort','followup']
        internal={q:{'t':'choice','crit':QUESTIONS[q]['criteria']} for q in ids}
        answer=agent._decode_answers(logits,np.full((3,2),.5),[{'markers':[1,2]},{'markers':[1,2]}],ids,internal,1)
        self.assertEqual(answer['effort']['probabilities']['deep'],.9997)
        self.assertEqual(answer['followup']['probabilities']['new'],.8808)
        self.assertTrue(np.array_equal(logits,original))

    def test_changed_question_or_invalid_temperature_fails_loading(self):
        class Fake:
            def __init__(self,cfg):self.cfg=cfg
        cls=agent_class(Fake)
        cfg={'questions':['effort'],'clara_temperature_by_question':{'effort':1.},'clara_question_hashes':{'effort':schema_hash('effort')}}
        cls(cfg)
        with self.assertRaisesRegex(ValueError,'changed'):
            cls({**cfg,'clara_question_hashes':{'effort':'stale'}})
        with self.assertRaisesRegex(ValueError,'Invalid'):
            cls({**cfg,'clara_temperature_by_question':{'effort':float('nan')}})

    def test_changed_answer_order_is_detected_even_when_labels_are_unchanged(self):
        class Fake:
            def __init__(self,cfg):self.cfg=cfg
        cls=agent_class(Fake)
        cfg={'questions':['effort'],'clara_temperature_by_question':{'effort':1.},
             'clara_question_hashes':{'effort':schema_hash('effort')},
             'clara_ordered_question_hashes':{'effort':ordered_schema_hash('effort')}}
        cls(cfg)
        reversed_spec={**QUESTIONS['effort'],'criteria':dict(reversed(list(QUESTIONS['effort']['criteria'].items())))}
        with patch.dict(QUESTIONS,{'effort':reversed_spec}):
            with self.assertRaisesRegex(ValueError,'answer order changed'):
                cls(cfg)


class ServingTests(unittest.TestCase):
    def test_legacy_primary_never_loads_an_extra_model(self):
        agent=SimpleNamespace(cfg={'questions':['route','effort']},
                              predict=Mock(return_value={'answers':{'effort':{'choice':'quick','probabilities':{'quick':.92}}}}))
        with tempfile.TemporaryDirectory() as td:
            path=Path(td);(path/'model.safetensors').touch()
            secondary=path/'legacy-secondary';secondary.mkdir()
            (secondary/'model.safetensors').touch()
            (secondary/'rl_agent_config.json').write_text(json.dumps({'questions':list(QUESTIONS)}))
            router=isolated_router(path)
            with patch.object(router,'load_agent',return_value=agent) as load:
                r=router.Router()
            load.assert_called_once()
            self.assertFalse(r.knows_need)
            self.assertIsNone(r.need_agent)
            self.assertEqual(r.diagnostics()['resident_models'],1)
            self.assertEqual(r.effort('read disk usage'),('quick',.92))
            agent.predict.assert_called_once_with(router.state('read disk usage'),{'effort':router.LEGACY_QUESTIONS['effort']})
            self.assertNotEqual(r.effort_question,QUESTIONS['effort'])

    def test_fresh_audit_failures_prevent_release(self):
        from eval_unified import release_checks
        def score(n):
            return {'total':n,'policy_correct':n,'accepted':n,'accepted_errors':0,'false_quick':0}
        summary={'regression':{q:score(n) for q,n in {'route':40,'effort':40,'need':50,'followup':36}.items()},
                 'challenge':{q:score(16) for q in QUESTIONS},
                 'fresh_audit':{q:score(16) for q in QUESTIONS}}
        self.assertTrue(all(release_checks(summary,True).values()))
        summary['fresh_audit']['followup']['policy_correct']=12
        self.assertFalse(release_checks(summary,True)['fresh_audit_each_question'])
        summary['fresh_audit']['route']['accepted_errors']=1
        self.assertFalse(release_checks(summary,True)['fresh_audit_no_accepted_route_errors'])

    def test_unified_checkpoint_is_loaded_only_once(self):
        agent=SimpleNamespace(cfg={'questions':list(QUESTIONS),'clara_temperature_by_question':{q:1. for q in QUESTIONS}})
        with tempfile.TemporaryDirectory() as td:
            path=Path(td);(path/'model.safetensors').touch()
            router=isolated_router(path)
            with patch.object(router,'load_agent',return_value=agent) as load:
                r=router.Router()
        load.assert_called_once()
        self.assertIs(r.agent,r.need_agent)
        self.assertTrue(r.knows_need)
        self.assertEqual(r.diagnostics()['resident_models'],1)
        self.assertEqual(r.diagnostics()['questions'],sorted(QUESTIONS))
        self.assertEqual(r.effort_question,QUESTIONS['effort'])
        self.assertEqual(r.need_question,QUESTIONS['need'])
        self.assertEqual(r.followup_question,QUESTIONS['followup'])

    def test_unified_route_uses_probability_not_entropy(self):
        router=isolated_router(Path('/unused-test-model'))
        r=router.Router.__new__(router.Router)
        r.unified=True;r.route_threshold=.9;r.knows_need=False
        r.agent=SimpleNamespace(predict=lambda *args:{'answers':{'route':{'choice':'chat','confidence':.65,'probabilities':{'chat':.94,'task':.03,'schedule':.03}}}})
        r._bonsai=Mock(side_effect=AssertionError('unneeded fallback'))
        result=r.route('hello')
        self.assertEqual((result.route,result.source,result.confidence),('chat','laya',.94))


if __name__=='__main__': unittest.main()
