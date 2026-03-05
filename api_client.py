"""
HTTP client for the FastAPI resume service.

Every public method transparently retries on transient failures using
exponential back-off.  A single ``httpx.Client`` is reused for connection
pooling.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

import config

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Raised when the API returns an unrecoverable error."""


class ResumeAPIClient:
    """Thin wrapper around the resume management REST API."""

    def __init__(
        self,
        base_url: str = config.API_BASE_URL,
        max_retries: int = config.MAX_RETRIES,
        backoff: float = config.RETRY_BACKOFF_FACTOR,
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff = backoff
        self._client = httpx.Client(
            base_url=self._base,
            timeout=timeout,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Internal retry helper
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Execute *method* on *path* with automatic retry + back-off.

        Retries are triggered by:
        * network / connection errors
        * HTTP 429 (rate-limited) and 5xx (server errors)

        Non-retryable 4xx errors raise immediately.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.request(method, path, **kwargs)

                if resp.status_code < 400:
                    return resp

                # Decide whether the error is retryable.
                if resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "Retryable HTTP %d on %s %s (attempt %d/%d)",
                        resp.status_code, method, path, attempt, self._max_retries,
                    )
                    last_exc = APIError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    # 4xx client errors are not retried.
                    raise APIError(
                        f"HTTP {resp.status_code} on {method} {path}: {resp.text[:200]}"
                    )

            except httpx.HTTPError as exc:
                logger.warning(
                    "Network error on %s %s (attempt %d/%d): %s",
                    method, path, attempt, self._max_retries, exc,
                )
                last_exc = exc

            # Exponential back-off: 1s → 2s → 4s …
            if attempt < self._max_retries:
                sleep_secs = self._backoff * (2 ** (attempt - 1))
                logger.debug("Sleeping %.1fs before retry…", sleep_secs)
                time.sleep(sleep_secs)

        raise APIError(f"All {self._max_retries} attempts failed for {method} {path}") from last_exc

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def list_resumes(self) -> Dict[str, Any]:
        """``GET /api/v1/resumes/`` → dict keyed by filename.

        The API wraps the file map inside a top-level envelope::

            {"sync_version": 1, "server_time": "...", "total_files": 1,
             "files": {"resume.pdf": {...}, ...}}

        We unwrap and return only the ``files`` dict.
        """
        resp = self._request("GET", "/api/v1/resumes/")
        payload = resp.json()
        return payload.get("files", {})

    def get_download_url(self, resume_id: str) -> str:
        """``GET /api/v1/resumes/{id}`` → signed download URL."""
        resp = self._request("GET", f"/api/v1/resumes/{resume_id}")
        data = resp.json()
        return data["signed_url"]

    def download_file(self, download_url: str, dest: Path) -> None:
        """Stream a file from *download_url* and write it to *dest*.

        This call also retries because the signed URL may be served by an
        external object store that can transiently fail.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                with httpx.stream("GET", download_url, timeout=60.0) as stream:
                    stream.raise_for_status()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with open(dest, "wb") as f:
                        for chunk in stream.iter_bytes(chunk_size=65_536):
                            f.write(chunk)
                logger.info("Downloaded %s", dest.name)
                return
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("Download attempt %d/%d failed: %s", attempt, self._max_retries, exc)
                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(self._backoff * (2 ** (attempt - 1)))

        raise APIError(f"Download failed after {self._max_retries} attempts") from last_exc

    # Map of file extensions to MIME types accepted by the API.
    _MIME_TYPES = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    def upload_file(self, filepath: Path) -> Dict[str, Any]:
        """``POST /api/v1/resumes/upload`` – multipart file upload.

        The API expects two form fields:
        * ``file``  – the binary file (must be PDF, DOC, or DOCX)
        * ``title`` – a human-readable name (we use the filename stem)
        """
        ext = filepath.suffix.lower()
        mime = self._MIME_TYPES.get(ext)
        if mime is None:
            raise APIError(
                f"Unsupported file type '{ext}' for {filepath.name}. "
                f"Allowed: {', '.join(self._MIME_TYPES.keys())}"
            )

        # Title is the company name, derived from the parent folder.
        # e.g. ~/resume_sync/Google/resume.pdf → title = "Google"
        # If the file is directly in resume_sync (no subfolder), fall back to filename stem.
        parent = filepath.parent.name
        sync_folder_name = config.SYNC_FOLDER.name
        if parent == sync_folder_name:
            title = filepath.stem
        else:
            title = parent
        with open(filepath, "rb") as f:
            resp = self._request(
                "POST",
                "/api/v1/resumes/upload",
                files={"file": (filepath.name, f, mime)},
                data={"title": title},
            )
        logger.info("Uploaded %s", filepath.name)
        return resp.json()

    def delete_resume(self, resume_id: str) -> None:
        """``DELETE /api/v1/resumes/{id}``."""
        self._request("DELETE", f"/api/v1/resumes/{resume_id}")
        logger.info("Deleted cloud resume id=%s", resume_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()