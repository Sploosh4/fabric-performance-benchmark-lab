"""Read-only bounded route survey of the welcome/mob display area."""
import json
import re
import time
import minescript as ms
from java import JavaClass
from lab_common import PROFILE, MC, guard_world
from lab_validation_core import assert_live

guard_world()
deadline = time.monotonic() + 20
while ms.screen_name() is not None and time.monotonic() < deadline:
    time.sleep(0.1)
assert_live()
AABB = JavaClass("net.minecraft.world.phys.AABB")
BlockPos = JavaClass("net.minecraft.core.BlockPos")
bounds = (-16, 0, 16, 40)
for x in (-16, 0, 16):
    for z in (0, 16, 32, 40):
        if not MC.level.hasChunkAt(BlockPos(x, 100, z)):
            raise RuntimeError("Survey area is not fully loaded")
layers = {}
for y in (100, 101, 102):
    states = re.findall(r"Block\{(minecraft:[a-z0-9_]+)\}", str(MC.level.getBlockStates(AABB(-16, y, 0, 16, y, 40)).toList()))
    if len(states) != 33 * 41:
        raise RuntimeError("Incomplete survey layer")
    # Single-Y layers avoid ambiguity about vertical iteration order.
    layers[str(y)] = [states[z * 33:(z + 1) * 33] for z in range(41)]
anchors = []
for x, z in ((1, 0), (1, 12), (-8, 20), (8, 20)):
    actual = str(MC.level.getBlockState(BlockPos(x, 100, z)))
    if layers['100'][z][x + 16] not in actual:
        raise RuntimeError("Survey ordering does not match direct reads")
    anchors.append({'x': x, 'z': z, 'state': actual})
entities = [{'type': e.type, 'position': e.position} for e in ms.entities(max_distance=80)]
result = {'bounds': bounds, 'layers': layers, 'anchors': anchors, 'entities': entities, 'blocks_changed': 0}
path = PROFILE / 'minescript/lab-results/mob-route-survey.json'
path.write_text(json.dumps(result, indent=2), encoding='utf-8')
ms.echo('Mob route survey saved; no world changes.')
