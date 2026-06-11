from __future__ import annotations

from typing import Final

PAPER_HISTORY: Final[str] = "paper_history"
LIVE: Final[str] = "live"
WATCH: Final[str] = "watch"
PAPER: Final[str] = "paper"

ALIASES: Final[dict[str, str]] = {
    "backtest": PAPER_HISTORY,
    PAPER_HISTORY: PAPER_HISTORY,
    LIVE: LIVE,
    WATCH: WATCH,
    PAPER: PAPER,
}


def normalize_paper_trade_mode(mode: str | None) -> str:
    return ALIASES.get(str(mode or "").strip(), str(mode or "").strip())


def display_paper_trade_mode(mode: str | None) -> str:
    normalized = normalize_paper_trade_mode(mode)
    if normalized == PAPER_HISTORY:
        return PAPER_HISTORY
    return normalized or ""
