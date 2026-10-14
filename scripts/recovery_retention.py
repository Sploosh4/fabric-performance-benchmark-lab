"""Bound retention for explicitly owned, unchanged test-world recovery copies."""
import json
from pathlib import Path
import re
import stat
import time

from experiment_protocol import digest,file_hash

OWNER='modpack-restworld-recovery-v1'
NAME=re.compile(r'[0-9]{8}-[0-9]{6}-[a-f0-9]{8}')


def plain(path):
    # Windows junctions and symlinks can escape a recursively removed directory.
    if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
        raise ValueError('Recovery path contains a reparse point')


def tree_hash(path):
    plain(path)
    files={}
    for child in path.rglob('*'):
        plain(child)
        if child.is_file():files[child.relative_to(path).as_posix()]=file_hash(child)
    if 'level.dat' not in files:raise ValueError('Recovery copy is not a world')
    return digest(files)


def register(root,path,backup_sha256,source_world):
    root=Path(root);path=Path(path)
    plain(root);plain(path)
    if path.resolve().parent!=root.resolve() or not NAME.fullmatch(path.name):
        raise ValueError('Recovery path escaped the owned root or naming convention')
    marker=root/('recovery-'+path.name+'.json')
    value={'owner':OWNER,'name':path.name,'source_backup_sha256':backup_sha256,
           'source_world':str(source_world),'tree_sha256':tree_hash(path),'created_unix_ns':time.time_ns()}
    with marker.open('x',encoding='utf-8') as output:json.dump(value,output,indent=2)
    return marker


def prune(root,keep_name,backup_sha256,source_world):
    """Delete only hash-verified copies with explicit creation receipts; keep current."""
    import shutil
    root=Path(root);plain(root)
    if not NAME.fullmatch(keep_name):raise ValueError('Invalid retained recovery name')
    keep=root/keep_name;keep_marker=root/('recovery-'+keep_name+'.json')
    if not keep_marker.is_file():raise ValueError('Retained recovery ownership receipt missing')
    records=[]
    for marker in root.glob('recovery-*.json'):
        plain(marker)
        value=json.loads(marker.read_text(encoding='utf-8'))
        name=value.get('name','')
        if value.get('owner')!=OWNER or not NAME.fullmatch(name) or marker.name!='recovery-'+name+'.json':
            raise ValueError('Recovery ownership receipt differs')
        if value.get('source_backup_sha256')!=backup_sha256 or value.get('source_world')!=str(source_world):
            raise ValueError('Recovery source identity differs')
        target=root/name
        plain(target)
        if target.resolve().parent!=root.resolve() or tree_hash(target)!=value['tree_sha256']:
            raise ValueError('Recovery copy escaped the root or changed; preserve it')
        records.append((name,target,marker))
    # Validate all targets and the retained copy before removing any directory.
    if keep_name not in {name for name,_,_ in records}:raise ValueError('Retained recovery not verified')
    removed=[]
    for name,target,marker in records:
        if name==keep_name:continue
        plain(target)
        if target.resolve().parent!=root.resolve():raise ValueError('Delete target escaped owned root')
        shutil.rmtree(target)
        marker.unlink()
        removed.append(name)
    return removed
