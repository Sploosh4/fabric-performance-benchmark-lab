"""Offline session boundaries and whole-controller cleanup checks."""
import json
import ast
import io
import itertools
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import capture_session
from session_protocol import OWNER, paths_for, phase_paths, schedule, validate_arm, validate_phase, publish, read_json

NONCE = "a" * 32


class Sessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="validation-session-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.profile = self.directory / "sodium-automation"
        self.lab = self.profile / "minescript/lab-results"
        self.lab.mkdir(parents=True)
        self.files = paths_for(self.lab, NONCE)
        now = time.time_ns()
        self.arm = {"owner": OWNER, "nonce": NONCE, "game_pid": 1234, "benchmark_accepted": False,
                    "created_unix_ns": now, "expires_unix_ns": now + 900 * 10**9,
                    "repeats": 1, "initial_issues": []}

    def test_nonce_pid_expiry_and_conditions_are_enforced(self):
        validate_arm(self.arm, self.files["arm"], time.time_ns(), 1234)
        for change in ({"game_pid": 777}, {"benchmark_accepted": True}, {"repeats": 11},
                       {"initial_issues": ["focus"]}, {"nonce": "../escape"}, {"expires_unix_ns": 0}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                validate_arm({**self.arm, **change}, self.files["arm"], time.time_ns(), 1234)

    def test_phase_order_cannot_be_changed(self):
        identity = {"owner": OWNER, "nonce": NONCE, "game_pid": 1234, "benchmark_accepted": False}
        value = {**identity, "phase": 1, "scenario": "movement"}
        validate_phase(value, identity, 1, "movement")
        for change in ({"phase": 2}, {"scenario": "interaction"}, {"nonce": "b" * 32}):
            with self.assertRaises(RuntimeError):
                validate_phase({**value, **change}, identity, 1, "movement")
        with self.assertRaises(RuntimeError):
            phase_paths(self.lab, NONCE, 30)

    def test_extended_workload_fits_bounded_session(self):
        extended = {**self.arm, "movement_workload": "player_actions_v1", "repeats": 5}
        validate_arm(extended, self.files["arm"], time.time_ns(), 1234)
        for change in ({"repeats": 6}, {"movement_workload": "unknown"}):
            with self.assertRaisesRegex(RuntimeError, "extended workload"):
                validate_arm({**extended, **change}, self.files["arm"], time.time_ns(), 1234)

    def test_repeats_are_bounded_and_removed_interaction_cannot_return(self):
        self.assertEqual(schedule(3), ("stationary", "movement") * 3)
        for invalid in (0, 11, True, 1.0):
            with self.assertRaises(RuntimeError):
                schedule(invalid)

    def fake_controller(self, fail_action=False, automatic=False, focused=True, expiring_window=False, diagnostic=False):
        request=None
        if automatic:
            from auto_prepare_protocol import SCHEMA,LIFETIME_NS,DIAGNOSTIC_LIFETIME_NS
            from experiment_protocol import SCHEMA as EXP_SCHEMA,digest
            from room_route_protocol import WORKLOAD,ROOM_POLICY
            manifest={'schema':EXP_SCHEMA,'configuration_id':'fixture','role':'control','workload':WORKLOAD,
                'analysis_policy':ROOM_POLICY,'world_origin_sha256':'0'*64,'conditions_sha256':'0'*64,
                'files':{'mods/fixture.jar':'0'*64},'expected_loaded_mods':{'fixture':'1'}}
            (self.profile/'minescript/lab-conditions.json').write_text(json.dumps({'world_folder':'Lab_fixture'}))
            (self.profile/'minescript/lab-experiment.json').write_text(json.dumps(manifest))
            now=time.time_ns()
            request={'schema':SCHEMA,'mode':'functional_only','benchmark_accepted':False,'nonce':'c'*32,
                'profile':str(self.profile.resolve()),'world_folder':'Lab_fixture','repeats':1,
                'created_unix_ns':now,'expires_unix_ns':now+(DIAGNOSTIC_LIFETIME_NS if diagnostic else LIFETIME_NS),'manifest_sha256':digest(manifest),'diagnostic_only':diagnostic}
            self.arm.update(auto_prepare_mode='functional_only',auto_prepare_nonce=request['nonce'],
                            experiment={'manifest_sha256':digest(manifest)},diagnostic_only=diagnostic)
        publish(self.files["arm"], self.arm)
        self.files["samples"].write_text("fixture only\n")
        monitor = Mock()
        monitor.sample.return_value = {"minecraft_foreground": focused, "original_game_alive": True}
        calls = []
        def fake_wait(session, path, timeout, require_focus=True):
            if path.exists():
                return read_json(path)
            identity = session.identity.copy()
            if path == self.files["started"]:
                identity["status"] = "started"
            elif path == self.files["done"]:
                identity.update(status="session_validation_passed", completed_phases=2)
                publish(path, identity)
            else:
                index = int(path.name.split("-phase-")[1].split("-")[0])
                scenario = schedule(1)[index]
                identity.update(phase=index, scenario=scenario)
                if path.name.endswith("-ready.json"):
                    identity["status"] = "ready"
                elif path.name.endswith("-action.json"):
                    if fail_action: raise RuntimeError("fixture failed action")
                    identity["status"] = "action_verified"
                    calls.append(scenario)
                else:
                    identity["status"] = "phase_complete"
            if not path.exists():
                publish(path, identity)
            return identity
        ticks = iter(i * 0.25 for i in range(10000))
        args = SimpleNamespace(profile=self.profile, results=self.directory / "results", functional_only=True,
                               presentmon=Path("unused"), expected_sha256="unused",no_resources=True,auto_prepare_request=request)
        inventory = {"games": [{"pid": 1234}]}
        original_init=capture_session.Session.__init__
        def initialize(session,*values,**kwargs):
            original_init(session,*values,**kwargs)
            if expiring_window:
                def gate():
                    if session.resource_context.get('phase',0)>=1:raise RuntimeError('Measurement window expired/revoked')
                session.measurement_gate=gate
        with patch.object(capture_session, "process_inventory", return_value=inventory), \
             patch.object(capture_session, "Monitor", return_value=monitor) as created_monitor, \
             patch.object(capture_session.Session, "wait", fake_wait), \
             patch.object(capture_session.Session, '__init__',initialize), \
             patch.object(capture_session.time, "monotonic", side_effect=lambda: next(ticks)), \
             patch.object(capture_session.time, "sleep"):
            code = capture_session.main(args)
        result = read_json(next((self.directory / "results").glob("*/session-result.json")))
        if created_monitor.called:
            self.assertTrue(self.files["stop"].exists());monitor.close.assert_called_once()
        else:monitor.close.assert_not_called()
        return code, calls, result

    def test_full_functional_controller_collects_both_phases(self):
        code, calls, result = self.fake_controller()
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["stationary", "movement"])
        self.assertEqual(result["status"], "session_validation_passed")
        self.assertFalse(result["benchmark_accepted"])

    def test_failed_action_aborts_and_requests_safe_cleanup(self):
        code, calls, result = self.fake_controller(fail_action=True)
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])
        self.assertEqual(result["phases"], [])
        self.assertIn("fixture failed action", result["reason"])
        self.assertTrue(phase_paths(self.lab, NONCE, 0)["stop"].exists())

    def test_automatic_functional_confirmation_uses_existing_session_and_no_frames(self):
        with patch.object(capture_session,'run',side_effect=AssertionError('Frame capture forbidden')) as capture:
            code,calls,result=self.fake_controller(automatic=True)
        self.assertEqual(code,0);capture.assert_not_called()
        self.assertEqual(read_json(self.files['confirm'])['nonce'],NONCE)
        self.assertEqual(result['mode'],'functional_only')
        self.assertEqual(result['auto_prepare_nonce'],'c'*32)

    def test_automatic_focus_loss_cannot_publish_confirmation(self):
        code,calls,result=self.fake_controller(automatic=True,focused=False)
        self.assertEqual(code,2)
        self.assertFalse(self.files['confirm'].exists())
        self.assertIn('minecraft_foreground',result['reason'])

    def test_automatic_request_cannot_enable_frame_controller(self):
        args=SimpleNamespace(results=self.directory/'results',functional_only=False,auto_prepare_request={'nonce':'c'*32})
        with patch.object(capture_session,'run') as frames,patch.object(capture_session,'Monitor') as monitor:
            self.assertEqual(capture_session.main(args),2)
        frames.assert_not_called();monitor.assert_not_called()

    def test_diagnostic_policy_is_preserved_with_only_game_identity_metadata(self):
        code,calls,result=self.fake_controller(automatic=True,diagnostic=True,focused=False)
        self.assertEqual(code,0)
        self.assertTrue(result['diagnostic_only']);self.assertFalse(result['benchmark_accepted'])
        self.assertEqual(result['purpose'],'diagnostic_integration')

    def test_normal_session_requires_no_battery_or_background_metadata(self):
        code,calls,result=self.fake_controller(automatic=True)
        self.assertEqual(code,0)
        self.assertTrue(self.files['claim'].exists())
        self.assertFalse(result['diagnostic_only'])

    def test_expired_window_at_later_phase_rejects_stops_and_closes_monitor(self):
        code,calls,result=self.fake_controller(expiring_window=True)
        self.assertEqual(code,2)
        self.assertEqual(calls,['stationary'])
        self.assertEqual(len(result['phases']),1)
        self.assertIn('expired/revoked',result['reason'])
        self.assertTrue(self.files['stop'].exists())
        self.assertFalse(phase_paths(self.lab,NONCE,1)['go'].exists())
        self.assertFalse(result['benchmark_accepted'])

    def test_window_is_a_phase_start_lease_without_timed_file_polling(self):
        monitor=Mock();monitor.sample.return_value={'ac_connected':True,'minecraft_foreground':True,'original_game_alive':True}
        session=capture_session.Session(self.arm,self.files,self.lab,monitor,io.StringIO())
        session.measurement_gate=Mock(side_effect=RuntimeError('Window expired'))
        phase=capture_session.Phase(session,0,'movement')
        # Existing timed health checks remain active; an in-flight finite phase can finish.
        phase.health();session.measurement_gate.assert_not_called()
        with self.assertRaisesRegex(RuntimeError,'Window expired'):phase.capture_start()
        self.assertFalse(phase.files['go'].exists())
        with self.assertRaisesRegex(RuntimeError,'Window expired'):phase.prepare({'pid':1234},self.directory,{})
        self.assertFalse(phase.files['request'].exists())

    def test_missing_acknowledgement_times_out_and_can_stop(self):
        monitor = Mock()
        monitor.sample.return_value = {"ac_connected": True, "minecraft_foreground": True, "original_game_alive": True}
        session = capture_session.Session(self.arm, self.files, self.lab, monitor, io.StringIO())
        ticks = itertools.count(0.0, 1.0)
        session.deadline = 100.0
        with patch.object(capture_session.time, "monotonic", side_effect=lambda: next(ticks)), patch.object(capture_session.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "acknowledgement timed out"):
                session.wait(self.files["started"], 1)
        session.stop()
        self.assertTrue(self.files["stop"].exists())
        self.assertFalse(self.files["started"].exists())

    def test_setup_delay_does_not_consume_active_controller_budget(self):
        monitor = Mock()
        monitor.sample.return_value = {"ac_connected": True, "minecraft_foreground": True, "original_game_alive": True}
        now = [0.0]
        with patch.object(capture_session.time, "monotonic", side_effect=lambda: now[0]):
            session = capture_session.Session(self.arm, self.files, self.lab, monitor, io.StringIO())
            now[0] = 295.0
            session.begin({**session.identity, "status": "started"})
            now[0] = 1201.0  # Beyond the former deadline, within the active budget.
            session.health()
            with self.assertRaisesRegex(RuntimeError, "cannot be restarted"):
                session.begin({**session.identity, "status": "started"})
            now[0] = 1496.0
            with self.assertRaisesRegex(RuntimeError, "bounded deadline"):
                session.health()

    def test_active_clock_requires_valid_start_and_healthy_conditions(self):
        monitor = Mock()
        monitor.sample.return_value = {"ac_connected": True, "minecraft_foreground": False, "original_game_alive": True}
        session = capture_session.Session(self.arm, self.files, self.lab, monitor, io.StringIO())
        for change in ({"status": "waiting"}, {"nonce": "b" * 32}, {"game_pid": 777}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                session.begin({**session.identity, "status": "started", **change})
            self.assertFalse(session.active_started)
        with self.assertRaisesRegex(RuntimeError, "minecraft_foreground"):
            session.begin({**session.identity, "status": "started"})
        self.assertFalse(session.active_started)

    def test_game_active_clock_restarts_only_after_confirmation_and_live_check(self):
        # Execute the actual game-side boundary with a clock advanced by setup;
        # importing the whole script would start a Minescript job.
        source = Path(__file__).resolve().parents[1] / "scenarios/labprepare.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        block = next(n for n in ast.walk(tree) if isinstance(n, ast.Try) and
                     any(isinstance(v, ast.For) for v in n.body))
        start_index = next(i for i, n in enumerate(block.body) if isinstance(n, ast.Expr) and
                           isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and
                           n.value.func.id == "publish" and ast.unparse(n.value.args[0]) == "files['started']")
        boundary = block.body[start_index - 5:start_index + 1]
        self.assertIn("validate_identity(confirm", ast.unparse(ast.Module(body=block.body[:start_index], type_ignores=[])))
        live = Mock()
        watchdog = Mock()
        published = Mock()
        environment = {"time": SimpleNamespace(monotonic=lambda: 610.0), "session_deadline": 1200.0,
                       "assert_live": live, "files": {"stop": self.files["stop"], "started": self.files["started"]},
                       "faulthandler": watchdog, "stack": io.StringIO(), "write": Mock(),
                       "publish": published, "identity": {"nonce": NONCE}}
        code = compile(ast.fix_missing_locations(ast.Module(body=boundary, type_ignores=[])), str(source), "exec")
        exec(code, environment)
        self.assertEqual(environment["session_deadline"], 1810.0)
        live.assert_called_once_with(self.files["stop"])
        watchdog.cancel_dump_traceback_later.assert_called_once()
        watchdog.dump_traceback_later.assert_called_once_with(1200, file=environment["stack"])
        published.assert_called_once()
        live.side_effect = RuntimeError("paused")
        published.reset_mock()
        environment["session_deadline"] = 1200.0
        with self.assertRaisesRegex(RuntimeError, "paused"):
            exec(code, environment)
        self.assertEqual(environment["session_deadline"], 1200.0)
        published.assert_not_called()


if __name__ == "__main__":
    unittest.main()
