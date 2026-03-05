"""
Configuration for the resume sync agent.

All tunables live here so the rest of the codebase stays free of magic
numbers and hard-coded paths.
"""

from pathlib import Path

# Paths
SYNC_FOLDER: Path = Path.home() / "resume"

# API
API_BASE_URL: str = "http://localhost:8000"

# Retry policy
MAX_RETRIES: int = 3
RETRY_BACKOFF_FACTOR: float = 1.0

# Watcher debounce window (seconds)
WATCHER_DEBOUNCE_SECONDS: float = 2.0

# Logging
LOG_LEVEL: str = "INFO"
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
