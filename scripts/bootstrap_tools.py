"""Install pinned diagnostic tools into this project's parent Modrinth profile.

Run with the bundled Python or another Python 3.11+ runtime. No game is launched.
All downloads and dependency checks finish before any profile jar is added.
Existing files are never overwritten. Use --check for a read-only preflight.
"""

import argparse
import json
import os
import tempfile
import urllib.request
from pathlib import Path

from fabric_inventory import PredicateChecker, inventory, sha512, validate


ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"User-Agent": "Sploosh4-modpack-performance-lab/0.1"}
PINNED = {
    "fabric-api": "3dM0X6ou",
    "spark": "e3hsPc1o",
    "minescript": "wib8NXKz",
    "chunky": "4Eotm6ov",
    "entity-detective": "cIcm8QRn",
}


def fetch_json(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.load(response)


def build_lock(pinned=None):
    components = []
    for slug, version_id in (PINNED if pinned is None else pinned).items():
        project = fetch_json("https://api.modrinth.com/v2/project/" + slug)
        version = fetch_json("https://api.modrinth.com/v2/version/" + version_id)
        if "26.1.2" not in version["game_versions"] or "fabric" not in version["loaders"]:
            raise RuntimeError("Wrong game/loader for " + slug)
        primary = next(file for file in version["files"] if file["primary"])
        components.append({
            "slug": slug,
            "project_id": project["id"],
            "version_id": version_id,
            "version": version["version_number"],
            "license": project["license"]["id"],
            "source": project.get("source_url"),
            "dependencies": version["dependencies"],
            "filename": primary["filename"],
            "url": primary["url"],
            "sha512": primary["hashes"]["sha512"],
            "size": primary["size"],
        })
    covered_projects = {component["project_id"] for component in components}
    covered_versions = {component["version_id"] for component in components}
    for component in components:
        for dependency in component["dependencies"]:
            if dependency["dependency_type"] != "required":
                continue
            if dependency.get("version_id"):
                covered = dependency["version_id"] in covered_versions
            else:
                covered = dependency.get("project_id") in covered_projects
            if not covered:
                raise RuntimeError("Unresolved dependency: " + repr(dependency))
    return {"minecraft": "26.1.2", "loader": "fabric", "components": components}


def preflight(lock, runtime, destination, install=False):
    destination = Path(destination)
    if not destination.is_dir():
        raise RuntimeError("Expected existing Modrinth profile mods directory")
    if lock["minecraft"] != runtime["minecraft"] or lock["loader"] != "fabric":
        raise RuntimeError("Lock and runtime target differ")
    components = lock["components"]
    names = [component["filename"] for component in components]
    if len(set(name.casefold() for name in names)) != len(names):
        raise RuntimeError("Duplicate pinned filenames")
    for name in names:
        if Path(name).name != name or "/" in name or "\\" in name or not name.endswith(".jar"):
            raise RuntimeError("Unsafe pinned filename")
    stale = [item.name for item in destination.iterdir()
             if item.is_file() and item.name.lower().endswith((".download", ".part"))]
    if stale:
        raise RuntimeError("Stale download files require inspection; preserving them: " + ", ".join(stale))
    existing = sorted(destination.glob("*.jar"))
    before = {item.name: sha512(item) for item in existing}
    checker = PredicateChecker(ROOT, runtime)
    # Validate the full proposed set rather than each jar in isolation.
    with tempfile.TemporaryDirectory(prefix=".modpack-stage-", dir=destination) as staging:
        staged = []
        for component in components:
            target = destination / component["filename"]
            if target.exists():
                if target.stat().st_size != component["size"] or sha512(target) != component["sha512"]:
                    raise RuntimeError("Existing pinned filename differs; preserving it: " + target.name)
                continue
            if not install:
                raise RuntimeError("Pinned jar missing: " + target.name)
            temporary = Path(staging) / target.name
            request = urllib.request.Request(component["url"], headers=HEADERS)
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("xb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            if temporary.stat().st_size != component["size"] or sha512(temporary) != component["sha512"]:
                raise RuntimeError("Downloaded file failed verification: " + target.name)
            staged.append((temporary, target))
        paths = [*existing, *(source for source, _ in staged)]
        report = validate(inventory(paths, runtime.get("environment", "client")), runtime, checker)
        after = {item.name: sha512(item) for item in destination.glob("*.jar")}
        if before != after:
            raise RuntimeError("Profile changed during preflight; no staged mods installed")
        added = []
        try:
            for source, target in staged:
                # Both paths are on the destination volume. Windows rename
                # refuses an existing target, preserving concurrent user files.
                if os.name != "nt":
                    raise RuntimeError("Atomic no-overwrite installation is currently Windows-only")
                source.rename(target)
                added.append((target, sha512(target)))
        except BaseException:
            # Roll back only verified files created by this invocation.
            for target, digest in reversed(added):
                if target.is_file() and sha512(target) == digest:
                    target.unlink()
            raise
        report.update({"pinned_components": len(components), "added_files": [path.name for path, _ in added],
                       "files": {path.name: sha512(path) for path in destination.glob("*.jar")},
                       "status": "static preflight passed"})
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-lock", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--runtime", type=Path, default=ROOT / "local.settings.json")
    parser.add_argument("--destination", type=Path, default=ROOT.parent / "mods")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    lock_path = ROOT / "manifests" / "tools-lock.json"
    if args.refresh_lock:
        lock = build_lock()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        print("Wrote pinned tool lock")
    else:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if args.install or args.check:
        runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
        report = preflight(lock, runtime, args.destination, install=args.install)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
