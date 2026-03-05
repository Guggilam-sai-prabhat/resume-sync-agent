"""
Real-time filesystem watcher using the *watchdog* library.

Monitors ~/resume_sync for file creation, modification, and deletion events.
A debounce mechanism prevents duplicate actions when editors trigger multiple
rapid filesystem events for a single logical save.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Dict

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

import config
from file_indexer import CloudFileInfo
from sync_engine import SyncEngine

logger = logging.getLogger(__name__)


class _DebouncedHandler(FileSystemEventHandler):
    """Filesystem event handler with per-file debounce.

    Many text editors perform atomic saves via write-to-temp → rename,
    which can fire created + modified + deleted in rapid succession.
    The debounce window collapses those into one action.
    """

    def __init__(
        self,
        engine: SyncEngine,
        cloud_index: Dict[str, CloudFileInfo],
        debounce_seconds: float = config.WATCHER_DEBOUNCE_SECONDS,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._cloud_index = cloud_index
        self._debounce = debounce_seconds
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Debounce plumbing
    # ------------------------------------------------------------------

    def _schedule(self, key: str, callback, *args) -> None:
        """Cancel any pending timer for *key* and schedule a new one."""
        with self._lock:
            existing = self._timers.pop(key, None)
            if existing is not None:
                existing.cancel()

            timer = threading.Timer(self._debounce, callback, args=args)
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    # ------------------------------------------------------------------
    # Watchdog event hooks
    # ------------------------------------------------------------------

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        logger.debug("FS event: created %s", path.name)
        self._schedule(f"create:{path.name}", self._engine.handle_created, path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        logger.debug("FS event: modified %s", path.name)
        self._schedule(f"modify:{path.name}", self._engine.handle_modified, path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        logger.debug("FS event: deleted %s", path.name)
        self._schedule(
            f"delete:{path.name}",
            self._engine.handle_deleted,
            path.name,
            self._cloud_index,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def update_cloud_index(self, new_index: Dict[str, CloudFileInfo]) -> None:
        """Replace the cached cloud index after a full sync cycle."""
        self._cloud_index = new_index


class FolderWatcher:
    """High-level wrapper that starts / stops the watchdog observer."""

    def __init__(
        self,
        sync_folder: Path,
        engine: SyncEngine,
        cloud_index: Dict[str, CloudFileInfo],
    ) -> None:
        self._folder = sync_folder
        self._handler = _DebouncedHandler(engine, cloud_index, sync_folder)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(sync_folder), recursive=True)

    def start(self) -> None:
        """Begin watching (non-blocking – runs on a background thread)."""
        logger.info("File watcher started on %s", self._folder)
        self._observer.start()

    def stop(self) -> None:
        """Stop the observer and wait for its thread to finish."""
        self._observer.stop()
        self._observer.join()
        logger.info("File watcher stopped.")

    def update_cloud_index(self, new_index: Dict[str, CloudFileInfo]) -> None:
        """Forward an updated cloud index to the event handler."""
        self._handler.update_cloud_index(new_index)