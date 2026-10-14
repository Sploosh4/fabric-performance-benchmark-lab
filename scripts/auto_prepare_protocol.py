"""One-use functional preparation request; no commands, arbitrary scripts or frame mode."""
from pathlib import Path
import re
import time
import json
import uuid

from experiment_protocol import digest
from session_protocol import validate_identity
from world_restore import plain

SCHEMA='fabric-lab-functional-preparation-v1'
LIFETIME_NS=300*10**9
DIAGNOSTIC_LIFETIME_NS=600*10**9


def request_lifetime_ns(value):
    """Minimized diagnostic startup gets a fixed ten-minute bound; normal remains five."""
    return DIAGNOSTIC_LIFETIME_NS if value.get('diagnostic_only') is True else LIFETIME_NS


def nonce(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise ValueError('Invalid automatic preparation nonce')
    return value


def validate_request(value,profile,conditions,manifest,now=None):
    now=time.time_ns() if now is None else now
    if value.get('schema')!=SCHEMA or value.get('mode')!='functional_only' or value.get('benchmark_accepted') is not False:
        raise ValueError('Only functional preparation is supported automatically')
    if type(value.get('diagnostic_only',False)) is not bool:raise ValueError('Invalid diagnostic policy')
    if type(value.get('quit_after',False)) is not bool or (value.get('quit_after') and not value.get('diagnostic_only')):
        raise ValueError('Automatic quit is restricted to diagnostic requests')
    nonce(value.get('nonce'))
    if value.get('profile')!=str(Path(profile).resolve()) or value.get('world_folder')!=conditions['world_folder']:
        raise ValueError('Automatic preparation belongs to another profile/world')
    created,expires=value.get('created_unix_ns'),value.get('expires_unix_ns')
    if type(created) is not int or type(expires) is not int or expires-created!=request_lifetime_ns(value) or not created<=now<expires:
        raise ValueError('Automatic preparation request is expired or future-dated')
    if type(value.get('repeats')) is not int or value['repeats']!=1:
        raise ValueError('Automatic functional pilot permits exactly one repeat')
    if value.get('manifest_sha256')!=digest(manifest):raise ValueError('Automatic preparation manifest differs')
    return value


def validate_launch_request(value,profile,conditions,manifest,now=None):
    if value.get('schema')==SCHEMA:return validate_request(value,profile,conditions,manifest,now)
    from capture_auto_protocol import validate_capture_request
    return validate_capture_request(value,profile,conditions,manifest,now)


def validate_launch_arm(arm,request):
    if request.get('schema')==SCHEMA:return validate_auto_arm(arm,request)
    from capture_auto_protocol import validate_capture_arm
    return validate_capture_arm(arm,request)


def files_for(directory,value):
    key=nonce(value)
    return {kind:Path(directory)/('auto-prepare-'+key+'-'+kind+'.json') for kind in ('claim','result')}


def validate_auto_arm(arm,request):
    validate_identity(arm,arm['nonce'],arm['game_pid'])
    if arm.get('auto_prepare_nonce')!=request['nonce'] or arm.get('auto_prepare_mode')!='functional_only':
        raise ValueError('Prepared session is not bound to this functional request')
    if arm.get('diagnostic_only',False)!=request.get('diagnostic_only',False):raise ValueError('Diagnostic arm policy differs')
    if arm.get('repeats')!=request['repeats'] or arm.get('experiment',{}).get('manifest_sha256')!=request['manifest_sha256']:
        raise ValueError('Automatic prepared count or experiment differs')
    return arm


def safe_directory(profile):
    directory=Path(profile)/'minescript/lab-results'
    plain(directory);return directory


def write_ticket(path,value):
    """The one mutable request slot; phase/claim/receipt files remain no-overwrite."""
    path=Path(path);plain(path)
    if path.name!='auto-prepare-request.json':raise ValueError('Unexpected automatic request slot')
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');plain(temporary)
    try:
        with temporary.open('x',encoding='utf-8') as stream:json.dump(value,stream)
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()
