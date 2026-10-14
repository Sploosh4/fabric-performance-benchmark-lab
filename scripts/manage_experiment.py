"""Bounded owned-profile staging and per-candidate identity; source collection stays read-only."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

from capture_headless import process_inventory
from experiment_protocol import SCHEMA,POLICY,digest,file_hash,file_inventory,validate_manifest
from room_route_protocol import WORKLOAD as ROOM_WORKLOAD,ROOM_POLICY
from lab_settings import load as load_settings

PACK=Path(__file__).resolve().parents[1]
WORKSPACE=PACK.parent
SETTINGS=load_settings(required=False)
PROFILE=SETTINGS.profile
SOURCE=Path(SETTINGS.data.get('candidate_source',PACK/'runtime/candidate-source'))
WORLD=PROFILE/'saves'/SETTINGS.world_folder
BACKUP_SHA=SETTINGS.world_archive_sha256
REGISTRY=SETTINGS.state/'experiments'


def closed():
    if not SETTINGS.configured:raise RuntimeError('Configure the lab before changing world or mod files')
    if process_inventory(PROFILE)["games"]:raise RuntimeError("Close the owned Minecraft client before changing game files")


def metadata(path):
    if path.is_symlink():raise ValueError("Symlink artifact is not permitted")
    with zipfile.ZipFile(path) as archive:
        value=json.loads(archive.read("fabric.mod.json"))
    if "${" in value["version"]:raise ValueError("Unresolved artifact version")
    return value


def restore_world(retain_failed_stage=False,prune_owned=False):
    from world_restore import restore
    if WORLD.resolve().parent!=(PROFILE/'saves').resolve():raise ValueError('World escaped configured profile saves')
    value=restore(SETTINGS.world_archive,WORLD,SETTINGS.state/'test-saves',BACKUP_SHA,closed,retain_failed_stage,prune_owned)
    (PROFILE/"minescript/lab-world-origin.json").write_text(json.dumps(value,indent=2))
    return value


def pin(name,role,baseline=None,route_only=False):
    closed()
    receipt=json.loads((PROFILE/"minescript/lab-world-origin.json").read_text())
    actual={p.relative_to(WORLD).as_posix():file_hash(p) for p in WORLD.rglob("*") if p.is_file() and p.name!="session.lock"}
    if receipt["backup_sha256"]!=BACKUP_SHA or digest(actual)!=receipt["restored_file_tree_sha256"]:
        raise ValueError("Restore the clean world before pinning")
    expected={"minecraft":"26.1.2","fabricloader":"0.19.5"}
    for path in (PROFILE/"mods").glob("*.jar"):
        value=metadata(path)
        if value["id"] in expected:raise ValueError("Duplicate artifact mod ID")
        expected[value["id"]]=value["version"]
    manifest={"schema":SCHEMA,"configuration_id":name,"role":role,"workload":ROOM_WORKLOAD,
              "analysis_policy":ROOM_POLICY,"world_origin_sha256":BACKUP_SHA,
              "world_restored_tree_sha256":receipt["restored_file_tree_sha256"],
              "conditions_sha256":file_hash(PROFILE/"minescript/lab-conditions.json"),
              "files":file_inventory(PROFILE),"expected_loaded_mods":expected}
    if route_only:
        from session_protocol import ROUTE_BATCH
        manifest["batch_protocol"] = ROUTE_BATCH
    if role=="candidate":
        if baseline is None:raise ValueError("Candidate requires pinned control")
        control=json.loads(Path(baseline).read_text())
        manifest["declared_changed_files"]=sorted(k for k in control["files"].keys()|manifest["files"].keys() if control["files"].get(k)!=manifest["files"].get(k))
    validate_manifest(manifest)
    REGISTRY.mkdir(parents=True,exist_ok=True)
    for path in (PROFILE/"minescript/lab-experiment.json",REGISTRY/(name+".json")):
        path.write_text(json.dumps(manifest,indent=2))
    return {"configuration_id":name,"manifest_sha256":digest(manifest),"expected_loaded_mods":expected}


def refresh_configs(baseline=None, setup_revision=False):
    """Adopt only first-launch-generated config files before any batch is prepared."""
    from session_protocol import fresh_sessions
    if fresh_sessions(PROFILE/"minescript/lab-results"):raise RuntimeError("Do not repin during a prepared or running session")
    path=PROFILE/"minescript/lab-experiment.json";manifest=json.loads(path.read_text())
    actual=file_inventory(PROFILE)
    changes={k for k in actual.keys()|manifest["files"].keys() if actual.get(k)!=manifest["files"].get(k)}
    allowed_prefixes=("config/","minescript/") if setup_revision else ("config/",)
    if setup_revision and manifest["role"]!="control":raise ValueError("Instrumentation setup revision is restricted to the initial control")
    if any(not k.startswith(allowed_prefixes) for k in changes):raise ValueError("Bootstrap changed unexpected files")
    if setup_revision:
        for name in changes:
            if not name.startswith("minescript/"):continue
            target=PROFILE/name
            source=(PACK/"scenarios"/target.name) if (PACK/"scenarios"/target.name).exists() else (PACK/"scripts"/target.name)
            if not target.exists() or not source.exists() or file_hash(target)!=file_hash(source):
                raise ValueError("Setup revision does not match authoritative source")
    manifest["files"]=actual
    if manifest["role"]=="candidate":
        if baseline is None:raise ValueError("Candidate bootstrap requires original control")
        control=json.loads(Path(baseline).read_text())
        manifest["declared_changed_files"]=sorted(k for k in actual.keys()|control["files"].keys() if actual.get(k)!=control["files"].get(k))
    validate_manifest(manifest)
    for target in (path,REGISTRY/(manifest["configuration_id"]+".json")):
        target.write_text(json.dumps(manifest,indent=2))
    return {"configuration_id":manifest["configuration_id"],"adopted_generated_config_files":sorted(changes),"manifest_sha256":digest(manifest)}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("operation",choices=("restore","pin","refresh-configs"));p.add_argument("--configuration");p.add_argument("--role",choices=("control","candidate"));p.add_argument("--control",type=Path);p.add_argument("--setup-revision",action="store_true");p.add_argument("--route-only",action="store_true")
    a=p.parse_args()
    if a.operation=="pin" and (not a.configuration or not a.role):p.error("Pin requires configuration and role")
    value=restore_world() if a.operation=="restore" else pin(a.configuration,a.role,a.control,a.route_only) if a.operation=="pin" else refresh_configs(a.control,a.setup_revision)
    print(json.dumps(value,indent=2))
