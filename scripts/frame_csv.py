"""Decode pinned PresentMon CSV transports without altering raw evidence bytes."""
import codecs
from pathlib import Path


def encoding_from_prefix(prefix):
    if prefix.startswith((codecs.BOM_UTF16_LE,codecs.BOM_UTF16_BE)):
        return "utf-16"
    return "utf-8-sig"


def csv_encoding(path):
    with Path(path).open("rb") as stream:
        return encoding_from_prefix(stream.read(4))


def csv_prefix(path,limit=8192):
    with Path(path).open("rb") as stream:
        prefix=stream.read(limit)
    # A live writer may be between bytes of the BOM or a UTF-16 code unit.
    if not prefix or prefix in (b"\xff",b"\xfe",b"\xef",b"\xef\xbb"):
        return ""
    return codecs.getincrementaldecoder(encoding_from_prefix(prefix))().decode(prefix,final=False)
