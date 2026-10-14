"""Cached, read-only Java calls for a counter tooling probe, not a benchmark."""
import math
import time


class CounterReader:
    def __init__(self, ms, minecraft_handle):
        self.ms, self.minecraft = ms, minecraft_handle
        self.handles = []
        try:
            clazz = ms.java_class("net.minecraft.client.Minecraft")
            self.handles.append(clazz)
            self.methods = {}
            for name in ("getFps", "isWindowActive", "isPaused"):
                handle = ms.java_member(clazz, name)
                self.handles.append(handle)
                self.methods[name] = handle
        except Exception:
            self.close()
            raise

    def close(self):
        if self.handles:
            self.ms.java_release(*self.handles)
            self.handles.clear()

    def value(self, name):
        result = self.ms.java_call_method(self.minecraft, self.methods[name])
        if result is None:
            raise RuntimeError("Counter API returned null: " + name)
        try:
            return self.ms.java_to_string(result)
        finally:
            self.ms.java_release(result)

    def boolean(self, name):
        value = self.value(name)
        if value not in ("true", "false"):
            raise RuntimeError("Counter API returned invalid boolean: " + name)
        return value == "true"

    def sample(self, qpc=None):
        started = time.monotonic()
        sample_before_qpc = qpc() if qpc else None
        before = time.time_ns()
        fps_before_qpc = qpc() if qpc else None
        fps = int(self.value("getFps"))
        fps_after_qpc = qpc() if qpc else None
        after = time.time_ns()
        record = {"fps_read_before_unix_ns": before, "fps_read_after_unix_ns": after,
                  "game_fps_counter": fps,
                  "foreground": self.boolean("isWindowActive"),
                  "paused": self.boolean("isPaused"),
                  "screen": self.ms.screen_name(),
                  "position": self.ms.player_position(),
                  "orientation": self.ms.player_orientation(),
                  "benchmark_accepted": False}
        record["sample_cost_seconds"] = time.monotonic() - started
        if qpc:
            record.update(sample_before_qpc=sample_before_qpc, sample_after_qpc=qpc(),
                          fps_read_before_qpc=fps_before_qpc, fps_read_after_qpc=fps_after_qpc)
        return record


def counter_issues(record, conditions):
    issues = []
    if record["game_fps_counter"] <= 0:
        issues.append("game_fps_counter")
    if record["paused"] or record["screen"] is not None or not record["foreground"]:
        issues.append("unpaused_foreground_world")
    for key, expected, tolerance in (
            ("position", conditions["start_position"], conditions["position_tolerance_blocks"]),
            ("orientation", conditions["start_orientation"], conditions["orientation_tolerance_degrees"])):
        values = record[key]
        if len(values) != len(expected) or any(not math.isfinite(a) or abs(a - b) > tolerance
                                               for a, b in zip(values, expected)):
            issues.append(key)
    return issues
