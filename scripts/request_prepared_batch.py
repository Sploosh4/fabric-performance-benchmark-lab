"""One bounded ordinary-process watcher; submits one exact prepared batch to the approved broker."""
import argparse
import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import time
import uuid

from capture_headless import process_inventory
from experiment_protocol import digest
from experiment_protocol import file_hash
from session_protocol import fresh_sessions, publish

from lab_settings import load
SETTINGS=load(required=False)
PROFILE=SETTINGS.profile
OUTPUTS=SETTINGS.outputs
BROKER=OUTPUTS/'capture-broker'


def check_broker_ready(kernel,broker,profile,config_path):
    if (broker/'stop.json').exists():raise RuntimeError('Capture broker stop request exists; wait for shutdown before restarting it')
    ready=json.loads((broker/'ready.json').read_text())
    if ready.get('status')!='ready' or ready.get('profile')!=str(profile) or ready.get('config_sha256')!=file_hash(config_path):
        raise RuntimeError('Start the matching user-approved broker first; ready/configuration identity differs')
    if type(ready.get('pid')) is not int or ready['pid']<=0:raise RuntimeError('Broker process identity missing')
    started=ready.get('started_unix_ns',0)
    if type(started) is not int or not 0<=time.time_ns()-started<6*3600*10**9:raise RuntimeError('Capture broker readiness expired')
    handle=kernel.OpenProcess(0x100000,False,ready['pid'])
    try:
        if not handle or kernel.WaitForSingleObject(handle,0)!=258:raise RuntimeError('Approved capture broker is not running')
    finally:
        if handle:kernel.CloseHandle(handle)
    return ready


def configured_kernel():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,W.BOOL,W.LPCWSTR];kernel.CreateMutexW.restype=W.HANDLE
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.ReleaseMutex.argtypes=[W.HANDLE]
    return kernel


def main(args):
    load()
    kernel=configured_kernel()
    check_broker_ready(kernel,BROKER,PROFILE,SETTINGS.config_path)
    mutex=kernel.CreateMutexW(None,True,'Local\\ModpackPreparedBatchDispatcher')
    if not mutex:raise RuntimeError('Dispatcher mutex unavailable')
    if ctypes.get_last_error()==183:
        kernel.CloseHandle(mutex);raise RuntimeError('A prepared-batch watcher is already running')
    try:
        pinned=json.loads((PROFILE/'minescript/lab-experiment.json').read_text())
        if digest(pinned)!=args.manifest_sha256:raise RuntimeError('Active manifest differs from requested batch')
        deadline=time.monotonic()+900
        print(f'Waiting for one fresh labprepare {args.repeats} with the pinned configuration.',flush=True)
        while time.monotonic()<deadline:
            pending=[(arm,files) for arm,files in fresh_sessions(PROFILE/'minescript/lab-results') if not files['claim'].exists()]
            if pending:
                if len(pending)!=1:raise RuntimeError('Multiple preparations; refusing to choose')
                arm,files=pending[0]
                if arm['repeats']!=args.repeats or arm.get('experiment',{}).get('manifest_sha256')!=args.manifest_sha256:
                    raise RuntimeError('Prepared count/configuration differs')
                inventory=process_inventory(PROFILE)
                if len(inventory['games'])!=1 or inventory['games'][0]['pid']!=arm['game_pid']:
                    raise RuntimeError('Prepared game process differs')
                check_broker_ready(kernel,BROKER,PROFILE,SETTINGS.config_path)
                request=BROKER/('request-'+uuid.uuid4().hex+'.json')
                publish(request,{'schema':'modpack-capture-request-v1','expires_unix_ns':time.time_ns()+900*10**9,
                                 'resources':False,'overhead':False,'nonce':arm['nonce']})
                print('Submitted one nonce-bound resource-OFF request: '+request.name,flush=True)
                # No more preflight polling once capture can start. The broker logs readiness/results.
                return
            time.sleep(1)
        raise RuntimeError('Preparation watcher expired; no request submitted')
    finally:
        kernel.ReleaseMutex(mutex);kernel.CloseHandle(mutex)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats',required=True,type=int,choices=(1,3,5))
    parser.add_argument('--manifest-sha256',required=True)
    try:main(parser.parse_args())
    except Exception as error:
        print('DISPATCH REJECTED: '+str(error),flush=True);raise SystemExit(2)
