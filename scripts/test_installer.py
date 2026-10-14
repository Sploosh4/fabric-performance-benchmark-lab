"""Optional Java-dependent installer fixtures; no game launches."""
import os
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import bootstrap_tools as installer
from fabric_inventory import PredicateChecker, inventory, validate

ROOT = Path(__file__).resolve().parents[1]


def jar_bytes(mod_id="fixture-mod", version="1.0.0", **extra):
    data = io.BytesIO()
    metadata = {"schemaVersion": 1, "id": mod_id, "version": version, **extra}
    nested = metadata.pop("nested", {})
    entries = metadata.pop("entries", {})
    if nested:
        metadata["jars"] = [{"file": name} for name in nested]
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps(metadata))
        for name, raw in entries.items():
            archive.writestr(name, raw)
        for name, raw in nested.items():
            archive.writestr(name, raw)
    return data.getvalue()


class InstallerSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('FABRIC_BENCHMARK_JAVA_TESTS')!='1':raise unittest.SkipTest('Optional Java installer checks require explicit opt-in and local.settings.json')
        cls.runtime = json.loads((ROOT / "local.settings.json").read_text(encoding="utf-8"))
        cls.checker = PredicateChecker(ROOT, cls.runtime)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="modpack-installer-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.destination = Path(self.temporary.name)

    def mod(self, name, **metadata):
        path = self.destination / name
        path.write_bytes(jar_bytes(**metadata))
        return path

    def check(self, runtime=None):
        return validate(inventory(self.destination.glob("*.jar")), runtime or self.runtime, self.checker)

    def test_native_predicate_boundaries(self):
        pairs = [("26.1.2", "~26.1-"), ("26.2", "~26.1-"),
                 ("0.19.5", ">=0.19.5"), ("0.19.4", ">=0.19.5"),
                 ("26.1.2", ">=26.1-rc.2"), ("25", ">=25"), ("21", ">=25")]
        self.assertEqual(self.checker.check(pairs), [True, False, True, False, True, True, False])

    def test_native_candidate_ordering(self):
        self.assertEqual(self.checker.compare([("4.1.1+abc", "4.1.0+def"),
                                              ("4.1.0+abc", "4.1.0+def"),
                                              ("1.0-rc.1", "1.0")]), [1, 0, -1])

    def test_nested_candidates_select_newer_and_validate_selected_dependencies(self):
        self.mod("first.jar", mod_id="fixture-first", nested={"a.jar": jar_bytes(
            "fixture-library", "4.1.1", depends={"java": ">=25"})})
        self.mod("second.jar", mod_id="fixture-second", nested={"b.jar": jar_bytes(
            "fixture-library", "4.1.0", depends={"fixture-obsolete": "*"})},
            depends={"fixture-library": ">=4.1.1"})
        report = self.check()
        self.assertEqual(report["modules"], 3)
        self.assertEqual(report["nested_candidate_choices"][0]["selected_version"], "4.1.1")
        self.assertEqual(report["runtime_loader_acceptance"], "untested")

    def test_nested_selected_candidate_cannot_evade_dependency_check(self):
        self.mod("first.jar", mod_id="fixture-first", nested={"a.jar": jar_bytes(
            "fixture-library", "4.1.1", depends={"fixture-missing": "*"})})
        self.mod("second.jar", mod_id="fixture-second", nested={"b.jar": jar_bytes(
            "fixture-library", "4.1.0")})
        with self.assertRaisesRegex(RuntimeError, "Missing dependency"):
            self.check()

    def test_nested_equal_order_conflicting_code_rejected(self):
        self.mod("first.jar", mod_id="fixture-first", nested={"a.jar": jar_bytes(
            "fixture-library", "4.1.0+abc")})
        self.mod("second.jar", mod_id="fixture-second", nested={"b.jar": jar_bytes(
            "fixture-library", "4.1.0+def")})
        with self.assertRaisesRegex(RuntimeError, "conflicting equal-order"):
            self.check()

    def test_nested_identical_library_deduplicated(self):
        library = jar_bytes("fixture-library", "2.0.0")
        self.mod("first.jar", mod_id="fixture-first", nested={"a.jar": library})
        self.mod("second.jar", mod_id="fixture-second", nested={"b.jar": library})
        self.assertEqual(self.check()["modules"], 3)

    def test_nested_same_version_different_class_rejected(self):
        for name, payload in (("first", b"original class"), ("second", b"changed class")):
            self.mod(name + ".jar", mod_id="fixture-" + name, nested={"library.jar": jar_bytes(
                "fixture-library", "2.0.0", entries={"Library.class": payload})})
        with self.assertRaisesRegex(RuntimeError, "conflicting equal-order"):
            self.check()

    def test_loom_manifest_set_order_does_not_create_false_duplicate(self):
        for name, order in (("first", "A.class;B.class"), ("second", "B.class;A.class")):
            manifest = "Manifest-Version: 1.0\r\nFabric-Loom-Client-Only-Entries: " + order + "\r\n\r\n"
            self.mod(name + ".jar", mod_id="fixture-" + name, nested={"library.jar": jar_bytes(
                "fixture-library", "2.0.0", entries={"A.class": b"same A", "B.class": b"same B",
                "META-INF/MANIFEST.MF": manifest})})
        self.assertEqual(self.check()["modules"], 3)

    def test_loom_manifest_entry_set_change_still_rejected(self):
        for name, order in (("first", "A.class;B.class"), ("second", "A.class")):
            manifest = "Manifest-Version: 1.0\r\nFabric-Loom-Client-Only-Entries: " + order + "\r\n\r\n"
            self.mod(name + ".jar", mod_id="fixture-" + name, nested={"library.jar": jar_bytes(
                "fixture-library", "2.0.0", entries={"A.class": b"same A", "B.class": b"same B",
                "META-INF/MANIFEST.MF": manifest})})
        with self.assertRaisesRegex(RuntimeError, "conflicting equal-order"):
            self.check()

    def test_duplicate_old_filename_rejected(self):
        self.mod("old-name.jar", version="0.9.0")
        self.mod("new-name.jar", version="1.0.0")
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            self.check()

    def test_nested_dependency_and_provided_alias(self):
        library = jar_bytes("fixture-library", "2.0.0", provides=["fixture-alias"])
        self.mod("parent.jar", nested={"META-INF/jars/library.jar": library},
                 depends={"fixture-alias": ["=1.0.0", ">=2.0.0"]})
        self.assertEqual(self.check()["modules"], 2)

    def test_missing_nested_dependency_rejected(self):
        self.mod("parent.jar", depends={"fixture-library": "*"})
        with self.assertRaisesRegex(RuntimeError, "Missing dependency"):
            self.check()

    def test_incompatible_game_loader_and_java_rejected(self):
        for mod_id, predicate in (("minecraft", "<26.1"), ("fabricloader", ">=0.20"), ("java", ">=26")):
            with self.subTest(mod_id=mod_id):
                self.mod("bad.jar", depends={mod_id: predicate})
                with self.assertRaisesRegex(RuntimeError, "constraint failed"):
                    self.check()

    def test_breaks_rejected_and_conflicts_warned(self):
        self.mod("bad.jar", breaks={"minecraft": "26.1.2"})
        with self.assertRaisesRegex(RuntimeError, "constraint failed"):
            self.check()
        self.mod("bad.jar", conflicts={"minecraft": "26.1.2"})
        self.assertEqual(len(self.check()["warnings"]), 1)

    def test_stale_download_preserved(self):
        stale = self.destination / "user.jar.download"
        stale.write_bytes(b"do not remove")
        lock = {"minecraft": "26.1.2", "loader": "fabric", "components": []}
        with self.assertRaisesRegex(RuntimeError, "Stale download"):
            installer.preflight(lock, self.runtime, self.destination, install=True)
        self.assertEqual(stale.read_bytes(), b"do not remove")

    def components(self, specs):
        result = []
        for name, raw in specs:
            result.append({"filename": name, "url": "https://example.invalid/" + name,
                           "sha512": hashlib.sha512(raw).hexdigest(), "size": len(raw)})
        return {"minecraft": "26.1.2", "loader": "fabric", "components": result}

    def test_all_downloads_checked_before_install(self):
        raw = jar_bytes()
        lock = self.components([("good.jar", raw), ("corrupt.jar", raw)])
        replies = [io.BytesIO(raw), io.BytesIO(b"corrupt")]
        with patch.object(installer.urllib.request, "urlopen", side_effect=replies):
            with self.assertRaisesRegex(RuntimeError, "verification"):
                installer.preflight(lock, self.runtime, self.destination, install=True)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_staged_duplicate_rejected_before_install(self):
        existing = self.mod("user-old.jar", version="0.9.0")
        preserved = existing.read_bytes()
        raw = jar_bytes(version="1.0.0")
        lock = self.components([("new.jar", raw)])
        with patch.object(installer.urllib.request, "urlopen", return_value=io.BytesIO(raw)):
            with self.assertRaisesRegex(RuntimeError, "Duplicate"):
                installer.preflight(lock, self.runtime, self.destination, install=True)
        self.assertEqual(existing.read_bytes(), preserved)
        self.assertEqual([p.name for p in self.destination.iterdir()], ["user-old.jar"])

    def test_existing_different_file_preserved(self):
        existing = self.mod("pinned.jar", version="0.9.0")
        preserved = existing.read_bytes()
        lock = self.components([("pinned.jar", jar_bytes(version="1.0.0"))])
        with self.assertRaisesRegex(RuntimeError, "preserving"):
            installer.preflight(lock, self.runtime, self.destination, install=True)
        self.assertEqual(existing.read_bytes(), preserved)

    def test_valid_staged_install_and_repeat(self):
        raw = jar_bytes(depends={"minecraft": "26.1.2", "java": ">=25"})
        lock = self.components([("valid.jar", raw)])
        with patch.object(installer.urllib.request, "urlopen", return_value=io.BytesIO(raw)):
            report = installer.preflight(lock, self.runtime, self.destination, install=True)
        self.assertEqual(report["added_files"], ["valid.jar"])
        report = installer.preflight(lock, self.runtime, self.destination)
        self.assertEqual(report["added_files"], [])

    def test_rollback_preserves_concurrent_target(self):
        first, second = jar_bytes("fixture-first"), jar_bytes("fixture-second")
        lock = self.components([("first.jar", first), ("second.jar", second)])
        real_rename = Path.rename
        def simulated_race(path, target):
            if Path(target).name == "second.jar":
                Path(target).write_bytes(b"concurrent user file")
            return real_rename(path, target)
        with patch.object(installer.urllib.request, "urlopen", side_effect=[io.BytesIO(first), io.BytesIO(second)]):
            with patch.object(Path, "rename", simulated_race):
                with self.assertRaises(FileExistsError):
                    installer.preflight(lock, self.runtime, self.destination, install=True)
        self.assertFalse((self.destination / "first.jar").exists())
        self.assertEqual((self.destination / "second.jar").read_bytes(), b"concurrent user file")


if __name__ == "__main__":
    unittest.main(verbosity=2)
