# Known issues and action plan

Recorded 2026-10-07 from the requested hypercritical read-only review.

These are **work items, not milestones**. They neither replace nor subdivide the user's Cesium milestones. Compilation, formatting and static investigation remain allowed during a Cesium milestone; regression/world tests wait until that whole milestone has been attempted/completed. The three port milestones produced in Milestone Two still require the user's definition or approval.

The user has resumed work. The earlier choice to finish setup and research first still applies: no exclusive foreground Minecraft runs until the computer is made available.

## KI-01 — Unsafe upstream issue #31 workaround

**Priority:** high. **Status:** confirmed upstream hazard; not imported into our port.

The `origin/issue/31` branch adds optional deletion of unreadable records. Its `KVDatabase` error path can request the write lock while holding the read lock, and its retry loop has no bound. Suppressing the crash by deleting data does not establish persistence correctness.

**Actions:** inspect the complete error/transaction/lock paths; preserve a source reference; do not cherry-pick the workaround. When the relevant whole port milestone is ready for regression testing, reproduce the compression/read failure in a disposable world, retain the input record, and fix the underlying cause. Preserve data and use bounded failure/recovery behavior rather than silently deleting records.

**Acceptance:** no workaround imported; documented lock/error design; relevant post-milestone regression cases establish preservation and termination. Current runtime reproduction is **untested**.

