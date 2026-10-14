"""Capture experiment identity and observed JVM collection state outside timing."""
import time
from java import JavaClass, JavaBoundMember
from lab_common import PROFILE, ManagementFactory, Runtime, MC, number, heap_snapshot, guard_world
from experiment_protocol import observed_experiment
INTERFACES = {}
LOADED_MODS = None


def loaded_mods(cancel=None):
    global LOADED_MODS
    if cancel is not None:cancel()
    if LOADED_MODS is not None:
        return dict(LOADED_MODS)
    def call(interface, obj, name):
        if cancel is not None:cancel()
        if interface not in INTERFACES:
            INTERFACES[interface] = JavaClass(interface)
        # Retain the class proxy; temporary JavaClass(...).id is released before
        # JavaBoundMember can invoke the method on some Minescript bridges.
        return JavaBoundMember(INTERFACES[interface].id, obj.id, name, ref=obj.ref)()
    loader = JavaClass("net.fabricmc.loader.api.FabricLoader").getInstance()
    result = {}
    containers=call("net.fabricmc.loader.api.FabricLoader",loader,"getAllMods")
    iterator=call("java.util.Collection",containers,"iterator")
    while call("java.util.Iterator",iterator,"hasNext"):
        container=call("java.util.Iterator",iterator,"next")
        metadata=call("net.fabricmc.loader.api.ModContainer",container,"getMetadata")
        mod_id=call("net.fabricmc.loader.api.metadata.ModMetadata",metadata,"getId")
        version=call("net.fabricmc.loader.api.metadata.ModMetadata",metadata,"getVersion")
        result[str(mod_id)]=str(call("net.fabricmc.loader.api.Version",version,"getFriendlyString"))
    # Fabric's loaded registry is immutable for this game process. Recheck
    # actual JAR/config hashes each phase, without repeating slow bridge calls.
    LOADED_MODS = result
    return dict(result)


def experiment_snapshot(cancel=None):
    return observed_experiment(PROFILE, loaded_mods(cancel))


def gc_snapshot():
    beans = ManagementFactory.getGarbageCollectorMXBeans().iterator()
    interface = JavaClass("java.lang.management.GarbageCollectorMXBean")
    result = {}
    while beans.hasNext():
        bean = beans.next()
        def call(method):
            return JavaBoundMember(interface.id, bean.id, method, ref=bean.ref)()
        result[str(call("getName"))] = {"count": number(call("getCollectionCount")),
                                       "time_ms": number(call("getCollectionTime"))}
    return result


def retained_checkpoint(stop, wait_live):
    """Explicit GC request, observed completion, then fixed quiet settling; NOT FPS."""
    guard_world()
    before = gc_snapshot()
    started = time.monotonic()
    Runtime.getRuntime().gc()
    confirmed = False
    while time.monotonic() - started < 20:
        wait_live(0.25, stop)
        after = gc_snapshot()
        # The pinned JVM uses G1. Young-only collections do not verify completion
        # of the requested old-generation collection; other collectors are untested.
        if any(after[name]["count"] > row["count"] >= 0 for name, row in before.items()
               if name in after and name == "G1 Old Generation"):
            confirmed = True
            break
    wait_live(3, stop)
    first = {"heap": heap_snapshot(), "gc": gc_snapshot()}
    wait_live(1, stop)
    second = {"heap": heap_snapshot(), "gc": gc_snapshot()}
    # Collector counters establish completion but not a universal full-GC guarantee.
    stable = first["gc"] == second["gc"]
    return {"procedure": "explicit-gc-observed-then-3s-settle-v1", "before_gc": before,
            "first": first, "second": second, "observed_collection": confirmed,
            "stable_collection_counters": stable,
            "retention_status": "post_collection_sample" if confirmed and stable else "inconclusive",
            "scope": "Post-observed-collection heap, not exact live-set or a continuous GC trace"}
