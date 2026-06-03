#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DEFAULT_INVESTMENT_DB = DATA_DIR / "investment.db"
PREFERRED_INVESTMENT_DB = DATA_DIR / "investment.main.db"


def resolve_investment_db() -> Path:
    """
    Prefer the normalized main DB when present.
    Fall back to the historical investment.db path for compatibility.
    """
    if PREFERRED_INVESTMENT_DB.exists():
        return PREFERRED_INVESTMENT_DB
    return DEFAULT_INVESTMENT_DB
