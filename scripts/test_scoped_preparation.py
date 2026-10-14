"""Authorization boundaries and recoverability, without Minecraft or frame capture."""
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from unittest.mock import Mock

import benchmark
from auto_prepare_protocol import SCHEMA,LIFETIME_NS,DIAGNOSTIC_LIFETIME_NS,validate_request,validate_auto_arm,write_ticket
from capture_auto_protocol import SCHEMA as CAPTURE_SCHEMA,WINDOW_SCHEMA,validate_capture_request,validate_window
from experiment_protocol import digest
from instrumentation_migration import plan,apply
from session_protocol import OWNER
from room_route_protocol import WORKLOAD,ROOM_POLICY
from session_protocol import paths_for,publish,read_json


class Requests(unittest.TestCase):
    def setUp(self):
        self.profile=Path(tempfile.gettempdir())/'fixture-profile'
        self.conditions={'world_folder':'Lab_fixture'};self.manifest={'pinned':'hash'}
        self.now=time.time_ns()
        self.request={'schema':SCHEMA,'mode':'functional_only','benchmark_accepted':False,
            'nonce':'a'*32,'profile':str(self.profile.resolve()),'world_folder':'Lab_fixture',
            'repeats':1,'created_unix_ns':self.now,'expires_unix_ns':self.now+LIFETIME_NS,
            'manifest_sha256':digest(self.manifest)}

    def check(self,value):return validate_request(value,self.profile,self.conditions,self.manifest,self.now)

    def test_valid_exact_request(self):self.check(self.request)

    def test_background_startup_has_fixed_bound_without_extending_normal_permission(self):
        value={**self.request,'diagnostic_only':True,'expires_unix_ns':self.now+DIAGNOSTIC_LIFETIME_NS}
        validate_request(value,self.profile,self.conditions,self.manifest,self.now+LIFETIME_NS)
        for changed in ({**value,'diagnostic_only':False},{**value,'expires_unix_ns':value['expires_unix_ns']+1}):
            with self.assertRaises(ValueError):self.check(changed)
        with self.assertRaises(ValueError):
            validate_request(value,self.profile,self.conditions,self.manifest,value['expires_unix_ns'])

    def test_expired_future_and_overlong_requests_rejected(self):
        for created,expires in ((self.now-LIFETIME_NS,self.now),(self.now+1,self.now+LIFETIME_NS+1),(self.now,self.now+LIFETIME_NS+1)):
            value={**self.request,'created_unix_ns':created,'expires_unix_ns':expires}
            with self.assertRaises(ValueError):self.check(value)

    def test_wrong_profile_world_manifest_rejected(self):
        for key,value in (('profile','elsewhere'),('world_folder','Lab_other'),('manifest_sha256','0'*64)):
            with self.assertRaises(ValueError):self.check({**self.request,key:value})

    def test_measurement_acceptance_and_extra_repeats_rejected(self):
        for key,value in (('mode','frame_capture'),('benchmark_accepted',True),('repeats',3),('nonce','../file')):
            with self.assertRaises(ValueError):self.check({**self.request,key:value})
        with self.assertRaises(ValueError):self.check({**self.request,'quit_after':True})

    def test_arm_requires_matching_request_and_manifest(self):
        arm={'owner':OWNER,'nonce':'b'*32,'game_pid':42,'benchmark_accepted':False,'repeats':1,
             'auto_prepare_mode':'functional_only','auto_prepare_nonce':'a'*32,
             'experiment':{'manifest_sha256':self.request['manifest_sha256']}}
        validate_auto_arm(arm,self.request)
        for key,value in (('auto_prepare_nonce','c'*32),('auto_prepare_mode','frame_capture'),('repeats',3)):
            with self.assertRaises(ValueError):validate_auto_arm({**arm,key:value},self.request)

    def test_mutable_request_slot_can_be_invalidated_without_overwriting_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'auto-prepare-request.json';write_ticket(path,self.request)
            write_ticket(path,{**self.request,'expires_unix_ns':0})
            self.assertEqual(json.loads(path.read_text())['expires_unix_ns'],0)
            self.assertFalse(list(Path(temp).glob('*.tmp')))
            with self.assertRaises(ValueError):write_ticket(path.with_name('claim.json'),self.request)

    def test_measured_permission_cannot_be_used_as_functional_permission(self):
        measured={**self.request,'schema':CAPTURE_SCHEMA,'mode':'functional_frame_capture','repeats':3,'measurement_window_nonce':'d'*32}
        manifest={'workload':WORKLOAD,'analysis_policy':ROOM_POLICY,'batch_protocol':'full-route-only-v1'}
        measured['manifest_sha256']=digest(manifest)
        validate_capture_request(measured,self.profile,self.conditions,manifest,self.now)
        with self.assertRaises(ValueError):validate_request(measured,self.profile,self.conditions,manifest,self.now)
        with self.assertRaises(ValueError):validate_capture_request(self.request,self.profile,self.conditions,self.manifest,self.now)
        for change in ({'repeats':1},{'measurement_window_nonce':'../wrong'},{'manifest_sha256':'0'*64}):
            with self.assertRaises(ValueError):validate_capture_request({**measured,**change},self.profile,self.conditions,manifest,self.now)

    def test_single_capture_is_diagnostic_and_uses_the_same_fixed_startup_bound(self):
        manifest={'workload':WORKLOAD,'analysis_policy':ROOM_POLICY,'batch_protocol':'full-route-only-v1'}
        value={**self.request,'schema':CAPTURE_SCHEMA,'mode':'functional_frame_capture','repeats':1,
               'measurement_window_nonce':'d'*32,'diagnostic_only':True,
               'expires_unix_ns':self.now+DIAGNOSTIC_LIFETIME_NS,'manifest_sha256':digest(manifest)}
        validate_capture_request(value,self.profile,self.conditions,manifest,self.now+LIFETIME_NS)
        for change in ({'diagnostic_only':False},{'expires_unix_ns':self.now+DIAGNOSTIC_LIFETIME_NS+1}):
            with self.assertRaises(ValueError):
                validate_capture_request({**value,**change},self.profile,self.conditions,manifest,self.now)

    def test_window_requires_current_profile_config_and_unexpired_explicit_clearance(self):
        with tempfile.TemporaryDirectory() as temp:
            from experiment_protocol import file_hash
            config=Path(temp)/'config.json';config.write_text('{}')
            settings=SimpleNamespace(profile=self.profile,config_path=config)
            window={'schema':WINDOW_SCHEMA,'status':'cleared','nonce':'d'*32,'profile':str(self.profile.resolve()),
                    'config_sha256':file_hash(config),'created_unix_ns':self.now,'expires_unix_ns':self.now+30*60*10**9}
            validate_window(window,settings,self.now)
            for change in ({'status':'paused'},{'expires_unix_ns':self.now},{'expires_unix_ns':self.now+31*60*10**9},{'config_sha256':'0'*64}):
                with self.assertRaises(ValueError):validate_window({**window,**change},settings,self.now)

    def test_absent_window_or_broker_refuses_before_dispatch_or_launch(self):
        import auto_measured_session
        settings=SimpleNamespace(outputs=self.profile/'outputs')
        for failure in ('window','broker'):
            with patch.object(auto_measured_session,'configured_kernel'),patch.object(auto_measured_session,'dispatch') as dispatch, \
                 patch.object(auto_measured_session,'check_window',side_effect=ValueError('window absent') if failure=='window' else None), \
                 patch.object(auto_measured_session,'check_broker_ready',side_effect=RuntimeError('broker absent')):
                settings.profile=self.profile;settings.config_path=Path('unused')
                with self.assertRaises((ValueError,RuntimeError)):auto_measured_session.main(settings,'d'*32,3)
                dispatch.assert_not_called()

    def test_measured_handshake_uses_matching_broker_claim_and_existing_go_file(self):
        import auto_measured_session
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);profile=root/'profile';lab=profile/'minescript/lab-results';lab.mkdir(parents=True)
            broker=root/'outputs/capture-broker';broker.mkdir(parents=True)
            settings=SimpleNamespace(profile=profile,outputs=root/'outputs',config_path=root/'config.json')
            arm={'owner':OWNER,'nonce':'b'*32,'game_pid':42,'benchmark_accepted':False}
            files=paths_for(lab,arm['nonce'])
            claim={**arm,'mode':'functional_frame_capture','controller_pid':777}
            publish(files['claim'],claim)
            monitor=Mock();monitor.sample.return_value={'ac_connected':True,'original_game_alive':True,'minecraft_foreground':True}
            def fake_dispatch(settings,request_factory,consume,precheck):
                precheck();return consume(arm,files,request_factory({'nonce':'a'*32}))
            def fake_publish(path,value):
                publish(path,value)
                if path==files['confirm']:
                    request=next(broker.glob('request-*.json'))
                    publish(request.with_name(request.stem.replace('request-','result-')+'.json'),
                        {'status':'finished','nonce':arm['nonce'],'broker_pid':777,'capture_exit_code':0})
            with patch.object(auto_measured_session,'configured_kernel'),patch.object(auto_measured_session,'check_window'), \
                 patch.object(auto_measured_session,'check_broker_ready',return_value={'pid':777}), \
                 patch.object(auto_measured_session,'dispatch',side_effect=fake_dispatch), \
                 patch.object(auto_measured_session,'publish',side_effect=fake_publish), \
                 patch('capture_headless.Monitor',return_value=monitor):
                self.assertEqual(auto_measured_session.main(settings,'d'*32,3),0)
            self.assertEqual(read_json(files['confirm'])['nonce'],arm['nonce'])
            sent=read_json(next(broker.glob('request-*.json')))
            self.assertFalse(sent['resources']);self.assertFalse(sent['overhead'])
            self.assertEqual(sent['auto_prepare_nonce'],'a'*32)
            monitor.close.assert_called_once()
            # A foreign/stale broker claim cannot produce confirmation.
            files['confirm'].unlink()
            claim['controller_pid']=999;files['claim'].write_text(json.dumps(claim))
            # The second source-only check uses a fresh submission (original evidence retained).
            with patch.object(auto_measured_session,'configured_kernel'),patch.object(auto_measured_session,'check_window'), \
                 patch.object(auto_measured_session,'check_broker_ready',return_value={'pid':777}), \
                 patch.object(auto_measured_session,'dispatch',side_effect=fake_dispatch):
                with self.assertRaisesRegex(ValueError,'matching approved broker'):auto_measured_session.main(settings,'d'*32,3)
            self.assertFalse(files['confirm'].exists())


