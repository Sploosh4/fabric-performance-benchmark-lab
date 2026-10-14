"""Offline entrypoint: no host broker, live-game commands, elevation or network service."""
import argparse
import json
from pathlib import Path,PurePosixPath
import re
import stat
import sys
import unittest
import zipfile

from experiment_protocol import file_hash
from lab_settings import ROOT
from world_restore import plain

INPUT=Path('/data/input')
OUTPUT=Path('/data/output')


def within(path,root):
    path=Path(path);plain(path);plain(root)
    resolved=path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError('Use an explicitly mounted data path under '+str(root))
    return resolved


def inspect_world(path):
    """Inspect the archive without extracting or replacing any world."""
    with zipfile.ZipFile(path) as package:
        entries=package.infolist()
        if len(entries)>20000 or sum(e.file_size for e in entries)>512*1024*1024:
            raise ValueError('World archive exceeds bounded limits')
        roots=set();seen=set()
        for entry in entries:
            name=PurePosixPath(entry.filename)
            if not name.parts or name.is_absolute() or '..' in name.parts or ':' in entry.filename or '\\' in entry.filename or stat.S_ISLNK(entry.external_attr>>16):
                raise ValueError('Unsafe world archive entry')
            roots.add(name.parts[0])
            if not entry.is_dir():
                key=PurePosixPath(*name.parts[1:]).as_posix().casefold()
                if len(name.parts)<2 or key in seen:raise ValueError('Duplicate or root-only archive file')
                seen.add(key)
        if len(roots)!=1 or 'level.dat' not in seen:
            raise ValueError('Expected one top-level world containing level.dat')
    return {'status':'archive_metadata_verified','benchmark_accepted':False,'sha256':file_hash(path),
            'files':len(seen),'uncompressed_bytes':sum(e.file_size for e in entries),
            'scope':'Archive names, bounds and fingerprint only; contents/CRC and world compatibility not tested. No extraction or restoration.'}


def write_reports(value,directory,name):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}',name):raise ValueError('Use a simple report name')
    directory=within(directory,OUTPUT)
    if not directory.is_dir():raise ValueError('Report destination must be a directory')
    targets=[directory/(name+suffix) for suffix in ('.json','.md')]
    for path in targets:
        plain(path)
        if path.exists():raise ValueError('Report already exists; choose another name: '+path.name)
    encoded=json.dumps(value,indent=2,allow_nan=False)+'\n'
    warning='Diagnostic integration only. Do not use these frame values for performance comparisons.' if value.get('diagnostic_only') else 'Use the status and methodology gates below; a report alone is not a universal mod ranking.'
    markdown='# Fabric Performance Benchmark Lab report\n\n'+warning+'\n\nStatus: `'+str(value.get('status','unknown'))+'`.\n\n```json\n'+encoded+'```\n'
    for path,content in zip(targets,(encoded,markdown)):
        with path.open('x',encoding='utf-8') as stream:stream.write(content)
    return [str(path) for path in targets]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('test',help='Synthetic offline tests; no game/capture processes')
    for command in ('analyze','diagnostic','compare','inspect-world'):
        p=sub.add_parser(command)
        p.add_argument('input',type=Path)
        p.add_argument('--output',type=Path,default=OUTPUT)
        p.add_argument('--name',default=command)
        if command=='compare':
            p.add_argument('--control',type=Path,required=True)
            p.add_argument('--control-after',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='test':
            result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(str(ROOT/'scripts'),pattern='test_*.py'))
            return 0 if result.wasSuccessful() else 1
        source=within(args.input,INPUT)
        if args.command=='inspect-world':value=inspect_world(source)
        elif args.command=='diagnostic':
            from analyze_session import analyze
            value=analyze(source)
            if not value.get('diagnostic_only'):raise ValueError('Use analyze for a normal benchmark suite')
        else:
            from analyze_benchmark import score_suite,compare
            measured=score_suite(source)
            value=compare(score_suite(within(args.control,INPUT)),measured,score_suite(within(args.control_after,INPUT))) if args.command=='compare' else measured
        print(json.dumps({'reports':write_reports(value,args.output,args.name),'status':value['status']}))
        return 0
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,zipfile.BadZipFile) as error:
        print('REJECTED: '+str(error),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
