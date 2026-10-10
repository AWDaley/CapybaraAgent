"""Shared filesystem boundary helpers for TAL workflows."""

from __future__ import annotations

import os


def resolve_workspace_path(workspace_dir: str, requested_path: str) -> str:
    """Resolve a relative path and ensure it remains in *workspace_dir*."""
    if not isinstance(requested_path, str) or not requested_path.strip():
        raise ValueError("A non-empty relative workspace path is required")
    if os.path.isabs(requested_path):
        raise ValueError("Absolute paths are not permitted")

    workspace = os.path.realpath(workspace_dir)
    resolved = os.path.realpath(os.path.join(workspace, requested_path))
    try:
        contained = os.path.commonpath([workspace, resolved]) == workspace
    except ValueError:
        contained = False
    if not contained:
        raise ValueError(f"Path '{requested_path}' escapes the workspace")
    return resolved
