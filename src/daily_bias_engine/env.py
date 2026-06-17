"""Local environment loading helpers."""

from __future__ import annotations

import os
from pathlib import Path


def load_local_env(project_root: Path, filenames: tuple[str, ...] = (".env.local", ".env")) -> None:
    """Load simple KEY=VALUE pairs without overriding process environment."""

    for filename in filenames:
        path = project_root / filename
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.lstrip("\ufeff").strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
