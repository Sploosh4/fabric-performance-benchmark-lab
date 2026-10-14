"""One elevated, bounded capture broker. Fixed profile/paths; no desktop input."""
import ctypes
from ctypes import wintypes as W
from datetime import datetime
import json
import importlib
import os
import contextlib
from pathlib import Path
import time
from types import SimpleNamespace

from session_protocol import publish, read_json

from lab_settings import load
from experiment_protocol import file_hash
SETTINGS=load(required=False)
PROFILE = SETTINGS.profile
OUTPUTS = SETTINGS.outputs
BROKER = OUTPUTS / "capture-broker"
PRESENTMON = SETTINGS.presentmon
SHA256 = SETTINGS.presentmon_sha256


def main():
    load()
    BROKER.mkdir(parents=True,exist_ok=True)
    if not ctypes.WinDLL("shell32").IsUserAnAdmin():
        raise RuntimeError("Capture broker requires user-approved administrator launch")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p,W.BOOL,W.LPCWSTR]
    kernel.CreateMutexW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.ReleaseMutex.argtypes = [W.HANDLE]
    handle = kernel.CreateMutexW(None,True,"Local\\ModpackOwnedCaptureBroker")
    if not handle:
        raise RuntimeError("Capture broker mutex unavailable")
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        raise RuntimeError("A capture broker is already running")
    pid=os.getpid()
    deadline=time.monotonic()+6*3600
    stop=BROKER/"stop.json"
    # A fresh launch never silently clears a prior stop request.
    try:
        if stop.exists(): raise RuntimeError("Capture broker stop request exists")
        (BROKER/"ready.json").write_text(json.dumps({"pid":pid,"status":"ready","started_unix_ns":time.time_ns(),
                                                   "profile":str(PROFILE),"config_sha256":file_hash(SETTINGS.config_path)}))
        print("Capture broker ready; waiting for project-owned session requests.",flush=True)
        print("Keep this window open. Minecraft commands and capture requests are handled by the agent.",flush=True)
        while time.monotonic()<deadline and not stop.exists():
            for path in sorted(BROKER.glob("request-*.json")):
                result_path=path.with_name(path.stem.replace("request-","result-")+".json")
                claim=path.with_suffix(".claimed")
                if result_path.exists() or claim.exists(): continue
                request=read_json(path)
                if request.get("schema")!="modpack-capture-request-v1" or request.get("expires_unix_ns",0)<time.time_ns():
                    publish(result_path,{"status":"rejected","reason":"Invalid or expired request"})
                    continue
                if set(request)-{"schema","expires_unix_ns","resources","overhead","nonce","auto_prepare_nonce"}:
                    publish(result_path,{"status":"rejected","reason":"Unexpected request fields"})
                    continue
                if type(request.get("resources")) is not bool or type(request.get("overhead")) is not bool:
                    publish(result_path,{"status":"rejected","reason":"Invalid sampling policy"})
                    continue
                # Fixed trusted controller modules, refreshed only between batches.
                # Reload protocol before discovering arms so route revisions register.
                for module_name in ("room_route_protocol","session_protocol","frame_csv","validate_capture",
                                    "experiment_protocol","auto_prepare_protocol","capture_auto_protocol","resource_monitor","capture_headless","capture_session"):
                    importlib.reload(importlib.import_module(module_name))
                # Bind exactly one already-prepared arm, never claim a different batch.
                from session_protocol import fresh_sessions
                pending=[(arm,files) for arm,files in fresh_sessions(PROFILE/"minescript/lab-results") if not files["claim"].exists()]
                if len(pending)!=1 or pending[0][0]["nonce"]!=request.get("nonce"):
                    publish(result_path,{"status":"rejected","reason":"Prepared session nonce differs"})
                    continue
                measured=None
                if request.get('auto_prepare_nonce') is not None:
                    try:
                        from capture_auto_protocol import validate_capture_request,validate_capture_arm,check_window
                        from experiment_protocol import validate_manifest
                        measured=read_json(PROFILE/'minescript/lab-results/auto-prepare-request.json')
                        if measured.get('nonce')!=request['auto_prepare_nonce'] or request['resources'] or request['overhead']:
                            raise ValueError('Measured automatic request identity/sampling differs')
                        manifest=validate_manifest(read_json(PROFILE/'minescript/lab-experiment.json'))
                        validate_capture_request(measured,PROFILE,read_json(PROFILE/'minescript/lab-conditions.json'),manifest)
                        validate_capture_arm(pending[0][0],measured)
                        check_window(SETTINGS,measured['measurement_window_nonce'])
                    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as error:
                        publish(result_path,{'status':'rejected','reason':str(error)});continue
                claim.write_text(str(pid))
                args=SimpleNamespace(profile=PROFILE,presentmon=PRESENTMON,expected_sha256=SHA256,
                                     results=OUTPUTS/"session-captures",functional_only=False,
                                     no_resources=not request["resources"],resource_overhead=request["overhead"],external_stop=stop,
                                     maximum_run_bytes=SETTINGS.data.get('maximum_run_bytes',1024**4),capture_prepare_request=measured)
                # Reload only these fixed project modules between completed requests.
                # This permits controller repairs without another administrator launch.
                import capture_session
                code=capture_session.main(args)
                publish(result_path,{"status":"finished","capture_exit_code":code,"nonce":request["nonce"],"broker_pid":pid})
                print("Request completed: "+path.name+" code="+str(code),flush=True)
            time.sleep(0.25)
    finally:
        print("Capture broker stopping: " + ("project stop request" if stop.exists() else "deadline reached or exception; inspect diagnostics"),flush=True)
        (BROKER/"ready.json").write_text(json.dumps({"pid":pid,"status":"stopped","stopped_unix_ns":time.time_ns()}))
        kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


if __name__=="__main__":
    load()
    BROKER.mkdir(parents=True,exist_ok=True)
    log=BROKER/("broker-"+datetime.now().strftime("%Y%m%d-%H%M%S")+".log")
    import sys
    class Mirror:
        def __init__(self,log,console):self.log,self.console=log,console
        def write(self,value):
            count=self.log.write(value)
            try:self.console.write(value)
            except OSError:pass
            return count
        def flush(self):
            self.log.flush()
            try:self.console.flush()
            except OSError:pass
    with log.open("x",encoding="utf-8",buffering=1) as output:
        with contextlib.redirect_stdout(Mirror(output,sys.stdout)), contextlib.redirect_stderr(Mirror(output,sys.stderr)):
            try:main()
            except Exception:
                import traceback
                traceback.print_exc()
                raise SystemExit(1)
