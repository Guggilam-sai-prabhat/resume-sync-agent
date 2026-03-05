"""
Deterministic synchronization engine.

Rules per filename:
  1. Cloud-only          → download
  2. Local-only          → upload
  3. Both, same checksum → skip
  4. Both, diff checksum → compare updated_at (cloud wins ties)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from api_client import ResumeAPIClient, APIError
from file_indexer import CloudFileInfo, LocalFileInfo

logger = logging.getLogger(__name__)


class SyncEngine:
    def __init__(self, client: ResumeAPIClient, sync_folder: Path) -> None:
        self._client = client
        self._sync_folder = sync_folder

    def run(self, local_index: Dict[str, LocalFileInfo], cloud_index: Dict[str, CloudFileInfo]) -> None:
        all_filenames = set(local_index.keys()) | set(cloud_index.keys())
        logger.info("Sync started – %d local, %d cloud, %d unique.", len(local_index), len(cloud_index), len(all_filenames))

        for fname in sorted(all_filenames):
            local = local_index.get(fname)
            cloud = cloud_index.get(fname)
            try:
                if cloud and not local:
                    logger.info("[DOWNLOAD] %s", fname)
                    self._download(cloud)
                elif local and not cloud:
                    logger.info("[UPLOAD]   %s", fname)
                    self._upload(local)
                elif local and cloud and local.checksum == cloud.checksum:
                    logger.debug("[OK]       %s", fname)
                elif local and cloud:
                    self._resolve_conflict(local, cloud)
            except APIError as exc:
                logger.error("Sync failed for %s: %s", fname, exc)

        logger.info("Sync cycle complete.")

    def _download(self, cloud: CloudFileInfo) -> None:
        url = self._client.get_download_url(cloud.id)
        self._client.download_file(url, self._sync_folder / cloud.filename)

    def _upload(self, local: LocalFileInfo) -> None:
        self._client.upload_file(local.filepath)

    def _resolve_conflict(self, local: LocalFileInfo, cloud: CloudFileInfo) -> None:
        if cloud.updated_at >= local.updated_at:
            logger.info("[CONFLICT] %s – cloud wins (%s >= %s); downloading.", local.filename, cloud.updated_at, local.updated_at)
            self._download(cloud)
        else:
            logger.info("[CONFLICT] %s – local wins (%s > %s); re-uploading.", local.filename, local.updated_at, cloud.updated_at)
            self._client.delete_resume(cloud.id)
            self._upload(local)

    # Watcher helpers
    def handle_created(self, filepath: Path) -> None:
        logger.info("[WATCH-CREATE] %s", filepath.name)
        try:
            self._client.upload_file(filepath)
        except APIError as exc:
            logger.error("Upload failed for %s: %s", filepath.name, exc)

    def handle_modified(self, filepath: Path) -> None:
        logger.info("[WATCH-MODIFY] %s", filepath.name)
        try:
            self._client.upload_file(filepath)
        except APIError as exc:
            logger.error("Re-upload failed for %s: %s", filepath.name, exc)

    def handle_deleted(self, filename: str, cloud_index: Dict[str, CloudFileInfo]) -> None:
        cloud = cloud_index.get(filename)
        if cloud is None:
            return
        logger.info("[WATCH-DELETE] %s (id=%s)", filename, cloud.id)
        try:
            self._client.delete_resume(cloud.id)
        except APIError as exc:
            logger.error("Cloud delete failed for %s: %s", filename, exc)
