"""Minecraft state/settings helpers; no desktop input or window control."""
import json
import math
from pathlib import Path
import sys
import time
import minescript as ms
import session_runtime
from java import JavaClass

PROFILE = Path(__file__).resolve().parent.parent
CONDITIONS = json.loads((PROFILE / "minescript/lab-conditions.json").read_text(encoding="utf-8"))
Minecraft = JavaClass("net.minecraft.client.Minecraft")
Runtime = JavaClass("java.lang.Runtime")
ManagementFactory = JavaClass("java.lang.management.ManagementFactory")
System = JavaClass("java.lang.System")
ProcessHandle = JavaClass("java.lang.ProcessHandle")
LevelResource = JavaClass("net.minecraft.world.level.storage.LevelResource")
MC = Minecraft.getInstance()


def number(value):
    # Minescript java.py does not unbox java.lang.Long automatically.
    return int(str(value))


def heap_snapshot():
    """Boundary snapshot, outside frame measurement; not a peak/GC-pause trace."""
    from java import JavaBoundMember
    bean = ManagementFactory.getMemoryMXBean()
    # Bind through the exported public interface, rather than sun.management.
    interface = JavaClass("java.lang.management.MemoryMXBean")
    usage = JavaBoundMember(interface.id, bean.id, "getHeapMemoryUsage", ref=bean.ref)()
    return {"used_heap_bytes": number(usage.getUsed()), "committed_heap_bytes": number(usage.getCommitted()),
            "maximum_heap_bytes": number(usage.getMax()),
            "scope": "Phase-boundary snapshot; continuous heap and GC events untested"}


def guard_world(expected_dimension=None):
    expected_dimension = CONDITIONS["dimension"] if expected_dimension is None else expected_dimension
    if expected_dimension not in ("minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"):
        raise RuntimeError("Requested dimension is outside the test whitelist")
    configured_profile=CONDITIONS.get('configured_profile')
    if (configured_profile and PROFILE.resolve()!=Path(configured_profile).resolve()) or (not configured_profile and PROFILE.name!='sodium-automation'):
        raise RuntimeError('Script is restricted to the configured disposable profile')
    version = ms.version_info()
    if version.minecraft != CONDITIONS["minecraft"]:
        raise RuntimeError("Unexpected Minecraft version")
    world = ms.world_info()
    if world.name not in CONDITIONS["world_names"] or world.dimension != expected_dimension:
        raise RuntimeError("Unexpected world/dimension")
    if not MC.hasSingleplayerServer():
        raise RuntimeError("Only the disposable local test world is permitted")
    actual = Path(str(MC.getSingleplayerServer().getWorldPath(LevelResource.ROOT))).resolve()
    expected = (PROFILE / "saves" / CONDITIONS["world_folder"]).resolve()
    if actual != expected:
        raise RuntimeError("World directory is not the disposable automation copy")
    return world, version


def apply_graphics_conditions():
    guard_world()
    options = MC.options
    options.applyGraphicsPreset(JavaClass("net.minecraft.client.GraphicsPreset").CUSTOM)
    for method, value in (("renderDistance", 12), ("simulationDistance", 8),
                          ("enableVsync", False), ("framerateLimit", JavaClass("net.minecraft.client.Options").UNLIMITED_FRAMERATE_CUTOFF),
                          ("biomeBlendRadius", 1), ("bobView", False), ("fov", 70),
                          ("fovEffectScale", 0.0), ("entityDistanceScaling", 1.0),
                          ("entityShadows", True)):
        getattr(options, method)().set(value)
    options.cloudStatus().set(JavaClass("net.minecraft.client.CloudStatus").OFF)
    options.inactivityFpsLimit().set(JavaClass("net.minecraft.client.InactivityFpsLimit").MINIMIZED)
    options.save()
    # Resolution, fullscreen, heap, camera and player position are untouched here.


