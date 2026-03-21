"""
Build filename-keyed indexes for both local and cloud file sets.

The cloud API keys files by title (company name), but each entry also
contains the actual filename.  We combine them as "title/filename"
(e.g. "8byte/Sai_Prabhat_Full_Stack.pdf") so they match the local
folder structure: F:\resume\8byte\Sai_Prabhat_Full_Stack.pdf
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
    filename: str       # relative path key, e.g. "8byte\Sai_Prabhat_Full_Stack.pdf"
    filepath: Path
    checksum: str
    size: int
    updated_at: datetime


@dataclass(frozen=True)
class CloudFileInfo:
    """Metadata about a single file in the cloud."""
    id: str
    filename: str       # matched key, e.g. "8byte/Sai_Prabhat_Full_Stack.pdf"
    title: str          # company name, e.g. "8byte"
    real_filename: str  # actual file, e.g. "Sai_Prabhat_Full_Stack.pdf"
    checksum: str
    size: int
    updated_at: datetime
    storage_path: str


# ---------------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------------

def build_local_index(sync_folder: Path) -> Dict[str, LocalFileInfo]:
    """Scan *sync_folder* recursively and return ``{relative_path: LocalFileInfo}``."""
    index: Dict[str, LocalFileInfo] = {}

    if not sync_folder.is_dir():
        logger.warning("Sync folder %s does not exist – creating it.", sync_folder)
        sync_folder.mkdir(parents=True, exist_ok=True)
        return index

    for entry in sync_folder.rglob("*"):
        if not entry.is_file():
            continue

        # Use the path relative to sync_folder as the key so that
        # "8byte\Sai_Prabhat_Full_Stack.pdf" stays distinct.
        relative = entry.relative_to(sync_folder)
        # Normalise to forward slashes for cross-platform matching with cloud keys.
        key = str(relative).replace("\\", "/")

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
    """Convert the raw ``GET /resumes`` JSON payload into ``{key: CloudFileInfo}``.

    The API returns files keyed by title (company name)::

        {
            "8byte": {
                "id": "...", "title": "8byte",
                "filename": "Sai_Prabhat_Full_Stack.pdf",
                "checksum": "...", ...
            }
        }

    We build a composite key "title/filename" (e.g. "8byte/Sai_Prabhat_Full_Stack.pdf")
    to match the local folder structure.
    """
    index: Dict[str, CloudFileInfo] = {}

    for title, meta in resumes_response.items():
        raw_ts = meta["updated_at"]
        if isinstance(raw_ts, str):
            updated = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        else:
            updated = raw_ts

        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)

        # The actual filename from the API response.
        real_filename = meta.get("filename", title)

        # Composite key: "company/resume.pdf" matches local "company\resume.pdf"
        key = f"{title}/{real_filename}"

        info = CloudFileInfo(
            id=meta["id"],
            filename=key,
            title=title,
            real_filename=real_filename,
            checksum=meta["checksum"],
            size=meta["size"],
            updated_at=updated,
            storage_path=meta["storage_path"],
        )
        index[key] = info
        logger.debug("Indexed cloud file: %s (id=%s)", key, info.id)

    logger.info("Cloud index built – %d file(s).", len(index))
    return index