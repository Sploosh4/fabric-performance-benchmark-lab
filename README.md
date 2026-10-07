# Minecraft performance modpack and Cesium port

Updated: 2026-10-08. Target: Minecraft Java **26.1.2**, Fabric.

## Decisions and current status

- Use the existing Modrinth **Development Modpack** profile. This `modpack/` directory is the source-controlled project; runtime mods, worlds and launcher state remain outside it.
- Create a **private** GitHub modpack repository under `Sploosh4`. Keep Cesium in a separate upstream-derived repository/fork, preserving its license and history.
- Benchmark and port Cesium on 26.1.2 first. A later Minecraft upgrade is a separate decision.
- Use a compatible replacement for Observable if one exists. Mark unavailable profiling coverage **untested**.
- Install PresentMon as a Windows application/tool, with its CLI available for automation.
- Compilation and formatting checks are allowed during Cesium milestones. Regression and world tests run only after an entire milestone has been attempted/completed. Fix failures and repeat that milestone's regression gate before continuing.
- The user defines Cesium milestones. Milestone Two produces three proposed port milestones; these require the user's definition/approval before execution.

This document distinguishes plans from measured results. No FPS improvements or Cesium runtime correctness have been demonstrated yet. Research, repository setup, installation and measurements each receive their own recorded status.

## Known issues and action plan

The requested hypercritical review is recorded in [research/known-issues.md](research/known-issues.md), with priorities, actions and acceptance criteria for all seven findings. These are work items, **not milestones**. The concise [execution plan](research/execution-plan.md) passed the requested adversarial planning gate on 2026-10-08: the first independent review reported zero medium/high findings; see [review evidence](research/plan-review.md). Setup and research resumed; foreground Minecraft tests remain deferred under the user's setup/research-first decision. Current installation and download evidence is in [research/setup-status.md](research/setup-status.md).

## License: can we fork and publish Cesium?

**Yes.** Upstream identifies the license as **LGPL-3.0-only**. We can modify Cesium, fork it and publish our version under that same license. Preserve copyright/license notices, identify modified files and dates, include the LGPL and incorporated GPL terms, and make the corresponding source and required build material available with binary releases. Retain notices for bundled dependencies. A fork should clearly identify its origin and our maintenance responsibility.

The modpack's own configuration/scripts are a separate project. Cesium's license does not automatically license every unrelated mod in a pack. Record each component's distribution rules and prefer Modrinth manifests referencing original downloads rather than redistributing jars without checking permission.

