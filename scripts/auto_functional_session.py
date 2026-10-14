"""One ordinary-process launch/functional route pilot; never starts PresentMon or a broker."""
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import uuid

from auto_prepare_protocol import SCHEMA,LIFETIME_NS,request_lifetime_ns,files_for,validate_launch_request,validate_launch_arm,safe_directory,write_ticket
from capture_headless import process_inventory
from experiment_protocol import digest,validate_manifest,file_inventory
from session_protocol import fresh_sessions,publish,read_json
from world_restore import plain


def main(settings,diagnostic_only=False):
    if type(diagnostic_only) is not bool:raise ValueError('Diagnostic policy must be boolean')
    return dispatch(settings,request_factory=lambda request:{**request,'diagnostic_only':diagnostic_only,'quit_after':diagnostic_only})


def dispatch(settings,request_factory=None,consume=None,precheck=None):
    from manage_experiment import closed
    if precheck is not None:precheck()
    closed()
    directory=safe_directory(settings.profile);directory.mkdir(exist_ok=True)
    lock=directory/'auto-launch-controller.lock';plain(lock)
    identity={'pid':os.getpid(),'nonce':uuid.uuid4().hex}
    # A crash leaves an inspectable lock. Never silently adopt/delete another controller's lock.
    with lock.open('x',encoding='utf-8') as stream:json.dump(identity,stream)
    try:return _dispatch(settings,request_factory,consume,precheck)
    finally:
        if json.loads(lock.read_text())==identity:lock.unlink()


def _dispatch(settings,request_factory=None,consume=None,precheck=None):
    """Shared finite launch/readiness handshake; callers are fixed project functions."""
    from manage_experiment import closed
    closed()
    directory=safe_directory(settings.profile);directory.mkdir(exist_ok=True)
    if fresh_sessions(directory):raise ValueError('An existing prepared session must finish or be cancelled first')
    manifest=validate_manifest(read_json(settings.profile/'minescript/lab-experiment.json'))
    if file_inventory(settings.profile)!=manifest['files']:
        raise ValueError('Prepare/pin the current script and mod configuration before automatic launch')
    conditions=read_json(settings.profile/'minescript/lab-conditions.json')
    if precheck is not None:precheck()
    now=time.time_ns()
    request={'schema':SCHEMA,'mode':'functional_only','benchmark_accepted':False,'nonce':uuid.uuid4().hex,
             'profile':str(settings.profile.resolve()),'world_folder':settings.world_folder,'repeats':1,
             'created_unix_ns':now,'expires_unix_ns':now+LIFETIME_NS,'manifest_sha256':digest(manifest)}
    if request_factory is not None:request=request_factory(request)
    request['expires_unix_ns']=now+request_lifetime_ns(request)
    if request.get('diagnostic_only'):
        from background_options import prepare
        print('Diagnostic background options: '+prepare(settings)['status'],flush=True)
    path=directory/'auto-prepare-request.json';plain(path)
    if path.exists():
        old=read_json(path)
        if old.get('expires_unix_ns',0)>now:
            old_files=files_for(directory,old.get('nonce'))
            if not old_files['result'].exists():raise ValueError('Another fresh automatic request is still pending')
    validate_launch_request(request,settings.profile,conditions,manifest)
    write_ticket(path,request)
    result_files=files_for(directory,request['nonce'])
    outcome={'nonce':request['nonce'],'mode':request['mode'],'benchmark_accepted':False,'status':'failed'}
    session_files=None
    try:
        if precheck is not None:precheck()
        from launch_lab_world import launch
        launch()
        deadline=time.monotonic()+request_lifetime_ns(request)/10**9
        print('Waiting for the exact world-scoped preparation: '+request['mode'],flush=True)
        while time.monotonic()<deadline:
            if result_files['result'].exists():raise RuntimeError('Autorun ended before the controller was ready')
            matching=[(arm,files) for arm,files in fresh_sessions(directory) if arm.get('auto_prepare_nonce')==request['nonce']]
            if matching:
                if len(matching)!=1:raise ValueError('Multiple automatic preparations; refusing to choose')
                arm,session_files=matching[0];validate_launch_arm(arm,request)
                games=process_inventory(settings.profile)['games']
                claim=read_json(result_files['claim'])
                if len(games)!=1 or games[0]['pid']!=arm['game_pid'] or claim.get('nonce')!=request['nonce'] or claim.get('game_pid')!=arm['game_pid']:
                    raise ValueError('Automatic preparation game identity differs')
                validate_launch_request(request,settings.profile,conditions,manifest)
                if precheck is not None:precheck()
                if consume is not None:
                    code=consume(arm,session_files,request)
                    outcome.update(status='controller_passed' if code==0 else 'controller_rejected',game_pid=arm['game_pid'],session_nonce=arm['nonce'])
                    return code
                from capture_session import main as controller
                code=controller(SimpleNamespace(profile=settings.profile,presentmon=settings.presentmon,
                    expected_sha256=settings.presentmon_sha256,results=settings.outputs/'functional-auto',
                    functional_only=True,no_resources=True,resource_overhead=False,auto_prepare_request=request))
                outcome.update(status='functional_controller_passed' if code==0 else 'functional_controller_rejected',game_pid=arm['game_pid'],session_nonce=arm['nonce'])
                return code
            time.sleep(.5)
        raise RuntimeError('Automatic world preparation exceeded its fixed startup deadline')
    finally:
        if session_files is not None and not session_files['stop'].exists():
            publish(session_files['stop'],{'owner':arm['owner'],'nonce':arm['nonce'],'game_pid':arm['game_pid'],'benchmark_accepted':False})
        # Invalidate unused requests too, so a later world entry cannot consume a failed pilot.
        if read_json(path).get('nonce')==request['nonce']:
            request['expires_unix_ns']=0;write_ticket(path,request)
        publish(directory/('auto-prepare-'+request['nonce']+'-controller-result.json'),outcome)
