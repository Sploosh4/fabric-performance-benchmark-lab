"""Tiny offline fixtures: no real profiles, elevation, downloads or game launches."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import zipfile

from experiment_protocol import file_hash
from lab_settings import load
import world_restore
from capture_headless import enforce_output_limit
import benchmark
import hashlib
import importlib
import os
import shutil


class PortablePreparation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.saves=self.root/'profile/saves';self.saves.mkdir(parents=True)
        self.world=self.saves/'Lab_fixture';self.world.mkdir();(self.world/'level.dat').write_bytes(b'valuable-old-world')
        self.archive=self.root/'master.zip';self.recovery=self.root/'state/recovery'
        self.make_archive({'RestWorld/level.dat':b'new-world','RestWorld/session.lock':b'lock'})
        self.closed=Mock()

    def make_archive(self,entries):
        with zipfile.ZipFile(self.archive,'w') as package:
            for name,data in entries.items():package.writestr(name,data)

    def restore(self,**kwargs):
        return world_restore.restore(self.archive,self.world,self.recovery,file_hash(self.archive),self.closed,**kwargs)

    def assert_old(self):
        self.assertEqual((self.world/'level.dat').read_bytes(),b'valuable-old-world')
        self.assertFalse(list(self.saves.glob('.fabric-bench-restore-*')))

    def test_success_preserves_original_and_excludes_lock_without_deleting_history(self):
        result=self.restore()
        self.assertEqual((self.world/'level.dat').read_bytes(),b'new-world')
        self.assertFalse((self.world/'session.lock').exists())
        self.assertEqual((Path(result['preserved_save'])/'level.dat').read_bytes(),b'valuable-old-world')
        self.restore()
        self.assertEqual(len(list(self.recovery.glob('recovery-*.json'))),2)
        self.assertFalse(list(self.saves.glob('.fabric-bench-restore-*')))

    def test_closed_gate_hash_and_archive_traversal_fail_before_replacing_world(self):
        self.closed.side_effect=RuntimeError('client running')
        with self.assertRaises(RuntimeError):self.restore()
        self.closed.side_effect=None
        with self.assertRaises(ValueError):world_restore.restore(self.archive,self.world,self.recovery,'a'*64,self.closed)
        self.make_archive({'Root/level.dat':b'new','Root/../../escape':b'unsafe'})
        with self.assertRaises(ValueError):self.restore()
        self.assert_old();self.assertFalse((self.root/'escape').exists())

    def test_duplicate_case_archive_and_overlapping_recovery_rejected(self):
        self.make_archive({'Root/level.dat':b'new','Root/LEVEL.DAT':b'collision'})
        with self.assertRaises(ValueError):self.restore()
        with self.assertRaises(ValueError):world_restore.restore(self.archive,self.world,self.saves,file_hash(self.archive),self.closed)
        self.assert_old()

    def test_failed_stage_cleaned_by_default_and_retained_only_with_opt_in(self):
        # File/directory collision fails halfway through extraction.
        self.make_archive({'Root/level.dat':b'new','Root/node':b'file','Root/node/child':b'impossible'})
        with self.assertRaises(OSError):self.restore()
        self.assert_old();self.assertFalse(list(self.recovery.glob('failed-stage-*')))
        with self.assertRaises(OSError):self.restore(retain_failed_stage=True)
        self.assert_old();self.assertEqual(len(list(self.recovery.glob('failed-stage-*'))),1)

    def test_install_failure_rolls_original_back_and_cleans_stage(self):
        original=world_restore.rename
        def fail_install(source,destination):
            if source.name=='world':raise OSError('fixture install failure')
            original(source,destination)
        with patch.object(world_restore,'rename',side_effect=fail_install):
            with self.assertRaises(OSError):self.restore()
        self.assert_old()

    def test_second_closed_gate_preserves_original(self):
        self.closed.side_effect=[None,RuntimeError('client started during extraction')]
        with self.assertRaises(RuntimeError):self.restore()
        self.assert_old()

    def test_explicit_prune_leaves_unreceipted_history_and_one_recent_copy(self):
        self.restore()
        unknown=self.recovery/'historical-copy';unknown.mkdir();(unknown/'level.dat').write_bytes(b'unknown-world')
        result=self.restore(prune_owned=True)
        self.assertEqual(len(result['removed_owned_recovery_copies']),1)
        self.assertEqual((unknown/'level.dat').read_bytes(),b'unknown-world')
        self.assertEqual(len(list(self.recovery.glob('recovery-*.json'))),1)

    def config(self,**change):
        data={'schema':'fabric-performance-benchmark-config-v1','minecraft':'26.1.2','loader':'fabric',
              'fabric_loader':'0.19.5','profile':'profile','world_archive':'master.zip','world_folder':'Lab_fixture',
              'world_archive_sha256':file_hash(self.archive),'outputs':'outputs','state':'state','presentmon':'tool.exe'}
        data.update(change);path=self.root/'benchmark.local.json';path.write_text(json.dumps(data));return path

    def test_config_relative_paths_and_runaway_limit(self):
        settings=load(self.config())
        self.assertEqual(settings.profile,self.root/'profile')
        with self.assertRaises(ValueError):load(self.config(maximum_run_bytes=1))

    def test_invalid_configuration_fails_clearly(self):
        for change in ({'schema':'unknown'},{'minecraft':'26.2'},{'fabric_loader':'0.19.6'},
                       {'world_folder':'../important'},{'world_folder':'Lab_bad.'},
                       {'state':'profile/saves/state'},{'outputs':'state/nested'},{'world_folder':None}):
            with self.subTest(change=change),self.assertRaises(ValueError):load(self.config(**change))

    def test_missing_output_startup_and_combined_runaway_guard(self):
        missing=self.root/'frames.csv';log=self.root/'cli-output.txt'
        enforce_output_limit((missing,log),10)
        missing.write_bytes(b'12345');log.write_bytes(b'123456')
        with self.assertRaisesRegex(RuntimeError,'Runaway'):enforce_output_limit((missing,log),10)
        self.assertEqual(missing.read_bytes(),b'12345')

    def test_broker_preflight_requires_alive_matching_consent_before_preparation(self):
        from request_prepared_batch import check_broker_ready
        import time
        broker=self.root/'broker';broker.mkdir();config=self.config()
        kernel=Mock();kernel.OpenProcess.return_value=1;kernel.WaitForSingleObject.return_value=258
        ready={'status':'ready','pid':123,'profile':str(self.root/'profile'),'config_sha256':file_hash(config),'started_unix_ns':time.time_ns()}
        path=broker/'ready.json';path.write_text(json.dumps(ready))
        self.assertEqual(check_broker_ready(kernel,broker,self.root/'profile',config),ready)
        kernel.WaitForSingleObject.return_value=0
        with self.assertRaisesRegex(RuntimeError,'not running'):check_broker_ready(kernel,broker,self.root/'profile',config)
        kernel.WaitForSingleObject.return_value=258
        path.write_text(json.dumps({**ready,'profile':'wrong'}))
        with self.assertRaisesRegex(RuntimeError,'identity'):check_broker_ready(kernel,broker,self.root/'profile',config)
        path.write_text(json.dumps(ready));(broker/'stop.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'stop request'):check_broker_ready(kernel,broker,self.root/'profile',config)

    def test_setup_closure_is_self_contained_and_does_not_overwrite_existing_user_files(self):
        settings=load(self.config());directory=settings.profile/'minescript';directory.mkdir()
        (directory/'labrun.py').write_text('valuable user script')
        with patch('manage_experiment.closed'),patch.object(benchmark,'check'):
            with self.assertRaisesRegex(ValueError,'preserve/move'):benchmark.setup(settings)
        self.assertEqual(list(directory.iterdir()),[directory/'labrun.py'])
        self.assertEqual((directory/'labrun.py').read_text(),'valuable user script')
        sources=benchmark.instrumentation()
        self.assertIn('labprepare.py',sources);self.assertIn('session_protocol.py',sources)
        self.assertIn('room_route_protocol.py',sources);self.assertIn('lab_common.py',sources)

    def test_setup_then_check_installed_conditions_and_idempotent_copy(self):
        settings=load(self.config())
        with patch('manage_experiment.closed'),patch.object(benchmark,'check'):
            first=benchmark.setup(settings);second=benchmark.setup(settings)
        self.assertEqual(first,second)
        installed=json.loads((settings.profile/'minescript/lab-conditions.json').read_text())
        self.assertEqual(installed['configured_profile'],str(settings.profile))
        self.assertEqual(installed['world_folder'],'Lab_fixture')

    def test_prepare_rejects_bad_candidate_before_restoring(self):
        from types import SimpleNamespace
        args=SimpleNamespace(name='candidate',role='candidate',control=None)
        with patch('manage_experiment.restore_world') as restore:
            with self.assertRaises(ValueError):benchmark.prepare(load(self.config()),args)
            restore.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows host-command fixture; container cannot verify host processes')
    def test_portable_cli_setup_prepare_pins_a_verified_synthetic_world(self):
        fixture_repo=self.root/'source';fixture_repo.mkdir()
        for folder in ('scripts','scenarios','presets','manifests'):
            (fixture_repo/folder).mkdir()
        for name,source in benchmark.instrumentation().items():
            shutil.copyfile(source,fixture_repo/('scenarios' if source.parent.name=='scenarios' else 'scripts')/name)
        shutil.copyfile(benchmark.ROOT/'presets/lab-conditions.json',fixture_repo/'presets/lab-conditions.json')
        mods=self.root/'profile/mods';mods.mkdir()
        components=[]
        for slug in ('fabric-api','minescript'):
            jar=mods/(slug+'.jar')
            with zipfile.ZipFile(jar,'w') as package:package.writestr('fabric.mod.json',json.dumps({'id':slug,'version':'fixture-version'}))
            components.append({'slug':slug,'filename':jar.name,'sha512':hashlib.sha512(jar.read_bytes()).hexdigest()})
        (fixture_repo/'manifests/tools-lock.json').write_text(json.dumps({'components':components}))
        tool=self.root/'tool.exe';tool.write_bytes(b'nonexecutable-fixture')
        config=self.config(presentmon_sha256='b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af')
        actual_hash=benchmark.file_hash
        def fixture_hash(path):
            return 'b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af' if Path(path)==tool else actual_hash(path)
        import manage_experiment as manager
        with patch.dict(os.environ,{'FABRIC_BENCHMARK_CONFIG':str(config)}):
            importlib.reload(manager)
            try:
                with patch.object(benchmark,'ROOT',fixture_repo),patch.object(benchmark,'file_hash',side_effect=fixture_hash),patch.object(manager,'process_inventory',return_value={'games':[]}):
                    self.assertEqual(benchmark.main(['--config',str(config),'setup']),0)
                    self.assertEqual(benchmark.main(['--config',str(config),'prepare','--name','fixture-control','--role','control']),0)
                    manifest=json.loads((manager.REGISTRY/'fixture-control.json').read_text())
                    self.assertEqual(manifest['world_origin_sha256'],actual_hash(self.archive))
                    self.assertEqual(manifest['batch_protocol'],'full-route-only-v1')
                    self.assertIn('mods/minescript.jar',manifest['files'])
                    self.assertEqual((self.world/'level.dat').read_bytes(),b'new-world')
            finally:
                # Restore module configuration for other tests; no real process actions.
                pass
        importlib.reload(manager)


if __name__=='__main__':unittest.main()
