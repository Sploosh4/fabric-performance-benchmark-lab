"""Pinned experiment identity; validation transport remains diagnostic."""
import hashlib
import json
import math
from pathlib import Path
import re
from room_route_protocol import WORKLOAD as ROOM_WORKLOAD,ROOM_POLICY
from session_protocol import batch_protocol

SCHEMA = "modpack-experiment-v1"
WORKLOAD = "mob_display_loop_v2"
POLICY = {"scene_weights": [1 / 8] * 8, "path_tolerance_blocks": 0.35,
          "endpoint_tolerance_blocks": 0.25, "camera_tolerance_degrees": 1.0,
          "minimum_path_samples": 3, "maximum_sample_gap_blocks": 4.0,
          "stutter_threshold_ms": 50, "minimum_measured_repeats": 3,
          "maximum_control_drift_pct": 5.0}
POLICY.update(warmup="exactly-one-full-unscored-route-pass-before-each-measured-route",
              one_percent_low_definition="1000 / mean of slowest ceil(N*0.01) complete frame intervals (milliseconds)")
STATE_KEYS = ("minecraft", "java_runtime", "java_major", "heap_cap_bytes",
              "framebuffer_width", "framebuffer_height", "monitor_refresh_hz",
              "fullscreen", "custom_fullscreen_mode_selected", "render_distance",
              "effective_render_distance", "simulation_distance", "vsync", "framerate_limit",
              "effective_framerate_limit", "framerate_throttle_reason", "unlimited_framerate_cutoff", "inactivity_fps_limit",
              "graphics_preset", "cloud_status", "biome_blend_radius", "bob_view", "fov",
              "fov_effect_scale", "entity_distance_scaling", "entity_shadows", "camera_type",
              "world_folder", "dimension", "raining", "thundering")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_inventory(profile):
    """Hash actual mods/settings/instrumentation outside capture, never secrets."""
    profile = Path(profile).resolve(strict=True)
    files = sorted((profile / "mods").glob("*.jar"))
    files += sorted(p for p in (profile / "config").rglob("*") if p.is_file())
    files += sorted((profile / "minescript").glob("*.py"))
    files += [profile / "minescript/lab-conditions.json"]
    if (profile / 'minescript/config.txt').is_file():files.append(profile / 'minescript/config.txt')
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(profile):
            raise ValueError("Experiment file escapes owned profile")
    return {p.relative_to(profile).as_posix(): file_hash(p) for p in files}


def validate_manifest(value):
    if value.get("schema") != SCHEMA or value.get("workload") not in (WORKLOAD,ROOM_WORKLOAD):
        raise ValueError("Unsupported experiment schema/workload")
    batch_protocol(value)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value.get("configuration_id", "")):
        raise ValueError("Invalid configuration ID")
    if value.get("role") not in ("control", "candidate"):
        raise ValueError("Unknown experiment role")
    if value.get("analysis_policy") != (ROOM_POLICY if value["workload"]==ROOM_WORKLOAD else POLICY):
        raise ValueError("Unregistered analysis policy")
    for key in ("world_origin_sha256", "conditions_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", value.get(key, "")):
            raise ValueError("Missing experiment hash: " + key)
    inventory = value.get("files")
    if not isinstance(inventory, dict) or not inventory or not any(k.startswith("mods/") for k in inventory):
        raise ValueError("Missing experiment inventory")
    for key, sha in inventory.items():
        if key.startswith("/") or ".." in Path(key).parts or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("Invalid experiment file/hash")
    if not isinstance(value.get("expected_loaded_mods"), dict) or not value["expected_loaded_mods"]:
        raise ValueError("Loaded-mod identity is required")
    return value


def observed_experiment(profile, loaded_mods):
    path = Path(profile) / "minescript/lab-experiment.json"
    if not path.exists():
        return None
    manifest = validate_manifest(json.loads(path.read_text(encoding="utf-8")))
    actual = file_inventory(profile)
    if actual != manifest["files"]:
        raise ValueError("Actual configuration files differ from pinned experiment")
    if file_hash(Path(profile) / "minescript/lab-conditions.json") != manifest["conditions_sha256"]:
        raise ValueError("Condition hash differs")
    if "world_restored_tree_sha256" in manifest:
        receipt=json.loads((Path(profile)/"minescript/lab-world-origin.json").read_text())
        if receipt["backup_sha256"]!=manifest["world_origin_sha256"] or receipt["restored_file_tree_sha256"]!=manifest["world_restored_tree_sha256"]:
            raise ValueError("World origin receipt differs")
    for mod, version in manifest["expected_loaded_mods"].items():
        if loaded_mods.get(mod) != version:
            raise ValueError("Running loaded mod differs: " + mod)
    # Extra loaded modules are recorded, allowing legitimate nested Fabric libraries.
    return {"manifest": manifest, "manifest_sha256": digest(manifest),
            "actual_files_sha256": digest(actual), "loaded_mods": dict(sorted(loaded_mods.items()))}


def matched_state(state):
    if any(key not in state for key in STATE_KEYS):
        raise ValueError("Effective state evidence is incomplete")
    if any(isinstance(state[key], float) and not math.isfinite(state[key]) for key in STATE_KEYS):
        raise ValueError("Effective state contains nonfinite values")
    return {key: state[key] for key in STATE_KEYS}
