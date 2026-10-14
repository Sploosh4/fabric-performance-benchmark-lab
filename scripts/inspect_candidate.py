"""Inspect one downloaded candidate and its nested libraries; never installs or executes it."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

from lab_settings import load
SETTINGS=load(required=False)
SOURCE=Path(SETTINGS.data.get('candidate_source',SETTINGS.state/'candidate-source')).resolve()


def inspect(path):
    path=Path(path).resolve(strict=True)
    if path.parent!=SOURCE or path.suffix!=".jar":raise ValueError("Candidate must be a JAR in the approved read-only collection")
    raw=path.read_bytes()
    result={"path":str(path),"size":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"sha512":hashlib.sha512(raw).hexdigest()}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        value=json.loads(archive.read("fabric.mod.json"))
        result["fabric_metadata"]=value;result["nested_mods"]=[]
        for nested in value.get("jars",[]):
            name=nested["file"]
            info=archive.getinfo(name)
            if info.file_size>16*1024**2:raise ValueError("Nested dependency exceeds inspection bound")
            with zipfile.ZipFile(io.BytesIO(archive.read(name))) as inner:
                if "fabric.mod.json" in inner.namelist():result["nested_mods"].append(json.loads(inner.read("fabric.mod.json")))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("filename")
    args=parser.parse_args();value=inspect(SOURCE/args.filename)
    target=SETTINGS.state/'candidate-artifacts'
    target.mkdir(parents=True,exist_ok=True)
    (target/(value["fabric_metadata"]["id"]+".json")).write_text(json.dumps(value,indent=2))
    print(json.dumps({"id":value["fabric_metadata"]["id"],"version":value["fabric_metadata"]["version"],
                      "depends":value["fabric_metadata"].get("depends",{}),"breaks":value["fabric_metadata"].get("breaks",{}),
                      "nested_mod_ids":[m["id"] for m in value["nested_mods"]],"sha256":value["sha256"]},indent=2))
