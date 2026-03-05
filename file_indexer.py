"""
Build filename-keyed indexes for both local and cloud file sets.

These indexes are the basis of the deterministic diff that the sync engine
performs on every startup cycle.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from checksum import compute_sha256

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes that normalise the two worlds into comparable shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LocalFileInfo:
    """Metadata about a single file on disk."""
    filename: str
    filepath: Path
    checksum: str
    size: int
    updated_at: datetime  # mtime converted to aware UTC datetime


@dataclass(frozen=True)
class CloudFileInfo:
    """Metadata about a single file in the cloud, as returned by GET /resumes."""
    id: str
    filename: str
    checksum: str
    size: int
    updated_at: datetime
    storage_path: str


# ---------------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------------

def build_local_index(sync_folder: Path) -> Dict[str, LocalFileInfo]:
    """Scan *sync_folder* and return ``{filename: LocalFileInfo}``."""
    index: Dict[str, LocalFileInfo] = {}

    if not sync_folder.is_dir():
        logger.warning("Sync folder %s does not exist – creating it.", sync_folder)
        sync_folder.mkdir(parents=True, exist_ok=True)
        return index

    for entry in sync_folder.rglob("*"):
        if not entry.is_file():
            continue  # skip directories / symlinks

        # Use the path relative to sync_folder as the key so that
        # "Google/resume.pdf" and "Amazon/resume.pdf" stay distinct.
        relative = entry.relative_to(sync_folder)
        key = str(relative)

        try:
            checksum = compute_sha256(entry)
            stat = entry.stat()
            mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            info = LocalFileInfo(
                filename=key,
                filepath=entry,
                checksum=checksum,
                size=stat.st_size,
                updated_at=mtime_utc,
            )
            index[key] = info
            logger.debug("Indexed local file: %s (sha256=%s)", key, checksum[:12])
        except (OSError, PermissionError) as exc:
            logger.error("Failed to index %s: %s", entry, exc)

    logger.info("Local index built – %d file(s).", len(index))
    return index


def build_cloud_index(resumes_response: Dict) -> Dict[str, CloudFileInfo]:
    """Convert the raw ``GET /resumes`` JSON payload into ``{filename: CloudFileInfo}``.

    The API returns::

        {
            "resume_a.pdf": {"id": "...", "checksum": "...", ...},
            ...
        }
    """
    index: Dict[str, CloudFileInfo] = {}

    for filename, meta in resumes_response.items():
        # The API may return ISO-8601 strings or already-parsed datetimes.
        raw_ts = meta["updated_at"]
        if isinstance(raw_ts, str):
            # Python < 3.11 doesn't accept the trailing 'Z'; replace with +00:00.
            updated = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        else:
            updated = raw_ts

        # Ensure timezone-aware for safe comparison with local mtimes.
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)

        info = CloudFileInfo(
            id=meta["id"],
            filename=filename,
            checksum=meta["checksum"],
            size=meta["size"],
            updated_at=updated,
            storage_path=meta["storage_path"],
        )
        index[filename] = info
        logger.debug("Indexed cloud file: %s (id=%s)", filename, info.id)

    logger.info("Cloud index built – %d file(s).", len(index))
    return index