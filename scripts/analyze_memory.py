"""Separate descriptive memory analysis; unknown collection state stays inconclusive."""
import json
import math
from pathlib import Path
import statistics

from analyze_benchmark import verify_experiment
from experiment_protocol import matched_state


def collection_verified(checkpoint):
    if checkpoint.get("procedure")!="explicit-gc-observed-then-3s-settle-v1":return False
    try:
        before=checkpoint["before_gc"]["G1 Old Generation"]["count"]
        first=checkpoint["first"]["gc"]["G1 Old Generation"]["count"]
        second=checkpoint["second"]["gc"]["G1 Old Generation"]["count"]
        return (checkpoint["observed_collection"] is True and checkpoint["stable_collection_counters"] is True
                and 0<=before<first==second and checkpoint["first"]["gc"]==checkpoint["second"]["gc"])
    except (KeyError,TypeError):return False


def summarize(record):
    if record.get("status")!="memory_pilot_complete":raise ValueError("Memory workload failed")
    manifest=verify_experiment(record["experiment"])
    if matched_state(record["initial_state"])!=matched_state(record["final_state"]):raise ValueError("Memory conditions changed")
    checkpoints=record["checkpoints"]
    if len(checkpoints)!=3:raise ValueError("Three memory checkpoints required")
    rows=[c["second"]["heap"] for c in checkpoints]
    for row in rows:
        if any(not isinstance(row[k],(int,float)) or not math.isfinite(row[k]) or row[k]<0
               for k in ("used_heap_bytes","committed_heap_bytes","maximum_heap_bytes")):
            raise ValueError("Invalid memory sample")
        if not row["used_heap_bytes"]<=row["committed_heap_bytes"]<=row["maximum_heap_bytes"]:
            raise ValueError("Heap bounds differ")
    verified=all(collection_verified(c) for c in checkpoints)
    return {"schema":"modpack-memory-analysis-v1","status":"post_collection_samples_verified" if verified else "retention_inconclusive",
            "benchmark_accepted":False,"configuration_id":manifest["configuration_id"],
            "median_post_collection_used_heap_bytes":statistics.median([r["used_heap_bytes"] for r in rows]) if verified else None,
            "median_committed_heap_bytes":statistics.median([r["committed_heap_bytes"] for r in rows]),
            "raw_used_heap_bytes":[r["used_heap_bytes"] for r in rows],
            "process_memory":"not measured by this heap-only pilot; collect separately",
            "scope":"Three checkpoints in one JVM, not independent process replicates or an exact live-set measurement"}


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("record",type=Path)
    args=parser.parse_args()
    value=summarize(json.loads(args.record.read_text()))
    target=args.record.with_name(args.record.stem+"-analysis.json")
    with target.open("x") as output:json.dump(value,output,indent=2)
    print(str(target))
