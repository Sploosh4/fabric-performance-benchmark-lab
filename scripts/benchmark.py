"""Checked command interface for the Windows Fabric performance benchmark lab."""
import argparse
import ast
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

from lab_settings import ROOT,ENV,load
from experiment_protocol import digest,file_hash,validate_manifest


def write_new(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2);stream.write('\n')


def init(args):
    profile=args.profile.resolve(strict=True);archive=args.world_archive.resolve(strict=True)
    if not (profile/'mods').is_dir() or not (profile/'saves').is_dir():raise ValueError('Create a dedicated Fabric profile with mods and saves directories first')
    config={'schema':'fabric-performance-benchmark-config-v1','minecraft':'26.1.2','loader':'fabric','fabric_loader':'0.19.5',
            'profile':str(profile),'world_archive':str(archive),'world_archive_sha256':file_hash(archive),
            'world_folder':args.world_folder,'state':str(ROOT/'runtime/state'),'outputs':str(ROOT/'runtime/outputs'),
            'presentmon':str(args.presentmon.resolve(strict=True)),'presentmon_sha256':file_hash(args.presentmon),
            'maximum_run_bytes':1024**4,'world_names':['RestWorld_26.1',args.world_folder]}
    if config['presentmon_sha256']!='b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af':
        raise ValueError('This release requires the verified PresentMon 2.6.0 console binary, not its GUI')
    # Validate the complete prospective config without replacing an existing one.
    import tempfile
    with tempfile.TemporaryDirectory(dir=args.config.parent) as temp:
        candidate=Path(temp)/'config.json';candidate.write_text(json.dumps(config));load(candidate)
    write_new(args.config,config)
    return {'config':str(args.config),'world_sha256':config['world_archive_sha256']}


def instrumentation():
    """Resolve the local Python dependency closure without importing game APIs."""
    sources={p.stem:p for directory in (ROOT/'scripts',ROOT/'scenarios') for p in directory.glob('*.py')}
    pending=['labprepare','labrun','labcancel','labstate','labpose','labautorun'];result={}
    while pending:
        name=pending.pop()
        if name in result:continue
        path=sources[name];result[name+'.py']=path
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node,ast.ImportFrom):names=[(node.module or '').split('.')[0]]
            elif isinstance(node,ast.Import):names=[item.name.split('.')[0] for item in node.names]
            else:continue
            pending.extend(name for name in names if name in sources and name+'.py' not in result)
    return result


def conditions_for(settings):
    conditions=json.loads((ROOT/'presets/lab-conditions.json').read_text())
    conditions.update(configured_profile=str(settings.profile),world_folder=settings.world_folder,
                      world_names=settings.data.get('world_names',['RestWorld_26.1',settings.world_folder]))
    return conditions


def setup_payload(settings):
    """Only lab-owned scripts/conditions and the Python command are changed."""
    payload={name:path.read_bytes() for name,path in instrumentation().items()}
    payload['lab-conditions.json']=(json.dumps(conditions_for(settings),indent=2)+'\n').encode()
    config=settings.profile/'minescript/config.txt'
    lines=config.read_text(encoding='utf-8-sig').splitlines() if config.exists() else []
    lines=[line for line in lines if not re.match(r'^\s*python\s*=',line)]
    # An explicit world-name hook is idle unless a fresh lab request exists.
    worlds=settings.data.get('world_names',['RestWorld_26.1',settings.world_folder])
    for world in worlds:
        if not isinstance(world,str) or not world or any(c in world for c in '*[]=\r\n'):
            raise ValueError('Autorun requires simple explicit world display names')
    existing=[]
    for line in lines:
        match=re.match(r'^\s*autorun\[([^]]+)\]\s*=\s*(.*)$',line)
        if match and (match[1]=='*' or match[1] in worlds):
            if match[1]=='*' or match[2].lstrip('\\')!='labautorun':
                raise ValueError('Existing matching/wildcard autorun needs explicit reconciliation before setup')
            continue
        existing.append(line)
    lines=existing
    lines.append('python='+json.dumps(sys.executable.replace('\\','/')))
    lines.extend('autorun['+world+']=labautorun' for world in dict.fromkeys(worlds))
    payload['config.txt']=('\n'.join(lines)+'\n').encode()
    return payload


