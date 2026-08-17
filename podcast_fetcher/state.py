from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: str | Path, default: Any) -> Any:
    """Read JSON from path, returning `default` if the file doesn't exist yet."""
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json_atomic(path: str | Path, data: Any) -> None:
    """Write JSON to path atomically: write to a temp file in the same
    directory, fsync it, then os.replace over the target. A crash or
    concurrent read mid-write can never observe a partial file, and a
    failure while writing leaves the original file untouched.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, p)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
