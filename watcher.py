"""
Real-time filesystem watcher with per-file debounce.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

import config
from file_indexer import CloudFileInfo
from sync_engine import SyncEngine

logger = logging.getLogger(__name__)


class _DebouncedHandler(FileSystemEventHandler):
    def __init__(
        self,
        engine: SyncEngine,
        cloud_index: Dict[str, CloudFileInfo],
        sync_folder: Path,
        debounce_seconds: float = config.WATCHER_DEBOUNCE_SECONDS,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._cloud_index = cloud_index
        self._sync_folder = sync_folder
        self._debounce: float = float(debounce_seconds)
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _schedule(self, key: str, callback, *args) -> None:
        with self._lock:
            existing = self._timers.pop(key, None)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(self._debounce, callback, args=args)
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _relative_key(self, path: Path) -> str:
        """Return the path relative to the sync folder, e.g. 'Google/resume.pdf'."""
        return str(path.relative_to(self._sync_folder))

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        key = self._relative_key(path)
        self._schedule(f"create:{key}", self._engine.handle_created, path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        key = self._relative_key(path)
        self._schedule(f"modify:{key}", self._engine.handle_modified, path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        key = self._relative_key(path)
        self._schedule(f"delete:{key}", self._engine.handle_deleted, key, self._cloud_index)

    def update_cloud_index(self, new_index: Dict[str, CloudFileInfo]) -> None:
        self._cloud_index = new_index


class FolderWatcher:
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
        logger.info("File watcher started on %s", self._folder)
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
        logger.info("File watcher stopped.")

    def update_cloud_index(self, new_index: Dict[str, CloudFileInfo]) -> None:
        self._handler.update_cloud_index(new_index)