def sample_state():
    started = time.monotonic()
    world, version = guard_world()
    window = MC.getWindow()
    monitor = window.findBestMonitor()
    if monitor is None:
        raise RuntimeError("Could not identify Minecraft's monitor")
    mode = monitor.getCurrentMode()
    options = MC.options
    preferred = window.getPreferredFullscreenVideoMode()
    record = {
        "unix_time_ns": time.time_ns(), "process_id": number(ProcessHandle.current().pid()),
        "minecraft": version.minecraft, "minescript": version.minescript,
        "java_runtime": str(System.getProperty("java.runtime.version")),
        "java_major": str(System.getProperty("java.specification.version")),
        "python_executable": sys.executable,
        "world_name": world.name, "dimension": world.dimension,
        "world_folder": CONDITIONS["world_folder"], "game_ticks": world.game_ticks,
        "day_ticks": world.day_ticks, "raining": world.raining, "thundering": world.thundering,
        "position": ms.player_position(), "orientation": ms.player_orientation(),
        "screen": ms.screen_name(), "foreground": MC.isWindowActive(),
        "paused": MC.isPaused(), "game_fps_counter": MC.getFps(),
        "diagnostic_only": session_runtime.diagnostic_only,
        "pause_on_lost_focus": options.pauseOnLostFocus,
        "framebuffer_width": window.getWidth(), "framebuffer_height": window.getHeight(),
        "fullscreen": window.isFullscreen(),
        "custom_fullscreen_mode_selected": preferred.isPresent(),
        "monitor_width": mode.getWidth(), "monitor_height": mode.getHeight(),
        "monitor_refresh_hz": mode.getRefreshRate(),
        "render_distance": options.renderDistance().get(),
        "effective_render_distance": options.getEffectiveRenderDistance(),
        "simulation_distance": options.simulationDistance().get(),
        "vsync": options.enableVsync().get(), "framerate_limit": options.framerateLimit().get(),
        "effective_framerate_limit": MC.gameRenderer.getGameRenderState().framerateLimit,
        "framerate_throttle_reason": str(MC.getFramerateLimitTracker().getThrottleReason().name()),
        "unlimited_framerate_cutoff": JavaClass("net.minecraft.client.Options").UNLIMITED_FRAMERATE_CUTOFF,
        "inactivity_fps_limit": str(options.inactivityFpsLimit().get().name()),
        "graphics_preset": str(options.graphicsPreset().get().getSerializedName()),
        "cloud_status": str(options.cloudStatus().get().name()),
        "biome_blend_radius": options.biomeBlendRadius().get(),
        "bob_view": options.bobView().get(), "fov": options.fov().get(),
        "fov_effect_scale": options.fovEffectScale().get(),
        "entity_distance_scaling": options.entityDistanceScaling().get(),
        "entity_shadows": options.entityShadows().get(),
        "camera_type": str(options.getCameraType().name()),
        "heap_cap_bytes": number(Runtime.getRuntime().maxMemory()),
        "benchmark_accepted": False,
    }
    record["sample_cost_seconds"] = time.monotonic() - started
    return record


def condition_issues(record, require_pose=False):
    issues = [key for key, expected in CONDITIONS["options"].items() if record.get(key) != expected]
    if not session_runtime.diagnostic_only and (record.get("effective_framerate_limit",0) < record.get("unlimited_framerate_cutoff",260) or record.get("framerate_throttle_reason") != "NONE"):
        issues.append("effective_frame_cap")
    if record["java_major"] != CONDITIONS["java_major"]:
        issues.append("java_major")
    heap_mib = record["heap_cap_bytes"] / 1024**2
    if abs(heap_mib - CONDITIONS["heap_cap_mib"]) > CONDITIONS["heap_alignment_tolerance_mib"]:
        issues.append("heap_cap")
    if not record["fullscreen"] or record["custom_fullscreen_mode_selected"]:
        issues.append("default_fullscreen_mode")
    if (record["framebuffer_width"], record["framebuffer_height"]) != (record["monitor_width"], record["monitor_height"]):
        issues.append("native_framebuffer")
    if session_runtime.live_issues(record['foreground'],record['paused'],record['screen']):
        issues.append("unpaused_foreground_world")
    if record["game_fps_counter"] <= 0 and not session_runtime.diagnostic_only:
        issues.append("game_fps_counter")
    if session_runtime.diagnostic_only and record.get('pause_on_lost_focus') is not False:
        issues.append('diagnostic_pause_on_lost_focus')
    if require_pose:
        if len(record["position"]) != 3 or any(not math.isfinite(a) or abs(a - b) > CONDITIONS["position_tolerance_blocks"] for a, b in zip(record["position"], CONDITIONS["start_position"])):
            issues.append("start_position")
        if len(record["orientation"]) != 2 or any(not math.isfinite(a) or abs(a - b) > CONDITIONS["orientation_tolerance_degrees"] for a, b in zip(record["orientation"], CONDITIONS["start_orientation"])):
            issues.append("start_orientation")
    return issues
