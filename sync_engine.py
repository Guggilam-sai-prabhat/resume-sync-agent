"""
Deterministic synchronization engine.

Compares the local and cloud file indexes and produces a series of actions
(download / upload / delete-then-replace) that bring the two sides into
agreement.  Every decision is logged so operators can audit what happened.

Synchronization rules (applied per filename):
  1. Cloud-only  → download to local folder.
  2. Local-only  → upload to cloud.
  3. Both exist, checksums match → no action required.
  4. Both exist, checksums differ →
       • If cloud is newer  → download (overwrite local).
       • If local is newer  → delete the stale cloud copy, then re-upload.
       • If timestamps are equal (edge case) → prefer cloud (server-of-record).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from api_client import ResumeAPIClient, APIError
from file_indexer import CloudFileInfo, LocalFileInfo

logger = logging.getLogger(__name__)


class SyncEngine:
    """Stateless engine – call :meth:`run` with two indexes and it does the rest."""

    def __init__(self, client: ResumeAPIClient, sync_folder: Path) -> None:
        self._client = client
        self._sync_folder = sync_folder

    # ------------------------------------------------------------------
    # Full bidirectional sync
    # ------------------------------------------------------------------

    def run(
        self,
        local_index: Dict[str, LocalFileInfo],
        cloud_index: Dict[str, CloudFileInfo],
    ) -> None:
        """Execute the deterministic sync across all files."""

        all_filenames = set(local_index.keys()) | set(cloud_index.keys())
        logger.info(
            "Sync started – %d local, %d cloud, %d unique filenames.",
            len(local_index), len(cloud_index), len(all_filenames),
        )

        for fname in sorted(all_filenames):
            local = local_index.get(fname)
            cloud = cloud_index.get(fname)

            try:
                if cloud and not local:
                    # Rule 1 – exists in cloud only → download.
                    logger.info("[DOWNLOAD] %s – present in cloud but missing locally.", fname)
                    self._download(cloud)

                elif local and not cloud:
                    # Rule 2 – exists locally only → upload.
                    logger.info("[UPLOAD]   %s – present locally but missing in cloud.", fname)
                    self._upload(local)

                elif local and cloud and local.checksum == cloud.checksum:
                    # Rule 3 – checksums match → nothing to do.
                    logger.debug("[OK]       %s – checksums match.", fname)

                elif local and cloud:
                    # Rule 4 – checksums differ → resolve by timestamp.
                    self._resolve_conflict(local, cloud)

            except APIError as exc:
                # Log and continue with the next file so one failure doesn't
                # block the entire sync cycle.
                logger.error("Sync action failed for %s: %s", fname, exc)

        logger.info("Sync cycle complete.")

    # ------------------------------------------------------------------
    # Individual sync actions
    # ------------------------------------------------------------------

    def _download(self, cloud: CloudFileInfo) -> None:
        """Download a cloud file into the correct subfolder.

        Cloud key is "company/resume.pdf", so we build the local path
        as sync_folder / company / resume.pdf.
        """
        url = self._client.get_download_url(cloud.id)
        dest = self._sync_folder / cloud.filename  # e.g. F:\resume\8byte\Sai_Prabhat_Full_Stack.pdf
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(url, dest)

    def _upload(self, local: LocalFileInfo) -> None:
        """Upload a local file to the cloud."""
        self._client.upload_file(local.filepath)

    def _resolve_conflict(self, local: LocalFileInfo, cloud: CloudFileInfo) -> None:
        """Resolve a checksum mismatch by comparing timestamps.

        • Cloud newer (or equal) → overwrite local with cloud version.
        • Local newer            → delete stale cloud copy and re-upload.
        """
        if cloud.updated_at >= local.updated_at:
            logger.info(
                "[CONFLICT] %s – cloud is newer or same age (%s >= %s); downloading.",
                local.filename, cloud.updated_at, local.updated_at,
            )
            self._download(cloud)
        else:
            logger.info(
                "[CONFLICT] %s – local is newer (%s > %s); re-uploading.",
                local.filename, local.updated_at, cloud.updated_at,
            )
            # Delete the outdated cloud version first, then upload the fresh local copy.
            self._client.delete_resume(cloud.id)
            self._upload(local)

    # ------------------------------------------------------------------
    # One-shot helpers used by the watcher for real-time events
    # ------------------------------------------------------------------

    def handle_created(self, filepath: Path) -> None:
        """A new file appeared locally → upload it."""
        logger.info("[WATCH-CREATE] %s", filepath.name)
        try:
            self._client.upload_file(filepath)
        except APIError as exc:
            logger.error("Upload failed for new file %s: %s", filepath.name, exc)

    def handle_modified(self, filepath: Path) -> None:
        """A local file was modified → re-upload it.

        We don't attempt a delete-then-upload here because the cloud
        endpoint for POST may handle upsert semantics.  If your API
        requires an explicit delete first, fetch the cloud index to get
        the id, delete, then upload.
        """
        logger.info("[WATCH-MODIFY] %s", filepath.name)
        try:
            self._client.upload_file(filepath)
        except APIError as exc:
            logger.error("Re-upload failed for %s: %s", filepath.name, exc)

    def handle_deleted(self, filename: str, cloud_index: Dict[str, CloudFileInfo]) -> None:
        """A local file was deleted → remove it from the cloud if it exists there."""
        cloud = cloud_index.get(filename)
        if cloud is None:
            logger.debug("[WATCH-DELETE] %s – not in cloud, nothing to do.", filename)
            return
        logger.info("[WATCH-DELETE] %s (cloud id=%s)", filename, cloud.id)
        try:
            self._client.delete_resume(cloud.id)
        except APIError as exc:
            logger.error("Cloud delete failed for %s: %s", filename, exc)