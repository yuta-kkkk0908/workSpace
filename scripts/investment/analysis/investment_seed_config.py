#!/usr/bin/env python3
"""Load investment backtest seed file lists from config."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs/investment-seeds.json"


def load_seed_paths(config_path: Path | None = None, list_name: str | None = None) -> list[Path]:
    path = config_path or DEFAULT_CONFIG
    data = json.loads(path.read_text(encoding="utf-8"))
    selected = list_name or data.get("defaultSeedList")
    seed_lists = data.get("seedLists") or {}
    if selected not in seed_lists:
        available = ", ".join(sorted(seed_lists)) or "none"
        raise KeyError(f"seed list not found: {selected!r}; available={available}")
    return [ROOT / item for item in seed_lists[selected]]
