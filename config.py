"""
Configuration for the resume sync agent.

All tunables live here so the rest of the codebase stays free of magic
numbers and hard-coded paths.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SYNC_FOLDER: Path = Path("F:/resume")

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
API_BASE_URL: str = "https://resume-sync-backend.onrender.com"

# ---------------------------------------------------------------------------
# Startup
STARTUP_DELAY_SECONDS: int = 30          # wait for network after logon
NETWORK_WAIT_TIMEOUT_SECONDS: int = 120  # max time to wait for API to respond  (applied to every outbound HTTP call)
# ---------------------------------------------------------------------------
MAX_RETRIES: int = 3
RETRY_BACKOFF_FACTOR: float = 1.0  # seconds; exponential: 1s, 2s, 4s …

# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------
# Debounce window – ignore duplicate filesystem events that fire within
# this many seconds of each other for the same file.
WATCHER_DEBOUNCE_SECONDS: float = 2.0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = "INFO"
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_MAX_BYTES = 5 * 1024 * 1024   # change file size threshold
LOG_BACKUP_COUNT = 3               # change how many old files to keep