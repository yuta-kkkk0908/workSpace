from __future__ import annotations

QUALITY_REASON_LABELS = {
    "CREDIT_THIN": "信用情報が薄い",
    "DATA_THIN": "シグナル件数が少ない",
    "MATERIAL_NONE_TODAY": "当日材料がない",
    "MATERIAL_STALE": "材料が古い",
    "NOON_DATA_GAP": "昼のスナップショット不足",
    "REPEATED_TICKER_BIAS": "同一銘柄の連続出現が多い",
    "SCENARIO_BIAS": "有望シグナル配分が偏っている",
    "SIDE_IMBALANCE": "上昇/下落方向の偏りが大きい",
}


def format_quality_reason(code: str) -> str:
    k = str(code or "").strip()
    if not k:
        return ""
    label = QUALITY_REASON_LABELS.get(k, "")
    if label:
        return f"{k}（{label}）"
    return k
