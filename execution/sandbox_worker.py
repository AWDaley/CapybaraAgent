"""JSON-line worker ENTRYPOINT. Run ONLY inside a configured OS container.

This script intentionally executes Python code with full language features;
Python AST filtering is not an OS security boundary. All model input must be
isolated by the owning container runtime, never passed to a host interpreter.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import sys

_MAX_REQUEST_BYTES = 65_536
_MAX_REPLY_BYTES = 256 * 1024
_MAX_VALUE_BYTES = 96 * 1024
_MAX_OUTPUT_CHARS = 2_000
_MISSING = object()
_namespace = {"__name__": "__capybara_user__"}


class _BoundedOutput(io.TextIOBase):
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.chars = 0

    def writable(self) -> bool:
        return True

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        allowed = _MAX_OUTPUT_CHARS - self.chars
        if allowed > 0:
            piece = data[:allowed]
            self.parts.append(piece)
            self.chars += len(piece)
        return len(data)

    def value(self) -> str:
        value = "".join(self.parts)
        return value + ("\n... (truncated)" if self.chars >= _MAX_OUTPUT_CHARS else "")


def _safe_json_copy(value, depth: int = 0):
    if depth > 10:
        return _MISSING
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else _MISSING
    if type(value) in (list, tuple) and len(value) <= 2048:
        items = [_safe_json_copy(x, depth + 1) for x in value]
        return _MISSING if any(item is _MISSING for item in items) else items
    if type(value) is dict and len(value) <= 2048:
        if any(type(k) is not str for k in value):
            return _MISSING
        copied = {k: _safe_json_copy(v, depth + 1) for k, v in value.items()}
        return _MISSING if any(v is _MISSING for v in copied.values()) else copied
    return _MISSING


def _snapshot(names: object) -> dict:
    if not isinstance(names, list) or len(names) > 96:
        raise ValueError("snapshot keys must be a bounded list")
    selected: dict = {}
    for name in names:
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
            raise ValueError("snapshot key must be a public identifier")
        if name not in _namespace:
            continue
        copied = _safe_json_copy(_namespace[name])
        if copied is _MISSING:
            continue
        try:
            encoded = json.dumps(copied, allow_nan=False, ensure_ascii=False)
        except (TypeError, ValueError):
            continue
        if len(encoded.encode("utf-8")) <= _MAX_VALUE_BYTES:
            selected[name] = copied
    return selected


def _send(reply: dict) -> None:
    text = json.dumps(reply, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded = (text + "\n").encode("utf-8")
    if len(encoded) > _MAX_REPLY_BYTES:
        encoded = (json.dumps({
            "id": reply.get("id"), "ok": False,
            "error": "WORKER_REPLY_TOO_LARGE",
        }) + "\n").encode("utf-8")
    sys.__stdout__.buffer.write(encoded)
    sys.__stdout__.buffer.flush()


def _process(request: dict) -> dict:
    op = request.get("op")
    if op == "exec":
        code = request.get("code")
        if not isinstance(code, str) or not 0 < len(code.encode("utf-8")) <= _MAX_REQUEST_BYTES - 1024:
            raise ValueError("Python input is empty or too large")
        captured = _BoundedOutput()
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                exec(compile(code, "<isolated-repl>", "exec"), _namespace)
        except BaseException as exc:
            # Never send a host-side traceback or arbitrary exception repr.
            return {
                "ok": False, "error": "WORKER_EXECUTION_ERROR",
                "output": f"{type(exc).__name__}: {str(exc)[:500]}",
            }
        return {"ok": True, "output": captured.value() or "Code executed successfully (no output)."}
    if op == "snapshot":
        return {"ok": True, "state": _snapshot(request.get("names"))}
    if op == "ping":
        return {"ok": True, "output": "ready"}
    raise ValueError("Unknown worker protocol operation")


def main() -> None:
    _send({"id": 0, "ok": True, "output": "ready"})
    while True:
        request = None
        line = sys.__stdin__.buffer.readline(_MAX_REQUEST_BYTES + 1)
        if not line:
            return
        if len(line) > _MAX_REQUEST_BYTES or not line.endswith(b"\n"):
            _send({"id": None, "ok": False, "error": "WORKER_FRAME_TOO_LARGE"})
            return
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")
            seq = request.get("id")
            if type(seq) is not int or seq < 1:
                raise ValueError("Invalid monotonically increasing request id")
            result = _process(request)
            _send({"id": seq, **result})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            _send({"id": request.get("id") if isinstance(request, dict) else None,
                   "ok": False, "error": "WORKER_PROTOCOL_INVALID",
                   "output": str(exc)[:300]})


if __name__ == "__main__":
    main()
