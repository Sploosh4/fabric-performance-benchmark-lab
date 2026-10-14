"""Receipted replacement of an existing lab's instrumentation, with no world/mod writes."""
from datetime import datetime
import difflib
import json
from pathlib import Path
import uuid

from experiment_protocol import file_hash
from world_restore import plain

SCHEMA='fabric-lab-instrumentation-migration-v1'


def plan(settings):
    from benchmark import check,setup_payload,write_new
    from manage_experiment import closed
    closed();check(settings)
    directory=settings.profile/'minescript';plain(directory)
    payload=setup_payload(settings)
    output=settings.state/'instrumentation-migrations'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    plain(output);output.mkdir(parents=True,exist_ok=False)
    (output/'before').mkdir();(output/'after').mkdir()
    entries={};diff=[]
    for name,raw in sorted(payload.items()):
        target=directory/name;plain(target)
        before=target.read_bytes() if target.exists() else None
        if before==raw:continue
        staged=output/'after'/name;staged.write_bytes(raw)
        if before is not None:(output/'before'/name).write_bytes(before)
        entries[name]={'before_sha256':file_hash(target) if before is not None else None,'after_sha256':file_hash(staged)}
        diff.extend(difflib.unified_diff((before or b'').decode('utf-8-sig').splitlines(True),raw.decode('utf-8-sig').splitlines(True),fromfile='before/'+name,tofile='after/'+name))
    value={'schema':SCHEMA,'status':'planned','profile':str(settings.profile.resolve()),'entries':entries,
           'worlds_changed':False,'mods_changed':False,'applied':[]}
    write_new(output/'receipt.json',value);(output/'changes.diff').write_text(''.join(diff),encoding='utf-8')
    return {'plan':str(output/'receipt.json'),'changed_files':sorted(entries),'diff':str(output/'changes.diff'),'worlds_changed':False,'mods_changed':False}


def apply(settings,receipt_path):
    from benchmark import check,setup_payload
    from manage_experiment import closed
    closed();check(settings)
    receipt_path=Path(receipt_path);plain(receipt_path)
    base=settings.state/'instrumentation-migrations'
    if receipt_path.resolve().parent.parent!=base.resolve() or receipt_path.name!='receipt.json':
        raise ValueError('Use a receipt from this lab migration directory')
    value=json.loads(receipt_path.read_text())
    if value.get('schema')!=SCHEMA or value.get('status')!='planned' or value.get('profile')!=str(settings.profile.resolve()):
        raise ValueError('Migration is not a pending plan for this profile')
    directory=settings.profile/'minescript';plain(directory)
    payload=setup_payload(settings)
    entries=value['entries']
    # Refuse stale source, stale target, unsafe names or damaged recovery copies before writing.
    for name,entry in entries.items():
        if name not in payload or Path(name).name!=name:raise ValueError('Unexpected migration filename')
        target=directory/name;staged=receipt_path.parent/'after'/name;before=receipt_path.parent/'before'/name
        for path in (target,staged,before):plain(path)
        current=file_hash(target) if target.exists() else None
        if current!=entry['before_sha256']:raise ValueError('Existing instrumentation changed after planning: '+name)
        if file_hash(staged)!=entry['after_sha256'] or staged.read_bytes()!=payload[name]:raise ValueError('Migration source changed after planning: '+name)
        if entry['before_sha256'] is not None and file_hash(before)!=entry['before_sha256']:raise ValueError('Recovery copy differs: '+name)
    # Any originally unchanged target must still match, too.
    for name,raw in payload.items():
        if name not in entries:
            target=directory/name;plain(target)
            if not target.is_file() or target.read_bytes()!=raw:raise ValueError('Unplanned instrumentation change: '+name)
    closed()
    def save():receipt_path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    value['status']='applying';save()
    try:
        for name,entry in entries.items():
            target=directory/name;pending=directory/(name+'.migration-pending');plain(pending)
            with pending.open('xb') as stream:stream.write(payload[name])
            pending.replace(target)
            value['applied'].append(name);save()
        check(settings,installed=True)
        value['status']='applied';save()
    except Exception:
        # Restore only bytes written by this migration; don't overwrite unexpected later edits.
        failures=[]
        for name in reversed(value['applied']):
            target=directory/name
            if file_hash(target)!=entries[name]['after_sha256']:
                failures.append(name);continue
            if entries[name]['before_sha256'] is None:target.unlink()
            else:target.write_bytes((receipt_path.parent/'before'/name).read_bytes())
        value['status']='rollback_incomplete' if failures else 'rolled_back';value['rollback_blocked_files']=failures;save()
        raise
    return {'status':value['status'],'receipt':str(receipt_path),'changed_files':sorted(entries),'worlds_changed':False,'mods_changed':False}
