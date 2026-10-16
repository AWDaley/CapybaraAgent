"""Shared, host-independent filesystem boundary helpers for TAL workflows."""

from __future__ import annotations

import ntpath
import os


def validate_relative_workspace_path(requested_path: str) -> str:
    """Reject traversal and Windows/POSIX absolute paths on every host OS."""
    if not isinstance(requested_path, str) or not requested_path.strip():
        raise ValueError("A non-empty relative workspace path is required")
    if "\x00" in requested_path:
        raise ValueError("NUL bytes are not permitted in workspace paths")
    normalized = requested_path.replace("\\", "/")
    drive, _ = ntpath.splitdrive(requested_path)
    if drive or normalized.startswith("/") or os.path.isabs(requested_path):
        raise ValueError("Absolute or drive-qualified paths are not permitted")
    if any(part == ".." for part in normalized.split("/")):
        raise ValueError("Path escapes the workspace: parent traversal is outside workspace")
    return requested_path


def resolve_workspace_path(workspace_dir: str, requested_path: str) -> str:
    """Resolve a relative path and ensure it remains inside *workspace_dir*."""
    validate_relative_workspace_path(requested_path)
    workspace = os.path.realpath(workspace_dir)
    resolved = os.path.realpath(os.path.join(workspace, requested_path))
    try:
        contained = os.path.commonpath([workspace, resolved]) == workspace
    except ValueError:
        contained = False
    if not contained:
        raise ValueError(f"Path '{requested_path}' escapes the workspace")
    return resolved
