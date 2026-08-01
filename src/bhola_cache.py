"""Privacy-preserving cache helpers for Bhola Pulse."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


_SAFE_PROCESS_CHARACTER = re.compile(r"[^A-Za-z0-9._+-]+")


def sanitize_process_name(value: str | None, limit: int = 32) -> str:
    """Return a short process label without paths, whitespace, or arguments."""
    if not value:
        return "unknown"
    basename = value.replace("\\", "/").rsplit("/", 1)[-1]
    sanitized = _SAFE_PROCESS_CHARACTER.sub("_", basename).strip("._-")
    return sanitized[:limit] or "unknown"


def atomic_write_json(output: Path, payload: dict[str, Any]) -> None:
    """Replace a JSON cache atomically in the target directory."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
