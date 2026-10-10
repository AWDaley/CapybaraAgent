import os
import tempfile

import pytest

from tal.artifact_catalog import ArtifactCatalog
from tal.repository_index import RepositoryIndex


def test_artifact_catalog_detects_changed_content():
    with tempfile.TemporaryDirectory() as workspace:
        target = os.path.join(workspace, "result.txt")
        with open(target, "w", encoding="utf-8") as artifact:
            artifact.write("verified result")

        catalog = ArtifactCatalog(workspace)
        catalog.record("result.txt", source_node="step_1")
        snapshot = catalog.to_dict()
        assert catalog.verify(snapshot) == []
        assert snapshot["result.txt"]["source_node"] == "step_1"

        with open(target, "w", encoding="utf-8") as artifact:
            artifact.write("mutated result")
        assert catalog.verify(snapshot) == ["Artifact content changed since checkpoint: result.txt"]


def test_artifact_catalog_rejects_workspace_escape():
    with tempfile.TemporaryDirectory() as workspace:
        catalog = ArtifactCatalog(workspace)
        with pytest.raises(ValueError, match="escapes the workspace"):
            catalog.record("../outside.txt")


def test_repository_index_finds_symbols_and_skips_invalid_python():
    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, "service.py"), "w", encoding="utf-8") as source:
            source.write("class Service:\n    pass\n\ndef build_service():\n    return Service()\n")
        with open(os.path.join(root, "broken.py"), "w", encoding="utf-8") as source:
            source.write("def not valid(:\n")
        os.makedirs(os.path.join(root, ".git"))
        with open(os.path.join(root, ".git", "ignored.py"), "w", encoding="utf-8") as source:
            source.write("def ignored():\n    pass\n")

        index = RepositoryIndex.build(root)
        found = index.search("service")
        assert [(item.kind, item.name) for item in found] == [
            ("class", "Service"),
            ("function", "build_service"),
        ]
        assert "service.py:4" in index.to_context("build_service")
