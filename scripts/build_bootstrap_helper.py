"""Compile the lab helper using an existing Java 25 JDK and cached Modrinth libraries; no downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
NAME='fabric-benchmark-bootstrap-26.1.2-0.1.0.jar'


def build(jdk,meta):
    helper=ROOT/'bootstrap-helper';build=helper/'build';classes=build/'classes'
    classes.mkdir(parents=True,exist_ok=True)
    game=meta/'versions/26.1.2/26.1.2.jar'
    version=json.loads((meta/'versions/26.1.2/26.1.2.json').read_text())
    paths=[game]
    for library in version['libraries']:
        artifact=library.get('downloads',{}).get('artifact')
        if artifact:
            path=meta/'libraries'/artifact['path']
            if path.exists():paths.append(path)
    for relative in ('net/fabricmc/fabric-loader/0.19.5/fabric-loader-0.19.5.jar',
                     'net/fabricmc/sponge-mixin/0.17.4+mixin.0.8.7/sponge-mixin-0.17.4+mixin.0.8.7.jar'):
        paths.append((meta/'libraries'/relative).resolve(strict=True))
    cp=';'.join(str(p) for p in paths)
    sources=sorted((helper/'src').rglob('*.java'))
    jar=build/NAME
    mixin_package=json.loads((helper/'resources/fabric-benchmark-bootstrap.mixins.json').read_text())['package']
    for source in sources:
        content=source.read_text()
        if 'package '+mixin_package+';' in content and '@Mixin(' not in content:
            raise ValueError('Ordinary helper classes must stay outside the reserved Mixin package')
    with tempfile.TemporaryDirectory(prefix='compile-',dir=build) as temporary:
        compiled=Path(temporary)/'classes';compiled.mkdir()
        subprocess.run([str(jdk/'bin/javac.exe'),'-proc:none','--release','25','-classpath',cp,'-d',str(compiled),*[str(p) for p in sources]],check=True)
        with zipfile.ZipFile(jar,'w') as package:
            entries=[(p,p.relative_to(compiled).as_posix()) for p in sorted(compiled.rglob('*.class'))]
            entries.extend((p,p.relative_to(helper/'resources').as_posix()) for p in sorted((helper/'resources').rglob('*')) if p.is_file())
            for path,name in entries:
                info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                package.writestr(info,path.read_bytes())
        import shutil
        for path in compiled.rglob('*.class'):
            target=classes/path.relative_to(compiled);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    lock={'schema':'fabric-lab-bootstrap-build-v1','filename':NAME,'sha256':hashlib.sha256(jar.read_bytes()).hexdigest(),
          'source_sha256':{p.relative_to(helper).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
          'minecraft':'26.1.2','fabric_loader':'0.19.5'}
    (build/'helper-lock.json').write_text(json.dumps(lock,indent=2))
    (build/'classpath.txt').write_text(cp)
    print(json.dumps(lock,indent=2));return jar


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--jdk',type=Path,required=True);parser.add_argument('--meta',type=Path,required=True)
    args=parser.parse_args();build(args.jdk.resolve(strict=True),args.meta.resolve(strict=True))