def check(settings,installed=False):
    from world_restore import plain
    if os.name!='nt':raise ValueError('Live preparation and captures require Windows')
    for path in (settings.profile,settings.world_archive,settings.presentmon,settings.state,settings.outputs):plain(path)
    if file_hash(settings.world_archive)!=settings.world_archive_sha256:raise ValueError('Master world hash differs')
    if file_hash(settings.presentmon)!=settings.presentmon_sha256 or settings.presentmon_sha256!='b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af':raise ValueError('PresentMon console identity differs')
    from manage_experiment import metadata
    mods={}
    for jar in (settings.profile/'mods').glob('*.jar'):
        value=metadata(jar)
        if value['id'] in mods:raise ValueError('Duplicate mod ID: '+value['id'])
        mods[value['id']]=value['version']
    required={'fabric-api':'0.155.3+26.1.2','minescript':'5.0-fabric-26.1.2'}
    # Version strings from the verified JAR metadata, rather than Modrinth labels.
    for component in json.loads((ROOT/'manifests/tools-lock.json').read_text())['components']:
        if component['slug'] not in required:continue
        jar=settings.profile/'mods'/component['filename']
        if not jar.is_file() or hashlib.sha512(jar.read_bytes()).hexdigest()!=component['sha512']:
            raise ValueError('Install the pinned '+component['slug']+' JAR from tools-lock.json')
    if installed:
        for name,source in instrumentation().items():
            if file_hash(settings.profile/'minescript'/name)!=file_hash(source):raise ValueError('Installed instrumentation differs: '+name)
        conditions=json.loads((settings.profile/'minescript/lab-conditions.json').read_text())
        if conditions!=conditions_for(settings):raise ValueError('Installed conditions differ from the fixed profile/world/graphics contract')
    return {'status':'offline_preflight_passed','mods':mods,'live_validation':'pending'}


def setup(settings):
    from manage_experiment import closed
    closed();check(settings)
    directory=settings.profile/'minescript';directory.mkdir(exist_ok=True)
    payload=setup_payload(settings)
    # Validate ALL existing paths before copying any. No user scripts overwritten.
    for name,raw in payload.items():
        target=directory/name
        if target.exists() and target.read_bytes()!=raw:raise ValueError('Existing instrumentation differs; preserve/move it before setup: '+name)
    closed()
    for name,raw in payload.items():
        if not (directory/name).exists():
            with (directory/name).open('xb') as stream:stream.write(raw)
    return {'installed_files':sorted(payload),'world_changed':False,'mods_changed':False}


