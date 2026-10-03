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
        for name in ('router_spec.py','effort_spec.py','need_spec.py','followup_spec.py'):
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
