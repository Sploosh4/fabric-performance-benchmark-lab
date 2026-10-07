"""Install pinned diagnostic tools into this project's parent Modrinth profile.

Run with the bundled Python or another Python 3.11+ runtime. No game is launched.
Existing files are preserved unless their SHA-512 already matches the lock.
"""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


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


def build_lock():
    components = []
    for slug, version_id in PINNED.items():
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


def sha512(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha512").hexdigest()


def install(lock):
    destination = ROOT.parent / "mods"
    if not destination.is_dir():
        raise RuntimeError("Expected existing Modrinth profile mods directory")
    for component in lock["components"]:
        name = component["filename"]
        if Path(name).name != name:
            raise RuntimeError("Unsafe filename")
        target = destination / name
        if target.exists():
            if sha512(target) != component["sha512"]:
                raise RuntimeError("Existing file differs; refusing overwrite: " + name)
            print("Already installed:", name)
            continue
        temporary = target.with_suffix(target.suffix + ".download")
        request = urllib.request.Request(component["url"], headers=HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("xb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            if temporary.stat().st_size != component["size"] or sha512(temporary) != component["sha512"]:
                raise RuntimeError("Downloaded file failed verification: " + name)
            temporary.rename(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        print("Installed:", name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-lock", action="store_true")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    lock_path = ROOT / "manifests" / "tools-lock.json"
    if args.refresh_lock:
        lock = build_lock()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        print("Wrote pinned tool lock")
    else:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if args.install:
        install(lock)


if __name__ == "__main__":
    main()
