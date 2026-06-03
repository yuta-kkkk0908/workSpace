from __future__ import annotations

QUALITY_REASON_LABELS = {
    "CREDIT_THIN": "信用情報が薄い",
    "DATA_THIN": "シグナル件数が少ない",
    "MATERIAL_NONE_TODAY": "当日材料がない",
    "MATERIAL_STALE": "材料が古い",
    "NOON_DATA_GAP": "昼のスナップショット不足",
    "REPEATED_TICKER_BIAS": "同一銘柄の連続出現が多い",
    "SCENARIO_BIAS": "シナリオ配分が偏っている",
    "SIDE_IMBALANCE": "上昇/下落方向の偏りが大きい",
}

DECISION_SUPPORT_WARNING_LABELS = {
    "winrate_drop": "勝率低下",
    "dd_worse": "ドローダウン悪化",
    "accepted_drop": "採択件数減少",
}

RULE_THIN_LABELS = {
    "(none)": "理由なし",
}

OPS_ERROR_CATEGORY_LABELS = {
    "discord_delivery": "Discord送信失敗",
    "source_fetch": "収集元取得失敗",
    "db_error": "DBエラー",
    "auth_error": "認証エラー",
    "process_error": "処理エラー",
    "ok": "正常",
    "unknown": "不明",
}


def format_labeled_code(code: str, labels: dict[str, str]) -> str:
    k = str(code or "").strip()
    if not k:
        return ""
    label = labels.get(k, "")
    if label:
        return f"{k}（{label}）"
    return k


def format_quality_reason(code: str) -> str:
    return format_labeled_code(code, QUALITY_REASON_LABELS)


def format_decision_warning(code: str) -> str:
    return format_labeled_code(code, DECISION_SUPPORT_WARNING_LABELS)


def format_ops_error_category(code: str) -> str:
    return format_labeled_code(code, OPS_ERROR_CATEGORY_LABELS)

