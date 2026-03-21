"""
Entry-point for the resume sync agent.

Lifecycle
---------
1. Wait for network to be ready (important for startup-on-logon).
2. Configure logging.
3. Ensure the local sync folder exists.
4. Perform a full bidirectional sync (startup reconciliation).
5. Start the filesystem watcher for continuous real-time sync.
6. Block the main thread until interrupted (Ctrl-C / SIGINT).
7. Tear down cleanly.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import signal
import sys
import threading
import time
from pathlib import Path

import httpx

import config
from api_client import ResumeAPIClient, APIError
from file_indexer import build_cloud_index, build_local_index
from sync_engine import SyncEngine
from watcher import FolderWatcher

logger = logging.getLogger("sync_agent")


def _setup_logging() -> None:
    """Initialise the root logger – logs to both console and a rotating file."""
    log_level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    formatter = logging.Formatter(config.LOG_FORMAT)

    root = logging.getLogger()
    root.setLevel(log_level)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler
    log_file = Path(__file__).resolve().parent / "sync_agent.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def _wait_for_network() -> None:
    """Block until the API is reachable, with an initial delay and timeout.

    On Windows logon the network adapter may not be ready for several
    seconds.  The Render backend also cold-starts, so we give it time.
    """
    # Initial delay – let Windows finish bringing up the network stack.
    delay = config.STARTUP_DELAY_SECONDS
    logger.info("Waiting %d seconds for network to stabilise…", delay)
    time.sleep(delay)

    # Now poll the API until it responds or we hit the timeout.
    deadline = time.monotonic() + config.NETWORK_WAIT_TIMEOUT_SECONDS
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        try:
            resp = httpx.get(
                f"{config.API_BASE_URL}/api/v1/resumes/",
                timeout=15.0,
                follow_redirects=True,
            )
            if resp.status_code < 500:
                logger.info("API is reachable (attempt %d).", attempt)
                return
        except (httpx.HTTPError, OSError) as exc:
            logger.warning(
                "Network not ready (attempt %d): %s", attempt, exc
            )

        time.sleep(10)  # retry every 10 seconds

    logger.error(
        "API not reachable after %d seconds – proceeding anyway.",
        config.NETWORK_WAIT_TIMEOUT_SECONDS,
    )


def _ensure_sync_folder(folder: Path) -> None:
    """Create the sync folder if it doesn't already exist."""
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        logger.info("Created sync folder: %s", folder)


def main() -> None:
    _setup_logging()
    logger.info("Resume sync agent starting…")

    # Wait for network before doing anything that hits the API.
    _wait_for_network()

    sync_folder: Path = config.SYNC_FOLDER
    _ensure_sync_folder(sync_folder)

    client = ResumeAPIClient()

    try:
        # Step 1 – Fetch the authoritative cloud state.
        logger.info("Fetching cloud file list…")
        raw_cloud = client.list_resumes()
        cloud_index = build_cloud_index(raw_cloud)

        # Step 2 – Build the local file index.
        local_index = build_local_index(sync_folder)

        # Step 3 – Run the deterministic sync.
        engine = SyncEngine(client, sync_folder)
        engine.run(local_index, cloud_index)

        # Refresh cloud index after sync for the watcher.
        cloud_index = build_cloud_index(client.list_resumes())

        # Step 4 – Start the real-time filesystem watcher.
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
        logger.critical("Fatal API error during startup sync: %s", exc)
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