# Fabric Performance Benchmark Lab

Repeatable Minecraft benchmarks with scripted routes and verified frame-time comparisons.

This experimental Windows tool compares a control configuration with one changed mod/configuration, then returns to the control to detect drift. Minescript drives the player through RestWorld's mob, painting and redstone rooms. PresentMon records frame intervals; the analyzer verifies the world, process, settings, route and capture before comparing results.

## Supported setup

- Windows 10/11, Python 3.11+, Java 25.
- Minecraft **26.1.2**, Fabric Loader **0.19.5**, Fabric API **0.155.3+26.1.2**, Minescript **5.0** (exact JARs in `manifests/tools-lock.json`).
- PresentMon **2.6.0 console** executable; administrator approval is required for capture.
- A dedicated disposable profile and a closed-world **RestWorld 26.1** master ZIP. The route is fixed to this world; arbitrary worlds and other Minecraft versions are unsupported.

No game files, worlds, mod JARs or native binaries are bundled. Install the dependencies from their original publishers. Sodium is an optional control renderer, not a required dependency.

## Start here

Follow the [human/AI workflow](docs/workflow.md) for setup, backups and exact PowerShell/Minecraft commands. Use [Docker for offline analysis, reports and tests](docs/container.md); Minecraft and the elevated Windows capture broker stay on the host. See [methodology](docs/methodology.md) for validity checks and [storage](docs/storage.md) for retention behavior.

Optional [automatic world entry and session commands](docs/automation.md) passed a live diagnostic integration check. Normal automatic comparison batches and fresh installations remain unverified.

```powershell
python .\scripts\benchmark.py --help
python -m unittest discover -s scripts -p 'test_*.py'
```

Three repeats screen candidates; five repeats confirm promising results. Each measured route has exactly one full unscored route first. You launch Minecraft, run `\labprepare 3`, then run `\labrun` after controller readiness. The controller supplies no desktop input and never approves Windows prompts.

## Status and license

Offline synthetic checks cover the command interface, archive restore/rollback, capture protocol and analysis. One live automatic diagnostic route passed through launch, minimized frame capture, analysis and normal save/quit; see [validation and limitations](docs/live-validation.md). Fresh installation and normal foreground comparison batches remain unverified. A five-minute screen is a target, not a verified promise. Existing laptop results do not establish universal mod rankings.

Original project code is [MIT licensed](LICENSE). Dependencies and the world retain their own licenses and [attribution](THIRD_PARTY_NOTICES.md). This is an unofficial tool, unaffiliated with Mojang, Microsoft, Fabric, Modrinth or Intel.