class Migration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.settings=SimpleNamespace(profile=root/'profile',state=root/'state',data={'world_names':['RestWorld_26.1']},world_folder='Lab_fixture')
        self.directory=self.settings.profile/'minescript';self.directory.mkdir(parents=True)
        (self.directory/'owned.py').write_bytes(b'old\n')
        self.payload={'owned.py':b'new\n','new.py':b'created\n'}
        self.mocks=[patch('manage_experiment.closed'),patch('benchmark.check'),patch('benchmark.setup_payload',return_value=self.payload)]
        for item in self.mocks:item.start()

    def tearDown(self):
        for item in reversed(self.mocks):item.stop()
        self.temp.cleanup()

    def receipt(self):return Path(plan(self.settings)['plan'])

    def test_apply_preserves_previous_bytes_and_unrelated_files(self):
        unrelated=self.directory/'human.py';unrelated.write_bytes(b'human\n')
        receipt=self.receipt();result=apply(self.settings,receipt)
        self.assertEqual(result['status'],'applied')
        self.assertEqual((receipt.parent/'before/owned.py').read_bytes(),b'old\n')
        self.assertEqual(unrelated.read_bytes(),b'human\n')
        self.assertEqual((self.directory/'owned.py').read_bytes(),b'new\n')
        with self.assertRaises(ValueError):apply(self.settings,receipt)

    def test_stale_target_refused_before_any_write(self):
        receipt=self.receipt();(self.directory/'owned.py').write_bytes(b'later\n')
        with self.assertRaises(ValueError):apply(self.settings,receipt)
        self.assertFalse((self.directory/'new.py').exists())
        self.assertEqual((self.directory/'owned.py').read_bytes(),b'later\n')

    def test_changed_source_or_backup_refused(self):
        for target in ('before/owned.py','after/owned.py'):
            receipt=self.receipt();(receipt.parent/target).write_bytes(b'damaged\n')
            with self.assertRaises(ValueError):apply(self.settings,receipt)
            self.assertEqual((self.directory/'owned.py').read_bytes(),b'old\n')

    def test_post_install_failure_rolls_back_owned_bytes(self):
        receipt=self.receipt()
        def fail_after_install(settings,installed=False):
            if installed:raise RuntimeError('fixture check failed')
        with patch('benchmark.check',side_effect=fail_after_install):
            with self.assertRaises(RuntimeError):apply(self.settings,receipt)
        self.assertEqual((self.directory/'owned.py').read_bytes(),b'old\n')
        self.assertFalse((self.directory/'new.py').exists())
        self.assertEqual(json.loads(receipt.read_text())['status'],'rolled_back')

    def test_matching_or_wildcard_existing_autorun_is_not_silently_overwritten(self):
        for text in ('autorun[*]=human\n','autorun[RestWorld_26.1]=human\n'):
            (self.directory/'config.txt').write_text(text)
            # Use the real renderer rather than the test payload mock.
            with patch('benchmark.setup_payload',new=REAL_PAYLOAD):
                with self.assertRaises(ValueError):REAL_PAYLOAD(self.settings)


REAL_PAYLOAD=benchmark.setup_payload


if __name__=='__main__':unittest.main()
