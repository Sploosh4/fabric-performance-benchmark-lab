# Cesium port base decision

Recorded 2026-10-08. This is static source investigation, not a milestone or a regression-test result.

**Keep `ec3e418c3ee2caa332428552f0a1abcda54b5223` (`dev/multiversion`, Minecraft 1.21.10) as the initial port base.** The local `port/26.1.2` branch already starts there. Keep the newer branch available as a reference for individual Minecraft hooks; do not merge its storage rewrite wholesale or import the issue #31 workaround.

Compared against `5d83dac5dbf7571a3c9eae5f543cbbd59acbfe24` on `mc/1.21.11`, which targets **1.21.11-rc3**, not a tested 26.1.2 release. Roughly 90 files change. The newer branch simplifies the build and brings game hooks closer to our target, but combines that work with a substantial unvalidated database/converter rewrite. Keeping the older base makes changes attributable to our port and retains the published version as the standards-pass comparison target. This is a scope decision, not a claim that the older implementation is reliable.

## File-level comparison

| Area | Older base | Newer branch | Consequence for our port |
| --- | --- | --- | --- |
| `build.gradle.kts`, `build.gradle`, `gradle.properties` | Loom 1.11.7; Kotlin/KSP, Stonecutter and Fletching Table; Java 21 for recent supported targets | Single-version Groovy build; Loom 1.14.4; Java 21; Loader 0.18.1 | Both need 26.1 toolchain migration. Decide the final single-version build in Milestone Two; do not introduce a functional build rewrite during formatting. |
| `api/database/*`, `common/lmdb/KVDatabase.java`, new `KVTransaction.java` | Pending writes and commit snapshots live in the database implementation | New interfaces separate database and transaction behavior | Avoid adopting an unrelated transaction rewrite as a prerequisite to changing Minecraft hooks. |
| `common/spec/WorldDatabaseSpecs.java`, `PlayerDatabaseSpecs.java` | Named databases `chunks`, `poi`, `entity`, `player_data`, `advancements`, `statistics` | Same names; specification class moved | Name equality is a static format assumption, not demonstrated migration compatibility. |
| `common/serializer/ChunkPosSerializer.java`, `UUIDSerializer.java`, old `SerializationHelper.java` | Chunk keys: big-endian X then Z; UUID keys: big-endian least-significant half then most-significant half | Same layouts, written directly | Preserve the exact key layouts, including negative coordinates; verify round trips after the applicable whole milestone. |
| `common/zstd/*`, dictionary resources | Dictionaries under `cesium/dictionaries/` | Same two dictionary blobs under `dictionaries/` | Git blob identities match (`4e9f7a0…`, `fd3a3fc…`). Resource location changes still require deliberate handling; NBT/native compatibility remains untested. |
| `maintenance/storage/*`, `maintenance/tasks/DatabaseConvert.java` | Combined world/player storage interfaces | Separate player/chunk implementations; raw chunk copy paths; changed concurrency | Both swallow asynchronous copy errors with `exceptionally(... return null)`. Neither establishes complete conversion merely by reaching the completion screen. Plan explicit failure propagation and data comparison. |
| Player storage implementations and converter roots | Old `playerdata`, `stats`, `advancements` paths | Same old names; player conversion uses Overworld dimension path as root | Both need explicit 26.1 player and world-root changes. New player export also writes stats/advancements without ensuring their parent directories exist. |
| `common/lmdb/LMDBInstance.java`, cursor/database implementations | Read transactions are created without clear owner closure; map-full retry does not consume an attempt | Similar concerns; new write preparation aborts without the old explicit `txn.close()` | Review transaction ownership, flush concurrency and bounded recovery within approved port work. Do not claim static suspicions are runtime reproductions. |
| `mixin/core/storage/*`, `mixin/core/upgrader/MixinWorldUpgrader.java`, chunk/player hooks | Older mixin/API targets, multiversion directives | Refactored hooks, including `MixinIOWorker`; still pre-26.1 upgrader assumptions | Use the newer source as a reference, then inspect the actual 26.1.2 classes. Neither branch solves the new world layout by itself. |
| `fabric.mod.json` | Explicit Minecraft target; breaks whole C2ME and Moonrise | Broad `>1.21.10` range; breaks two C2ME modules | A permissive version range or narrower incompatibility list is not proof of support. Keep incompatible experiments separate until demonstrated compatible. |

## Remaining constraints

- The two branches share persistence/conversion hazards. The older branch is a known comparison point, not a safety guarantee.
- Issue #31 branch `dfee4c3adc925dc633cf73ffd398ba76b746bd1b` can delete unreadable records and request a write lock while holding a read lock. It remains excluded. No failure has been reproduced locally.
- On-disk database names, keys and dictionary identity are the compatibility assumptions established here. Complete serialized value, compression, native-library and migration compatibility remain **untested**.
- No Cesium source was changed, built or regression-tested during this comparison. Milestone One and its gate still precede Milestone Two; user approval still precedes the three port milestones.

Sources: [selected base](https://github.com/CesiumMC/cesium-fabric/tree/ec3e418c3ee2caa332428552f0a1abcda54b5223), [newer branch commit](https://github.com/CesiumMC/cesium-fabric/tree/5d83dac5dbf7571a3c9eae5f543cbbd59acbfe24), [unsafe workaround](https://github.com/CesiumMC/cesium-fabric/tree/dfee4c3adc925dc633cf73ffd398ba76b746bd1b).
