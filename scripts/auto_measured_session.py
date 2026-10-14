"""Ordinary launch/handshake orchestration around the existing approved capture broker."""
import time
import uuid

from auto_functional_session import dispatch
from capture_auto_protocol import SCHEMA,WINDOW_SCHEMA,check_window
from experiment_protocol import file_hash
from request_prepared_batch import configured_kernel,check_broker_ready
from session_protocol import publish,read_json,validate_identity


def clear_window(settings,minutes,diagnostic_only=False):
    """Explicit operator assertion; this does not detect or stop background workloads."""
    if type(minutes) is not int or not 1<=minutes<=30:raise ValueError('Window duration must be 1–30 minutes')
    if type(diagnostic_only) is not bool:raise ValueError('Diagnostic policy must be boolean')
    key=uuid.uuid4().hex;now=time.time_ns();directory=settings.state/'measurement-windows'
    from world_restore import plain
    plain(directory);directory.mkdir(parents=True,exist_ok=True)
    value={'schema':WINDOW_SCHEMA,'status':'cleared','nonce':key,'profile':str(settings.profile.resolve()),
           'config_sha256':file_hash(settings.config_path),'created_unix_ns':now,'expires_unix_ns':now+minutes*60*10**9,
           'diagnostic_only':diagnostic_only}
    publish(directory/('window-'+key+'.json'),value)
    return {'measurement_window_nonce':key,'expires_unix_ns':value['expires_unix_ns'],
            'diagnostic_only':diagnostic_only,
            'operator_assertion':'Diagnostic integration only; FPS is not comparison evidence. No capture started.' if diagnostic_only else 'Other workloads stopped; matching conditions will be maintained. No capture started.'}


def main(settings,key,repeats):
    if type(repeats) is not int or repeats not in (1,3,5):raise ValueError('Choose one diagnostic repeat, or three/five fixed-route repeats')
    if repeats==1 and not check_window(settings,key).get('diagnostic_only'):
        raise ValueError('A single captured repeat is restricted to diagnostic integration')
    broker=settings.outputs/'capture-broker';kernel=configured_kernel()
    def gate():
        check_window(settings,key)
        return check_broker_ready(kernel,broker,settings.profile,settings.config_path)
    gate() # Refuse absent window/broker before issuing tickets, preparation or launch.
    def factory(request):return {**request,'schema':SCHEMA,'mode':'functional_frame_capture','repeats':repeats,'measurement_window_nonce':key,
                                 'diagnostic_only':check_window(settings,key).get('diagnostic_only',False),
                                 'quit_after':check_window(settings,key).get('diagnostic_only',False)}
    def consume(arm,files,request):
        gate()
        submitted=broker/('request-'+uuid.uuid4().hex+'.json')
        result=submitted.with_name(submitted.stem.replace('request-','result-')+'.json')
        publish(submitted,{'schema':'modpack-capture-request-v1','expires_unix_ns':time.time_ns()+900*10**9,
            'resources':False,'overhead':False,'nonce':arm['nonce'],'auto_prepare_nonce':request['nonce']})
        deadline=time.monotonic()+300
        while not files['claim'].exists():
            gate()
            if result.exists():raise RuntimeError('Approved broker rejected the request: '+str(read_json(result).get('reason')))
            if time.monotonic()>deadline:raise RuntimeError('Approved broker did not claim the prepared session')
            time.sleep(.25)
        ready=gate();claim=read_json(files['claim']);validate_identity(claim,arm['nonce'],arm['game_pid'])
        if claim.get('mode')!='functional_frame_capture' or claim.get('controller_pid')!=ready['pid']:
            raise ValueError('Controller claim is not the matching approved broker')
        from capture_headless import Monitor
        monitor=Monitor(arm['game_pid'])
        try:
            sample=monitor.sample()
            required=('original_game_alive',) if request.get('diagnostic_only') else ('original_game_alive','minecraft_foreground')
            if any(not sample[k] for k in required):
                raise ValueError('Focus/original game checks failed before automatic confirmation')
        finally:monitor.close()
        gate()
        publish(files['confirm'],{'owner':arm['owner'],'nonce':arm['nonce'],'game_pid':arm['game_pid'],'benchmark_accepted':False})
        # Use existing broker/controller time budget and stop files; no polling during timed routes.
        deadline=time.monotonic()+1300
        while not result.exists():
            if time.monotonic()>deadline:raise RuntimeError('Broker completion exceeded the bounded batch deadline')
            time.sleep(1)
        outcome=read_json(result)
        if outcome.get('status')!='finished' or outcome.get('nonce')!=arm['nonce'] or outcome.get('broker_pid')!=ready['pid']:
            raise ValueError('Broker completion identity differs')
        return outcome['capture_exit_code']
    return dispatch(settings,request_factory=factory,consume=consume,precheck=gate)