Source: [upstream workaround](https://github.com/CesiumMC/cesium-fabric/blob/dfee4c3/src/main/java/de/yamayaki/cesium/common/lmdb/KVDatabase.java).

## KI-02 — Cesium base branch not selected with sufficient evidence

**Priority:** high. **Status:** static decision documented on 2026-10-08; runtime format assumptions untested.

Our preparation branch starts at `ec3e418` on `dev/multiversion`. The newer `mc/1.21.11` branch at `5d83dac` targets `1.21.11-rc3` and changes roughly 90 files, including the storage/conversion APIs and build system. The initial code-size estimate and Stonecutter-specific plan describe the older branch.

**Actions:** compare build/toolchain, database keys and serialization, dimension/player paths, converters, transactions/flush/close behavior, mixins, supported versions and relevant fixes. Record a base-commit decision with reasons and discarded risks before implementing a standards pass or port. Keep upstream history and useful branches available; do not presume the newer branch is safer.

**Acceptance:** an explicit base commit, a file-level comparison and compatible on-disk format assumptions are documented. No runtime compatibility claim is made without the applicable milestone gate.

**Progress:** [base decision](cesium-base-decision.md) retains `ec3e418` to avoid importing the newer storage/converter rewrite wholesale. Database names, key layouts and identical dictionary blobs were compared; complete value/native/migration compatibility is not claimed. Source remains unchanged.

## KI-03 — PresentMon capture can accept the wrong or empty workload

**Priority:** high. **Status:** open.

The initial wrapper accepts any `java`/`javaw` PID, then accepts exit success and CSV existence. It does not establish Minecraft identity, world readiness, valid samples, capture duration, the intended presentation stream or route/action success.

**Actions:** require a run specification and explicit scenario evidence; check game identity without writing authentication arguments into logs. Validate process identity and lifetime, sufficient finite positive frame intervals, measured duration, presentation stream, duplicate/rejected samples and foreground/scenario markers. Produce a machine-readable result marked accepted/rejected with reasons. Preserve raw evidence locally; a rejected run never enters performance summaries.

**Acceptance:** wrong-PID, header-only, insufficient-duration, mixed-stream, invalid-frame and failed-scenario cases are rejected; a valid fixture is accepted. Minecraft live capture remains **untested** until calibration.

## KI-04 — Minecraft/OpenGL measurement accuracy not established

**Priority:** high. **Status:** open; Chrome smoke capture only.

The Windows tool works, but Chrome tracing does not validate Minecraft frame measurement. OpenGL instrumentation has limitations; zero or missing latency fields must not be treated as a precise CPU/GPU timing measurement.

**Actions:** pin the installed PresentMon release and CSV schema; explicitly distinguish presented-frame intervals from displayed-frame intervals. Choose and justify the primary FPS metric. Validate it against a Minecraft-side frame counter and scene duration during an exclusive calibration session. Disable the GUI overlay and other profilers during headline runs; quantify capture overhead using matched runs.

**Acceptance:** a documented column/stream/filter policy, Minecraft calibration results, known unavailable metrics and measured capture overhead. Until then all Minecraft FPS conclusions are **untested**.

Source: [PresentMon 2.6.0 limitations](https://github.com/GameTechDev/PresentMon/blob/v2.6.0/README.md).

## KI-05 — Baselines and common automation are not implemented

**Priority:** high. **Status:** open.

Development Modpack currently contains diagnostic and automation mods. It is not a true vanilla or Sodium-only baseline. Inactive profilers can still add overhead.

**Actions:** define separate exact manifests for true vanilla, a Fabric automation control, Sodium and the accepted stack. Define separate diagnostic variants. Use matching automation dependencies only in comparisons where they are explicitly accounted for. Start with fixed-viewpoint calibration, then validate walking/interactions, full-world reset and deterministic scene markers. Pin launcher/runtime and visual settings; randomize/interleave repeated runs.

**Acceptance:** every run names a manifest/settings/world/scenario hash; dependencies and diagnostic overhead are attributable; routes and actions have rejection criteria. The headline three-instance comparison remains **untested**.

## KI-06 — Git history and delivered documentation are inconsistent

**Priority:** high. **Status:** history reconciled and setup published on 2026-10-08; normal Git authentication unavailable and documented.

The remote was populated through the authenticated GitHub connector, giving it a different initial history from local Git. New setup files are not yet committed/published, and the output mirror and README tracker lag behind the setup evidence. Ordinary Git authentication is unavailable.

**Actions:** preserve both histories and local work. Reconcile against the existing remote without a force push or losing files; use the connector for authorized publication while ordinary authentication remains unavailable. Commit the actual setup and research, update statuses, refresh the output mirror, and record runtime/tool hashes. State clearly which Git operations work and which require normal authentication.

**Acceptance:** local/remote tracked contents and authoritative history match or their exact remaining limitation is documented; no untracked deliverable is omitted; README, setup evidence and delivered mirror agree. No credentials are committed.

**Progress:** published the reviewed plan, verdict, locks, scripts and setup evidence. Imported connector-retrieved Git objects only after verifying their exact hashes, compared local/remote trees, advanced remote `main` normally, and aligned local `main` without changing working files. The earlier local history is retained at `archive/setup-before-reconciliation` (`93da65d`). Current tracked contents follow the remote history. Refresh the delivered text mirror after documentation updates. Ordinary CLI push/pull authentication is still unavailable; use the authenticated connector until configured.

## KI-07 — Installer does not detect duplicate mod IDs or all constraints

**Priority:** medium. **Status:** open; current profile was empty before installation.

Checking an expected filename does not detect an older jar under another name with the same mod ID. Project API dependencies do not fully represent nested Fabric modules or runtime version constraints.

**Actions:** inventory top-level and nested jar metadata before changes, compare existing and intended IDs/versions, and fail on conflicts without overwriting/removing the user's files. Validate required/provided IDs and applicable version constraints. Stage and verify downloads before installation; use unique temporary files owned by the current invocation so cleanup cannot remove a pre-existing file.

**Acceptance:** incompatible duplicate IDs, missing dependencies, incompatible game/loader/Java versions and stale downloads are rejected before installing any new jar. Valid existing pinned files are retained. Runtime loader acceptance remains **untested**.

## Work order

1. Bring the known-issues register, README, setup evidence and Git delivery into agreement; preserve the review record.
2. Compare Cesium branches and document the base decision before applying coding standards or port changes.
3. Harden installation and pin runtime/baseline/diagnostic manifests.
4. Harden capture validation and define the measurement/automation protocol.
5. When the computer is available, calibrate Minecraft capture, settings, world and routes; then execute the benchmark matrix.
6. Continue the user's Cesium milestones and their whole-milestone regression gates. Handle the upstream error-path hazard within the applicable approved port scope.

Work items may be completed where independent; this order does not authorize running Cesium regression tests early or inventing additional milestones.
