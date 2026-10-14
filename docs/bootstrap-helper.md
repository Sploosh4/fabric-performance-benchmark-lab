# Optional automatic world entry

The original MIT-licensed helper in `bootstrap-helper/` acknowledges only the experimental-world prompt for an explicitly authorized disposable lab world. It does not bypass version, downgrade, conversion, customized-world, login or Windows security prompts. No world or datapack editing is used to suppress the warning.

This integration targets Minecraft **26.1.2**, Fabric Loader **0.19.5** and Modrinth **0.21.9**. The allowed saved versions are the verified RestWorld master **26.1 / DataVersion 4786** and its normally saved **26.1.2 / DataVersion 4790** copy. Other versions require new validation.

On 14 October 2026, the corrected helper passed three fresh-process world-entry checks in the existing lab, including the configured `benchmark.py launch` command. Each used a fresh permission and matching PID receipt; no new backup ZIPs were created, and datapack/master hashes stayed unchanged. Seventeen Java guard fixtures and six Python launcher tests passed. These checks do not validate other machines or performance measurements.

## Install once, with Minecraft closed

Use an existing Java 25 **JDK** and the launcher's cached game/libraries. This build does not download libraries:

```powershell
python .\scripts\build_bootstrap_helper.py --jdk 'C:\path\to\jdk25' --meta 'C:\path\to\ModrinthApp\meta'
```

Copy `bootstrap-helper\build\fabric-benchmark-bootstrap-26.1.2-0.1.0.jar` into the dedicated profile's `mods` folder. Preserve any previous helper before replacing it. The build creates a local helper hash lock; the launcher requires the installed JAR to match it. Add the helper **before** preparing/pinning an experiment, and keep the identical helper in control and candidate runs. Its effect on measurements has not been isolated.

In your ignored local configuration, set `modrinth_app`, optionally `modrinth_database`, and `"auto_acknowledge_experimental": true`. The already configured master archive and its hash supply the retained backup. Then launch normally:

```powershell
python .\scripts\benchmark.py launch
```

An explicit invocation for an existing configured lab is also available:

```powershell
python .\scripts\launch_lab_world.py --profile 'C:\path\to\ModrinthApp\profiles\your-lab' --app 'C:\path\to\Modrinth App.exe' --world Lab_RestWorld_benchmark --allow-experimental --master-archive 'C:\path\to\master.zip' --master-sha256 YOUR_VERIFIED_MASTER_SHA256
```

## What the permission covers

Each launch creates a fresh five-minute, one-use authorization under the profile's `minescript\lab-results`. The helper checks the exact world/profile, running and saved versions, immutable master, helper, conditions, level metadata and complete datapack file hashes. Linked/reparse paths and replayed permissions are rejected. A mismatch leaves the normal dialog visible.

Successful acknowledgement writes `bootstrap-<nonce>-accepted.json` with the Minecraft PID and world identity. Verify it belongs to the newly launched process, and check actual world readiness rather than treating the launcher request as success. No per-launch ZIP is created. Normal gameplay and saving still write the disposable world as usual; the retained master and datapacks remain unchanged.

The plain launch command does not start preparation or measurement. Experimental [automatic session commands](automation.md) build on the same nonce/claim/confirmation contract; their source tests pass, but migrated startup and actual unattended capture still need live validation. The manual broker, `\labprepare` and `\labrun` workflow remains available. This helper never supplies desktop input or approves elevation.

Compile-only dependencies come from separately installed Minecraft, Fabric Loader, Mixin and game libraries. Their binaries are not included in the source repository; retain their upstream terms and notices. No upstream warning-suppression mod source is incorporated.
