"""Optional checked Modrinth deep link; launcher manages credentials, no desktop input."""
from pathlib import Path
import argparse
from contextlib import closing
import json
import sqlite3
import subprocess
from urllib.parse import quote,urlencode
from capture_headless import process_inventory
from lab_settings import load


def launch(check_only=False,profile=None,app=None,database=None,world=None,
           allow_experimental=False,master_archive=None,master_sha256=None):
    if profile is None:
        settings=load();profile=settings.profile
        app=Path(settings.data.get('modrinth_app',''))
        database=Path(settings.data.get('modrinth_database',profile.parent.parent/'app.db'))
        world=settings.world_folder
        allow_experimental=settings.data.get('auto_acknowledge_experimental',False)
        if allow_experimental:
            master_archive=settings.world_archive;master_sha256=settings.world_archive_sha256
    elif app is None or world is None:
        raise ValueError('Explicit launch requires profile, app and disposable world')
    profile=Path(profile);app=Path(app);database=Path(database or profile.parent.parent/'app.db')
    from world_restore import plain
    for path in (profile,app,database):plain(path)
    profile=profile.resolve(strict=True);app=app.resolve(strict=True);database=database.resolve(strict=True)
    if not app.is_file():raise ValueError('For optional launch, configure modrinth_app; otherwise launch the dedicated profile manually')
    if not isinstance(world,str) or not world.startswith('Lab_') or Path(world).name!=world or any(c in world for c in ('/','\\',':')) or world.endswith(('.', ' ')):
        raise ValueError('Launch requires a simple disposable Lab_ world folder')
    if profile.parent!=(database.parent/'profiles').resolve():raise ValueError('Profile is outside this launcher database profiles directory')
    save=profile/'saves'/world
    plain(save)
    if not (save/'level.dat').is_file() or save.resolve().parent!=(profile/'saves').resolve():raise ValueError('Prepare the disposable world first')
    conditions=json.loads((profile/'minescript/lab-conditions.json').read_text())
    if conditions.get('minecraft')!='26.1.2' or conditions.get('world_folder')!=world:
        raise ValueError('Minescript conditions identify another version/world')
    configured=conditions.get('configured_profile')
    if (configured and Path(configured).resolve()!=profile) or (not configured and profile.name!='sodium-automation'):
        raise ValueError('Minescript instance guard is not configured for this profile')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as connection:
        try:
            rows=connection.execute('''SELECT i.id,i.path,i.name,i.install_stage,c.game_version,c.loader,c.loader_version
                FROM instances i JOIN instance_content_sets c ON c.id=i.applied_content_set_id AND c.instance_id=i.id
                WHERE i.path = ?''',(profile.name,)).fetchall()
        except sqlite3.Error as error:raise ValueError('Unsupported Modrinth instance/content-set schema; use manual launch') from error
    if len(rows)!=1:raise ValueError('The launcher database does not identify exactly one matching profile')
    row=rows[0]
    if row[3:]!=('installed','26.1.2','fabric','0.19.5'):raise ValueError('Registered instance is not the installed Fabric 26.1.2 / 0.19.5 target')
    if process_inventory(profile)['games']:raise ValueError('Minecraft is already running; no duplicate launch requested')
    uri='modrinth://launch/instance/'+quote(row[0],safe='')+'?'+urlencode({'singleplayer_world':world})
    report={'status':'launch_preflight_passed' if check_only else 'launch_requested','profile':str(profile),
            'instance_id':row[0],'instance_name':row[2],'world_folder':world,'minecraft':row[4],
            'fabric_loader':row[6],'world_ready_verified':False,'desktop_input_performed':False}
    if allow_experimental:
        if master_archive is None or master_sha256 is None:raise ValueError('Scoped prompt acknowledgement requires the immutable master and its pinned SHA256')
        from bootstrap_authorization import authorize
        report['bootstrap']=authorize(profile,world,master_archive,master_sha256,check_only)
    print('Profile: '+row[2]+'; world: '+world,flush=True)
    if not check_only:
        process=subprocess.Popen([str(app),uri],cwd=app.parent,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        report['launcher_request_pid']=process.pid
    print('Launch requested; live world readiness must still be verified.' if not check_only else 'Read-only launch checks passed.',flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',type=Path);parser.add_argument('--app',type=Path)
    parser.add_argument('--database',type=Path);parser.add_argument('--world');parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--allow-experimental',action='store_true');parser.add_argument('--master-archive',type=Path);parser.add_argument('--master-sha256')
    args=parser.parse_args()
    try:print(json.dumps(launch(args.check_only,args.profile,args.app,args.database,args.world,
                               args.allow_experimental,args.master_archive,args.master_sha256),indent=2))
    except (ValueError,RuntimeError,OSError) as error:
        print('Launch refused: '+str(error));raise SystemExit(2)
