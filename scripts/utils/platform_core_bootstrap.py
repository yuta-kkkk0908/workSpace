from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_platform_core_importable() -> None:
    candidates = []
    env_path = os.getenv("PLATFORM_CORE_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path("/mnt/e/platformCore"),
            Path("/mnt/e/platformCore/temp"),
        ]
    )
    for candidate in candidates:
        if not candidate.exists():
            continue
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
        return
