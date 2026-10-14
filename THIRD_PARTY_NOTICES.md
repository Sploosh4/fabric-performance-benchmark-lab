# Third-party tools and world

The root MIT license covers this project's original code. It does not relicense installed dependencies, Minecraft assets or worlds. No third-party executable, mod JAR or world is included in this source repository.

The Docker recipe uses the official Python image as a separate base. Python retains its [PSF license and notices](https://docs.python.org/3/license.html); Debian components retain their own package licenses. Base-image notices are retained. This repository distributes the recipe and original tooling, not a prebuilt image or a relicensing of its operating-system dependencies.

| Component | Attribution / license | Use |
| --- | --- | --- |
| [RestWorld](https://cleanpack.art/restworld/index.html) | Ken Arnold / BlueMeanial, with JUMBOshrimp277; CC BY 4.0 | Fixed world layout; users obtain their own 26.1 archive. A restored disposable copy retains the world content; scripts move the player through its rooms. |
| [Minescript](https://modrinth.com/mod/minescript) | maxuser / upstream contributors; GPL-3.0-only | Installed separately for Python commands and game state access. |
| [Fabric API](https://github.com/FabricMC/fabric) | FabricMC contributors; Apache-2.0 (see upstream notices) | Installed separately for Minescript. |
| [PresentMon](https://github.com/GameTechDev/PresentMon/blob/main/LICENSE.txt) | Intel Corporation / contributors; MIT core license, distribution dependencies have separate notices | Installed separately; capture invokes the console executable. Retain the installer distribution's notices. |

Optional tool/mod metadata and exact download hashes in `manifests/tools-lock.json` are references, not redistribution rights. Preserve each publisher's license and notices if distributing their binaries separately. Minecraft and the Modrinth launcher remain governed by their publishers' terms. This tool does not read or distribute account tokens.
