"""Idle on normal world entry; consumes one scoped functional ticket when explicitly armed."""
import json
from pathlib import Path
import runpy
import sys
import time

import minescript as ms
from lab_common import PROFILE,CONDITIONS,guard_world,number,ProcessHandle,MC
from auto_prepare_protocol import validate_launch_request,files_for,safe_directory
from experiment_protocol import validate_manifest,file_inventory
from session_protocol import publish
from world_restore import plain


def main():
    directory=safe_directory(PROFILE);request_path=directory/'auto-prepare-request.json';plain(request_path)
    if not request_path.exists():return
    value=json.loads(request_path.read_text(encoding='utf-8'))
    manifest=validate_manifest(json.loads((PROFILE/'minescript/lab-experiment.json').read_text(encoding='utf-8')))
    validate_launch_request(value,PROFILE,CONDITIONS,manifest)
    files=files_for(directory,value['nonce'])
    for path in files.values():plain(path)
    if files['claim'].exists() or files['result'].exists():return
    guard_world()
    if file_inventory(PROFILE)!=manifest['files']:raise ValueError('Installed experiment changed before autorun')
    pid=number(ProcessHandle.current().pid())
    # Exclusive creation prevents two concurrent hooks from starting the same request.
    with files['claim'].open('x',encoding='utf-8') as stream:
        json.dump({'schema':value['schema'],'nonce':value['nonce'],'game_pid':pid,'claimed_unix_ns':time.time_ns()},stream)
    previous=sys.argv
    try:
        sys.argv=['labprepare',str(value['repeats'])]
        state=runpy.run_path(str(Path(__file__).with_name('labprepare.py')),init_globals={'AUTO_PREPARE_REQUEST':value})
        result=state['result']
        publish(files['result'],{'nonce':value['nonce'],'game_pid':pid,'status':result['status'],
                                'session_nonce':result['nonce'],'benchmark_accepted':False,'mode':value['mode']})
        if value.get('quit_after'):
            # Let the existing controller finish copying evidence and stopping its trace first.
            completed=directory/('auto-prepare-'+value['nonce']+'-controller-result.json')
            deadline=time.monotonic()+30
            while not completed.exists() and time.monotonic()<deadline:time.sleep(.1)
            if not completed.exists():raise RuntimeError('Controller completion not confirmed; game left running')
            receipt=json.loads(completed.read_text(encoding='utf-8'))
            if receipt.get('nonce')!=value['nonce'] or receipt.get('benchmark_accepted') is not False:
                raise RuntimeError('Controller completion identity differs; game left running')
            guard_world()
            publish(directory/('auto-prepare-'+value['nonce']+'-quit-requested.json'),{'nonce':value['nonce'],'game_pid':pid,'normal_quit':True})
            MC.stop() # Native Minecraft shutdown; saves normally, no Windows input or force kill.
    finally:sys.argv=previous


if __name__=='__main__':
    try:main()
    except Exception as error:
        ms.echo('Automatic lab preparation did not start/finish: '+str(error))
