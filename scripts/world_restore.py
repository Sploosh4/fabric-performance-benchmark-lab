"""Verified disposable-world replacement, rollback and bounded recovery retention."""
from datetime import datetime
import json
from pathlib import Path,PurePosixPath
import re
import stat
import tempfile
import time
import uuid
import zipfile

from experiment_protocol import digest,file_hash
from recovery_retention import register,prune


def plain(path):
    for candidate in (path,*path.parents):
        if not candidate.exists() and not candidate.is_symlink():continue
        info=candidate.lstat()
        if candidate.is_symlink() or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
            raise ValueError('World paths must not contain symlinks or junctions')


def rename(source,destination):
    source.rename(destination)


def restore(archive,destination,recovery_root,expected_sha256,closed,retain_failed_stage=False,prune_owned=False):
    archive=Path(archive);destination=Path(destination);recovery_root=Path(recovery_root)
    if not re.fullmatch('[a-f0-9]{64}',expected_sha256):raise ValueError('An exact master archive SHA256 is required')
    if not destination.name.startswith('Lab_'):raise ValueError('Only an explicitly named disposable Lab_ world can be restored')
    closed()
    for path in (archive,destination.parent,recovery_root):plain(path)
    if destination.exists():plain(destination)
    if destination.exists() and (not destination.is_dir() or not (destination/'level.dat').is_file()):
        raise ValueError('Existing disposable destination is not a recognized world; preserve it')
    if file_hash(archive)!=expected_sha256:raise ValueError('Master world archive hash differs')
    if destination.resolve().is_relative_to(recovery_root.resolve()) or recovery_root.resolve().is_relative_to(destination.resolve()) or archive.resolve().is_relative_to(destination.resolve()):
        raise ValueError('Archive/recovery data must stay outside the active disposable world')
    # Validate all names/sizes before extracting. A failed stage is always removed.
    with zipfile.ZipFile(archive) as package:
        entries=package.infolist()
        if len(entries)>20000 or sum(e.file_size for e in entries)>512*1024*1024:raise ValueError('World archive exceeds bounded limits')
        roots=set();seen=set();members=[]
        for entry in entries:
            name=PurePosixPath(entry.filename)
            if not name.parts or name.is_absolute() or '..' in name.parts or ':' in entry.filename or '\\' in entry.filename or stat.S_ISLNK(entry.external_attr>>16):
                raise ValueError('Unsafe world archive entry')
            roots.add(name.parts[0]);relative=Path(*name.parts[1:])
            key=relative.as_posix().casefold()
            if not entry.is_dir():
                if not name.parts[1:] or key in seen:raise ValueError('Duplicate or root-only archive file')
                seen.add(key)
                if key!='session.lock':members.append((entry,relative))
        if len(roots)!=1 or 'level.dat' not in seen:raise ValueError('Expected one top-level world containing level.dat')
        recovery_root.mkdir(parents=True,exist_ok=True);plain(recovery_root)
        with tempfile.TemporaryDirectory(prefix='.fabric-bench-restore-',dir=destination.parent) as temporary:
            stage=Path(temporary)/'world';stage.mkdir();expected={}
            try:
                for entry,relative in members:
                    target=stage/relative
                    if not target.resolve().is_relative_to(stage.resolve()):raise ValueError('Archive escaped staging')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with package.open(entry) as source,target.open('xb') as output:
                        while chunk:=source.read(1024*1024):output.write(chunk)
                    if target.stat().st_size!=entry.file_size:raise ValueError('Archive extraction size differs')
                    expected[relative.as_posix()]=file_hash(target)
                closed()
                if any(file_hash(stage/name)!=sha for name,sha in expected.items()):raise ValueError('Staged world changed')
            except Exception:
                if retain_failed_stage:
                    diagnostic=recovery_root/('failed-stage-'+uuid.uuid4().hex)
                    stage.rename(diagnostic)
                raise
            preserved=recovery_root/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
            if destination.exists():
                plain(destination);rename(destination,preserved)
            try:rename(stage,destination)
            except BaseException:
                if preserved.exists() and not destination.exists():rename(preserved,destination)
                raise
    value={'schema':'modpack-world-origin-v1','backup_sha256':expected_sha256,
           'restored_file_tree_sha256':digest(expected),'restored_unix_ns':time.time_ns(),
           'preserved_save':str(preserved) if preserved.exists() else None,'verified_files':len(expected)}
    if preserved.exists():
        try:
            closed();register(recovery_root,preserved,expected_sha256,destination)
            value['removed_owned_recovery_copies']=prune(recovery_root,preserved.name,expected_sha256,destination) if prune_owned else []
            value['recovery_retention']='one-most-recent-receipted-test-copy' if prune_owned else 'preserve-until-explicit-prune'
        except Exception as error:value['recovery_retention_pending']=str(error)
    return value
