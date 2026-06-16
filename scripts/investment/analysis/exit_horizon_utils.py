from __future__ import annotations

import json
from collections.abc import Iterable


def win_rate(vals: list[float]) -> float:
    if not vals:
        return 0.0
    return sum(1 for v in vals if v > 0) / len(vals) * 100.0


def avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _price_path_ret(price_path_json: str | None, *, offset: int, side: str | None) -> float | None:
    if not price_path_json:
        return None
    try:
        payload = json.loads(price_path_json)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    bars = payload.get("bars") or []
    if not isinstance(bars, list) or len(bars) <= offset:
        return None
    base = payload.get("base_close")
    try:
        base_f = float(base)
    except Exception:
        base_f = None
    if base_f is None or base_f == 0:
        return None
    bar = bars[offset]
    if not isinstance(bar, dict):
        return None
    try:
        close = float(bar.get("close"))
    except Exception:
        return None
    sign = -1.0 if str(side or "").strip().lower() == "short" else 1.0
    return ((close / base_f) - 1.0) * 100.0 * sign


def collect_price_path_returns(rows: Iterable[object], *, offset: int) -> list[float]:
    out: list[float] = []
    for row in rows:
        price_path_json = row["price_path_json"]
        side = row["side"]
        ret = _price_path_ret(price_path_json, offset=offset, side=side)
        if ret is not None:
            out.append(float(ret))
    return out
