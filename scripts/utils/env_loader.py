from __future__ import annotations

import os
from pathlib import Path


def load_env_files(*paths: Path) -> None:
    for env_file in paths:
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            key, value = s.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
