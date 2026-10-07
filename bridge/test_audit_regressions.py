"""Offline regression tests. Temporary state, fake HTTP, no model/cloud/account calls.
Run with the Bridge environment: python -m unittest discover -s bridge -p test_audit_regressions.py -v
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="clara-regression-")
BASE = Path(TEMP.name)
for key, folder in {"CLARA_DATA_DIR":"data", "CLARA_WORKSPACE":"workspace", "CLARA_STATE_DIR":"state", "HERMES_HOME":"hermes"}.items():
    os.environ[key] = str(BASE/folder)
    (BASE/folder).mkdir()
(BASE/'hermes/.env').write_text('API_SERVER_KEY=isolated-test\n')
sys.path.insert(0, str(ROOT/'bridge'))
import app
import connectors
import video
from store import Store
import httpx
from fastapi import HTTPException

# The Bridge reads its folders when its modules are first imported. If another test module in the same process
# imported them first, these tests would write into the live Clara state (2026-10-03 one left a takeover flag that
# paused Clara's browser). Refuse to run unless everything points into this run's temporary folder.
for _name, _folder in {"state": app.STATE_DIR, "workspace": app.WORKSPACE, "takeover flag": app.TAKEOVER_FILE,
                       "database": Path(app.store.db.execute("PRAGMA database_list").fetchone()[2])}.items():
    if BASE not in Path(_folder).resolve().parents and Path(_folder).resolve() != BASE:
        raise SystemExit(f"Refusing to run: the Bridge's {_name} is {_folder}, outside the test folder {BASE}. "
                         "Run this file in its own process (see the docstring).")

def plugin(name, path):
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

browse = plugin('audit_browse', ROOT/'hermes/plugins/clara-browse/__init__.py')
guardian = plugin('audit_guardian', ROOT/'hermes/plugins/clara-guardian/__init__.py')
interrupt = types.ModuleType('tools.interrupt')
interrupt.is_interrupted = lambda: False
sys.modules['tools.interrupt'] = interrupt
# The plugins reach each other as hermes_plugins.<name>, the way Hermes loads them.
sys.modules['hermes_plugins'] = types.ModuleType('hermes_plugins')
sys.modules['hermes_plugins.clara_guardian'] = guardian

class Stream:
    def __init__(self, status=200, lines=()): self.status=status; self.lines=lines
    def raise_for_status(self): httpx.Response(self.status,request=httpx.Request('GET','https://test.invalid')).raise_for_status()
    async def __aenter__(self): return self
    async def __aexit__(self,*_): pass
    async def aiter_lines(self):
        for line in self.lines: yield line

def response(status, data):
    return httpx.Response(status, json=data, request=httpx.Request('POST','https://test.invalid'))

class LayaSpecTests(unittest.TestCase):
    def test_bridge_asks_exactly_what_laya_was_trained_on(self):
        for name in ('router_spec.py','effort_spec.py','need_spec.py','followup_spec.py','risk_spec.py'):
            self.assertEqual((ROOT/'bridge'/name).read_text(),(ROOT/'laya'/name).read_text(),name)


class PolicyTests(unittest.TestCase):
    def test_submission_gate(self):
        for label in ['Publish','Post','Remove','Save','Continue']:
            self.assertIsNotNone(browse.actions.commit_label({'action':'click','ref':'@e1'},f'- button "{label}" [ref=e1]'))
        self.assertIsNotNone(browse.actions.commit_label({'action':'press','key':'Enter'},''))

    def test_unknown_password_and_otp_refs_fail_closed(self):
        for ref,snapshot in [('@e9',''),('@e1','- textbox "Password" [ref=e1]'),('@e1','- textbox "Verification code" [ref=e1]')]:
            self.assertIsNotNone(browse.actions.veto({'action':'fill','ref':ref,'text':'example'},snapshot))

    def test_long_fill_is_preserved(self):
        text='a'*750
        self.assertEqual(browse.actions.parse_action(json.dumps({'action':'fill','ref':'e1','text':text}))['text'],text)

    def test_alternate_write_paths_require_authorization(self):
        for tool,args in [('browser_click',{'ref':'@e1'}),('terminal',{'command':'curl -X POST https://example.com -d test'}),('terminal',{'command':'python /var/lib/clara/workspace/job.py'}),('execute_code',{'code':'exec("code")'})]:
            self.assertIsNotNone(guardian.rules.decide(tool,args))

    def test_takeover_waits_until_handback_without_a_time_limit(self):
        flag=BASE/'state/takeover'
        for wait in (browse._wait_if_taken_over, guardian._wait_for_handback):
            flag.touch();threading.Timer(.6,lambda:flag.unlink(missing_ok=True)).start()
            with patch.object(guardian,'TAKEOVER',str(flag)):wait()
            self.assertFalse(flag.exists())

    def test_stop_ends_a_takeover_wait(self):
        flag=BASE/'state/takeover';flag.touch()
        try:
            with patch.object(interrupt,'is_interrupted',lambda:True),patch.object(guardian,'TAKEOVER',str(flag)):
                with self.assertRaises(RuntimeError):browse._wait_if_taken_over()
                with self.assertRaises(TimeoutError):guardian._wait_for_handback()
        finally:flag.unlink(missing_ok=True)

    def test_patient_waits_for_the_answer_and_stops_on_stop(self):
        import time as _time
        self.assertEqual(guardian.patient(lambda:(_time.sleep(.6),'once')[1]),'once')
        with self.assertRaises(ValueError):guardian.patient(lambda:(_ for _ in ()).throw(ValueError('x')))
        with patch.object(interrupt,'is_interrupted',lambda:True):
            started=_time.monotonic()
            self.assertIs(guardian.patient(lambda:_time.sleep(5)),guardian.STOPPED)
            self.assertLess(_time.monotonic()-started,2)

    def test_browser_approval_stop(self):
        with patch.object(browse,'_link',side_effect=lambda *a,**k:__import__('time').sleep(5)),patch.object(browse,'_conversation',return_value='c'),\
             patch.object(interrupt,'is_interrupted',lambda:True):
            self.assertIs(browse._ok('click "Submit"','https://example.com/form'),guardian.STOPPED)
        with patch.object(browse,'_link',return_value={'choice':'once'}) as link,patch.object(browse,'_conversation',return_value='c'):
            self.assertIs(browse._ok('click "Submit"','https://example.com/form'),True)
        sent=link.call_args.args[1]
        self.assertEqual((sent['description'],sent['source']),('Clara wants to click "Submit" on example.com','browser'))
        self.assertIsNone(link.call_args.kwargs['timeout'])

    def test_calendar_partial_patch(self):
        data=connectors.event_body(end='2026-10-02T15:00:00-04:00', attendees=[], defaults=False)
        self.assertEqual(data['attendees'],[])
        self.assertEqual(data['end']['dateTime'],'2026-10-02T15:00:00-04:00')
        self.assertNotIn('end',connectors.event_body(start='2026-10-02T13:00:00-04:00',defaults=False))

    def test_pairing_consumed_atomically(self):
        store=Store(str(BASE/'pair.db'));code=store.new_pairing_code();gate=threading.Barrier(2);results=[]
        def redeem():
            gate.wait();results.append(store.redeem_pairing_code(code,'test'))
        threads=[threading.Thread(target=redeem) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(x is not None for x in results),1)
        store.db.close()

    def test_queue_overflow_requests_resync(self):
        bus=app.Bus();q=bus.subscribe()
        for i in range(1001):bus.publish('message.delta',text=str(i))
        self.assertEqual(q.get_nowait()['event'],'resync')
        self.assertEqual(q.get_nowait()['text'],'1000')

    def test_video_finish_uses_unique_scratch(self):
        folders=[];gate=threading.Barrier(2);errors=[]
        def run(args):
            output=Path(args[-1]);output.write_bytes(b'fake-video')
            if output.name=='.part0.mp4':folders.append(output.parent);gate.wait(timeout=3)
        def finish(name):
            try:video.finish([BASE/'input.mp4'],BASE/name,(1280,720))
            except Exception as e:errors.append(e)
        with patch.object(video,'_run',side_effect=run),patch.object(video,'dimensions',return_value=(1280,720)),patch.object(video,'has_audio',return_value=True):
            ts=[threading.Thread(target=finish,args=(n,)) for n in ['one.mp4','two.mp4']]
            for t in ts:t.start()
            for t in ts:t.join()
        self.assertFalse(errors,errors);self.assertEqual(len(set(folders)),2)
        self.assertTrue((BASE/'one.mp4').exists());self.assertTrue((BASE/'two.mp4').exists())

class BrowserRaceTests(unittest.TestCase):
    def setUp(self):
        (BASE/'state/browser-control.lock').touch()
        (BASE/'state/takeover').unlink(missing_ok=True)

    def tearDown(self):
        (BASE/'state/takeover').unlink(missing_ok=True)

    def test_changing_scroll_position_is_progress(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name,value in [('_pin_session',None),('_prepare',None),('_logins',[]),('_shot',None),('_safe_page','https://example.com'),('_browser',{'success':True,'data':{'snapshot':''}}),
                               ('_verify',{'verified':True,'reason':''})]:
                stack.enter_context(patch.object(browse,name,return_value=value))
            stack.enter_context(patch.object(browse,'_progress',side_effect=[1,2,3,4]))
            stack.enter_context(patch.object(browse.time,'sleep'))
            stack.enter_context(patch.object(browse,'_ask',side_effect=['{"action":"scroll"}']*3+['{"action":"done","summary":"Found it"}']))
            dispatch=stack.enter_context(patch.object(browse,'_do',return_value={'success':True}))
            result=browse._drive('Find bottom','','test','chat')
        self.assertTrue(result['success']);self.assertEqual(dispatch.call_count,3)

    def test_done_is_checked_against_the_page(self):
        # Live run 2026-10-02: Bonsai said "PLAY clicked" while the page still said "canvas not clicked".
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name,value in [('_pin_session',None),('_prepare',None),('_logins',[]),('_shot',None),('_safe_page','https://example.com'),('_browser',{'success':True,'data':{'snapshot':'- button "Play" [ref=e1]'}})]:
                stack.enter_context(patch.object(browse,name,return_value=value))
            stack.enter_context(patch.object(browse,'_progress',side_effect=[1,2,3,4]))
            verify=stack.enter_context(patch.object(browse,'_verify',side_effect=[{'verified':False,'reason':'canvas not clicked'},{'verified':True,'reason':'ok'}]))
            ask=stack.enter_context(patch.object(browse,'_ask',side_effect=['{"action":"done","summary":"Clicked PLAY"}','{"action":"click","ref":"@e1"}','{"action":"done","summary":"Clicked PLAY"}']))
            dispatch=stack.enter_context(patch.object(browse,'_do',return_value={'success':True}))
            result=browse._drive('Click play','','test','chat')
        self.assertTrue(result['success']);self.assertEqual(dispatch.call_count,1);self.assertEqual(verify.call_count,2)
        self.assertIn('canvas not clicked',ask.call_args_list[1].args[4])
        self.assertNotIn('unverified',result)

    def test_takeover_during_model_decision_prevents_dispatch(self):
        from contextlib import ExitStack
        def decide(*args):
            (BASE/'state/takeover').write_text('human')
            return '{"action":"scroll"}'
        with ExitStack() as stack:
            for name,value in [('_pin_session',None),('_prepare',None),('_logins',[]),('_shot',None),('_safe_page','https://example.com'),('_browser',{'success':True,'data':{'snapshot':''}}),('_progress',1)]:
                stack.enter_context(patch.object(browse,name,return_value=value))
            stack.enter_context(patch.object(browse,'MAX_STEPS',1))
            stack.enter_context(patch.object(browse,'_ask',side_effect=decide))
            dispatch=stack.enter_context(patch.object(browse,'_do'))
            result=browse._drive('Browse','','test','chat')
        self.assertFalse(result['success']);dispatch.assert_not_called()

    def test_local_current_page_is_blocked(self):
        with patch.object(browse,'_page_url',return_value='http://127.0.0.1:8700'):
            with self.assertRaises(RuntimeError):browse._safe_page('test')
        with patch.object(browse,'_page_url',return_value=''):
            with self.assertRaises(RuntimeError):browse._safe_page('test')

    def test_covered_click_is_not_reported_successful(self):
        results=[{'success':True},{'success':True,'data':{'x':10,'y':10,'width':50,'height':20}}, {'success':True,'data':{'result':False}}]
        with patch.object(browse,'_browser',side_effect=results),patch.object(browse,'_tap_point') as tap:
            self.assertFalse(browse._tap_ref('test','@e1','Send')['success']);tap.assert_not_called()

    def test_blocked_browser_tools_are_hidden_from_the_model(self):
        names=['browser_use','browser_snapshot','browser_vision','browser_click','browser_navigate','browser_type','browser_scroll',
               'browser_press','browser_back','browser_console','browser_cdp','browser_dialog','browser_get_images','web_search','email_search']
        tools=[{'type':'function','function':{'name':n,'parameters':{}}} for n in names]
        out=guardian._hide_blocked_tools({'model':'bonsai','tools':tools})['request']
        kept=[t['function']['name'] for t in out['tools']]
        self.assertEqual(kept,['browser_use','browser_snapshot','browser_vision','web_search','email_search'])
        self.assertEqual(out['model'],'bonsai')
        self.assertIsNone(guardian._hide_blocked_tools({'tools':[t for t in tools if t['function']['name'] in kept]}))  # nothing to hide
        self.assertIsNone(guardian._hide_blocked_tools({'messages':[]}))
        for name in set(names)-set(kept):   # hidden means Guardian refuses it anyway (console: only harmless without a script)
            verdict=guardian.rules.decide(name,{'expression':'1+1'} if name=='browser_console' else {})
            self.assertEqual((verdict or ('',))[0],'block',name)

    def test_helper_lineage_and_cloud_header(self):
        guardian._session_owners['parent']=('chat-a','run-a')
        guardian._on_subagent_start(parent_session_id='parent',child_session_id='child')
        self.assertEqual(guardian.session_owner('child'),('chat-a','run-a'))
        req=guardian._cloud_request({'model':'test'},base_url='http://127.0.0.1:8700/cloud/v1',session_id='child')
        self.assertEqual(req['request']['extra_headers']['x-clara-run-id'],'run-a')
        self.assertIsNone(guardian._cloud_request({},base_url='https://other.invalid',session_id='child'))
        guardian._on_subagent_stop(child_session_id='child')
        self.assertNotIn('child',guardian._session_owners)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old=app.store;app.store=Store(str(BASE/(os.urandom(8).hex()+'.db')))
        self.cid=app.store.create_conversation()['id']
        app._run_tasks.clear();app._stop_requested.clear();app._send_locks.clear();app._pair_attempts.clear()
        app.helper_grants.clear()
        (BASE/'state/takeover').unlink(missing_ok=True)
        (BASE/'state/browser-control.lock').touch()
    async def asyncTearDown(self):
        tasks=list(app._run_tasks.values())
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        app.store.db.close();app.store=self.old

    async def test_upload_collision_and_stream_limit(self):
        class Request:
            def __init__(self,data):self.data=data
            async def stream(self):
                for piece in self.data:yield piece
        first=await app.upload(Request([b'one']),name='photo.jpg',dev={})
        second=await app.upload(Request([b'two']),name='photo.jpg',dev={})
        self.assertNotEqual(first['path'],second['path'])
        self.assertEqual((app.WORKSPACE/first['path']).read_bytes(),b'one')
        before=set((app.WORKSPACE/'uploads').iterdir())
        with patch.object(app,'UPLOAD_MAX',3):
            with self.assertRaises(HTTPException) as error:await app.upload(Request([b'abc',b'd']),name='large',dev={})
        self.assertEqual(error.exception.status_code,413)
        self.assertEqual(before,set((app.WORKSPACE/'uploads').iterdir()))

    async def test_cloud_grants_only_requesting_run(self):
        other=app.store.create_conversation()['id']
        app.store.set_active_run(self.cid,'run-a');app.store.set_active_run(other,'run-b')
        with patch.object(app.store,'api',return_value={'secret':'test'}),patch.object(app,'_ask_cloud',new=AsyncMock(return_value='task')) as ask:
            self.assertIsNone(await app._cloud_allowed('agent','model',self.cid))
            self.assertTrue(app.store.run_granted(['run-a']))
            self.assertFalse(app.store.run_granted(['run-b']))
            await app._cloud_allowed('agent','model',other)
            self.assertEqual(ask.await_count,2)

    async def test_unscoped_cloud_does_not_reuse_any_task_grant(self):
        app.store.set_active_run(self.cid,'run-a');app.store.grant_run('run-a')
        with patch.object(app.store,'api',return_value={'secret':'test'}),patch.object(app,'_ask_cloud',new=AsyncMock(return_value='once')) as ask:
            self.assertIsNone(await app._cloud_allowed('agent','model'))
            self.assertEqual(ask.await_count,1)
            self.assertEqual(ask.call_args.kwargs['choices'],['deny','once','always'])

    async def test_helper_requires_identity_and_uses_correct_conversation(self):
        other=app.store.create_conversation()['id'];app.store.set_active_run(self.cid,'run-a');app.store.set_active_run(other,'run-b')
        self.assertEqual(await app._phone_approval('test','payload','rule'),'deny')
        task=asyncio.create_task(app._phone_approval('test','payload','rule',conversation_id=self.cid))
        await asyncio.sleep(0)
        approval=app.store.approvals('pending')[0]
        self.assertEqual(approval['conversation_id'],self.cid)
        app.helper_approvals[approval['id']].set_result('once')
        self.assertEqual(await task,'once')

    async def test_hermes_500_is_not_success(self):
        client=types.SimpleNamespace(post=AsyncMock(return_value=response(500,{'detail':'test'})))
        with patch.object(app,'hermes',client),patch.object(app,'_job_ids',new=AsyncMock(return_value=set())):
            await app._agent(self.cid,[],'test','task')
        text=app.store.messages(self.cid)[-1]['content']
        self.assertIn("couldn't start",text);self.assertNotEqual(text,'Done.')

    async def test_model_500_and_truncated_stream_are_errors(self):
        for stream in [Stream(500),Stream(200,['data: {"choices":[{"delta":{"content":"partial"}}]}'])]:
            with patch.object(app,'llm',types.SimpleNamespace(stream=lambda *a,**k:stream)):
                await app._chat(self.cid,[],'test')
            self.assertIn("couldn't complete",app.store.messages(self.cid)[-1]['content'])

    async def test_stop_cancels_direct_chat(self):
        class WaitingStream(Stream):
            async def aiter_lines(self):
                await asyncio.Event().wait()
                yield ''
        app.store.set_active_run(self.cid,'starting:test')
        with patch.object(app,'llm',types.SimpleNamespace(stream=lambda *a,**k:WaitingStream())):
            app._launch_run(self.cid,app._chat(self.cid,[],'test'))
            await asyncio.sleep(0)
            await app.stop(self.cid,dev={})
        self.assertNotIn(self.cid,app._run_tasks)
        self.assertIsNone(app.store.get_conversation(self.cid)['active_run'])

    async def test_second_message_rejected_before_persistence(self):
        app.store.set_active_run(self.cid,'run-a')
        with self.assertRaises(HTTPException) as error:
            await app.send_message(self.cid,app.MessageIn(text='second'),dev={})
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(app.store.messages(self.cid),[])

    async def test_old_run_cannot_clear_new_owner(self):
        app.store.set_active_run(self.cid,'new')
        app.store.clear_active_run(self.cid,'old')
        self.assertEqual(app.store.get_conversation(self.cid)['active_run'],'new')

    async def test_brand_names_do_not_collide(self):
        self.assertIsInstance(app._model_brand('anthropic/model'),str)
        self.assertIsInstance(app._brand(),dict)

    async def test_busy_all_day_blocks_free_slots(self):
        events=[{'all_day':True,'busy':True,'start':'2026-10-02','end':'2026-10-03'}]
        with patch.object(connectors,'calendar_events',new=AsyncMock(return_value=events)):
            self.assertEqual(await connectors.free_slots(None,'2026-10-02'),[])
        events[0]['busy']=False
        with patch.object(connectors,'calendar_events',new=AsyncMock(return_value=events)):
            self.assertEqual(len(await connectors.free_slots(None,'2026-10-02')),1)

    async def test_calendar_move_preserves_duration(self):
        current={'all_day':False,'start':'2026-10-02T10:00:00-04:00','end':'2026-10-02T12:00:00-04:00'}
        with patch.object(connectors,'calendar_get',new=AsyncMock(return_value=current)),patch.object(connectors,'api',new=AsyncMock(return_value={'id':'event'})) as call:
            await connectors.calendar_update(None,'event',start='2026-10-02T14:00:00-04:00')
        self.assertEqual(call.call_args.kwargs['json']['end']['dateTime'],'2026-10-02T16:00:00-04:00')

    async def test_failed_video_submits_replacement(self):
        job={'id':'test','name':'test','model':'fake','resolution':'720p','aspect_ratio':'16:9','sound':False,'narration':'', 'shots':[{'prompt':'test','seconds':5}], 'clips':[{'job':'old','status':'failed'}]}
        with patch.object(app.videolib,'submit',new=AsyncMock(return_value={'id':'new'})) as submit,patch.object(app.videolib,'poll',new=AsyncMock(return_value={'status':'failed'})) as poll,patch.object(app,'_save_video_job'),patch.object(app,'_video_progress'):
            with self.assertRaises(RuntimeError):await app._render_clip(job,0,'fake')
        submit.assert_awaited_once();self.assertEqual(poll.call_args.args[1],'new')

    async def test_takeover_ownership(self):
        self.assertTrue(await app._set_takeover(True,'phone-a','A'))
        self.assertFalse(await app._set_takeover(True,'phone-b','B'))
        self.assertFalse(await app._set_takeover(False,'phone-b','B'))
        self.assertEqual(app._takeover_owner(),'phone-a')
        self.assertTrue(await app._set_takeover(False,'phone-a','A'))

    async def test_takeover_waits_for_inflight_action(self):
        held=threading.Event();release=threading.Event()
        def action():
            with browse.action_guard():held.set();release.wait(2)
        worker=asyncio.create_task(asyncio.to_thread(action))
        await asyncio.to_thread(held.wait,1)
        takeover=asyncio.create_task(app._set_takeover(True,'phone','Test'))
        await asyncio.sleep(.02)
        self.assertFalse(takeover.done())
        release.set();await worker
        self.assertTrue(await takeover)
        with self.assertRaises(browse.ControlChanged):
            with browse.action_guard():self.fail('action entered during takeover')
        await app._set_takeover(False,'phone','Test')

    async def test_pairing_rate_limit(self):
        for _ in range(10):
            with self.assertRaises(HTTPException):await app.pair(app.PairIn(code='bad',device_name='test'))
        with self.assertRaises(HTTPException) as error:await app.pair(app.PairIn(code='bad',device_name='test'))
        self.assertEqual(error.exception.status_code,429)

    async def test_stop_during_routing_prevents_launch(self):
        app.store.set_active_run(self.cid,'starting:routing')
        await app.stop(self.cid,dev={})
        invoked=[]
        async def work():invoked.append(True)
        app._launch_run(self.cid,work())
        await asyncio.gather(*list(app._run_tasks.values()),return_exceptions=True)
        self.assertFalse(invoked)
        self.assertIsNone(app.store.get_conversation(self.cid)['active_run'])

    async def test_recovery_skips_live_routing(self):
        app.store.set_active_run(self.cid,'starting:routing')
        async with app._send_locks[self.cid]:
            await app._reconcile_runs()
        self.assertEqual(app.store.get_conversation(self.cid)['active_run'],'starting:routing')

    async def test_late_takeover_grant_is_released_on_cancellation(self):
        held=threading.Event();release=threading.Event()
        def action():
            with browse.action_guard():held.set();release.wait(2)
        worker=asyncio.create_task(asyncio.to_thread(action))
        await asyncio.to_thread(held.wait,1)
        takeover=asyncio.create_task(app._set_takeover(True,'cancelled-phone','Test'))
        await asyncio.sleep(.02);takeover.cancel();release.set();await worker
        with self.assertRaises(asyncio.CancelledError):await takeover
        self.assertIsNone(app._takeover_owner())

    async def test_phone_approval_waits_until_answered_or_stopped(self):
        app.store.set_active_run(self.cid,'run-a')
        task=asyncio.create_task(app._phone_approval('test','payload','rule',conversation_id=self.cid))
        await asyncio.sleep(.05)
        self.assertFalse(task.done())   # no timeout: still waiting on the phone
        with patch.object(app,'hermes',httpx.AsyncClient(base_url='http://hermes',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={})))):
            await app.stop(self.cid,dev=None)
        self.assertEqual(await asyncio.wait_for(task,1),'deny')
        self.assertEqual(app.store.approvals('pending'),[])
        self.assertEqual(app._waiting,{})

    async def test_orphaned_takeover_is_handed_back(self):
        # 2026-10-05: a takeover flag left by an interrupted test paused Clara's browser task indefinitely.
        app._takeover_orphaned_since=None;app._screen_owners.clear();app._screen_devices.clear()
        app.TAKEOVER_FILE.write_text('cancelled-phone')
        try:
            self.assertFalse(await app._check_takeover(now=1000))        # nobody holds it: the grace period starts
            self.assertFalse(await app._check_takeover(now=1000+119))
            self.assertTrue(app.TAKEOVER_FILE.exists())
            self.assertTrue(await app._check_takeover(now=1000+121))     # two minutes later: handed back
            self.assertFalse(app.TAKEOVER_FILE.exists())
            self.assertTrue(app.HANDBACK_FILE.exists())                  # Clara re-observes the page afterwards
            self.assertIn('Handed the browser back',app.store.activity(None,5)[0]['detail'])
        finally:app.TAKEOVER_FILE.unlink(missing_ok=True)

    async def test_held_takeover_waits_however_long(self):
        app._takeover_orphaned_since=None;app._screen_owners.clear();app._screen_devices.clear()
        try:
            app.TAKEOVER_FILE.write_text('socket:phone-1:abc');app._screen_owners.add('socket:phone-1:abc')
            for t in (0,500,5000):self.assertFalse(await app._check_takeover(now=t))   # its socket is open: never cleared
            app._screen_owners.discard('socket:phone-1:abc')                           # the phone went away
            await app._check_takeover(now=6000);self.assertTrue(await app._check_takeover(now=6200))
            app.TAKEOVER_FILE.write_text('device:phone-2');app._screen_devices['phone-2']=1   # a device takeover, its screen open
            for t in (7000,9000):self.assertFalse(await app._check_takeover(now=t))
            app._screen_devices['phone-2']=0
            await app._check_takeover(now=9500);self.assertTrue(await app._check_takeover(now=9700))
        finally:
            app.TAKEOVER_FILE.unlink(missing_ok=True);app._screen_owners.clear();app._screen_devices.clear()

    async def test_warm_up_once_per_restart_and_never_over_a_task(self):
        app._warmed_for=None
        warm=AsyncMock()
        with patch.object(app,'_service_marks',return_value=('100','200')),patch.object(app,'_services_ready',new=AsyncMock(return_value=True)),\
             patch.object(app,'_warm_agent',new=warm):
            self.assertEqual(await app._maybe_warm(),'warmed')
            self.assertEqual(await app._maybe_warm(),'skip')                 # same restart: nothing to do
            self.assertEqual(warm.await_count,1)
        with patch.object(app,'_service_marks',return_value=('100','300')),patch.object(app,'_services_ready',new=AsyncMock(return_value=True)),\
             patch.object(app,'_warm_agent',new=warm):
            app.store.set_active_run(self.cid,'run-real')                     # Hermes restarted while a task runs
            self.assertEqual(await app._maybe_warm(),'busy')
            self.assertEqual(warm.await_count,1)
            app.store.set_active_run(self.cid,None)
        with patch.object(app,'_service_marks',return_value=('400','300')),patch.object(app,'_services_ready',new=AsyncMock(return_value=False)),\
             patch.object(app,'_warm_agent',new=warm):
            self.assertEqual(await app._maybe_warm(),'skip')                 # Bonsai still loading: wait
        self.assertEqual(app.WARMUP_INSTRUCTIONS.count('not a message from the user'),1)

    async def test_browser_steps_land_in_the_activity_log(self):
        app.store.set_active_run(self.cid,'run-b')
        with patch.object(app.bus,'publish') as publish:
            self.assertEqual(await app.internal_activity(app.ActivityIn(conversation_id=self.cid,kind='browser.step',detail='Clicked "Next"'),ok=True),{'ok':True})
        row=app.store.activity(self.cid,1)[0]
        self.assertEqual((row['kind'],row['run_id'],row['detail']),('browser.step','run-b','Clicked "Next"'))
        publish.assert_called_once()
        with self.assertRaises(HTTPException):   # only browser steps: Clara can't write other kinds of entries
            await app.internal_activity(app.ActivityIn(conversation_id=self.cid,kind='approval.approved',detail='x'),ok=True)
        self.assertEqual(await app.internal_activity(app.ActivityIn(conversation_id='nope',kind='browser.step',detail='x'),ok=True),{'ok':False})
        app.store.set_active_run(self.cid,None)

    async def test_digests_come_with_safe_one_tap_actions(self):
        brief=('Morning! Overnight: Sam asked if Thursday works for the review. Vercel says your Pro trial ends Oct 8 '
               'and you will be charged $20. Florida says DEVIGNITE LLC needs reinstatement by Oct 31. Your Chewy order shipped '
               'and arrives Wednesday. Nothing else needs you today.')
        reply='{"actions": ["Draft a reply to Sam saying Thursday works", "Pay the Vercel bill", "Add the Vercel trial end (Oct 8) to my calendar"]}'
        with patch.object(app,'_llm_once',new=AsyncMock(return_value=reply)):
            self.assertEqual(await app._suggest_actions(brief),['Draft a reply to Sam saying Thursday works','Add the Vercel trial end (Oct 8) to my calendar'])
            app.store.set_job_conversation('job-brief',self.cid)
            await app._deliver_cron('job-brief',brief)
        msg=app.store.messages(self.cid)[-1]
        self.assertEqual(msg['route'],'schedule')
        self.assertIn('Draft a reply to Sam saying Thursday works',json.dumps(msg.get('suggestions')))
        with patch.object(app,'_llm_once',new=AsyncMock(return_value=reply)) as llm_call:
            await app._deliver_cron('job-brief','Time to stretch!')   # a short reminder: no buttons, no model call
            llm_call.assert_not_called()
        async def slow(*a,**k): await asyncio.sleep(5); return reply
        with patch.object(app,'_llm_once',new=slow):
            self.assertEqual(await app._suggest_actions(brief,limit=0.05),[])   # too slow: the brief goes out without buttons
        with patch.object(app,'_llm_once',new=AsyncMock(side_effect=RuntimeError('model down'))):
            self.assertEqual(await app._suggest_actions(brief),[])

    async def test_laya_second_opinion_on_clicks(self):
        stub=types.SimpleNamespace(knows_risk=True,risk=unittest.mock.Mock(return_value=('commits',0.93)))
        with patch.object(app,'router',stub):
            out=await app.internal_risk(app.RiskIn(control='button "Done"',site='target.com',page='Order summary'),ok=True)
            self.assertEqual(out,{'risky':True,'p':0.93,'known':True})
            stub.risk.return_value=('commits',0.62)       # unsure: no extra approval
            self.assertFalse((await app.internal_risk(app.RiskIn(control='button "Done"'),ok=True))['risky'])
            stub.risk.side_effect=RuntimeError('model busy')   # any failure: no extra approval
            self.assertEqual((await app.internal_risk(app.RiskIn(control='button "Done"'),ok=True))['known'],False)
        with patch.object(app,'router',types.SimpleNamespace(knows_risk=False)):   # older model: never asked
            self.assertEqual(await app.internal_risk(app.RiskIn(control='button "Done"'),ok=True),{'risky':False,'p':0.0,'known':False})

    def test_browser_adds_but_never_removes_an_approval(self):
        snap='- button "Done" [ref=e1]\n- button "Submit" [ref=e2]'
        with patch.object(browse,'_eval',return_value='Order summary'),patch.object(browse,'_link',return_value={'risky':True,'p':0.9}) as link:
            self.assertEqual(browse._second_opinion('t',{'action':'click','ref':'@e1'},snap,'https://target.com/cart'),'click "Done"')
            sent=link.call_args.args[1]
            self.assertEqual((sent['control'],sent['site'],sent['page']),('button "Done"','target.com','Order summary'))
            self.assertIsNone(browse._second_opinion('t',{'action':'click','ref':'@e2'},snap,'https://x.com'))   # word list asks anyway
        with patch.object(browse,'_eval',return_value=''),patch.object(browse,'_link',side_effect=OSError('bridge down')):
            self.assertIsNone(browse._second_opinion('t',{'action':'click','ref':'@e1'},snap,'https://target.com'))
        with patch.object(browse,'_eval',return_value=''),patch.object(browse,'_link',return_value={'risky':False,'p':0.2}):
            self.assertIsNone(browse._second_opinion('t',{'action':'click','ref':'@e1'},snap,'https://target.com'))

    async def test_stop_tells_every_device_right_away(self):
        app.store.set_active_run(self.cid,'run-a')
        with patch.object(app,'hermes',httpx.AsyncClient(base_url='http://hermes',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={})))),\
             patch.object(app.bus,'publish') as publish:
            await app.stop(self.cid,dev=None)
        publish.assert_any_call('run.stopping',conversation_id=self.cid,run_id='run-a')
        with patch.object(app.bus,'publish') as publish:   # nothing running: nothing to announce
            app.store.set_active_run(self.cid,None);await app.stop(self.cid,dev=None)
        publish.assert_not_called()

    async def test_website_tasks_skip_the_long_think(self):
        # 2026-10-02: "Use your browser to create a Google Group" waited 25-73 s on deep thinking before browser_use.
        laya_stub=types.SimpleNamespace(effort=unittest.mock.Mock(return_value=('deep',0.07)))
        with patch.object(app,'router',laya_stub):
            laya=laya_stub.effort
            for text in ['Use your browser to create a Google Group. Go to groups.google.com.','check the price of AirPods on amazon.com',
                         'open https://example.com and read me the headline','go to the DMV website and find the hours']:
                self.assertEqual(app._pick_effort(self.cid,text,'task','laya'),'quick',text)
            laya.assert_not_called()
            self.assertEqual(app._pick_effort(self.cid,'write a script that scrapes example.com','task','make'),'deep')
            self.assertEqual(app._pick_effort(self.cid,'Use your browser, and think it through step by step','task','laya'),'deep')
            self.assertEqual(app._pick_effort(self.cid,'go to the website again','task','followup'),app._last_effort.get(self.cid,'deep'))
            self.assertEqual(app._pick_effort(self.cid,'plan my week around my goals','task','laya'),'deep')
            self.assertEqual(app._pick_effort(self.cid,'what is on that website','chat','laya'),'chat')

    async def test_laya_browser_need_opens_the_fast_lane(self):
        # No keyword (no "browser", no site name): Laya's need answer alone sends it down the website lane.
        laya_stub=types.SimpleNamespace(effort=unittest.mock.Mock(return_value=('deep',0.07)))
        with patch.object(app,'router',laya_stub):
            self.assertEqual(app._pick_effort(self.cid,'book me a table for two saturday at 7','task','laya','browser',0.91),'quick')
            self.assertEqual(app._pick_effort(self.cid,'book me a table for two saturday at 7','task','laya','browser',0.40),'deep')   # unsure: think
            self.assertEqual(app._pick_effort(self.cid,'book me a table for two saturday at 7','task','laya','search',0.95),'deep')
        self.assertTrue(app._is_browse('book me a table','task','laya','browser',0.9))
        self.assertFalse(app._is_browse('book me a table','task','followup','browser',0.9))

    async def test_laya_decides_followups(self):
        import time as _t
        last={'role':'assistant','route':'task','created':_t.time()-60,'content':"I found the RTX 3090 for $649 used. Want me to watch the price?"}
        history=[{'role':'user','route':'task','created':_t.time()-120,'content':'find a 3090'},last]
        def stub(p): return types.SimpleNamespace(knows_need=True,followup=unittest.mock.Mock(return_value=('continue' if p>0.5 else 'new',p)))
        with patch.object(app,'router',stub(0.93)):
            self.assertTrue(await app._agent_followup(history,'does the used one come with a warranty'))   # the old rules say no
        with patch.object(app,'router',stub(0.08)):
            self.assertFalse(await app._agent_followup(history,'good morning clara'))
            self.assertTrue(await app._agent_followup(history,'yes please'))     # "yes" to her offer always continues
        with patch.object(app,'router',stub(0.99)) as r:
            self.assertFalse(await app._agent_followup(history,'thank you!'))  # thanks never reaches Laya
            r.followup.assert_not_called()
        old=dict(last,created=_t.time()-3600)                                   # an hour ago: not a follow-up at all
        with patch.object(app,'router',stub(0.99)) as r:
            self.assertFalse(await app._agent_followup([history[0],old],'which one'))
            r.followup.assert_not_called()
        with patch.object(app,'router',types.SimpleNamespace(knows_need=False)):   # untrained model: the keyword rules
            self.assertTrue(await app._agent_followup(history,'do it'))
            self.assertFalse(await app._agent_followup(history,'does the used one come with a warranty'))

    async def test_semantic_need_survives_message_dispatch(self):
        decision=types.SimpleNamespace(route='task',source='laya',confidence=.97,ms=10,
                                       effort='deep',effort_conf=.1,need='search',need_conf=.94)
        router=types.SimpleNamespace(route=lambda text:decision,effort=lambda text:('deep',.1),knows_need=False)
        calls=[]
        def capture(cid,coroutine):
            calls.append(dict(coroutine.cr_frame.f_locals))
            coroutine.close()
        with patch.object(app,'router',router),patch.object(app,'_launch_run',side_effect=capture),\
             patch.object(app,'_mentions_connected',return_value=False),\
             patch.object(app,'_connector_view',return_value={'connected':False}):
            result=await app._send_message(self.cid,app.MessageIn(text='look into the recent developments for me'),{})
        self.assertEqual(result['route'],'task')
        self.assertEqual((calls[0]['need'],calls[0]['need_conf']),('search',.94))

    async def test_short_interruptions_keep_context_without_swallowing_new_requests(self):
        import time as _t
        last={'role':'assistant','route':'task','created':_t.time()-60,
              'content':'The reply is drafted. Want me to send it?'}
        router=types.SimpleNamespace(knows_need=True,followup=unittest.mock.Mock(return_value=('new',.02)))
        with patch.object(app,'router',router):
            for text in ('no wait','Wait!','hold on','stop that','not yet','no thanks'):
                self.assertTrue(await app._agent_followup([last],text),text)
            router.followup.assert_not_called()
            self.assertFalse(await app._agent_followup([last],"no wait, what's the weather in Oslo"))
            self.assertFalse(await app._agent_followup([last],'cancel my flight tomorrow'))
            self.assertEqual(router.followup.call_count,2)
            old={**last,'created':_t.time()-3600}
            self.assertFalse(await app._agent_followup([old],'no wait'))

    async def test_agent_uses_confident_need_without_changing_permissions_or_model(self):
        client=types.SimpleNamespace(post=AsyncMock(return_value=response(500,{'detail':'isolated test'})))
        with patch.object(app,'hermes',client),patch.object(app,'_job_ids',new=AsyncMock(return_value=set())),\
             patch.object(app,'_connected',return_value=[]),\
             patch.object(app,'_connector_view',return_value={'connected':False}):
            await app._agent(self.cid,[],'look into this','task',need='search',need_conf=.94)
            payload=client.post.call_args.kwargs['json']
            self.assertIn('available search or retrieval tools',payload['instructions'])
            self.assertIn('preserve existing approval and spending limits',payload['instructions'])
            self.assertNotIn('model',payload)
            for route,need,confidence in [('task','search',.4),('task','unknown',.99),('schedule','search',.99)]:
                await app._agent(self.cid,[],'look into this',route,need=need,need_conf=confidence)
                self.assertNotIn('Task guidance:',client.post.call_args.kwargs['json']['instructions'])
            await app._agent(self.cid,[],'check my agenda','task',need='email_calendar',need_conf=.94)
            instructions=client.post.call_args.kwargs['json']['instructions']
            self.assertIn('If access is missing',instructions)
            self.assertNotIn("Google account is connected",instructions)

    async def test_made_up_inbox_is_held_back_and_checked_again(self):
        # 2026-10-06: after only calendar_events, Bonsai listed an Outlook inbox that doesn't exist.
        made_up=("I can now see your Outlook inbox. Here's what's there:\n\n- **GitHub** - PR #142 waiting on your review (2026-10-05 13:27).\n"
                 "- **LinkedIn** - a DM from Mckenna Combs (2026-10-05 09:15).\n- **weSponsored** - a campaign nudge.")
        real="Your Outlook inbox has 3 emails:\n- Microsoft 365: Weekly digest (Oct 5, 11:49)\n- GoDaddy: New sign-in detected (Oct 1, 12:52)\n- The Wider Lens: tester signup (Oct 1)"
        def run(tool,answer):
            return Stream(200,[f'data: {json.dumps({"event":"tool.started","tool":tool})}',
                               f'data: {json.dumps({"event":"message.delta","delta":answer[:40]})}',
                               f'data: {json.dumps({"event":"run.completed","output":answer})}'])
        for streams,expect in [([run('calendar_events',made_up),run('email_search',real)],real),
                               ([run('calendar_events',made_up),run('calendar_events',made_up)],"won't guess")]:
            posts=[response(200,{'run_id':'r1'}),response(200,{'run_id':'r2'})]
            client=types.SimpleNamespace(post=AsyncMock(side_effect=posts),stream=lambda *a,**k:streams.pop(0))
            published=[]
            with patch.object(app,'hermes',client),patch.object(app,'_job_ids',new=AsyncMock(return_value=set())),\
                 patch.object(app,'_mail_accounts',return_value=['microsoft']),\
                 patch.object(app,'_suggest_actions',new=AsyncMock(return_value=[])),\
                 patch.object(app.bus,'publish',side_effect=lambda event,**kw:published.append(event)):
                await app._agent(self.cid,[],'I connected it can you look again','task',mail=True)
            self.assertIn(expect,app.store.messages(self.cid)[-1]['content'])
            self.assertNotIn('message.delta',published)   # nothing unchecked reached the phone
            self.assertEqual(client.post.await_count,2)
            self.assertIn('answer only from what those tools return',client.post.await_args_list[1].kwargs['json']['instructions'])
            kinds=[a['kind'] for a in app.store.activity(self.cid,50)]
            self.assertIn('grounding.retry',kinds)

    async def test_three_thinking_levels(self):
        cid=app.store.create_conversation()['id']
        with patch.object(app,'router') as router:
            router.effort.return_value=('quick',.95)
            self.assertEqual(app._pick_effort(cid,'how many ounces in a cup','task','laya'),'light')   # Laya's quick: a short think
            router.effort.return_value=('deep',.1)
            self.assertEqual(app._pick_effort(cid,'compare three laptops for video editing','task','laya'),'deep')
        self.assertEqual(app._pick_effort(cid,'remind me at 5','schedule','laya'),'quick')
        self.assertEqual(app._pick_effort(cid,'think it through: plan my week','task','laya'),'deep')
        sent=[]
        class LLM:
            async def post(self,url,json=None,timeout=None):
                sent.append(json);return httpx.Response(200,json={'ok':1})
        with patch.object(app,'llm',LLM()):
            for mode in ('fast','light','deep'):
                req=types.SimpleNamespace(json=AsyncMock(return_value={'messages':[],'reasoning_effort':'high'}))
                await app.bonsai_lighter(mode,req,ok=True)
        self.assertEqual(sent[0]['chat_template_kwargs'],{'enable_thinking':False});self.assertNotIn('thinking_budget_tokens',sent[0])
        self.assertEqual(sent[1]['thinking_budget_tokens'],app.LIGHT_BUDGET);self.assertIn('answer',sent[1]['reasoning_budget_message'])
        self.assertNotIn('reasoning_effort',sent[1])
        self.assertEqual(sent[2]['thinking_budget_tokens'],app.DEEP_BUDGET);self.assertEqual(sent[2]['max_tokens'],app.TURN_MAX['deep'])
        self.assertIn('/bonsai/deep/v1',(ROOT/'hermes/config.yaml.template').read_text())
        self.assertEqual(sent[1]['max_tokens'],app.TURN_MAX['light']);self.assertEqual(sent[0]['max_tokens'],app.TURN_MAX['fast'])   # no runaway replies
        with self.assertRaises(HTTPException):
            await app.bonsai_lighter('turbo',types.SimpleNamespace(json=AsyncMock(return_value={})),ok=True)
        client=types.SimpleNamespace(post=AsyncMock(return_value=response(500,{'detail':'isolated test'})))
        with patch.object(app,'hermes',client),patch.object(app,'_job_ids',new=AsyncMock(return_value=set())):
            for effort,model in (('quick','bonsai-fast'),('light','bonsai-light'),('deep',None)):
                await app._agent(cid,[],'test','task',effort=effort)
                self.assertEqual(client.post.call_args.kwargs['json'].get('model'),model)
        template=(ROOT/'hermes/config.yaml.template').read_text()
        self.assertIn('bonsai-light:',template);self.assertIn('/bonsai/light/v1',template)

    def test_email_padding_is_cleaned(self):
        track='https://click.example.com/email/'+'x'*300
        body=('Sign-In detected \u200c \u200c \u200c\u200b\n\n\n\n[https://img.example.com/logo.png]\nHelp<'+track+'>\n'
              'Device: Chrome  Android\nShort link: https://godaddy.com/help')
        clean=connectors.clean_body(body)
        self.assertNotIn('\u200c',clean);self.assertNotIn('logo.png',clean);self.assertNotIn('x'*50,clean)
        self.assertIn('<link to click.example.com>',clean);self.assertIn('https://godaddy.com/help',clean)
        self.assertIn('Device: Chrome Android',clean);self.assertNotIn('\n\n\n',clean)

    async def test_digests_land_in_the_chat_open_now(self):
        older=app.store.create_conversation()['id'];app.store.set_job_conversation('job-brief',older)
        newer=(await app.new_conversation(dev={'id':'phone'}))['id']   # a new chat tomorrow morning
        with patch.object(app,'_suggest_actions',new=AsyncMock(return_value=[])),patch.object(app.bus,'publish'):
            await app._deliver_cron('job-brief','Good morning, here is your brief.')
            self.assertEqual(app.store.messages(newer)[-1]['content'],'Good morning, here is your brief.')
            self.assertFalse(any(m['content'].startswith('Good morning') for m in app.store.messages(older)))
            await app.conversation_messages(older,dev={'id':'phone'})   # the user goes back to the old chat at noon
            await app._deliver_cron('job-evening','Your 5 PM digest.')
            self.assertEqual(app.store.messages(older)[-1]['content'],'Your 5 PM digest.')
            app._post_proactive('Check-in time',[], {'kind':'checkin'})
            self.assertEqual(app.store.messages(older)[-1]['content'],'Check-in time')
            app.store.delete_conversation(older)   # the open chat was deleted: fall back to the latest one
            await app._deliver_cron('job-x','Reminder')
            self.assertEqual(app.store.messages(app.store.latest_conversation_id())[-1]['content'],'Reminder')

    def test_telling_clara_about_yourself_goes_to_memory(self):
        for text in ['my name is Jorge Maure my address is 3105 Sandhurst road','I\'m a man','call me J','I live in Jacksonville',
                     'my shoe size is 7.5','remember that I like oat milk']:
            self.assertTrue(app.MEMORY_REQUEST.search(text),text)
        for text in ['what is the name of that song','find shoes in my size','a man walks into a bar']:
            self.assertFalse(app.MEMORY_REQUEST.search(text),text)
        self.assertIn('profile',app._NEED_GUIDANCE)

    def test_grounding_only_flags_reports_without_a_look(self):
        listing="Here's what's in your inbox:\n- Sam: lunch Thursday (10:30)\n- Billing: invoice 77 is due Friday, please pay soon\n- GitHub: a review request"
        self.assertEqual(app._ungrounded(listing,{'calendar_events'}),'email')
        self.assertIsNone(app._ungrounded(listing,{'email_search'}))
        self.assertIsNone(app._ungrounded("Outlook isn't connected yet. Open Connectors and add it, then ask me again.",set()))
        cal="Tomorrow you have 2 meetings on your calendar:\n- 10:00 Dentist at Main St Dental\n- 14:00 Team call with the design group, about an hour"
        self.assertEqual(app._ungrounded(cal,set()),'calendar')
        self.assertIsNone(app._ungrounded(cal,{'calendar_events'}))
        # a scheduling task that changed jobs is never re-run (it would find its own new job and misreport it)
        self.assertIsNone(app._ungrounded(listing,{'cronjob'}))
        self.assertIsNone(app._ungrounded(listing,{'email_search','cronjob'}))
        with patch.object(app,'_mail_accounts',return_value=['google']):
            self.assertTrue(app._mail_context('I connected it can you look again',[{'role':'user','content':"what's in my Outlook inbox?"}]))
            self.assertFalse(app._mail_context('what is the capital of France',[{'role':'user','content':'hello'}]))
        with patch.object(app,'_mail_accounts',return_value=[]):
            self.assertFalse(app._mail_context('check my email',[]))

    async def test_help_and_vault_waits_end_on_stop(self):
        app.store.set_active_run(self.cid,'run-a')
        help_task=asyncio.create_task(app.ask_for_help(app.HelpIn(reason='captcha',conversation_id=self.cid),ok=True))
        await asyncio.sleep(.05);self.assertFalse(help_task.done())
        app._release_waits(self.cid)
        self.assertEqual(await asyncio.wait_for(help_task,1),{'result':'stopped'})

    async def test_browser_cards_are_not_labeled_helper(self):
        with patch.object(app,'_phone_approval',new=AsyncMock(return_value='once')) as ask:
            await app.helper_ask(app.HelperAsk(conversation_id=self.cid,description='Clara wants to click "Submit" on example.com',source='browser'),ok=True)
            self.assertEqual(ask.call_args.args[0],'Clara wants to click "Submit" on example.com')
            await app.helper_ask(app.HelperAsk(conversation_id=self.cid,description='write a file'),ok=True)
            self.assertEqual(ask.call_args.args[0],'☁️ Helper: write a file')

    async def test_cloud_retry_joins_the_pending_card(self):
        task1=asyncio.create_task(app._ask_cloud('agent','m',self.cid))
        await asyncio.sleep(0)
        task2=asyncio.create_task(app._ask_cloud('agent','m',self.cid))
        await asyncio.sleep(0)
        self.assertEqual(len(app.cloud_requests),1)
        next(iter(app.cloud_requests.values()))['future'].set_result('task')
        self.assertEqual(await asyncio.wait_for(asyncio.gather(task1,task2),1),['task','task'])

    async def test_stale_helper_cannot_approve_new_run(self):
        app.store.set_active_run(self.cid,'new-run')
        result=await app.helper_ask(app.HelperAsk(conversation_id=self.cid,run_id='old-run',description='write'),ok=True)
        self.assertEqual(result,{'choice':'deny'})

    async def test_calendar_availability_paginates(self):
        def event(key,start,end):return {'id':key,'start':{'dateTime':start},'end':{'dateTime':end}}
        api=AsyncMock(side_effect=[{'items':[], 'nextPageToken':'next'}, {'items':[event('late','2026-10-02T09:00:00+00:00','2026-10-02T18:00:00+00:00')]}])
        with patch.object(connectors,'api',new=api):
            events=await connectors.calendar_events(app.store,all_pages=True)
        self.assertEqual(len(events),1);self.assertEqual(api.await_count,2)

    async def test_video_reservations_count_other_rendering_jobs(self):
        state={'cloud_daily_cap':10,'spent_today':2,'cloud_monthly_cap':None,'spent_month':2}
        job={'id':'existing','status':'rendering','estimate':6,'clips':[{'cost':1}]}
        with patch.object(app,'_cloud_state',return_value=state),patch.object(app,'_video_jobs',return_value={'existing':job}):
            self.assertIsNotNone(app._video_budget_error(4))
            self.assertIsNone(app._video_budget_error(3))
            self.assertIsNotNone(app._video_budget_error(None))

    async def test_normal_browser_close_reconnects_and_cancels_other_pump(self):
        from fastapi import WebSocketDisconnect
        cancelled=asyncio.Event()
        class Phone:
            headers={'authorization':'Bearer test'}
            async def accept(self):pass
            async def send_json(self,data):pass
            async def receive_json(self):
                try:await asyncio.Future()
                finally:cancelled.set()
        class Browser:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            def __aiter__(self):return self
            async def __anext__(self):
                await asyncio.sleep(0)
                raise StopAsyncIteration
        with patch.object(app.store,'device_for_token',return_value={'id':'test','name':'Test'}),patch.object(app.websockets,'connect',side_effect=[Browser(),WebSocketDisconnect()]) as connect:
            await asyncio.wait_for(app.screen_stream(Phone()),1)
        self.assertTrue(cancelled.is_set());self.assertEqual(connect.call_count,2)

    async def test_immediate_direct_stop_cleans_task_marker(self):
        app.store.set_active_run(self.cid,'starting:test')
        async def _chat():await asyncio.Future()
        app._launch_run(self.cid,_chat())
        await app.stop(self.cid,dev={})
        await asyncio.sleep(0)
        self.assertNotIn(self.cid,app._run_tasks)
        self.assertIsNone(app.store.get_conversation(self.cid)['active_run'])

    async def test_browser_approval_cannot_grant_session(self):
        app.store.set_active_run(self.cid,'run-a')
        with patch.object(app,'_phone_approval',new=AsyncMock(return_value='once')) as ask:
            await app.helper_ask(app.HelperAsk(conversation_id=self.cid,description='Submit',allow_session=False),ok=True)
        self.assertEqual(ask.call_args.kwargs['choices'],('once','deny'))


class JobsProxyTests(unittest.IsolatedAsyncioTestCase):
    async def jobs(self,handler):
        client=httpx.AsyncClient(base_url='http://hermes',transport=httpx.MockTransport(handler))
        with patch.object(app,'hermes',client):
            return await app.upcoming(dev=None)

    async def test_hermes_down_is_503_not_500(self):
        def down(request):raise httpx.ConnectError('All connection attempts failed',request=request)
        with self.assertRaises(HTTPException) as e:await self.jobs(down)
        self.assertEqual(e.exception.status_code,503)

    async def test_hermes_error_is_passed_on(self):
        with self.assertRaises(HTTPException) as e:await self.jobs(lambda r:httpx.Response(500,text='boom'))
        self.assertEqual(e.exception.status_code,502)
        with self.assertRaises(HTTPException) as e:await self.jobs(lambda r:httpx.Response(404,text='no job'))
        self.assertEqual(e.exception.status_code,404)

    async def test_jobs_listed(self):
        self.assertEqual(await self.jobs(lambda r:httpx.Response(200,json={'jobs':[]})),{'jobs':[]})

if __name__=='__main__':unittest.main()
