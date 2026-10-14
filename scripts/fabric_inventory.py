"""Conservative static mod preflight; the live Loader remains the final authority."""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

MAX_JAR_BYTES = 128 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_NESTING = 8
MAX_MODULES = 1024


def sha512(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha512").hexdigest()


def inventory(paths, environment="client"):
    modules = []
    total_nested = 0

    def visit(source, location, depth, root, digest):
        nonlocal total_nested
        if depth > MAX_NESTING or len(modules) >= MAX_MODULES:
            raise RuntimeError("Nested mod inventory exceeds bounds")
        with zipfile.ZipFile(source) as jar:
            info = jar.getinfo("fabric.mod.json")
            if info.file_size > MAX_METADATA_BYTES:
                raise RuntimeError("Oversized Fabric metadata: " + location)
            metadata = json.loads(jar.read(info))
            if not isinstance(metadata, dict) or metadata.get("schemaVersion") != 1:
                raise RuntimeError("Unsupported Fabric metadata schema: " + location)
            mod_id, version = metadata.get("id"), metadata.get("version")
            if not isinstance(mod_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", mod_id):
                raise RuntimeError("Invalid Fabric mod ID: " + location)
            if not isinstance(version, str) or not version:
                raise RuntimeError("Missing Fabric mod version: " + location)
            declared_environment = metadata.get("environment", "*")
            if declared_environment not in ("*", "client", "server"):
                raise RuntimeError("Unsupported environment metadata: " + location)
            if declared_environment not in ("*", environment):
                return
            aliases = metadata.get("provides", [])
            if not isinstance(aliases, list) or any(not isinstance(item, str) for item in aliases):
                raise RuntimeError("Invalid provided IDs: " + location)
            modules.append({"id": mod_id, "version": version, "provides": aliases,
                            "location": location, "root": root, "depth": depth,
                            "sha512": digest, "depends": metadata.get("depends", {}),
                            "breaks": metadata.get("breaks", {}),
                            "conflicts": metadata.get("conflicts", {})})
            if depth > 0:
                # Equivalent nested libraries can differ in ZIP timestamps and
                # ordering of Loom's set of client-only entries in MANIFEST.MF.
                entries = [item for item in jar.infolist() if not item.is_dir()]
                if len({item.filename for item in entries}) != len(entries):
                    raise RuntimeError("Duplicate nested archive entry: " + location)
                if sum(item.file_size for item in entries) > MAX_JAR_BYTES:
                    raise RuntimeError("Oversized uncompressed nested archive: " + location)
                content = hashlib.sha512()
                for item in sorted(entries, key=lambda entry: entry.filename):
                    raw_entry = jar.read(item)
                    if item.filename == "META-INF/MANIFEST.MF":
                        raw_entry = canonical_manifest(raw_entry, {e.filename for e in entries})
                    name_bytes = item.filename.encode("utf-8")
                    content.update(len(name_bytes).to_bytes(8, "big")); content.update(name_bytes)
                    content.update(len(raw_entry).to_bytes(8, "big")); content.update(raw_entry)
                modules[-1]["content_sha512"] = content.hexdigest()
            for child in metadata.get("jars", []):
                name = child["file"]
                member = jar.getinfo(name)
                total_nested += member.file_size
                if member.file_size > MAX_JAR_BYTES or total_nested > 512 * 1024 * 1024:
                    raise RuntimeError("Nested jar inventory exceeds byte bounds")
                raw = jar.read(member)
                visit(io.BytesIO(raw), location + "!" + name, depth + 1, root,
                      hashlib.sha512(raw).hexdigest())

    for path in sorted(map(Path, paths)):
        if path.is_symlink() or path.stat().st_size > MAX_JAR_BYTES:
            raise RuntimeError("Unsupported mod file: " + str(path))
        visit(path, path.name, 0, path.name, sha512(path))
    return modules


def canonical_manifest(raw, entry_names):
    """Normalize only main-section attribute order and Loom client-entry order."""
    try:
        lines = raw.decode("utf-8").rstrip("\r\n").splitlines()
        if "" in lines:  # Preserve manifests containing named/signed sections.
            return raw
        unfolded = []
        for line in lines:
            if line.startswith(" "):
                if not unfolded:
                    return raw
                unfolded[-1] += line[1:]
            else:
                unfolded.append(line)
        values = {}
        for line in unfolded:
            key, value = line.split(": ", 1)
            key = key.lower()
            if key in values:
                return raw
            if key == "fabric-loom-client-only-entries":
                paths = value.split(";")
                if not paths or any(path not in entry_names for path in paths):
                    return raw
                value = ";".join(sorted(paths))
            values[key] = value
        return json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return raw


class PredicateChecker:
    def __init__(self, root, runtime):
        self.runtime = runtime
        for key in ("java_exe", "javac_exe", "loader_jar"):
            if not Path(runtime[key]).is_file():
                raise RuntimeError("Missing verifier dependency: " + key)
        loader = Path(runtime["loader_jar"])
        if sha512(loader) != runtime["loader_sha512"]:
            raise RuntimeError("Fabric Loader verifier hash mismatch")
        java = subprocess.run([runtime["java_exe"], "-version"], capture_output=True,
                              text=True, check=True)
        if not re.search(r'version "' + str(runtime["java_major"]) + r'[.\"]', java.stderr + java.stdout):
            raise RuntimeError("Configured Java does not match declared major version")
        with zipfile.ZipFile(loader) as archive:
            loader_metadata = json.loads(archive.read("fabric.mod.json"))
            if loader_metadata.get("version") != runtime["loader_version"]:
                raise RuntimeError("Configured Loader version does not match jar")
        self.classes = Path(root) / "runtime" / "predicate-checker"
        self.classes.mkdir(parents=True, exist_ok=True)
        source = Path(root) / "scripts" / "FabricPredicateCheck.java"
        classfile = self.classes / "FabricPredicateCheck.class"
        if not classfile.exists() or classfile.stat().st_mtime_ns < source.stat().st_mtime_ns:
            subprocess.run([runtime["javac_exe"], "--release", "21", "-cp", str(loader),
                            "-d", str(self.classes), str(source)], check=True, capture_output=True)

    def check(self, pairs):
        if not pairs:
            return []
        def encode(value):
            return base64.b64encode(value.encode("utf-8")).decode("ascii")
        data = "".join(encode(version) + "\t" + encode(predicate) + "\n"
                       for version, predicate in pairs)
        classpath = os.pathsep.join((str(self.classes), self.runtime["loader_jar"]))
        run = subprocess.run([self.runtime["java_exe"], "-cp", classpath, "FabricPredicateCheck"],
                             input=data, capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise RuntimeError("Fabric predicate parser rejected metadata: " + run.stderr[-2000:])
        output = run.stdout.splitlines()
        if len(output) != len(pairs) or any(value not in ("true", "false") for value in output):
            raise RuntimeError("Invalid predicate verifier response")
        return [value == "true" for value in output]


    def compare(self, pairs):
        """Order nested candidates using the pinned Loader's version API."""
        if not pairs:
            return []
        def encode(value):
            return base64.b64encode(value.encode("utf-8")).decode("ascii")
        data = "".join("compare\t" + encode(left) + "\t" + encode(right) + "\n"
                       for left, right in pairs)
        classpath = os.pathsep.join((str(self.classes), self.runtime["loader_jar"]))
        run = subprocess.run([self.runtime["java_exe"], "-cp", classpath, "FabricPredicateCheck"],
                             input=data, capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise RuntimeError("Fabric version comparison failed: " + run.stderr[-2000:])
        output = run.stdout.splitlines()
        if len(output) != len(pairs) or any(value not in ("-1", "0", "1") for value in output):
            raise RuntimeError("Invalid version comparison response")
        return list(map(int, output))


def select_nested_candidates(modules, checker):
    """Conservative highest-version preflight, not Fabric's full SAT resolver.

    Only nested libraries may have alternate candidates. Top-level duplicate
    IDs and equal-order candidates with different contents remain errors.
    If highest candidates fail constraints we stop; we do not guess whether
    Loader could choose lower or omit optional libraries instead.
    """
    groups = {}
    for module in modules:
        groups.setdefault(module["id"], []).append(module)
    selected, choices = [], []
    for mod_id, candidates in groups.items():
        if len(candidates) == 1:
            selected.append(candidates[0])
            continue
        if any(module["depth"] == 0 for module in candidates):
            raise RuntimeError("Duplicate top-level mod ID " + mod_id)
        # Check every equal-order pair, including lower discarded candidates.
        pairs = [(left, right) for i, left in enumerate(candidates)
                 for right in candidates[i + 1:]]
        ordering = checker.compare([(left["version"], right["version"]) for left, right in pairs])
        losing = set()
        for (left, right), order in zip(pairs, ordering):
            if order == 0:
                equivalent = (left["sha512"] == right["sha512"] or
                              left.get("content_sha512") is not None and
                              left.get("content_sha512") == right.get("content_sha512"))
                if not equivalent:
                    raise RuntimeError("Duplicate nested mod ID with conflicting equal-order contents: " + mod_id)
            else:
                losing.add(id(left if order < 0 else right))
        highest = next(module for module in candidates if id(module) not in losing)
        selected.append(highest)
        choices.append({"id": mod_id, "selected_version": highest["version"],
                        "selected_location": highest["location"],
                        "candidates": [{"version": c["version"], "location": c["location"]}
                                       for c in candidates]})
    return selected, choices


def validate(modules, runtime, checker):
    discovered_count = len(modules)
    modules, choices = select_nested_candidates(modules, checker)
    available = {"minecraft": {"version": runtime["minecraft"], "location": "runtime"},
                 "fabricloader": {"version": runtime["loader_version"], "location": "runtime"},
                 "java": {"version": str(runtime["java_major"]), "location": "runtime"}}
    for module in modules:
        for mod_id in [module["id"], *module["provides"]]:
            previous = available.get(mod_id)
            if previous:
                same_nested = (previous.get("depth", 0) > 0 and module["depth"] > 0
                               and previous["id"] == module["id"]
                               and previous["version"] == module["version"]
                               and (previous.get("sha512") == module["sha512"] or
                                    previous.get("content_sha512") is not None and
                                    previous.get("content_sha512") == module.get("content_sha512")))
                if same_nested:
                    continue
                raise RuntimeError("Duplicate/provided mod ID " + mod_id + ": "
                                   + previous["location"] + " and " + module["location"])
            available[mod_id] = module
    checks = []
    for module in modules:
        for field in ("depends", "breaks", "conflicts"):
            constraints = module[field]
            if not isinstance(constraints, dict):
                raise RuntimeError("Invalid dependency metadata: " + module["location"])
            for mod_id, declared in constraints.items():
                provider = available.get(mod_id)
                if not provider:
                    if field == "depends":
                        raise RuntimeError("Missing dependency " + mod_id + " for " + module["location"])
                    continue
                predicates = [declared] if isinstance(declared, str) else declared
                if not isinstance(predicates, list) or not predicates or any(not isinstance(p, str) for p in predicates):
                    raise RuntimeError("Invalid version constraint for " + mod_id)
                checks.append((module, field, mod_id, provider["version"], predicates))
    pairs = [(version, predicate) for _, _, _, version, predicates in checks for predicate in predicates]
    answers = iter(checker.check(pairs))
    warnings = []
    for module, field, mod_id, version, predicates in checks:
        matches = any([next(answers) for _ in predicates])
        if (field == "depends" and not matches) or (field == "breaks" and matches):
            raise RuntimeError(f"{module['id']} {field} constraint failed for {mod_id} {version}: {predicates}")
        if field == "conflicts" and matches:
            warnings.append(f"{module['id']} declares a soft conflict with {mod_id} {version}")
    return {"modules": len(modules), "discovered_modules": discovered_count,
            "nested_candidate_choices": choices,
            "selection_policy": "Conservative highest nested version; not the full Loader resolver",
            "provided_ids": len(available), "predicate_checks": len(pairs),
            "warnings": warnings, "runtime_loader_acceptance": "untested"}
