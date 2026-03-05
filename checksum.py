"""
SHA-256 checksum computation for local files.
Reads in fixed-size chunks so memory usage stays constant.
"""

import hashlib
from pathlib import Path

_CHUNK_SIZE: int = 65_536


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()
