# Execution plan

Target: Minecraft Java 26.1.2 in Development Modpack. This is a work plan, **not a set of milestones**. The user's Cesium milestones and testing gates retain authority.

## Important steps

1. **Make the project record dependable.** Preserve local and remote Git history, publish the setup and research to the private modpack repository, keep Cesium in its separate licensed fork, and synchronize the README, known-issues register and delivered copies. Never commit credentials, runtime binaries or worlds.
2. **Resolve setup hazards before adding more mods.** Compare Cesium's published and newer branches and record a justified base choice. Keep the unsafe issue #31 workaround out. Harden the installer to reject duplicate mod IDs, missing or incompatible dependencies and game/loader/Java mismatches before changing the profile; stage verified downloads and preserve existing files.
3. **Prepare distinct, reproducible configurations.** Pin true vanilla, a Fabric automation control, Sodium, the accepted optimization stack and separate diagnostic variants. Keep equivalent visual settings, runtime and world state. Use PresentMon for frame capture, spark for CPU/tick diagnosis and Entity Detective for entity/block-entity attribution; record missing coverage rather than assuming it works.
4. **Validate the benchmark before trusting results.** Keep the downloaded world immutable and work on disposable copies. When the computer is available for exclusive Minecraft use, validate 26.1.2 support, exact coordinates, route, actions and state reset. Start with a fixed view, then walking and interactions. Reject wrong-process, empty, short, mixed-stream or failed-scenario captures. Calibrate PresentMon against a game-side frame counter, distinguish presented from displayed frames, and measure capture/automation overhead.
5. **Measure the three configurations and each candidate fairly.** Use matching scenarios, warm-up and repeated interleaved runs. Add candidates one at a time to the accepted stack, testing their claimed workload and ordinary gameplay; use standalone checks or removal checks when interactions or redundancy are uncertain. Report variability, frame times, tick times and relevant memory/I/O benefits. Accept improvements only when they exceed noise without correctness or visual regressions. Unrun coverage stays untested.
6. **Extend the research and repeat candidate testing.** Check exact Fabulously Optimized manifests, narrower optimization projects and unmaintained candidates. Record version support, mechanism, source/license, maintenance, project size and estimated port work. Include Cesium alternatives, and distinguish storage improvements from FPS claims. Do not copy another pack wholesale.
7. **Follow the user's Cesium milestones exactly.** Finish Milestone One's standards audit/pass before regression testing. Finish Milestone Two's change analysis and propose exactly three port milestones; wait for the user's definition/approval before implementing them. Compilation and formatting are allowed during milestones; regression/world tests wait until each whole milestone has been attempted/completed. Fix failures and rerun that gate before advancing. Include save/reopen, structured data preservation, import/export, bounded Chunky generation and Nether coverage where applicable; never use valuable saves.
8. **Keep evidence and storage under control.** Retain compact results, source/tool/config/world identifiers and useful failure reproductions. Clean only verified project-owned temporary paths. Update known issues and test status as evidence arrives; a plan or successful launch is not a measured improvement or proof of data preservation.

## Current boundaries

- Setup and research can continue now. Foreground Minecraft calibration and benchmarks remain deferred until the user makes the computer available.
- No Cesium implementation has started. The three port scopes in the README are drafts awaiting user approval after Milestone Two.
- All seven hypercritical findings remain tracked in [known-issues.md](known-issues.md); this plan does not mark their runtime acceptance criteria passed.

## Adversarial review gate

Implementation is paused while this plan is reviewed. An independent hypercritical subagent must find no unresolved medium or high issues **in the plan** before this gate opens. Revise the plan and request another review whenever either severity remains. Existing implementation defects and untested work remain tracked separately after the planning gate passes.

Status: **passed on 2026-10-08 after round 1**, with zero medium/high findings. See [plan-review.md](plan-review.md). Passing this gate does not approve Cesium port milestones or authorize foreground tests.
