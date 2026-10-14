"""One-use experimental-warning permission; no world writes or broad input endpoint."""
import json
from pathlib import Path
import re
import time
import uuid
from experiment_protocol import file_hash
from world_restore import plain

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'bootstrap-helper/build/helper-lock.json'


def authorize(profile,world,master,expected_sha256,check_only=False):
    profile=Path(profile);master=Path(master)
    plain(profile);plain(master)
    profile=profile.resolve(strict=True);master=master.resolve(strict=True)
    if file_hash(master)!=expected_sha256:raise ValueError('Bootstrap immutable master hash differs')
    lock=json.loads(LOCK.read_text())
    if lock.get('schema')!='fabric-lab-bootstrap-build-v1' or Path(lock['filename']).name!=lock['filename']:
        raise ValueError('Unknown helper build identity')
    jar=profile/'mods'/lock['filename'];plain(jar)
    if file_hash(jar)!=lock['sha256']:raise ValueError('Installed helper differs from the checked build')
    save=profile/'saves'/world;plain(save)
    if not save.name.startswith('Lab_') or save.resolve().parent!=(profile/'saves').resolve() or master.is_relative_to(save.resolve()):
        raise ValueError('Bootstrap world/master confinement differs')
    conditions=profile/'minescript/lab-conditions.json';plain(conditions)
    settings=json.loads(conditions.read_text())
    if settings['minecraft']!='26.1.2' or settings['world_folder']!=world:raise ValueError('Bootstrap Minescript conditions differ')
    packs={};plain(save/'datapacks');plain(save/'level.dat')
    for path in sorted((save/'datapacks').rglob('*')):
        plain(path)
        if path.is_file():packs[path.relative_to(save/'datapacks').as_posix()]=file_hash(path)
    if not packs:raise ValueError('Expected the pinned lab datapack inventory')
    directory=profile/'minescript/lab-results';plain(directory)
    ticket=directory/'bootstrap-launch-authorization.json';plain(ticket)
    if ticket.exists():
        previous=json.loads(ticket.read_text())
        if previous.get('schema')!='fabric-lab-launch-authorization-v1' or not re.fullmatch('[a-f0-9]{32}',previous.get('nonce','')):
            raise ValueError('Previous bootstrap ticket identity is malformed; preserve and inspect it')
        accepted=directory/('bootstrap-'+previous['nonce']+'-accepted.json')
        plain(accepted)
        if previous.get('expires_unix_ms',0)>time.time_ns()//10**6 and not accepted.exists():
            raise ValueError('An unconsumed launch authorization is still pending; inspect it before retrying')
    now=time.time_ns()//10**6
    value={'schema':'fabric-lab-launch-authorization-v1','status':'armed','nonce':uuid.uuid4().hex,
           'created_unix_ms':now,'expires_unix_ms':now+300000,'minecraft':'26.1.2',
           'profile':str(profile),'world_folder':world,'world_names':settings['world_names'],
           'master_archive':str(master),'master_sha256':expected_sha256,'helper_sha256':lock['sha256'],
           'level_dat_sha256':file_hash(save/'level.dat'),'conditions_sha256':file_hash(conditions),
           'datapack_files':packs}
    if not check_only:
        directory.mkdir(exist_ok=True);pending=ticket.with_suffix('.pending')
        with pending.open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)
        pending.replace(ticket)
    return {'nonce':value['nonce'],'authorization_written':not check_only,'ticket':str(ticket),
            'expected_acceptance_receipt':str(directory/('bootstrap-'+value['nonce']+'-accepted.json'))}
