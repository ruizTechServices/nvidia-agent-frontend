"""Sandboxed command executor.

Runs shell commands in a restricted subprocess with
timeout enforcement and output capture.

Threat model: protect against agent (LLM) only — the user is trusted.
Platform-aware whitelists are loaded based on sys.platform at init time.
"""

import logging
import platform
import shlex
import subprocess
import sys
from pathlib import Path

from exceptions import SandboxSecurityError, SandboxTimeoutError
from models import ExecutionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform whitelists / blocklists
# ---------------------------------------------------------------------------

LINUX_WHITELIST: set[str] = {
    "ls", "grep", "cat", "find", "head", "tail", "wc", "awk",
    "df", "free", "nvidia-smi", "jtop",
    "echo", "pwd", "date", "uname", "whoami", "env", "printenv",
}

WINDOWS_WHITELIST: set[str] = {
    # Native Windows commands
    "dir", "findstr", "type", "where", "echo", "cd", "date", "whoami", "set",
    # Git Bash Unix equivalents
    "ls", "grep", "cat", "find", "head", "tail", "wc", "awk", "pwd", "uname",
}

GLOBAL_BLOCKLIST: set[str] = {
    "sudo", "chmod", "chown", "curl", "wget", "nc", "ncat",
    "ssh", "scp", "shutdown", "reboot", "mkfs", "dd",
    "kill", "killall", "pkill",
}

ORIN_NANO_BLOCKLIST: set[str] = {
    "jetson_clocks", "nvpmodel",
}

DANGEROUS_PATTERNS: list[str] = [
    "rm -rf", "rm -fr",
]


def _is_orin_nano() -> bool:
    """Detect if running on an Nvidia Jetson (ARM64 Linux)."""
    return sys.platform == "linux" and platform.machine() == "aarch64"


class SandboxExecutor:
    """Execute shell commands within a security sandbox.

    Commands are validated against platform-specific whitelists
    and a global blocklist before execution.
    """

    def __init__(self, workspace_root: str, timeout: int | None = None) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._timeout = timeout or 30
        self._is_windows = sys.platform == "win32"

        if self._is_windows:
            self._whitelist = WINDOWS_WHITELIST.copy()
        else:
            self._whitelist = LINUX_WHITELIST.copy()

        self._blocklist = GLOBAL_BLOCKLIST.copy()
        if _is_orin_nano():
            self._blocklist |= ORIN_NANO_BLOCKLIST

        logger.info(
            "SandboxExecutor initialized: platform=%s, workspace=%s, timeout=%d",
            sys.platform, self._workspace_root, self._timeout,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Run a whitelisted command and return its output.

        Raises:
            SandboxSecurityError: If the command or path is not allowed.
            SandboxTimeoutError: If the command exceeds the timeout.
        """
        logger.debug("execute() called: command=%r, cwd=%r", command, cwd)
        self._validate_command(command)

        effective_cwd: str | None = None
        if cwd is not None:
            effective_cwd = self._validate_path(cwd)

        effective_timeout = timeout if timeout is not None else self._timeout

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=effective_cwd,
            )
            exec_result = ExecutionResult(
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
            logger.info(
                "Command completed: returncode=%d, stdout_len=%d",
                exec_result.returncode, len(exec_result.stdout),
            )
            return exec_result

        except subprocess.TimeoutExpired as exc:
            logger.error("Command timed out after %ds: %r", effective_timeout, command)
            raise SandboxTimeoutError(
                f"Command timed out after {effective_timeout}s: {command}"
            ) from exc

        except OSError as exc:
            logger.error("Command execution failed: %s", exc)
            raise SandboxSecurityError(
                f"Command execution failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_command(self, command: str) -> str:
        """Validate a command string against whitelist/blocklist.

        Returns the base command name if valid.

        Raises:
            SandboxSecurityError: If the command is blocked or not whitelisted.
        """
        # Check dangerous patterns first (substring match on full command)
        command_lower = command.lower()
        for pattern in DANGEROUS_PATTERNS:
            if pattern in command_lower:
                raise SandboxSecurityError(
                    f"Blocked dangerous pattern '{pattern}' in command: {command}"
                )

        # Parse command to extract base
        try:
            tokens = shlex.split(command)
        except ValueError:
            raise SandboxSecurityError(
                f"Could not parse command: {command}"
            )

        if not tokens:
            raise SandboxSecurityError("Empty command")

        base_cmd = Path(tokens[0]).name  # strip path prefix if any

        # Check blocklist (base command)
        if base_cmd in self._blocklist:
            raise SandboxSecurityError(
                f"Command '{base_cmd}' is blocked by security policy"
            )

        # Also check for blocked commands anywhere in a pipe chain
        for token in tokens:
            token_name = Path(token).name
            if token_name in self._blocklist:
                raise SandboxSecurityError(
                    f"Command '{token_name}' is blocked by security policy"
                )

        # Check whitelist
        if base_cmd not in self._whitelist:
            raise SandboxSecurityError(
                f"Command '{base_cmd}' is not in the allowed command list"
            )

        return base_cmd

    def _validate_path(self, path: str) -> str:
        """Validate that a path is under the workspace root.

        Returns the resolved absolute path string.

        Raises:
            SandboxSecurityError: If path traversal is detected.
        """
        resolved = Path(path).resolve()
        if not str(resolved).startswith(str(self._workspace_root)):
            raise SandboxSecurityError(
                f"Path traversal detected: {path} resolves outside workspace "
                f"{self._workspace_root}"
            )
        return str(resolved)
