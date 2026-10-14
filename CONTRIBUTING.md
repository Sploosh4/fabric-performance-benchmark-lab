# Contributing

Read the [workflow](docs/workflow.md), [methodology](docs/methodology.md) and [host/container boundary](docs/container.md) before changing behavior. This release targets Fabric Minecraft 26.1.2 and the fixed RestWorld route; additional versions and worlds need their own verified contracts.

Run `python -m unittest discover -s scripts -p 'test_*.py'` on Windows. Run the documented Docker offline checks for Linux portability. Native game/capture validation is separate from synthetic tests; record failures and missing coverage honestly.

Preserve exact profile/PID/session identities, no-overwrite protocol publication, closed-client restoration, bounded owned-path cleanup and diagnostic exclusion. Keep app/background-process and power/charging checks out of the code. Do not introduce automatic Windows security approval, global desktop input or privileged container/host-control shortcuts.

Keep configuration, credentials, captures, worlds, JARs and generated files out of commits. When reporting a bug, include versions, the command and a short redacted error. Review logs and reports for personal paths before sharing. Do not attach account tokens or world content without permission to redistribute it.

Changes to live behavior need relevant integration evidence. A passing synthetic test or diagnostic capture does not establish a valid mod comparison. Original contributions use the project's MIT license; third-party material retains its own license.
