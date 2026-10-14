# Measurement contract

The current workload is `restworld_rooms_v1`, using `full-route-only-v1` batches. It covers three equally weighted scenes: mob displays, paintings and a passive redstone display. Every measured repeat has exactly one full unscored pass of the same route. No shortened replacement workload is scored as equivalent.

World/master hash, restored file tree, configuration files, instrumentation, game PID, loaded mod versions, Java/heap, native framebuffer, graphics settings and sampling policy must be verified. World folder, singleplayer and dimension guards precede commands. Route evidence verifies physical movement, sprint/jump observations, content and camera exposure. Missing evidence rejects the run.

Fixed conditions: render distance 12, simulation distance 8, native default fullscreen, VSync off, unlimited FPS, Java 25 and 6144 MiB heap. The options contract is in `presets/lab-conditions.json`. Foreground/focus and original process identity are required throughout timing. You control power and background load; they are not detected or enforced. Teleport/readiness windows and intervals crossing scene boundaries are excluded; full stalls entirely inside a scene remain included.

PresentMon records presented-frame intervals, not a guarantee of displayed frames. Average FPS is derived from complete intervals; 1% low is `1000 / mean(slowest ceil(N * 0.01) intervals in ms)`. p95/p99 use the analyzer's fixed percentile method. A spike is a complete interval above 50 ms; report frequency, total spike time and worst frame. Keep raw CSV/QPC data and validity records together.

Three repeats are screens; five fresh repeats confirm. Run grouped control → isolated candidate → identical return control. Median control drift above 5% rejects the comparison. The analyzer also rejects changed instrumentation, runtime/settings, world identity or batch protocol. A passing screen still requires correctness/visual review; it does not establish statistical significance or universal performance rankings.

Continuous CPU/RAM/GPU resource sampling is off for headline FPS. Heap boundary snapshots are diagnostic and not peak memory or GC-pause measurements. Optional resource/overhead and legacy counter tooling remain advanced diagnostics with separate validation; do not mix them with headline scores.

Untested scope includes arbitrary worlds/versions, active redstone mechanisms, generation/lighting throughput, networking, despawning, server tick performance and Nether/End workloads. A mod targeting one of these needs a separately defined and validated workload before a claim about that behavior. This route cannot establish those gains.

## Developer checks

```powershell
python -m unittest discover -s scripts -p 'test_*.py'
```

Synthetic fixtures exercise failure boundaries without launching Minecraft or ETW. The Java installer group requires explicit `FABRIC_BENCHMARK_JAVA_TESTS=1`, a configured `local.settings.json` and toolchain; it is skipped by default. The core benchmark workflow uses Python's standard library. The optional read-only NBT corridor survey requires `nbtlib` and is not part of normal setup.

Still pending: live validation of the portable setup/session interface; new route-only batch duration; clean ETW drain and repeat-local corridor reuse in a complete live batch. Initial Modrinth 0.21.9 native instance/world launch was verified separately after human backup-dialog handling, with six focused launcher boundary fixtures. Unattended world entry is unverified; native profile cloning remains manual. Do not use synthetic FPS fixtures as laptop performance evidence.
