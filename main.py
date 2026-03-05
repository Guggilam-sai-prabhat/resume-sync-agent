"""
Entry-point for the resume sync agent.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from pathlib import Path

import config
from api_client import ResumeAPIClient, APIError
from file_indexer import build_cloud_index, build_local_index
from sync_engine import SyncEngine
from watcher import FolderWatcher

logger = logging.getLogger("sync_agent")


def _setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format=config.LOG_FORMAT,
    )


def main() -> None:
    _setup_logging()
    logger.info("Resume sync agent starting…")

    sync_folder: Path = config.SYNC_FOLDER
    sync_folder.mkdir(parents=True, exist_ok=True)

    client = ResumeAPIClient()

    try:
        # 1 – Fetch cloud state
        logger.info("Fetching cloud file list…")
        cloud_index = build_cloud_index(client.list_resumes())

        # 2 – Build local index
        local_index = build_local_index(sync_folder)

        # 3 – Full sync
        engine = SyncEngine(client, sync_folder)
        engine.run(local_index, cloud_index)

        # Refresh cloud index after sync
        cloud_index = build_cloud_index(client.list_resumes())

        # 4 – Start watcher
        watcher = FolderWatcher(sync_folder, engine, cloud_index)
        watcher.start()

        logger.info("Agent is running.  Press Ctrl-C to stop.")
        shutdown = threading.Event()

        def _signal_handler(signum, frame):
            logger.info("Received signal %s – shutting down.", signum)
            shutdown.set()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        shutdown.wait()

    except APIError as exc:
        logger.critical("Fatal API error during startup: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Shutting down…")
        if "watcher" in locals():
            watcher.stop()
        client.close()
        logger.info("Goodbye.")


if __name__ == "__main__":
    main()
