# Setup evidence and remaining validation

Checked 2026-10-07. The user selected **setup and research first**, deferring exclusive foreground benchmark runs.

## Installed

PresentMon **2.6.0** desktop application is installed under `C:\Program Files\Intel\PresentMon`, with a Start Menu entry and its shared service running. Both official release downloads matched their published SHA-256 digests. A three-second elevated CLI capture against Chrome exited successfully and produced 19,152 bytes of frame-time CSV. This establishes tool operation, **not Minecraft/OpenGL capture accuracy or Minecraft performance**. Non-elevated tracing was denied by Windows. Run a complete benchmark batch from one elevated launcher; no user-group/security changes were made.

Source: [official release](https://github.com/GameTechDev/PresentMon/releases/tag/v2.6.0).

Installed into Development Modpack's `mods/`, with exact file sizes and SHA-512 verified against Modrinth:

- spark `1.10.187-fabric`.
- Entity Detective `26.1.2+v2.5.4`.
- Minescript `5.0-fabric-26.1.2`.
- Chunky `1.5.3`.
- Fabric API `0.155.3+26.1.2`.

Inspected top-level and nested Fabric metadata: required mod IDs are present, including Fabric Permissions API `0.7.0` supplied by a nested jar. Development Modpack uses Fabric Loader `0.19.5` and Java 25. Mods have **not been launched or benchmarked**. Runtime compatibility remains untested.

## Observable replacement

[Entity Detective](https://modrinth.com/mod/entity-detective) is an MIT-licensed Fabric project. Its documented commands include `/ed entity profile all 100`, entity-type profiling, dimension/range filters, block-entity profiling and per-position tick counts. Use it for location/type attribution, spark for execution stacks/GC, and PresentMon for client frames.

It is not a complete replacement for Observable's UI. Structured automatic export and equivalent per-position timing coverage are **unverified**. Do not treat tick counts as elapsed time. Validate output capture through Minescript/logging or a supported API before claiming fully automated diagnostics. [Source](https://github.com/netcrafts/Entity-Detective).

## World

Downloaded CurseForge file **8147210**, `RestWorld_26.1.zip`: 49,135,284 bytes compressed, 176,859,034 bytes represented by archive members. The clean archive is in the ignored `runtime/worlds/` directory; its SHA-256 is in `manifests/world-lock.json`.

The listing supports **26.1.2**, but the actual `level.dat` was saved in **26.1** (DataVersion 4786). It uses the new dimension/player layout. This is a compatible-version candidate, not a world already runtime-validated on 26.1.2.

Source-derived spawn: dimension `minecraft:overworld`, block position **(0, 101, 0)**, yaw **0**, pitch **0**. This is a spawn metadata value, not a calibrated player waypoint or guarantee of safe footing. Exact room paths, interaction targets and successful player inputs remain pending in-game calibration. The datapack declares format `[101, 1]`.

## Repositories

- Private pack repository: [Sploosh4/modpack](https://github.com/Sploosh4/modpack).
- Public upstream-derived fork: [Sploosh4/cesium-fabric](https://github.com/Sploosh4/cesium-fabric). It preserves all six upstream branches and tags. GitHub's ordinary fork of this public upstream is public; the pack repository is private.
- Local Cesium checkout: `work/cesium-source`, remotes `upstream` and `origin`, branch `port/26.1.2`.

GitHub publication currently uses the authenticated connector. Ordinary command-line Git has no GitHub credentials on this machine. Local Git and the remote repository exist, but their initial commit histories differ because publication used GitHub's contents API. Do not force-push or claim ordinary push/pull synchronization is configured until normal Git authentication and history reconciliation are complete.

No Minecraft FPS data has been collected, and no Cesium regression/world tests have run.
