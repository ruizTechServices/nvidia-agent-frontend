"""Sandboxed filesystem operations.

Provides workspace creation, file uploads, directory listing,
and cleanup — all scoped to a managed base directory.

Threat model: The user is trusted; guard against agent (LLM) misuse only.
"""

import logging
import os
import re
import shutil
from pathlib import Path

from config.settings import SANDBOX_MAX_UPLOAD_MB, SANDBOX_WORKSPACE_DIR
from exceptions import SandboxSecurityError

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manage sandboxed workspace directories for agent file operations."""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir or SANDBOX_WORKSPACE_DIR).resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("WorkspaceManager initialized: base_dir=%s", self._base_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_workspace(self, name: str) -> str:
        """Create a managed workspace directory.

        Args:
            name: Workspace name (sanitized to alphanumeric + hyphens/underscores).

        Returns:
            Absolute path to the created directory.
        """
        safe_name = self._sanitize_name(name)
        workspace_path = self._base_dir / safe_name
        workspace_path.mkdir(parents=True, exist_ok=True)
        logger.info("Created workspace: %s", workspace_path)
        return str(workspace_path)

    def register_path(self, user_path: str) -> str:
        """Validate and register a user-specified directory path.

        The user is trusted per our threat model, so no traversal check
        is applied — we only verify the path exists and is a directory.

        Args:
            user_path: Path to register.

        Returns:
            Resolved absolute path string.

        Raises:
            SandboxSecurityError: If path doesn't exist or is not a directory.
        """
        resolved = Path(user_path).resolve()
        if not resolved.exists():
            raise SandboxSecurityError(
                f"Path does not exist: {user_path}"
            )
        if not resolved.is_dir():
            raise SandboxSecurityError(
                f"Path is not a directory: {user_path}"
            )
        logger.info("Registered user path: %s", resolved)
        return str(resolved)

    def list_workspace(self, path: str) -> list[dict]:
        """List contents of a workspace directory.

        Args:
            path: Directory path to list.

        Returns:
            List of dicts with keys: name, type ("file"/"directory"), size.

        Raises:
            SandboxSecurityError: If path doesn't exist or is not a directory.
        """
        dir_path = Path(path)
        if not dir_path.exists() or not dir_path.is_dir():
            raise SandboxSecurityError(
                f"Invalid workspace path: {path}"
            )

        entries = []
        with os.scandir(dir_path) as scanner:
            for entry in scanner:
                try:
                    stat = entry.stat()
                    entries.append({
                        "name": entry.name,
                        "type": "directory" if entry.is_dir() else "file",
                        "size": stat.st_size if entry.is_file() else 0,
                    })
                except OSError:
                    logger.warning("Could not stat entry: %s", entry.name)
        return entries

    def handle_upload(self, filename: str, data: bytes) -> str:
        """Save uploaded file data into the workspace base directory.

        Args:
            filename: Original filename (will be sanitized).
            data: Raw file bytes.

        Returns:
            Absolute path to the saved file.

        Raises:
            SandboxSecurityError: If file exceeds size limit.
            OSError: If disk space is insufficient.
        """
        max_bytes = SANDBOX_MAX_UPLOAD_MB * 1024 * 1024
        if len(data) > max_bytes:
            raise SandboxSecurityError(
                f"File size {len(data)} bytes exceeds limit of "
                f"{SANDBOX_MAX_UPLOAD_MB} MB"
            )

        if not self.check_disk_space(len(data)):
            raise OSError(
                f"Insufficient disk space for {len(data)} byte upload"
            )

        safe_name = self._sanitize_filename(filename)
        dest = self._base_dir / safe_name
        dest.write_bytes(data)
        logger.info("Uploaded file: %s (%d bytes)", dest, len(data))
        return str(dest)

    def cleanup_workspace(self, path: str) -> None:
        """Remove a workspace directory.

        Only allows deletion of directories under the base_dir to
        prevent accidental removal of unrelated paths.

        Raises:
            SandboxSecurityError: If path is not under base_dir.
        """
        resolved = Path(path).resolve()
        if not str(resolved).startswith(str(self._base_dir)):
            raise SandboxSecurityError(
                f"Cannot cleanup path outside base directory: {path}"
            )
        if resolved.exists():
            shutil.rmtree(resolved)
            logger.info("Cleaned up workspace: %s", resolved)

    def check_disk_space(self, required_bytes: int) -> bool:
        """Check if enough disk space is available.

        Args:
            required_bytes: Number of bytes needed.

        Returns:
            True if sufficient space is available.
        """
        try:
            usage = shutil.disk_usage(self._base_dir)
            has_space = usage.free >= required_bytes
            if not has_space:
                logger.warning(
                    "Low disk space: %d bytes free, %d required",
                    usage.free, required_bytes,
                )
            return has_space
        except OSError:
            logger.error("Could not check disk space for %s", self._base_dir)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Strip unsafe characters from a workspace name."""
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", name)
        return sanitized or "workspace"

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Strip unsafe characters from a filename, preserving extension."""
        name = Path(filename).name  # remove any directory components
        sanitized = re.sub(r"[^a-zA-Z0-9_.\-]", "", name)
        return sanitized or "upload"
