"""Read-only palette survey of the user's two screenshot corridors in an owned save."""
import io
import json
from pathlib import Path
import sys
import zlib

PACK=Path(__file__).resolve().parents[1]
import nbtlib

from lab_settings import load
SETTINGS=load()
WORLD=SETTINGS.profile/'saves'/SETTINGS.world_folder
CACHE={}


def chunk(cx,cz,kind="region"):
    key=(cx,cz,kind)
    if key in CACHE:return CACHE[key]
    path=WORLD/"dimensions/minecraft/overworld"/kind/f"r.{cx//32}.{cz//32}.mca"
    with path.open("rb") as stream:
        stream.seek(4*((cx%32)+(cz%32)*32));location=int.from_bytes(stream.read(4),"big")
        if not location:return None
        stream.seek((location>>8)*4096);length=int.from_bytes(stream.read(4),"big")
        compression=stream.read(1)[0];data=stream.read(length-1)
    if compression!=2:raise ValueError("Unsupported chunk compression")
    CACHE[key]=nbtlib.File.parse(io.BytesIO(zlib.decompress(data))).unpack()
    return CACHE[key]


def block(x,y,z):
    data=chunk(x//16,z//16)
    section=next(s for s in data["sections"] if s["Y"]==y//16)
    states=section["block_states"];palette=states["palette"]
    if len(palette)==1:return palette[0]
    bits=max(4,(len(palette)-1).bit_length());per_long=64//bits
    index=(y%16)*256+(z%16)*16+x%16
    packed=int(states["data"][index//per_long])&((1<<64)-1)
    return palette[(packed>>((index%per_long)*bits))&((1<<bits)-1)]


if __name__=="__main__":
    result={}
    for name,x,zs in (("paintings",-48,range(17,27)),("redstone",46,range(-26,-13))):
        result[name]=[{"position":[x,101,z],"blocks":[block(x,y,z) for y in range(100,105)]} for z in zs]
    print(json.dumps(result,indent=2))
