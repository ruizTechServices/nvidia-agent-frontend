"""Tests for sandbox.filesystem — workspace management."""

import os
import sys
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exceptions import SandboxSecurityError
from sandbox.filesystem import WorkspaceManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager(tmp_path):
    """WorkspaceManager with a temporary base directory."""
    return WorkspaceManager(str(tmp_path))


@pytest.fixture
def base_dir(tmp_path):
    """Return the tmp_path string for convenience."""
    return str(tmp_path)


# ---------------------------------------------------------------------------
# create_workspace
# ---------------------------------------------------------------------------

def test_create_workspace(manager, tmp_path):
    """Directory created and path returned."""
    path = manager.create_workspace("test-project")
    assert os.path.isdir(path)
    assert "test-project" in path


def test_create_workspace_sanitize(manager):
    """Bad characters stripped from name."""
    path = manager.create_workspace("my project!!@#$%")
    dir_name = os.path.basename(path)
    assert dir_name == "myproject"
    assert os.path.isdir(path)


def test_create_workspace_empty_name(manager):
    """Empty/all-bad-chars name falls back to 'workspace'."""
    path = manager.create_workspace("@#$%")
    assert os.path.basename(path) == "workspace"


# ---------------------------------------------------------------------------
# register_path
# ---------------------------------------------------------------------------

def test_register_path(manager, tmp_path):
    """Valid directory registered."""
    subdir = tmp_path / "existing"
    subdir.mkdir()
    result = manager.register_path(str(subdir))
    assert os.path.isabs(result)
    assert os.path.isdir(result)


def test_register_path_nonexistent(manager):
    """Missing path raises error."""
    with pytest.raises(SandboxSecurityError, match="does not exist"):
        manager.register_path("/nonexistent/path/xyz")


def test_register_path_file_not_dir(manager, tmp_path):
    """File path (not directory) raises error."""
    f = tmp_path / "afile.txt"
    f.write_text("hello")
    with pytest.raises(SandboxSecurityError, match="not a directory"):
        manager.register_path(str(f))


# ---------------------------------------------------------------------------
# list_workspace
# ---------------------------------------------------------------------------

def test_list_workspace(manager, tmp_path):
    """Returns entries with name, type, size."""
    # Create a file and a subdirectory
    (tmp_path / "hello.txt").write_text("hello world")
    (tmp_path / "subdir").mkdir()

    entries = manager.list_workspace(str(tmp_path))
    names = {e["name"] for e in entries}
    assert "hello.txt" in names
    assert "subdir" in names

    file_entry = next(e for e in entries if e["name"] == "hello.txt")
    assert file_entry["type"] == "file"
    assert file_entry["size"] > 0

    dir_entry = next(e for e in entries if e["name"] == "subdir")
    assert dir_entry["type"] == "directory"


def test_list_workspace_empty(manager, tmp_path):
    """Empty directory returns empty list."""
    empty = tmp_path / "empty"
    empty.mkdir()
    entries = manager.list_workspace(str(empty))
    assert entries == []


def test_list_workspace_invalid_path(manager):
    """Non-existent path raises error."""
    with pytest.raises(SandboxSecurityError, match="Invalid workspace path"):
        manager.list_workspace("/nonexistent/path")


# ---------------------------------------------------------------------------
# handle_upload
# ---------------------------------------------------------------------------

def test_handle_upload(manager, tmp_path):
    """File saved to workspace."""
    data = b"file content here"
    path = manager.handle_upload("test.txt", data)
    assert os.path.isfile(path)
    with open(path, "rb") as f:
        assert f.read() == data


def test_handle_upload_sanitizes_filename(manager):
    """Dangerous filename characters stripped."""
    data = b"data"
    path = manager.handle_upload("../../evil.txt", data)
    assert os.path.isfile(path)
    # Should not contain path traversal
    assert ".." not in os.path.basename(path)


def test_handle_upload_size_limit(manager):
    """Oversized file rejected."""
    # Create data larger than limit (patch to 1MB for test)
    with patch("sandbox.filesystem.SANDBOX_MAX_UPLOAD_MB", 1):
        big_data = b"x" * (2 * 1024 * 1024)  # 2 MB
        with pytest.raises(SandboxSecurityError, match="exceeds limit"):
            manager.handle_upload("big.bin", big_data)


# ---------------------------------------------------------------------------
# cleanup_workspace
# ---------------------------------------------------------------------------

def test_cleanup_workspace(manager, tmp_path):
    """Directory removed."""
    ws_path = manager.create_workspace("to-delete")
    assert os.path.isdir(ws_path)
    manager.cleanup_workspace(ws_path)
    assert not os.path.exists(ws_path)


def test_cleanup_traversal_blocked(manager, tmp_path):
    """Can't cleanup outside base_dir."""
    outside = str(tmp_path / ".." / "some-other-dir")
    from pathlib import Path
    resolved = str(Path(outside).resolve())
    resolved_base = str(Path(str(tmp_path)).resolve())
    if not resolved.startswith(resolved_base):
        with pytest.raises(SandboxSecurityError, match="outside base directory"):
            manager.cleanup_workspace(outside)


# ---------------------------------------------------------------------------
# check_disk_space
# ---------------------------------------------------------------------------

def test_check_disk_space(manager):
    """Returns bool based on available space."""
    # Requesting 1 byte should always succeed
    assert manager.check_disk_space(1) is True


def test_check_disk_space_huge(manager):
    """Requesting absurd amount returns False."""
    # 1 exabyte — should exceed any disk
    result = manager.check_disk_space(10**18)
    assert result is False