Sources: [Cesium license](https://github.com/CesiumMC/cesium-fabric/blob/dev/multiversion/LICENSE), [LGPL v3](https://www.gnu.org/licenses/lgpl-3.0.html), [accessible license mirror](https://www.gnu.de/documents/lgpl-3.0.en.html).

## Repository and filesystem layout

```text
Development Modpack/
  mods/, saves/, config/             Modrinth runtime; not source-controlled here
  modpack/                          Git repository
    README.md                       requirements, decisions, protocol, status
    manifests/                      exact mod IDs, versions, hashes, dependencies
    presets/                        fixed benchmark settings and configuration
    scenarios/                      scene definitions and player action scripts
    scripts/                        setup, launch, capture, reset and analysis
    research/                       mod evidence, licenses and port assessments
    results/                        compact tables and approved summaries
    .gitignore                      excludes binaries, worlds, caches and secrets
```

Cesium source belongs in a separate checkout, not copied into this repository. Use an `upstream` remote, a personal `origin`, and a dedicated 26.1.2 branch. Record source commits in this repository. Version control text manifests, settings, scripts and summaries. Exclude Minecraft assets, jars, Java installations, native binaries, saves, profiler recordings, account files, auth tokens and launcher databases. Do not edit Modrinth's SQLite database directly.

Maintain three isolated benchmark instances: **vanilla**, **Sodium only**, and **Sodium plus accepted optimizations**. Use separate saves and settings. The development profile is the project home; do not silently overwrite its existing mods or worlds to obtain a baseline.

## 1. Download a 26.1.2 test world with moving parts

Candidate found: **RestWorld_26.1.zip**, explicitly listed for 26.1.2, published 2026-05-26: [exact download entry](https://www.curseforge.com/minecraft/worlds/restworld/files/8147210).

RestWorld cycles blocks and mobs through variants, contains interactive controls, a biome/structure sampler and a battle arena. It is a candidate for animated scenes, not yet a validated performance benchmark. Its command/function overhead is itself part of the workload and must remain fixed between runs. The author's website identifies the world as CC BY 4.0; preserve attribution and verify the downloaded archive's notices before redistribution.

Download the exact version, record its SHA-256 and inspect its datapack/version metadata. Validate it in 26.1.2 and identify a fixed loop phase. Keep an immutable clean archive. Work only on copies. Add separate controlled scenes where needed: redstone/hoppers, visible and occluded mobs/block entities, chunk traversal, particles, and Nether travel. Do not claim this world already includes every required stress case.

Sources: [RestWorld project](https://www.curseforge.com/minecraft/worlds/restworld), [author's description and license](https://claritypack.com/restworld/index.html).

## 2. Accurate, repeatable character actions

Preferred automation: **Minescript** for version-supported player movement, camera direction, commands and interactions, with a fixed scenario script. A Fabric 26.1.2 release exists: `5.0-fabric-26.1.2` (Modrinth version `wib8NXKz`). Verify API support for each interaction before relying on it.

Use in-game commands/datapacks to establish time, weather, player inventory, entities and redstone phase. Use normal player input for interaction tests: placing blocks with commands is not evidence that a player right-clicked them. Validate the target block/entity, distance, yaw/pitch and resulting state before recording a successful action.

For exact vanilla comparisons, prefer a common externally driven input route and vanilla datapack setup. Installing Minescript in one baseline changes that baseline. If scripting requires Fabric, report both a true vanilla run and a separately labelled Fabric automation control; apply identical automation dependencies to the modded comparisons. Separate route calibration/diagnostic overhead from headline FPS captures.

Define actions in simulation ticks for reproducible game state; record wall time and achieved tick rate independently. If the game falls behind, compare matching route segments rather than mismatched frames or mob states. Restore the complete closed-world snapshot between runs, including entities, POI, player and dimension data. QuickPlay can select a world, but startup readiness requires a verified marker, not a guessed delay.

Sources: [Minescript documentation](https://minescript.net/docs), [Fabric automatic testing](https://docs.fabricmc.net/develop/automatic-testing).

## 3. Measurement tools and distinct roles

| Tool | Specific role | Automation | 26.1.2 status |
| --- | --- | --- | --- |
| PresentMon | Client frame intervals, average FPS, tail frame times and stutter counts | Windows CLI, process ID, timed CSV captures | Installed 2.6.0; Chrome smoke capture passed; Minecraft/OpenGL calibration untested |
| spark | CPU call stacks, tick-time diagnosis, allocation/GC and identifying expensive execution paths | Game/server commands; save captures to files | Fabric `1.10.187-fabric`, Modrinth `e3hsPc1o`, installed; in-game validation untested |
| Entity Detective (Observable substitute) | Entity/block-entity type/location attribution | Commands; structured export must be validated | Installed `26.1.2+v2.5.4`; per-position tick counts are not elapsed time; missing coverage untested |

The tools intentionally measure different layers, though their capabilities overlap slightly. Do not run all profilers during headline FPS runs. First collect PresentMon-only measurements, then separate spark/entity diagnostics. Measure profiler overhead. If no compatible entity profiler exists, use spark where helpful and explicitly mark entity-level timing coverage untested.

PresentMon CLI flags must be checked against the installed version. Intended capture shape: target the actual Java game PID, finite duration, CSV output, automatic termination. OpenGL/Vulkan presentation events do not guarantee all CPU-latency fields are available; record unavailable fields rather than interpreting blanks as zero.

Sources: [PresentMon CLI](https://github.com/GameTechDev/PresentMon/blob/main/README-ConsoleApplication.md), [spark commands](https://spark.lucko.me/docs/Command-Usage), [Observable source](https://github.com/tasgon/observable).

## 4. Coordinates, route and interaction specification

**Exact route coordinates await in-game inspection and calibration.** The downloaded world's source-derived spawn is `(0, 101, 0)` in the Overworld; it is not a validated waypoint. Store one authoritative scenario definition with dimension, player XYZ, yaw/pitch, game mode, inventory, target block/entity IDs, waypoint coordinates, tick numbers, action type and expected resulting state. Record the world archive and modified snapshot hashes.

Initial scenario set:

1. Animated RestWorld room: stationary view, then a fixed walking circuit and validated control-button interactions.
2. Mob workload: fixed species/counts, AI state and confinement; visible and occluded camera views. Measure client frames and server tick times separately.
3. Block entities/redstone: fixed active hopper/container/piston layout, deterministic clock phase, lever toggles and container open/close actions.
4. Terrain route: repeatable traversal across already generated chunks; a separate fresh-generation route uses identical restored terrain state.
5. Nether: fixed portal/dimension entry and route, with separate generation and persistence cases.

Reject a run if the player route, action success, world state, foreground state or capture process does not match its specification. Small visual snapshots plus machine-readable state markers can establish that the intended workload ran.

## 5. Fixed vanilla and Sodium settings

Proposed common preset, to verify against 26.1.2's actual settings:

| Setting | Value |
| --- | --- |
| Resolution | 1920 x 1080, fixed window mode and render scale |
| FPS limit / VSync | Unlimited / off |
| Render / simulation distance | 12 / 8 chunks |
| Graphics | Fancy; no shaders or external resource packs |
| FOV | 70; FOV effects and view bobbing disabled for route consistency |
| Clouds | Off |
| Particles | All |
| Entity distance | 100% |
| Biome blend | Fixed equivalent value, initially 3 x 3 |
| Java | Same verified Java 25 runtime for all 26.1.2 instances |
| Heap | Same fixed cap; choose after inspecting available RAM, initially consider 4 GiB |

Also pin ambient occlusion, mipmaps, entity shadows, lighting, sound, language and any new rendering/backend selection. Sodium may expose settings with no vanilla equivalent: document them, preserve visual quality and hold them fixed. Do not presume old `options.txt` keys or unlimited-FPS numeric encodings remain valid.

Record CPU/GPU, driver, OS, display, power mode, plugged-in state and process/background activity. Detected hardware: Ryzen AI 7 445, Radeon 840M. Shared-memory graphics make heap and memory pressure especially relevant. Run one game at a time, foreground, after warm-up and with thermals stable.

## 6. Preliminary Sodium companion configuration

Candidate availability checked through Modrinth on 2026-10-07; compatibility claims require installed-version validation.

| Candidate | Fabric 26.1.2 release | Workload to test | Current verdict |
| --- | --- | --- | --- |
| Sodium | `mc26.1.2-0.9.2-fabric`, `tZQ3jqnf` | Rendering across every client scene | Available; untested |
| Lithium | `mc26.1.2-0.24.7-fabric`, `Oqq8TOAV` | Mob AI, collisions, redstone/hoppers and integrated-server tick costs | Available; untested |
| FerriteCore | `9.0.0-fabric`, `d5ddUdiB` | Memory/heap use and GC pressure; do not require a direct FPS gain | Available; untested |
| EntityCulling | `1.11.2`, `YDFyjf5b` | Occluded entities/block entities, visibility correctness and CPU overhead | Available; untested |

Begin with defaults, pin dependencies and save complete configuration snapshots. Add one candidate at a time; availability is not evidence that it helps this hardware. Check Sodium interactions and current upstream issues. Do not add visual compromises to the primary quality-preserving preset.

Sources: [Sodium](https://modrinth.com/mod/sodium), [Lithium](https://modrinth.com/mod/lithium), [FerriteCore](https://modrinth.com/mod/ferrite-core), [EntityCulling](https://modrinth.com/mod/entityculling).

## 7. Three-instance comparison

Compare true vanilla, Sodium alone, and Sodium plus the accepted stack. Pin game/runtime, world snapshot, scene, route, resolution and settings. Record any loader/automation control separately so its overhead is not attributed to Sodium.

Start with 60 seconds of warm-up and 120 seconds of capture, at least five repetitions per scene/configuration. Extend a run only when variance or workload coverage requires it. Randomize/interleave configuration order to reduce thermal/order bias. Clearly distinguish warm-cache rendering from cold-start loading and fresh generation.

Report per-run and aggregate average FPS, p50/p95/p99 frame time, consistently defined 1% low FPS, stutter count, tick-time distribution, heap/GC, and relevant load/save/generation times. Calculate FPS from valid measured frame durations; do not average arbitrary instantaneous FPS samples. Retain sample counts and variability. Gains must exceed run-to-run noise and repeat across relevant scenes. No benchmark results exist yet.

## 8. Test each optimization independently

Primary method: **incremental add-one testing against the already accepted stack**. This answers whether a mod improves the pack we are actually building. Use a targeted workload and an ordinary gameplay scene for each candidate.

For promising or conflicting candidates, additionally test Sodium plus that candidate alone, then remove it from the final stack as an ablation. These checks identify redundancy and interactions without requiring every possible mod combination. A memory/storage mod can earn its place through memory or I/O gains even without higher steady-state FPS; report that benefit accurately.

For every candidate, record exact versions, dependencies, settings, changes to visual/gameplay behavior, workload, repetitions, metrics, variance, conflicts and accepted/rejected/untested status. Never infer the result of a mob, storage or lighting workload from an unrelated stationary FPS scene. Mark unavailable versions, missing profiler coverage and unrun scenes as untested.

## 9. Compare established optimization packs

Inspect the exact 26.1.2 manifests/configuration of **Fabulously Optimized** and suitable peers. Classify entries as performance, dependency, compatibility, UI or feature restoration; a popular pack's inclusion does not prove an FPS benefit.

For missed candidates, check current loader/game support and upstream rationale, then repeat section 8. Record the pack/version/date used and which settings materially affect results. Do not import an entire preset and lose attribution of gains.

Source: [Fabulously Optimized](https://modrinth.com/modpack/fabulously-optimized).

## 10. Less popular optimization projects

Search current Fabric 26.1.2 projects and upstream repositories for narrower gains: packet/network work, entity/block-entity rendering, allocation, chunk scheduling, visibility, model caching, startup and disk storage. Verify source, maintenance history, supported versions and licenses. Investigate competing approaches separately and run the workload each approach claims to improve.

Research queue, not endorsements: ImmediatelyFast, MoreCulling, ModernFix and C2ME where supported, plus smaller projects discovered during research. Cesium currently declares C2ME and Moonrise incompatible; keep those experiments in separate configurations. Do not assume older optimization mods still help after vanilla or Sodium changes.

## 11. Unmaintained projects and Cesium alternatives

For each project record: current relevance, claimed mechanism, measured or unmeasured expected benefit, last upstream activity, Minecraft/loader support, source availability, exact license, source size, native dependencies, maintenance risk and estimated port effort. Separate upstream claims from our results.

### Cesium assessment so far

- Project: [Cesium Storage Format](https://modrinth.com/mod/cesium), [source](https://github.com/CesiumMC/cesium-fabric).
- Modrinth labels it unmaintained/experimental. Published `0.2.6` supports up to 1.21.10; no published 26.1.2 build found.
- License: LGPL-3.0-only. Source audit: about 56 Java files, 3,091 nonempty Java lines and 18 mixin source files. These are approximate code-size counts, not a port estimate by themselves.
- Audited upstream commit: `ec3e418c3ee2caa332428552f0a1abcda54b5223` on `dev/multiversion`.
- Replaces Anvil storage using LMDB and zstd. Main potential benefit is storage/I/O and associated stalls, not automatically higher average FPS.
- 26.1 changes Java/tooling, dimension locations, player data paths and world-upgrader internals. Cesium's old world-root assumptions, player paths, synthetic mixin targets and upgrade hooks need review.
- Upstream reports include native crashes under heavy generation, conversion/export failures and chunk/compression problems. Reports are not independently reproduced here: issues [19](https://github.com/CesiumMC/cesium-fabric/issues/19), [31](https://github.com/CesiumMC/cesium-fabric/issues/31), [32](https://github.com/CesiumMC/cesium-fabric/issues/32), [33](https://github.com/CesiumMC/cesium-fabric/issues/33).
- Preliminary engineering estimate: roughly 2–4 working weeks for a skilled developer to investigate, port and validate; substantial uncertainty remains. No port implementation or regression tests have started. A later-discovered `mc/1.21.11` branch targets a release candidate and differs substantially; the figures above describe the older multiversion branch. Compare both before choosing the port base (KI-02).

Alternative research queue: Linear region format implementations, region compression settings supported by the current game, and other maintained storage/conversion projects. Verify exact repositories, current compatibility, migration guarantees and license before recommending any. Chunk scheduling mods are not equivalent storage-format replacements. No verified drop-in Cesium alternative has been selected.

Other abandoned candidates to assess rather than presume useful: Starlight, LazyDFU, older model/memory optimizers and render optimizers superseded by vanilla or Sodium. Record when the original benefit has already been incorporated or no longer applies.

Sources: [Fabric 26.1 migration](https://fabricmc.net/2026/03/14/261.html), [Minecraft 26.1 world-storage changes](https://www.minecraft.net/en-us/article/minecraft-java-edition-26-1).

## 12. Cesium milestones and regression gates

### User-defined Milestone One: coding standards

Audit existing conventions and tooling first. The initial repository listing has no obvious `.editorconfig` or formatter configuration; a full convention audit is still pending. Preserve established conventions where coherent. If no enforced standard exists, choose standards close to Fabric/Minecraft modding: consistent Java formatting with a pinned formatter, appropriate Kotlin/Gradle formatting, `.editorconfig`, and a short `CONTRIBUTING.md`. Keep formatting-only changes separate from functional changes and preserve Stonecutter directives/multiversion behavior.

Apply the whole agreed standards pass before running its regression gate. Formatting and compilation checks may happen during the pass. After completion, verify the existing supported upstream target still builds/loads and can round-trip a disposable world with no observable data differences. If a baseline defect prevents a clean comparison, document it and fix or resolve it before claiming this gate passed.

### User-defined Milestone Two: change analysis and three proposed milestones

Inspect all build, native-library, mixin, serialization, directory, conversion and upgrade assumptions. Produce a file-level change map, dependencies and acceptance criteria. Propose exactly three port milestones for the user to define/approve. The following are **draft scopes, not approved milestones**:

1. Toolchain and live storage integration on 26.1.2: Java 25/Fabric build migration, native-library compatibility, current mixin hooks and fresh-world chunk/entity/POI/player persistence.
2. Migration and conversion correctness: dimension/player/saved-data paths, existing Anvil import, Cesium reopen/export, world upgrading and preserving all data classes.
3. Reliability and performance readiness: flush/shutdown/error behavior, large-generation/native stability, configuration compatibility, packaging and reproducible benchmarking.

No port changes start under these draft scopes until the user approves/defines them. Compilation and formatting may run within each approved milestone. Regression/world tests wait until that entire milestone has been attempted/completed; failures are fixed within that milestone and its gate rerun before advancing. Do not subdivide a milestone to justify earlier regression runs.

### Required regression workloads after each applicable whole milestone

- Fresh Overworld save/reopen and controlled entity, block-entity, POI, inventory, advancement and stats checks.
- Nether generation and save/reopen; End and namespaced saved-data coverage where applicable.
- Existing Anvil import and Cesium-to-Anvil export, with structured NBT/data comparison rather than visual appearance alone.
- Chunky generation on disposable worlds with a bounded radius, including the Nether. Fabric 26.1.2 `1.5.3` (`4Eotm6ov`) is available; actual generation is untested.
- Clean shutdown/flush, repeated reopen and applicable recovery/failure tests.
- Storage size, save/load/generation times, tail frame times and profiling under the corresponding workload.

A world opening successfully is necessary but insufficient: silent missing entities, player files or saved data count as regressions. Preserve world seed, coordinates, state markers and expected data for comparisons. Any relevant scenario not executed remains untested.

### Storage discipline

Use disposable copies and no valuable gameplay saves. Retain one clean input archive/snapshot and the current working copy; preserve compact results and failure repros rather than accumulating full worlds. Begin with bounded Chunky regions and inspect free space before growth. Remove obsolete downloads/build caches only after their replacements are verified. Keep cleanup confined to known project-owned paths; never recursively delete an unchecked or launcher-shared directory.

## Execution tracker

| Work | Status |
| --- | --- |
| Target/profile/privacy/testing decisions | Confirmed by user |
| Cesium source/license audit | Preliminary research complete |
| 26.1.2 candidate world | Downloaded and hashed; saved in 26.1 and listed compatible with 26.1.2; in-game validation untested |
| Exact route/coordinates/player interactions | Pending world inspection and calibration |
| Modrinth/Git/GitHub setup | Profile and both repositories available; setup published and histories reconciled; ordinary CLI Git authentication unavailable (KI-06) |
| PresentMon installation | Windows application/CLI installed; elevated Chrome smoke capture succeeded; Minecraft accuracy untested (KI-04) |
| spark and compatible entity profiler | spark and Entity Detective installed, with Minescript, Chunky and Fabric API; Minecraft launch and export coverage untested |
| Fixed presets and pinned candidate stack | Semantic preset and diagnostic tool lock saved; applied game settings and performance stack untested |
| Three-instance and individual-mod measurements | Untested |
| Established packs and niche/abandoned mod review | Preliminary queue only |
| Cesium Milestone One standards pass | Not started |
| Cesium Milestone Two change map | Not started |
| Three port milestones | Await user definition/approval after Milestone Two |

Results are only promoted from planned/untested when the actual evidence is recorded. This tracker must be updated as work proceeds.
