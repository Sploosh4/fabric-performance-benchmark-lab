"""Explicit machine-local configuration; no account data or launcher database writes."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
ENV='FABRIC_BENCHMARK_CONFIG'


def load(path=None,required=True):
    path=Path(path or os.environ.get(ENV,ROOT/'benchmark.local.json')).resolve()
    if not path.is_file():
        if required:raise ValueError('Create a local benchmark configuration with the init command first')
        return SimpleNamespace(configured=False,config_path=path,profile=ROOT/'runtime/unconfigured-profile',
            world_archive=ROOT/'runtime/unconfigured-master.zip',world_archive_sha256='',
            world_folder='Lab_RestWorld_benchmark',outputs=ROOT/'runtime/outputs',state=ROOT/'runtime',
            presentmon=Path(os.environ.get('PROGRAMFILES',r'C:\Program Files'))/'Intel/PresentMon/PresentMonConsoleApplication/PresentMon-2.6.0-x64.exe',
            presentmon_sha256='b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af',data={})
    data=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data,dict):raise ValueError('Configuration must be a JSON object')
    if data.get('schema')!='fabric-performance-benchmark-config-v1':raise ValueError('Unsupported configuration schema')
    if data.get('minecraft')!='26.1.2' or data.get('loader')!='fabric' or data.get('fabric_loader')!='0.19.5':
        raise ValueError('This release supports Fabric 0.19.5 / Minecraft 26.1.2 only')
    def location(key):
        value=data.get(key)
        if not isinstance(value,str) or not value:raise ValueError('Missing configured path: '+key)
        candidate=Path(value).expanduser()
        return (candidate if candidate.is_absolute() else path.parent/candidate).absolute()
    world=data.get('world_folder','')
    if not isinstance(world,str) or not world.startswith('Lab_') or Path(world).name!=world or world.endswith(('.', ' ')) or any(c in world for c in ('/','\\',':')):
        raise ValueError('Use a simple Lab_ disposable-world folder name')
    limit=data.get('maximum_run_bytes',1024**4)
    if type(limit) is not int or limit<1024**3:raise ValueError('Runaway-output limit must be an integer of at least 1 GiB')
    profile=location('profile');state=location('state');outputs=location('outputs');archive=location('world_archive')
    if any(p.resolve().is_relative_to(profile.resolve()) for p in (state,outputs,archive)):
        raise ValueError('Master archive, state and output paths must be outside the game profile')
    if state.resolve().is_relative_to(outputs.resolve()) or outputs.resolve().is_relative_to(state.resolve()):
        raise ValueError('Use separate state and output directories')
    return SimpleNamespace(configured=True,config_path=path,data=data,profile=location('profile'),
        world_archive=location('world_archive'),world_archive_sha256=data.get('world_archive_sha256',''),
        world_folder=world,outputs=location('outputs'),state=location('state'),
        presentmon=location('presentmon'),presentmon_sha256=data.get('presentmon_sha256',''))
