# Human / AI benchmark workflow

Use PowerShell from the repository root. `python` must be a normal installed Python 3.11+ executable; no particular AI app runtime is required. Substitute your own absolute paths. Keep one configuration file per lab (`benchmark.local.json` is ignored by Git). For a different file, put `--config 'C:\path\lab.local.json'` before the command on **every** invocation, including the elevated broker.

## 1. One-time setup

1. Create a dedicated Modrinth profile: Minecraft 26.1.2, Fabric Loader 0.19.5, Java 25, 6144 MiB maximum heap. Install the exact Fabric API and Minescript JARs listed in `manifests/tools-lock.json`. Do not add profiling mods to headline FPS runs.
2. Download [RestWorld 26.1](https://www.curseforge.com/minecraft/worlds/restworld/files/8147210). Keep this original ZIP outside the profile. `manifests/world-lock.json` identifies the original download. The ZIP must contain one top-level world folder and `level.dat`.
3. Install PresentMon 2.6.0 from [Intel's official project](https://github.com/GameTechDev/PresentMon/releases). Use `PresentMonConsoleApplication\PresentMon-2.6.0-x64.exe`, not the GUI executable. Close its GUI for measurements; the shared service may remain running.
4. Close Minecraft. Initialize the local configuration and install the project's scripts (existing different scripts/settings are preserved and cause a clear refusal):

```powershell
python .\scripts\benchmark.py init --profile 'C:\path\to\dedicated-profile' --world-archive 'C:\path\to\RestWorld_26.1.zip' --presentmon 'C:\Program Files\Intel\PresentMon\PresentMonConsoleApplication\PresentMon-2.6.0-x64.exe'
python .\scripts\benchmark.py setup
python .\scripts\benchmark.py check
```

`init` hashes your archive/tool and creates local configuration. `setup` copies only required Python instrumentation and configures Minescript to use that Python executable. It changes no mod JARs or worlds. Do not replace a working profile's scripts without preserving them first; for initial evaluation, a new dedicated profile is simplest.

**Backups:** If adapting your own existing world, first save and quit Minecraft and create one master ZIP manually, with a single top-level world folder. Keep your original world separately. This release's route only supports RestWorld's specified geometry. Once configured, `prepare` restores a disposable `Lab_` copy automatically; you do not make a new master ZIP each run.

## 2. Prepare one control batch (Minecraft closed)

Keep the desired control mod/configuration set installed. Use a unique configuration ID for each distinct set, but reuse the **same** control ID and identical files for its return check:

```powershell
python .\scripts\benchmark.py prepare --name sodium-control --role control
```

This checks files and a closed client, restores the clean world, preserves the previous disposable world as a receipted recovery copy, then pins actual JAR/config/script hashes. State/manifests are in `runtime\state\experiments` by default. The master archive is unchanged.

By default recovery copies accumulate. To explicitly permit bounded cleanup of **unchanged, receipted copies from the same world/master**, add `--prune-owned-recovery` to preparation. It keeps the newest receipted recovery copy; it never adopts or prunes historical unreceipted copies. Do not use this flag if you want every prior disposable world retained. Failed extraction stages are cleaned automatically; `--retain-failed-stage` opts into retaining them for diagnostics.

## 3. Start the broker once, then launch Minecraft

Open a separate PowerShell **as administrator**, approve the Windows prompt yourself, change to this repository, and run:

```powershell
python .\scripts\benchmark.py broker
```

Leave that window open. It waits for exact prepared-session requests and expires after six hours. The command does not elevate itself or control Minecraft. After a previous explicit stop, remove `runtime\outputs\capture-broker\stop.json` manually only once the old broker has stopped, then start a new approved broker.

Launch the configured profile in Modrinth and open `Lab_RestWorld_benchmark`. If the experimental-world screen appears, choose **“I know what I'm doing!”** because the immutable master is already retained. Avoid another launcher backup for each test.

Optional launch command: add `modrinth_app` (absolute executable path) and, if necessary, `modrinth_database` to your local JSON. Then `python .\scripts\benchmark.py launch` reads the instance database without changing it and requests the profile/world deep link. Schema support currently targets Modrinth 0.21.9; other schemas need validation. Manual launch remains supported.

For an existing lab instance, initial launcher integration can also be checked without configuring capture/restore paths:

```powershell
python .\scripts\launch_lab_world.py --profile 'C:\path\to\ModrinthApp\profiles\your-lab' --app 'C:\path\to\Modrinth App.exe' --world Lab_RestWorld_benchmark --check-only
```

Remove `--check-only` to request a launch; warn the computer's user first because it may take foreground. The launcher requires the existing Minescript conditions/instance guard, reads only instance/content-set metadata, verifies installed Fabric 26.1.2 / Loader 0.19.5, and rejects an already running client. It never edits launcher/account data or handles tokens. Dedicated profile creation/duplication still uses Modrinth's native human-operated interface; no clone action is automated.

For automatic acknowledgement of the experimental-world prompt, see the optional [scoped launch helper](bootstrap-helper.md). It takes the existing **no-backup** continuation for the explicitly authorized disposable world, without modifying its datapacks or experimental flags. Launcher/world entry checks are functional checks, not validation of the capture workflow.

If first launch creates mod configuration files after pinning: quit Minecraft, run `python .\scripts\benchmark.py refresh-configs`, then launch again. For a candidate, also supply `--control .\runtime\state\experiments\sodium-control.json`. This only adopts generated `config/` changes; unexpected file changes are rejected. Never refresh during a running/prepared batch.

## 4. Start a batch (ordinary PowerShell + two Minecraft commands)

Keep the same display, power mode and background load across comparisons. You manage these external conditions; the tool does not inspect battery/charging status or other applications. Do not manually resize the game; preparation applies the default native fullscreen mode, uncapped FPS and VSync off.

In **ordinary** PowerShell, start the one-shot watcher:

```powershell
python .\scripts\benchmark.py session --repeats 3
```

Then, in Minecraft chat:

```text
\labprepare 3
```

Close chat/F3 and wait for **Lab prepared** and the broker's **Controller ready**. Preparation itself moves the player through an unscored route. Once ready, in Minecraft chat:

```text
\labrun
```

Close chat/F3 and leave Minecraft focused with controls untouched until completion. The route includes sprint-jumps, walking and camera checks in all three rooms. It excludes inventory, punching, stationary jumps and the sky/lever section. Teleports between rooms are outside scored windows.

For confirmation, use `--repeats 5` and `\labprepare 5`; `\labrun` remains the same. A shorter batch is not accepted merely because the game finished: frame/identity/path checks must pass. Record the **Session results** directory printed by the broker. Do not assume an old result is the latest run.

## 5. Candidate, return control, compare

Quit Minecraft before changing JARs, configuration or world files. Change only the candidate mod/configuration, retaining all instrumentation and control settings, then:

```powershell
python .\scripts\benchmark.py prepare --name sodium-candidate --role candidate --control .\runtime\state\experiments\sodium-control.json
```

Launch and repeat step 4. Next quit, restore the original control JAR/config files **exactly**, prepare again with `--name sodium-control --role control`, launch and repeat step 4. The broker can stay open between these batches. A mod's filename alone is not sufficient: hashes and effective graphics/runtime state must match.

Compare all three suites directly; substitute the actual directories:

```powershell
python .\scripts\benchmark.py compare 'C:\path\candidate-suite' --control 'C:\path\first-control-suite' --control-after 'C:\path\return-control-suite'
```

Optional individual report:

```powershell
python .\scripts\benchmark.py analyze 'C:\path\suite'
```

Reports are write-once: `benchmark-comparison.json` or `benchmark-measurement.json`. Existing reports are never overwritten. Direct comparison scores the three source suites itself, so separate reports are unnecessary. A valid three-repeat result is screening evidence; use fresh five-repeat blocks to confirm, with a fresh return control. Report FPS, 1% low, p95/p99 and spikes, plus scope/visual correctness; do not describe a screen as statistical proof.

## 6. Finish or cancel

In Minecraft, `\labcancel` requests cancellation. Interruption, pause, focus loss, changed state or controller error rejects the affected run; preserve its results and inspect the reason before retrying. Create a fresh preparation/session rather than reusing an old claim. Do not bypass Windows security or login prompts.

To stop the broker from ordinary PowerShell:

```powershell
python .\scripts\benchmark.py stop-broker
```

Wait for it to report stopped; save and quit Minecraft normally. No controller needs to run between sessions. An AI follows the same steps: it may prepare files only with the client closed, asks the human to approve elevation, sends no desktop input during captures, and distinguishes functional-only checks from real frame measurements.
