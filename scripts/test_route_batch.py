"""Route-only synthetic acceptance/rejection checks; never laptop FPS evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from analyze_benchmark import score_suite, compare
from capture_headless import stop_owned_trace, verify_route_capture, run as capture_run
from capture_session import Phase, sampling_order
from experiment_protocol import digest
from room_route_protocol import WORKLOAD, ROOM_POLICY
from session_protocol import OWNER, LEGACY_BATCH, ROUTE_BATCH, batch_protocol, schedule, publish
from test_benchmark_end_to_end import make_suite
from test_rooms_route import route


def make_route_suite(root):
    make_suite(root)
    arm=json.loads((root/'session-arm.json').read_text())
    arm.update(movement_workload=WORKLOAD,batch_protocol=ROUTE_BATCH)
    manifest=arm['experiment']['manifest']
    manifest.update(workload=WORKLOAD,analysis_policy=ROOM_POLICY,batch_protocol=ROUTE_BATCH)
    arm['experiment']['manifest_sha256']=digest(manifest)
    (root/'session-arm.json').write_text(json.dumps(arm))
    old=[json.loads(line) for line in (root/'game-samples.jsonl').read_text().splitlines()]
    report=json.loads((root/'session-result.json').read_text())
    identity={k:arm[k] for k in ('owner','nonce','game_pid','benchmark_accepted')}
    events=[];phases=[]
    for index,previous in enumerate((1,3,5)):
        base=1_000_000_000+previous*150_000_000
        warm=route(base-39_000_000,1_000_000)
        scored=route(base+100_000,1_000_000)
        events += [{'event':'unscored_route_start','phase':index,'pass':1,'qpc':base-40_000_000},
                   *warm,{'event':'unscored_route_complete','phase':index,'pass':1,'qpc':base-1_000_000},*scored]
        for event in old:
            if event.get('phase')==previous and event['event'] in ('phase_context','action_start'):
                value=copy.deepcopy(event);value['phase']=index
                if value['event']=='phase_context':value['experiment']=arm['experiment']
                events.append(value)
        phase={**identity,'phase':index,'scenario':'movement','run_directory':str(previous),'resources_enabled':False}
        phases.append(phase)
        folder=root/'runs'/str(previous)
        capture=json.loads((folder/'result.json').read_text())
        capture.update(capture_policy='verified-route-completion-plus-two-second-drain-v1',
                       cli_exit_code=0,owned_session_stop_exit_code=0,maximum_capture_seconds=180,
                       route_completion={**identity,'phase':index,'scenario':'movement','status':'action_verified',
                                         'completed_qpc':scored[-1]['qpc']+100,'qpc_frequency':1_000_000})
        (folder/'result.json').write_text(json.dumps(capture))
    events.sort(key=lambda e:e['qpc'])
    (root/'game-samples.jsonl').write_text(''.join(json.dumps({'nonce':arm['nonce'],'benchmark_accepted':False,'qpc_frequency':1_000_000,**e})+'\n' for e in events))
    report['phases']=phases
    (root/'session-result.json').write_text(json.dumps(report))
    done=json.loads((root/'game-done.json').read_text());done['completed_phases']=3
    (root/'game-done.json').write_text(json.dumps(done))


class RouteBatch(unittest.TestCase):
    def test_live_capture_loop_drains_owned_trace_after_verified_action(self):
        # Fake the external processes/clock, exercising the actual controller loop.
        # No ETW, game or administrative process is launched by this fixture.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tool=root/'tool.exe';tool.write_bytes(b'fixture')
            clock={'seconds':0.,'stopped':False}
            sample={'ac_connected':True,'minecraft_foreground':True,'original_game_alive':True}
            monitor=SimpleNamespace(lock=lambda:None,sample=lambda:dict(sample),close=lambda:None)
            child=SimpleNamespace(returncode=0,poll=lambda:0 if clock['stopped'] else None)
            def start(command,**kwargs):
                frames='Application,ProcessID,SwapChainAddress,Runtime,TimeInSeconds,msBetweenPresents,QPCTime\n'
                frames+=''.join(f'javaw.exe,123,0x1,Other,{i/100},{0 if i==0 else 10},{1_000_000+i*10_000}\n' for i in range(201))
                kwargs['stdout'].write(frames.encode());kwargs['stdout'].flush()
                return child
            def stop(*args):clock['stopped']=True;return 0
            action={'completed_qpc':2_000_000,'qpc_frequency':1_000_000}
            pair=SimpleNamespace(end_on_action=True,requires_frame_stream_ready=True,
                                 prepare=lambda game,folder,report:None,start=lambda:None,
                                 capture_start=lambda:None,health=lambda:None,stop=lambda:None,
                                 capture_complete=lambda:action)
            args=SimpleNamespace(duration=180,warmup=0,profile=root,results=root/'results',presentmon=tool,
                                 expected_sha256=hashlib.sha256(tool.read_bytes()).hexdigest(),check_only=False)
            with patch('capture_headless.C.WinDLL',return_value=SimpleNamespace(IsUserAnAdmin=Mock(return_value=True)),create=True), \
                 patch('capture_headless.subprocess.CREATE_NO_WINDOW',0,create=True), \
                 patch('capture_headless.process_inventory',return_value={'games':[{'pid':123}],'other_capture_pids':[],'chrome_process_count':0,'service_running':True}), \
                 patch('capture_headless.Monitor',return_value=monitor),patch('capture_headless.subprocess.Popen',side_effect=start), \
                 patch('capture_headless.stop_owned_trace',side_effect=stop) as stopped, \
                 patch('capture_headless.time.monotonic',side_effect=lambda:clock['seconds']), \
                 patch('capture_headless.time.sleep',side_effect=lambda seconds:clock.update(seconds=clock['seconds']+seconds)):
                self.assertEqual(capture_run(args,pair),0)
                stopped.assert_called_once()
            result=json.loads(next((root/'results').glob('*/result.json')).read_text())
            self.assertEqual(result['status'],'tool_check_passed')
            self.assertEqual(result['duration_seconds'],2.)
            self.assertEqual(result['route_completion'],action)

    def test_full_route_schedule_and_legacy_are_distinct(self):
        self.assertEqual(schedule(3,ROUTE_BATCH),('movement',)*3)
        self.assertEqual(schedule(5,ROUTE_BATCH),('movement',)*5)
        self.assertEqual(schedule(3),('stationary','movement')*3)
        with self.assertRaises(RuntimeError):schedule(6,ROUTE_BATCH)
        with self.assertRaises(RuntimeError):schedule(3,'unknown')
        with self.assertRaises(RuntimeError):batch_protocol({'batch_protocol':ROUTE_BATCH,'workload':'mob_display_loop_v2'})
        with self.assertRaises(ValueError):sampling_order({'batch_protocol':ROUTE_BATCH,'movement_workload':WORKLOAD,'repeats':4},SimpleNamespace(resource_overhead=True,no_resources=False))

    def test_success_with_next_repeat_warmup_outside_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);make_route_suite(root);result=score_suite(root)
            self.assertEqual(result['status'],'measurement_valid')
            self.assertFalse(result['benchmark_accepted'])
            self.assertEqual(len(result['repeats']),3)
            self.assertEqual([r['phase'] for r in result['repeats']],[0,1,2])
            self.assertEqual(len(result['repeats'][0]['sections']),3)
            self.assertAlmostEqual(result['repeats'][0]['fixed_weight_presented_fps'],100)

    def test_missing_warmup_wrong_completion_and_unclean_stop_rejected(self):
        for change in ('warmup','clock','stop','early','mode'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);make_route_suite(root)
                path=root/'runs/1/result.json';capture=json.loads(path.read_text())
                if change=='clock':capture['route_completion']['qpc_frequency']=123
                elif change=='stop':capture['owned_session_stop_exit_code']=7
                elif change=='early':capture['route_completion']['completed_qpc']=1
                elif change=='mode':
                    arm=json.loads((root/'session-arm.json').read_text());arm['batch_protocol']=LEGACY_BATCH
                    (root/'session-arm.json').write_text(json.dumps(arm))
                else:
                    rows=[json.loads(line) for line in (root/'game-samples.jsonl').read_text().splitlines()]
                    rows=[e for e in rows if not(e['event']=='unscored_route_complete' and e['phase']==1)]
                    (root/'game-samples.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in rows))
                path.write_text(json.dumps(capture))
                with self.assertRaises((ValueError,RuntimeError)):score_suite(root)

    def test_complete_frame_after_action_is_required_even_with_valid_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);make_route_suite(root)
            action={'completed_qpc':10**15}
            with self.assertRaisesRegex(ValueError,'after route completion'):
                verify_route_capture(root/'runs/1/frames.csv',action)

    def test_trace_stop_never_targets_other_sessions_or_ignores_failure(self):
        with patch('capture_headless.subprocess.run',return_value=SimpleNamespace(returncode=0)) as run, \
             patch('capture_headless.subprocess.CREATE_NO_WINDOW',0,create=True):
            with self.assertRaises(RuntimeError):stop_owned_trace(Path('tool.exe'),'PresentMon')
            run.assert_not_called()
            self.assertEqual(stop_owned_trace(Path('tool.exe'),'Modpack_'+'a'*32),0)
            self.assertEqual(run.call_args.args[0],['tool.exe','--terminate_existing_session','--session_name','Modpack_'+'a'*32])
            run.return_value.returncode=7
            with self.assertRaises(RuntimeError):stop_owned_trace(Path('tool.exe'),'Modpack_'+'b'*32)

    def test_phase_completion_requires_owned_verified_action_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);nonce='a'*32
            arm={'owner':OWNER,'nonce':nonce,'game_pid':123,'movement_workload':WORKLOAD,'batch_protocol':ROUTE_BATCH}
            session=SimpleNamespace(arm=arm,directory=directory,identity={**arm,'benchmark_accepted':False})
            phase=Phase(session,0,'movement')
            self.assertIsNone(phase.capture_complete())
            action={**session.identity,'phase':0,'scenario':'movement','status':'action_verified','completed_qpc':1,'qpc_frequency':1000}
            publish(phase.files['action'],action)
            self.assertEqual(phase.capture_complete(),action)
            phase.files['action'].write_text(json.dumps({**action,'nonce':'b'*32}))
            with self.assertRaises(RuntimeError):phase.capture_complete()

    def test_old_and_new_batch_comparisons_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);make_route_suite(root);control=score_suite(root);candidate=copy.deepcopy(control)
            candidate['experiment']['manifest'].update(batch_protocol=LEGACY_BATCH,role='candidate',configuration_id='candidate')
            candidate['experiment']['manifest_sha256']=digest(candidate['experiment']['manifest'])
            with self.assertRaisesRegex(ValueError,'batch protocol'):compare(control,candidate,control)


if __name__=='__main__':unittest.main()
