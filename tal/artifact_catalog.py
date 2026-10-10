"""Content-addressed provenance for pipeline artifacts."""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from typing import Any

from .safe_paths import resolve_workspace_path


@dataclass(frozen=True)
class ArtifactRecord:
    """A verified artifact snapshot, stored relative to its workspace."""

    path: str
    sha256: str
    size_bytes: int
    modified_ns: int
    source_node: str = ""


class ArtifactCatalog:
    """Records artifact content hashes and detects unsafe resume conditions."""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self._records: dict[str, ArtifactRecord] = {}

    @staticmethod
    def _sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as artifact:
            for block in iter(lambda: artifact.read(64 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def record(self, relative_path: str, source_node: str = "") -> ArtifactRecord:
        path = resolve_workspace_path(self.workspace_dir, relative_path)
        stat = os.stat(path)
        record = ArtifactRecord(
            path=relative_path.replace("\\", "/"),
            sha256=self._sha256(path),
            size_bytes=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            source_node=source_node,
        )
        self._records[record.path] = record
        return record

    def record_many(self, relative_paths: list[str], source_node: str = "") -> list[ArtifactRecord]:
        return [self.record(path, source_node) for path in relative_paths]

    def to_dict(self) -> dict[str, Any]:
        return {path: asdict(record) for path, record in sorted(self._records.items())}

    def verify(self, serialized: dict[str, Any]) -> list[str]:
        """Return a clear problem for every missing, malformed, or changed file."""
        problems: list[str] = []
        for path, raw_record in serialized.items():
            if not isinstance(path, str) or not isinstance(raw_record, dict):
                problems.append("Artifact catalog contains an invalid record")
                continue
            expected = raw_record.get("sha256")
            if not isinstance(expected, str) or len(expected) != 64:
                problems.append(f"Artifact catalog has invalid hash for {path}")
                continue
            try:
                resolved = resolve_workspace_path(self.workspace_dir, path)
                actual = self._sha256(resolved)
            except (OSError, ValueError):
                problems.append(f"Artifact is missing or outside workspace: {path}")
                continue
            if actual != expected:
                problems.append(f"Artifact content changed since checkpoint: {path}")
        return problems
