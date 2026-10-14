# Experimental automatic sessions

Automatic world entry, preparation, controller confirmation, one diagnostic captured route, analysis and normal save/quit passed a live integration check on 14 October 2026. The recorded route ran minimized, with real PresentMon frames. This is one machine's diagnostic evidence; normal foreground comparison batches and a fresh public installation still need validation. See [validation and limitations](live-validation.md), and keep the [manual workflow](workflow.md) available.

The extensions use Minescript's documented [world-specific autorun](https://minescript.net/docs), a fresh bounded request, and the existing session nonce, claim and confirmation files. Normal startup has a five-minute limit; diagnostic startup has a ten-minute limit because minimized rendering slows bridge calls. Neither request is renewed automatically. The hook is idle on ordinary entry. It runs only in the configured disposable world, with matching pinned files. No global keyboard/mouse daemon or automatic elevation is used.

## Updating an existing lab

With Minecraft closed, preserve and review changes before migrating:

```powershell
python .\scripts\benchmark.py migration-plan
python .\scripts\benchmark.py migrate --plan 'C:\path\printed\receipt.json'
python .\scripts\benchmark.py setup
python .\scripts\benchmark.py check
```

The plan retains previous bytes and a readable diff under local state. A stale target, changed source or damaged recovery copy is refused before writing. Only required scripts, lab conditions and the Python/world-specific hook configuration are replaced. Existing unrelated scripts/configuration are preserved; conflicting matching/wildcard autorun commands need reconciliation. No worlds or mod JARs are changed by migration. Repin the experiment after changing instrumentation.

## One automatic functional pilot

First follow the one-time setup and helper installation. With the client closed, prepare a clean pinned control. Then:

```powershell
python .\scripts\benchmark.py prepare --name sodium-control --role control --prune-owned-recovery
python .\scripts\benchmark.py functional-auto-launch
```

This launches the exact profile/world, requests one functional route repeat, and confirms the existing controller after readiness, identity and focus checks. Each route still has its complete unscored pass. It never starts PresentMon or requests an elevated broker. Leave the game focused and the controls idle. Background applications and battery/charging status are not inspected.

If the controller crashes, the small `minescript\lab-results\auto-launch-controller.lock` may remain. Inspect its PID and active game/jobs before removing that exact stale lock manually. The tool never silently takes over another controller. Failed requests are invalidated; preparation/session cancellation uses the existing stop files and `\labcancel`.

## One automatic measured batch

Keep graphics, heap and display consistent. Manage power mode and background load yourself for comparable results; the tool does not enforce them. Start the matching broker as administrator yourself using the manual workflow.

With Minecraft closed and a clean pinned experiment ready, explicitly declare the available measurement window:

```powershell
python .\scripts\benchmark.py clear-measurement-window --minutes 30
```

This creates an expiring, configuration-bound local declaration and prints its nonce. It is an operator assertion, not automatic detection of a quiet computer. It starts no capture. Then use the printed value:

```powershell
python .\scripts\benchmark.py measured-auto-launch --measurement-window PRINTED_NONCE --repeats 3
```

Use `5` for confirmation. The measured command refuses absent/expired clearance or a missing, stopped, expired or mismatched approved broker before launching or issuing a preparation ticket. Measured permissions are separate from functional permissions; neither can be consumed in the other's mode.

After preparation, it submits one exact resource-OFF request to the existing broker, verifies the claim's session nonce/PID and broker PID, checks focus, then publishes the same confirmation as `\labrun`. The original controller handles each phase and capture. The window is checked before each phase preparation and scored start. An already active finite scored phase may finish after lease expiry/revocation; the next phase or scored start rejects it and requests cancellation. This avoids additional file polling during timed frames. Focus, process and cancellation checks remain continuously active. The ordinary dispatcher waits for completion without collecting resource telemetry during timed routes.

A completed capture still requires analysis and the original return-to-control comparison. Automation does not waive route quality, one unscored pass per repeat, settings identity, frame-stream checks or drift limits. Neither command changes mod sets. Normal sessions leave the game open; quit normally before preparing the next configuration. Diagnostic sessions request native shutdown after their controller finishes, as described below.

One retained master is reused. `--prune-owned-recovery` keeps the latest unchanged, receipted recovery copy for that same world/master; historical unreceipted worlds are untouched. No backup ZIP is made per launch.

## Diagnostic integration

For checking the workflow without using FPS as comparison evidence, use `functional-auto-launch --diagnostic-only` and create the capture window with `clear-measurement-window --diagnostic-only`. The latter marks its automatic captured batch diagnostic-only throughout the ticket, game arm, controller and raw capture reports. Standard benchmark analysis refuses these batches as performance measurements. Normal analysis still relies on you to keep external conditions comparable.

For a single captured integration check, pass `--repeats 1` to `measured-auto-launch` with the diagnostic window's nonce. One repeat is refused for normal measurement windows. Preparation, a full unscored pass and the measured route still run; minimizing the client can make this substantially slower than a foreground screen.

Diagnostic sessions can be unfocused or minimized. Their dedicated profile uses `pauseOnLostFocus:false`; any necessary options update is made with the client closed and retains previous bytes plus a receipt. The in-game policy is enabled only after validating the explicit diagnostic request. It still rejects a paused world, menus, wrong world, changed files and invalid route actions. The observed rendering throttle/FPS are recorded rather than treated as an uncapped benchmark. Normal sessions retain foreground/uncapped requirements.

Minimized Minecraft may throttle rendering or stop producing usable presentation events. Successful player movement does not prove a successful frame capture: the first-frame, raw-stream, identity and completion checks still apply. Missing frames are reported as a capture failure; no values are invented or substituted from the game's FPS counter.

Diagnostic automation requests a normal Minecraft shutdown only after the controller has finalized its result and stopped its owned trace. This uses Minecraft's own `stop()` method through Minescript, without desktop input or force termination. If controller completion is not confirmed within the bounded wait, it leaves the game running and reports the blocker. There is no automatic restore/focus action; use the normal diagnostic workflow to test the game's actual minimized behavior.

Launch can bring Minecraft to the foreground. Minimize the correct client yourself once if testing that state; the controller does not operate desktop windows. Diagnostic corner corrections use bounded sneak pulses and release movement before slow position checks. Final waypoint tolerances, real walking, both sprint-jumps and camera checks remain enforced. Normal foreground benchmarks retain their original movement control.
