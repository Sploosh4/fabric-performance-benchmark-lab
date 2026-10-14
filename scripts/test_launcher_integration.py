"""Initial launcher boundary fixtures; no real GUI/game/elevation/account data."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from launch_lab_world import launch


class LauncherIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='launcher-integration-fixture-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.profile=self.root/'profiles/lab-fixture';self.profile.mkdir(parents=True)
        self.world='Lab_fixture';save=self.profile/'saves'/self.world;save.mkdir(parents=True);(save/'level.dat').write_bytes(b'fixture')
        (self.profile/'minescript').mkdir()
        self.conditions={'minecraft':'26.1.2','world_folder':self.world,'configured_profile':str(self.profile)}
        self.write_conditions()
        self.app=self.root/'launcher.exe';self.app.write_bytes(b'not executable')
        self.db=self.root/'app.db'
        with closing(sqlite3.connect(self.db)) as c,c:
            c.executescript('CREATE TABLE instances (id,path,name,install_stage,applied_content_set_id); CREATE TABLE instance_content_sets (id,instance_id,game_version,loader,loader_version);')
            c.execute('INSERT INTO instances VALUES (?,?,?,?,?)',('local:fixture',self.profile.name,'Fixture','installed','set:fixture'))
            c.execute('INSERT INTO instance_content_sets VALUES (?,?,?,?,?)',('set:fixture','local:fixture','26.1.2','fabric','0.19.5'))

    def write_conditions(self):
        (self.profile/'minescript/lab-conditions.json').write_text(json.dumps(self.conditions))

    def call(self,check_only=True,world=None,profile=None):
        return launch(check_only,profile or self.profile,self.app,self.db,world or self.world)

    def test_check_only_reads_instance_without_mutation_or_launch(self):
        before=self.db.read_bytes()
        with patch('launch_lab_world.process_inventory',return_value={'games':[]}),patch('launch_lab_world.subprocess.Popen') as popen:
            result=self.call();popen.assert_not_called()
        self.assertEqual(result['status'],'launch_preflight_passed');self.assertFalse(result['world_ready_verified'])
        self.assertEqual(self.db.read_bytes(),before)

    def test_launch_uses_native_instance_uri_and_no_console_credentials(self):
        with patch('launch_lab_world.process_inventory',return_value={'games':[]}),patch('launch_lab_world.subprocess.Popen') as popen:
            popen.return_value.pid=123;self.call(check_only=False)
        self.assertEqual(popen.call_args.args[0],[str(self.app),'modrinth://launch/instance/local%3Afixture?singleplayer_world=Lab_fixture'])
        self.assertEqual(popen.call_args.kwargs['stdout'],-3);self.assertEqual(popen.call_args.kwargs['stderr'],-3)

    def test_duplicate_client_never_launches(self):
        with patch('launch_lab_world.process_inventory',return_value={'games':[{'pid':123}]}),patch('launch_lab_world.subprocess.Popen') as popen:
            with self.assertRaisesRegex(ValueError,'already running'):self.call(check_only=False)
            popen.assert_not_called()

    def test_world_traversal_and_wrong_instance_guard_rejected(self):
        with self.assertRaises(ValueError):self.call(world='../important')
        self.conditions['configured_profile']=str(self.root/'other-profile');self.write_conditions()
        with self.assertRaisesRegex(ValueError,'instance guard'):self.call()

    def test_registered_wrong_loader_version_rejected(self):
        with closing(sqlite3.connect(self.db)) as c,c:c.execute("UPDATE instance_content_sets SET loader_version='wrong'")
        with self.assertRaisesRegex(ValueError,'Registered instance'):self.call()

    def test_unknown_launcher_schema_fails_without_writing_it(self):
        with closing(sqlite3.connect(self.db)) as c,c:c.execute('DROP TABLE instance_content_sets')
        before=self.db.read_bytes()
        with self.assertRaisesRegex(ValueError,'schema'):self.call()
        self.assertEqual(self.db.read_bytes(),before)


if __name__=='__main__':unittest.main()
