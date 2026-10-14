# Docker and Windows responsibilities

Docker packages the offline Python tools. It does not replace the Windows game, launcher or capture broker. The image uses a digest-pinned official Python 3.11.17 base, includes original source and notices, and installs no additional Python packages.

| Work | Where it runs | Reason |
| --- | --- | --- |
| Minecraft, Modrinth, Fabric, Minescript and player actions | Windows host | Live game, graphics, world and input state |
| PresentMon console, administrator approval and ETW broker | Windows host | Windows tracing and original client PID/lifetime |
| Profile preparation, mod changes, restore/rollback and launch/session orchestration | Windows host | Must verify that the exact Windows client is closed or alive before changing its files |
| Captured-frame validation, scene analysis and control/candidate comparisons | Container or host Python | Read completed evidence; no game or graphics access needed |
| JSON/Markdown reporting | Container | Writes new reports to a separate explicit output mount |
| World ZIP inspection | Container | Read-only name/bounds/fingerprint check; no extraction, content/CRC validation or world loading |
| Synthetic offline tests, including restore/protocol fixtures | Container and host | Only disposable fixture paths; native Windows calls mocked where appropriate |
| Java helper compilation and optional Java installer fixtures | Host | Java/Fabric dependencies are installed separately and not bundled in this image |

Live-world restoration is deliberately unavailable through the container entrypoint. Sharing a live profile and a host-control service would add privileges and a new trust boundary without replacing the existing Windows process safeguards. Pure restoration code is covered with synthetic container fixtures; that is not a live Docker-to-host restoration test.

## Build and test

Run from the repository root with Docker Desktop using Linux containers:

```powershell
docker build -t fabric-performance-benchmark-lab:local .
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=128m,mode=1777 fabric-performance-benchmark-lab:local test
```

This runs without administrator privileges inside the container, network access, exposed ports, a Docker socket or credentials. The root filesystem is read-only; temporary normalization and test files use `/tmp`. The image's default UID/GID is `10001:10001`. The optional Java installer fixture is skipped; the Windows host-command fixture is also skipped on Linux. Mocked Windows API tests are synthetic coverage, not ETW validation.

The Docker engine itself requires the permissions described by its publisher. This project never mounts its socket or requests a privileged container.

## Analyze completed host captures

First finish and stop the host capture. Share only the completed capture directory, not your whole profile, home directory or credentials. Docker's [bind mounts](https://docs.docker.com/engine/storage/bind-mounts/) make the explicitly selected host directories available at the container paths below.

In PowerShell, substitute your capture directory:

```powershell
New-Item -ItemType Directory -Path .\runtime\container-output -Force | Out-Null
$env:LAB_INPUT = (Resolve-Path .\runtime\outputs\session-captures).Path
$env:LAB_OUTPUT = (Resolve-Path .\runtime\container-output).Path
docker compose build
docker compose run --rm offline diagnostic /data/input/YOUR_DIAGNOSTIC_SUITE --name diagnostic-check
```

For a normal captured batch, use `analyze` instead of `diagnostic`. For a full comparison:

```powershell
docker compose run --rm offline compare /data/input/CANDIDATE --control /data/input/CONTROL_BEFORE --control-after /data/input/CONTROL_AFTER --name comparison
```

These commands revalidate evidence; changing the command cannot bypass repeat, route, settings, drift or diagnostic-exclusion gates. `diagnostic` requires a diagnostic-labeled suite; normal `analyze` and `compare` refuse diagnostic suites. No network connection or host-control broker is used for analysis.

`LAB_INPUT` is mounted read-only at `/data/input`; `LAB_OUTPUT` is the only persistent writable mount, at `/data/output`. Both host directories must already exist. Without these variables, Compose uses `runtime/container-input` and `runtime/container-output`, which you must create first. Input paths outside `/data/input`, symlink paths and output paths outside `/data/output` are refused. Reports contain source metadata and may include personal paths; review them before sharing. Raw evidence is unchanged. Existing reports are never overwritten: choose a new `--name` to rerun.

On Linux, the output directory must be writable by the container user. From an ordinary non-root account, use `docker compose run --rm --user "$(id -u):$(id -g)" offline ...` to match your own UID/GID and directory ownership. Do not solve permissions with a privileged container or a broad writable profile mount. Windows Docker Desktop permissions were verified with the documented output bind mount. Input data on the Windows filesystem can be slower than Linux-native mounts; [Docker's WSL guidance](https://docs.docker.com/desktop/features/wsl/best-practices/) describes that tradeoff.

For a master ZIP already in the input directory:

```powershell
docker compose run --rm offline inspect-world /data/input/master.zip --name master-inspection
```

This does not restore or modify a world. Continue to use the [host workflow](workflow.md) for verified disposable restoration.

## Validation and limits

The Linux image's offline suite and Windows offline suite pass. The container also analyzed the existing completed live diagnostic capture from a read-only Windows mount and produced labeled reports; normal analysis rejected the same diagnostic capture. Only reviewed source dependencies enter the image build context. Local configuration, worlds, captures, account data and native binaries are excluded.

This validates host capture data to container analysis/reporting. It does not validate container-driven game launch, elevated capture, live restoration, automated mod switching or normal automatic comparison batches. No game, world, mod JAR, PresentMon executable or account credential is bundled. Docker image publication is not configured; build locally. The [live validation limitations](live-validation.md) still apply.
