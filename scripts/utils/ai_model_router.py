#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "ai_model_routing.json"


def resolve_model(route_key: str, config_path: Path | None = None) -> tuple[str, str]:
    cfg_path = config_path or DEFAULT_CONFIG
    if not cfg_path.exists():
        return ("openai", "gpt-5-mini")
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return ("openai", "gpt-5-mini")

    routes = cfg.get("routes") if isinstance(cfg, dict) else {}
    defaults = cfg.get("defaults") if isinstance(cfg, dict) else {}
    route = routes.get(route_key, {}) if isinstance(routes, dict) else {}

    provider = str(route.get("provider") or defaults.get("provider") or "openai").strip().lower()
    model = str(route.get("model") or defaults.get("model") or "gpt-5-mini").strip()
    if not provider:
        provider = "openai"
    if not model:
        model = "gpt-5-mini"
    return (provider, model)
