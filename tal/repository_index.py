"""Small deterministic Python symbol index for selective SLM context recovery."""

from __future__ import annotations

import ast
import os
from dataclasses import asdict, dataclass


_EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "data", "workspace"}


@dataclass(frozen=True)
class SymbolRecord:
    name: str
    kind: str
    path: str
    line: int


class RepositoryIndex:
    """Indexes module-level Python symbols without relying on a model to browse."""

    def __init__(self, root_dir: str, symbols: list[SymbolRecord]):
        self.root_dir = os.path.realpath(root_dir)
        self.symbols = sorted(symbols, key=lambda item: (item.path, item.line, item.name))

    @classmethod
    def build(cls, root_dir: str, max_files: int = 2_000) -> "RepositoryIndex":
        root = os.path.realpath(root_dir)
        symbols: list[SymbolRecord] = []
        files_seen = 0
        for current, directories, filenames in os.walk(root):
            directories[:] = sorted(name for name in directories if name not in _EXCLUDED_DIRS)
            for filename in sorted(filenames):
                if not filename.endswith(".py"):
                    continue
                files_seen += 1
                if files_seen > max_files:
                    return cls(root, symbols)
                absolute = os.path.join(current, filename)
                try:
                    with open(absolute, "r", encoding="utf-8") as source:
                        tree = ast.parse(source.read(), filename=absolute)
                except (OSError, UnicodeDecodeError, SyntaxError):
                    continue
                relative = os.path.relpath(absolute, root).replace("\\", "/")
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(SymbolRecord(node.name, "function", relative, node.lineno))
                    elif isinstance(node, ast.ClassDef):
                        symbols.append(SymbolRecord(node.name, "class", relative, node.lineno))
        return cls(root, symbols)

    def search(self, query: str, limit: int = 12) -> list[SymbolRecord]:
        needle = query.strip().lower()
        if not needle or limit <= 0:
            return []
        exact = [item for item in self.symbols if item.name.lower() == needle]
        partial = [item for item in self.symbols if needle in item.name.lower() and item not in exact]
        return (exact + partial)[:limit]

    def to_context(self, query: str, limit: int = 12) -> str:
        return "\n".join(
            f"- {item.kind} {item.name} at {item.path}:{item.line}"
            for item in self.search(query, limit)
        )

    def to_dict(self) -> list[dict[str, object]]:
        return [asdict(symbol) for symbol in self.symbols]
