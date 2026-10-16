"""One-use authorizations bound to a TAL task, session and exact tool arguments.

The model never receives an authorization token. The executor must consume the
token immediately before calling a tool, even when it needs no user approval.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass


def fingerprint_arguments(arguments: str) -> str:
    """Canonicalize JSON arguments; fail rather than accepting invalid JSON."""
    parsed = json.loads(arguments)
    normalized = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthorizedAction:
    action_id: str
    task_id: str
    manifest_hash: str
    session_id: str
    tool_name: str
    tool_version: str
    arguments_hash: str
    target_ref: str
    phase: str
    expires_at: float


class AuthorizationDenied(PermissionError):
    """The action has no matching, unconsumed authorization."""


class ToolAuthorizationService:
    """In-process one-use capability tokens, intentionally never model-facing."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._issued: set[str] = set()

    def issue(
        self, *,
        task_id: str, manifest_hash: str, session_id: str, tool_name: str,
        arguments: str, phase: str, requires_approval: bool,
        approval_granted: bool, ttl_seconds: float = 60.0,
        tool_version: str = "builtin-v1",
    ) -> AuthorizedAction:
        if requires_approval and not approval_granted:
            raise AuthorizationDenied("Explicit user approval is required")
        if not manifest_hash or not session_id or not tool_name or ttl_seconds <= 0:
            raise AuthorizationDenied("Missing action identity or invalid authorization lifetime")
        try:
            argument_hash = fingerprint_arguments(arguments)
            decoded = json.loads(arguments)
        except (ValueError, TypeError) as exc:
            raise AuthorizationDenied("Arguments are not valid JSON") from exc
        target = str(decoded.get("path", decoded.get("key", ""))) if isinstance(decoded, dict) else ""
        action = AuthorizedAction(
            action_id=uuid.uuid4().hex,
            task_id=task_id, manifest_hash=manifest_hash, session_id=session_id,
            tool_name=tool_name, tool_version=tool_version,
            arguments_hash=argument_hash, target_ref=target, phase=phase,
            expires_at=time.monotonic() + ttl_seconds,
        )
        with self._lock:
            self._issued.add(action.action_id)
        return action

    def consume(
        self, action: AuthorizedAction, *, task_id: str, manifest_hash: str,
        session_id: str, tool_name: str, arguments: str, phase: str,
    ) -> None:
        """Validate and atomically consume a token, before any side effects."""
        try:
            digest = fingerprint_arguments(arguments)
            decoded = json.loads(arguments)
        except (ValueError, TypeError) as exc:
            raise AuthorizationDenied("Arguments changed or became invalid") from exc
        target = str(decoded.get("path", decoded.get("key", ""))) if isinstance(decoded, dict) else ""
        with self._lock:
            if action.action_id not in self._issued:
                raise AuthorizationDenied("Action approval has already been consumed or is unknown")
            # Even a failed attempt invalidates the authorization token.
            self._issued.remove(action.action_id)
            if (
                time.monotonic() >= action.expires_at
                or action.task_id != task_id
                or action.manifest_hash != manifest_hash
                or action.session_id != session_id
                or action.tool_name != tool_name
                or action.arguments_hash != digest
                or action.target_ref != target
                or action.phase != phase
            ):
                raise AuthorizationDenied("Authorization does not match the current action")
