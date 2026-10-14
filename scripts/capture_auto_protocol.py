"""Separate measured preparation permission; requires a cleared, expiring measurement window."""
from pathlib import Path
import time

from auto_prepare_protocol import nonce,request_lifetime_ns
from experiment_protocol import digest,file_hash
from session_protocol import ROUTE_BATCH,batch_protocol,validate_identity,read_json
from world_restore import plain

SCHEMA='fabric-lab-measured-preparation-v1'
WINDOW_SCHEMA='fabric-lab-measurement-window-v1'


def validate_capture_request(value,profile,conditions,manifest,now=None):
    now=time.time_ns() if now is None else now
    if value.get('schema')!=SCHEMA or value.get('mode')!='functional_frame_capture' or value.get('benchmark_accepted') is not False:
        raise ValueError('A separate measured preparation permission is required')
    if type(value.get('diagnostic_only',False)) is not bool:raise ValueError('Invalid diagnostic policy')
    if type(value.get('quit_after',False)) is not bool or (value.get('quit_after') and not value.get('diagnostic_only')):
        raise ValueError('Automatic quit is restricted to diagnostic requests')
    nonce(value.get('nonce'));nonce(value.get('measurement_window_nonce'))
    if value.get('profile')!=str(Path(profile).resolve()) or value.get('world_folder')!=conditions['world_folder']:
        raise ValueError('Measured preparation belongs to another profile/world')
    created,expires=value.get('created_unix_ns'),value.get('expires_unix_ns')
    if type(created) is not int or type(expires) is not int or expires-created!=request_lifetime_ns(value) or not created<=now<expires:
        raise ValueError('Measured preparation request expired')
    counts=(1,3,5) if value.get('diagnostic_only') else (3,5)
    if type(value.get('repeats')) is not int or value['repeats'] not in counts or batch_protocol(manifest)!=ROUTE_BATCH:
        raise ValueError('Measured automation permits only three/five fixed full-route repeats')
    if value.get('manifest_sha256')!=digest(manifest):raise ValueError('Measured preparation manifest differs')
    return value


def validate_capture_arm(arm,request):
    validate_identity(arm,arm['nonce'],arm['game_pid'])
    if arm.get('auto_prepare_nonce')!=request['nonce'] or arm.get('auto_prepare_mode')!='functional_frame_capture':
        raise ValueError('Prepared arm is not bound to this measured request')
    if arm.get('diagnostic_only',False)!=request.get('diagnostic_only',False):raise ValueError('Diagnostic arm policy differs')
    if arm.get('repeats')!=request['repeats'] or arm.get('experiment',{}).get('manifest_sha256')!=request['manifest_sha256'] or batch_protocol(arm)!=ROUTE_BATCH:
        raise ValueError('Measured count/route/manifest differs')


def validate_window(value,settings,now=None):
    now=time.time_ns() if now is None else now
    if value.get('schema')!=WINDOW_SCHEMA or value.get('status')!='cleared':raise ValueError('Measurement window is not explicitly cleared')
    if type(value.get('diagnostic_only',False)) is not bool:raise ValueError('Invalid diagnostic window policy')
    nonce(value.get('nonce'))
    created,expires=value.get('created_unix_ns'),value.get('expires_unix_ns')
    if type(created) is not int or type(expires) is not int or not 0<expires-created<=30*60*10**9 or not created<=now<expires:
        raise ValueError('Measurement window expired or is invalid')
    if value.get('profile')!=str(settings.profile.resolve()) or value.get('config_sha256')!=file_hash(settings.config_path):
        raise ValueError('Measurement window belongs to another profile/configuration')
    return value


def check_window(settings,key):
    path=settings.state/'measurement-windows'/('window-'+nonce(key)+'.json');plain(path)
    value=validate_window(read_json(path),settings)
    if value['nonce']!=key:raise ValueError('Measurement window filename differs')
    return value