def prepare(settings,args):
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',args.name):raise ValueError('Use a simple lowercase configuration ID')
    if args.role=='candidate' and args.control is None:raise ValueError('Candidate requires --control pointing to the original pinned control manifest')
    if args.control is not None:
        control=validate_manifest(json.loads(args.control.read_text()))
        if control['role']!='control':raise ValueError('The original manifest must be a control')
    check(settings,installed=True)
    import manage_experiment as manager
    manager.closed()
    restored=manager.restore_world(args.retain_failed_stage,args.prune_owned_recovery)
    pinned=manager.pin(args.name,args.role,args.control,route_only=True)
    return {'restored':restored,'pinned':pinned,'next':'Launch the configured profile/world, then start session watcher'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path(os.environ.get(ENV,ROOT/'benchmark.local.json')))
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('init');p.add_argument('--profile',type=Path,required=True);p.add_argument('--world-archive',type=Path,required=True)
    p.add_argument('--world-folder',default='Lab_RestWorld_benchmark');p.add_argument('--presentmon',type=Path,required=True)
    sub.add_parser('check');sub.add_parser('setup');sub.add_parser('migration-plan')
    p=sub.add_parser('migrate');p.add_argument('--plan',type=Path,required=True)
    p=sub.add_parser('prepare');p.add_argument('--name',required=True);p.add_argument('--role',choices=('control','candidate'),required=True)
    p.add_argument('--control',type=Path);p.add_argument('--retain-failed-stage',action='store_true');p.add_argument('--prune-owned-recovery',action='store_true')
    sub.add_parser('broker');sub.add_parser('stop-broker');sub.add_parser('launch')
    p=sub.add_parser('functional-auto-launch');p.add_argument('--diagnostic-only',action='store_true')
    p=sub.add_parser('clear-measurement-window');p.add_argument('--minutes',type=int,default=30);p.add_argument('--diagnostic-only',action='store_true')
    p=sub.add_parser('measured-auto-launch');p.add_argument('--measurement-window',required=True)
    p.add_argument('--repeats',type=int,choices=(1,3,5),default=3)
    p=sub.add_parser('refresh-configs');p.add_argument('--control',type=Path)
    p=sub.add_parser('session');p.add_argument('--repeats',type=int,choices=(3,5),default=3)
    p=sub.add_parser('analyze');p.add_argument('suite',type=Path)
    p=sub.add_parser('compare');p.add_argument('candidate',type=Path);p.add_argument('--control',type=Path,required=True);p.add_argument('--control-after',type=Path,required=True)
    args=parser.parse_args(argv);args.config=args.config.resolve();os.environ[ENV]=str(args.config)
    try:
        if args.command=='init':result=init(args)
        elif args.command in ('analyze','compare'):
            from analyze_benchmark import score_suite,compare
            suite=args.suite if args.command=='analyze' else args.candidate
            result=score_suite(suite) if args.command=='analyze' else compare(score_suite(args.control),score_suite(suite),score_suite(args.control_after))
            write_new(suite/('benchmark-measurement.json' if args.command=='analyze' else 'benchmark-comparison.json'),result)
        else:
            settings=load(args.config)
            if args.command=='check':result=check(settings,installed=True)
            elif args.command=='setup':result=setup(settings)
            elif args.command=='migration-plan':
                from instrumentation_migration import plan
                result=plan(settings)
            elif args.command=='migrate':
                from instrumentation_migration import apply
                result=apply(settings,args.plan)
            elif args.command=='prepare':result=prepare(settings,args)
            elif args.command=='refresh-configs':
                import manage_experiment as manager
                manager.closed();result=manager.refresh_configs(args.control)
            elif args.command=='launch':
                from launch_lab_world import launch
                launch();return 0
            elif args.command=='functional-auto-launch':
                check(settings,installed=True)
                from auto_functional_session import main as functional
                return functional(settings,args.diagnostic_only)
            elif args.command=='clear-measurement-window':
                from auto_measured_session import clear_window
                result=clear_window(settings,args.minutes,args.diagnostic_only)
            elif args.command=='measured-auto-launch':
                check(settings,installed=True)
                from auto_measured_session import main as measured
                return measured(settings,args.measurement_window,args.repeats)
            elif args.command=='broker':
                check(settings,installed=True)
                # Elevation is performed by the human; this command never prompts/relaunches itself.
                from capture_broker import main as broker_main
                broker_main();return 0
            elif args.command=='stop-broker':
                from session_protocol import publish
                settings.outputs.mkdir(parents=True,exist_ok=True);(settings.outputs/'capture-broker').mkdir(exist_ok=True)
                publish(settings.outputs/'capture-broker/stop.json',{'requested_unix_ns':time.time_ns()})
                result={'status':'stop_requested','restart':'After broker stops, manually remove stop.json before a new approved launch'}
            elif args.command=='session':
                check(settings,installed=True)
                manifest=validate_manifest(json.loads((settings.profile/'minescript/lab-experiment.json').read_text()))
                from request_prepared_batch import main as request
                request(SimpleNamespace(repeats=args.repeats,manifest_sha256=digest(manifest)));return 0
        print(json.dumps(result,indent=2,allow_nan=False));return 0
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as error:
        print('REJECTED: '+str(error),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
