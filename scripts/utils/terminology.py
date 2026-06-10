from __future__ import annotations


def scenario_tier_label(v: str) -> str:
    tier = (v or "").strip().lower()
    if tier == "trade":
        return "become"
    if tier == "paper_trade_only":
        return "paper"
    if tier == "watch":
        return "watch"
    return tier or ""


def glossary_line() -> str:
    return "用語: trade=実エントリー / become=有望シグナル / watch=監視"
