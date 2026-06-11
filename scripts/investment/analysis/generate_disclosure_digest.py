#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()

CATEGORY_LABELS = {
    "upward_revision_highest_profit": "上方修正・最高益",
    "upward_revision_plus_dividend": "上方修正・配当材料",
    "upward_revision": "上方修正",
    "dividend_revision": "配当修正",
    "offering_or_dilution": "希薄化・売出",
    "downward_revision_dividend_cut": "下方修正・減配",
    "weak_earnings_or_guidance": "弱い業績・ガイダンス",
}

POSITIVE_CATEGORIES = {
    "upward_revision_highest_profit",
    "upward_revision_plus_dividend",
    "upward_revision",
    "dividend_revision",
}
NEGATIVE_CATEGORIES = {
    "offering_or_dilution",
    "downward_revision_dividend_cut",
    "weak_earnings_or_guidance",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a TDnet disclosure digest draft from investment DB.")
    p.add_argument("--date", default=date.today().isoformat(), help="Target date (YYYY-MM-DD)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "topics/investment-research/inbox",
        help="Directory where the markdown outputs will be written.",
    )
    p.add_argument("--lookback-days", type=int, default=90)
    p.add_argument("--limit", type=int, default=20)
    return p.parse_args()


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,)).fetchone()
    return bool(row)


def ensure_storage_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collection_artifacts (
          artifact_key TEXT NOT NULL,
          artifact_date TEXT NOT NULL,
          artifact_type TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(artifact_key, artifact_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_digest (
          topic TEXT NOT NULL,
          date TEXT NOT NULL,
          path TEXT NOT NULL,
          summary TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(topic, date)
        )
        """
    )


def fetch_disclosures(conn: sqlite3.Connection, target_date: str, limit: int) -> list[dict[str, Any]]:
    if not table_exists(conn, "tdnet_disclosures"):
        return []
    rows = conn.execute(
        """
        SELECT date,disclosed_at,ticker,company,title,category,tdnet_url,source_kind,source_path
        FROM tdnet_disclosures
        WHERE date=?
        ORDER BY
          CASE
            WHEN category IN ('upward_revision_highest_profit','upward_revision_plus_dividend','downward_revision_dividend_cut','offering_or_dilution') THEN 0
            WHEN COALESCE(category,'')<>'' THEN 1
            ELSE 2
          END,
          disclosed_at DESC,
          ticker
        LIMIT ?
        """,
        (target_date, max(1, limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_signal_context(conn: sqlite3.Connection, target_date: str, ticker: str) -> list[dict[str, Any]]:
    if not table_exists(conn, "signals"):
        return []
    rows = conn.execute(
        """
        SELECT signal_id,signal_type,expected_direction,long_rank,short_rank,gate_status,source,url
        FROM signals
        WHERE date=? AND ticker=?
        ORDER BY
          CASE WHEN LOWER(COALESCE(gate_status,''))='pass' THEN 0 ELSE 1 END,
          signal_id
        LIMIT 5
        """,
        (target_date, ticker),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_entry_candidate_context(conn: sqlite3.Connection, target_date: str, ticker: str) -> list[dict[str, Any]]:
    if not table_exists(conn, "entry_candidates"):
        return []
    rows = conn.execute(
        """
        SELECT date,side,candidate_type,signal_id,ticker,company,rank,long_rank,short_rank,
               expected_direction,trade_use,gate_status,score,url
        FROM entry_candidates
        WHERE date=? AND ticker=?
        ORDER BY
          CASE WHEN LOWER(COALESCE(gate_status,''))='pass' THEN 0 ELSE 1 END,
          COALESCE(score, -9999) DESC,
          CASE WHEN COALESCE(rank,'')='' THEN 9999 ELSE CAST(rank AS INTEGER) END,
          side
        LIMIT 5
        """,
        (target_date, ticker),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_artifact_context(conn: sqlite3.Connection, target_date: str) -> dict[str, Any]:
    if not table_exists(conn, "collection_artifacts"):
        return {}
    out: dict[str, Any] = {}
    for key in ("signal_pipeline_kpi", "scenario_promotion_ai_review", "us_market_overview"):
        row = conn.execute(
            """
            SELECT payload_json
            FROM collection_artifacts
            WHERE artifact_key=? AND artifact_date=?
            """,
            (key, target_date),
        ).fetchone()
        if not row or not row[0]:
            continue
        try:
            out[key] = json.loads(str(row[0]))
        except json.JSONDecodeError:
            out[key] = {"raw": str(row[0])}
    return out


def format_us_market_overview_lines(overview: dict[str, Any]) -> list[str]:
    if not overview:
        return []
    summary = str(overview.get("summary") or "").strip()
    sector = str(overview.get("sectorImpact") or "").strip()
    lines: list[str] = []
    if summary:
        lines.append(f"- 米市場概況: {summary}")
    if sector:
        lines.append(f"- 日本セクター影響: {sector}")
    return lines


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get((category or "").strip(), (category or "未分類"))


def pick_disclosure_type(categories: list[str]) -> tuple[str, str]:
    valid = [c for c in categories if c]
    if not valid:
        return "", "未分類"
    counts = Counter(valid)
    category = counts.most_common(1)[0][0]
    labels = sorted({category_label(c) for c in valid})
    if len(labels) == 1:
        return category, labels[0]
    return category, f"{labels[0]}ほか{len(labels) - 1}"


def signal_bias(categories: list[str], signals: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> str:
    expected = " ".join(str(s.get("expected_direction") or "") for s in signals).lower()
    candidate_expected = " ".join(str(c.get("expected_direction") or "") for c in candidates).lower()
    has_pass = any(str(s.get("gate_status") or "").lower() == "pass" for s in signals)
    has_pass = has_pass or any(str(c.get("gate_status") or "").lower() == "pass" for c in candidates)
    positive = any(c in POSITIVE_CATEGORIES for c in categories)
    negative = any(c in NEGATIVE_CATEGORIES for c in categories)
    if positive and negative:
        return "強弱材料が混在"
    if positive:
        return "強気寄り" if ("up" in expected or "up" in candidate_expected or has_pass) else "好材料だがシグナル確認待ち"
    if negative:
        return "警戒寄り" if ("down" in expected or "down" in candidate_expected or has_pass) else "悪材料だがシグナル確認待ち"
    if signals or candidates:
        return "シグナル要確認"
    return "材料のみ"


def format_pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:+.1f}%"


def calc_return_pct(newer: float | None, older: float | None) -> float | None:
    if newer in (None, "") or older in (None, "", 0):
        return None
    return (float(newer) / float(older) - 1.0) * 100.0


def fetch_latest_price_context(conn: sqlite3.Connection, target_date: str, ticker: str) -> dict[str, Any]:
    if not table_exists(conn, "facts_price_daily"):
        return {}
    latest = conn.execute(
        """
        SELECT date,open,high,low,close
        FROM facts_price_daily
        WHERE ticker=? AND date<=?
        ORDER BY date DESC
        LIMIT 1
        """,
        (ticker, target_date),
    ).fetchone()
    if not latest:
        return {}
    latest_dict = dict(latest)
    prev = conn.execute(
        """
        SELECT date,close
        FROM facts_price_daily
        WHERE ticker=? AND date<?
        ORDER BY date DESC
        LIMIT 1
        """,
        (ticker, latest_dict["date"]),
    ).fetchone()
    prev_dict = dict(prev) if prev else {}
    latest_dict["prev_close"] = prev_dict.get("close")
    latest_dict["prev_date"] = prev_dict.get("date")
    latest_dict["return_pct"] = calc_return_pct(latest_dict.get("close"), latest_dict.get("prev_close"))
    latest_dict["price_kind"] = "facts_price_daily_latest_close"
    return latest_dict


def fetch_signal_price_snapshot(conn: sqlite3.Connection, target_date: str, ticker: str) -> dict[str, Any]:
    if not table_exists(conn, "market_signal_snapshots"):
        return {}
    preferred_slots = ("inv-evening-preclose", "inv-morning-preclose")
    placeholders = ",".join("?" for _ in preferred_slots)
    row = conn.execute(
        f"""
        SELECT date,ticker,slot,snapshot_time,price,return_pct,source_kind,source_ref,payload_json
        FROM market_signal_snapshots
        WHERE date=? AND ticker=? AND slot IN ({placeholders})
        ORDER BY
          CASE slot
            WHEN ? THEN 0
            WHEN ? THEN 1
            ELSE 2
          END,
          snapshot_time DESC
        LIMIT 1
        """,
        (target_date, ticker, *preferred_slots, *preferred_slots),
    ).fetchone()
    if not row:
        return {}
    snapshot = dict(row)
    payload: dict[str, Any] = {}
    if snapshot.get("payload_json"):
        try:
            payload = json.loads(str(snapshot["payload_json"]))
        except json.JSONDecodeError:
            payload = {}
    source_date = str(payload.get("source_date") or "")
    prev_close_date = str(payload.get("prev_close_date") or "")
    snapshot.update(
        {
            "source_date": source_date,
            "prev_date": prev_close_date,
            "price_kind": "signal_snapshot",
            "close": snapshot.get("price"),
            "prev_close": None,
            "return_pct": snapshot.get("return_pct"),
            "snapshot_payload": payload,
        }
    )
    return snapshot


def fetch_future_close(conn: sqlite3.Connection, ticker: str, base_date: str, offset_days: int) -> float | None:
    if not table_exists(conn, "facts_price_daily"):
        return None
    row = conn.execute(
        """
        SELECT close
        FROM facts_price_daily
        WHERE ticker=? AND date>?
        ORDER BY date ASC
        LIMIT 1 OFFSET ?
        """,
        (ticker, base_date, max(0, offset_days - 1)),
    ).fetchone()
    return float(row[0]) if row and row[0] not in (None, "") else None


def fetch_past_price_reaction(
    conn: sqlite3.Connection,
    target_date: str,
    ticker: str,
    categories: list[str],
    lookback_days: int,
) -> dict[str, Any]:
    if not table_exists(conn, "tdnet_disclosures") or not table_exists(conn, "facts_price_daily"):
        return {}
    if not categories:
        return {}
    category_placeholders = ",".join("?" for _ in categories)
    start = (date.fromisoformat(target_date) - date.resolution * max(1, lookback_days)).isoformat()
    rows = conn.execute(
        f"""
        SELECT DISTINCT date
        FROM tdnet_disclosures
        WHERE ticker=? AND date>=? AND date<? AND category IN ({category_placeholders})
        ORDER BY date DESC
        LIMIT 5
        """,
        (ticker, start, target_date, *categories),
    ).fetchall()
    recent_events: list[dict[str, Any]] = []
    t1_values: list[float] = []
    t5_values: list[float] = []
    for row in rows:
        event_date = str(row[0])
        event_close_row = conn.execute(
            "SELECT close FROM facts_price_daily WHERE ticker=? AND date=?",
            (ticker, event_date),
        ).fetchone()
        if not event_close_row or event_close_row[0] in (None, ""):
            continue
        event_close = float(event_close_row[0])
        t1_close = fetch_future_close(conn, ticker, event_date, 1)
        t5_close = fetch_future_close(conn, ticker, event_date, 5)
        t1_return = calc_return_pct(t1_close, event_close)
        t5_return = calc_return_pct(t5_close, event_close)
        if t1_return is not None:
            t1_values.append(t1_return)
        if t5_return is not None:
            t5_values.append(t5_return)
        if len(recent_events) < 3:
            recent_events.append(
                {
                    "date": event_date,
                    "t1_pct": t1_return,
                    "t5_pct": t5_return,
                }
            )
    sample_count = max(len(t1_values), len(t5_values))
    if sample_count == 0:
        return {}
    return {
        "sample_count": sample_count,
        "avg_t1_pct": sum(t1_values) / len(t1_values) if t1_values else None,
        "avg_t5_pct": sum(t5_values) / len(t5_values) if t5_values else None,
        "recent_events": recent_events,
    }


def build_price_note(
    latest_price: dict[str, Any],
    past_reaction: dict[str, Any],
    target_date: str,
) -> str:
    bits: list[str] = []
    if latest_price:
        close = latest_price.get("close")
        high = latest_price.get("high")
        low = latest_price.get("low")
        price_date = str(latest_price.get("date") or "")
        source_date = str(latest_price.get("source_date") or price_date)
        change = format_pct(latest_price.get("return_pct"))
        if str(latest_price.get("price_kind") or "") == "signal_snapshot":
            text = f"前営業日終値 {source_date} {float(close):.2f}" if close not in (None, "") else f"前営業日価格 {source_date}"
            if change:
                text += f"（前営業日比 {change}）"
            bits.append(text)
        elif price_date == target_date:
            text = f"当日終値 {close:.2f}" if close not in (None, "") else f"当日価格 {price_date}"
            if change:
                text += f"（前営業日比 {change}）"
            if high not in (None, "") and low not in (None, ""):
                text += f" / 高安 {float(low):.2f}-{float(high):.2f}"
            bits.append(text)
        else:
            text = f"直近終値 {price_date} {float(close):.2f}" if close not in (None, "") else f"直近価格 {price_date}"
            if change:
                text += f"（前営業日比 {change}）"
            text += " / 当日価格データ待ち"
            bits.append(text)
    else:
        bits.append("価格データなし")
    if past_reaction:
        sample = int(past_reaction.get("sample_count") or 0)
        t1 = format_pct(past_reaction.get("avg_t1_pct"))
        t5 = format_pct(past_reaction.get("avg_t5_pct"))
        reaction_text = f"同種開示の過去{sample}回"
        if t1:
            reaction_text += f"で翌営業日平均 {t1}"
        if t5:
            reaction_text += f" / 5営業日平均 {t5}"
        bits.append(reaction_text)
        recent_events = past_reaction.get("recent_events") or []
        recent_bits = []
        for ev in recent_events[:2]:
            date_s = str(ev.get("date") or "")
            t1_s = format_pct(ev.get("t1_pct")) or "n/a"
            t5_s = format_pct(ev.get("t5_pct")) or "n/a"
            if date_s:
                recent_bits.append(f"{date_s} T+1 {t1_s} / T+5 {t5_s}")
        if recent_bits:
            bits.append("直近事例: " + " ; ".join(recent_bits))
    return " / ".join(bits)


def build_signal_note(signals: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> str:
    if not signals and not candidates:
        return "シグナル参照なし"
    pass_count = sum(1 for s in signals if str(s.get("gate_status") or "").lower() == "pass")
    candidate_pass_count = sum(1 for c in candidates if str(c.get("gate_status") or "").lower() == "pass")
    parts: list[str] = []
    if signals:
        parts.append(f"signals {len(signals)}件")
    if candidates:
        parts.append(f"candidates {len(candidates)}件")
    total_pass = pass_count + candidate_pass_count
    if total_pass:
        parts.append(f"pass {total_pass}件")
    if not parts:
        return "シグナル参照あり"
    return " / ".join(parts)


def build_summary(disclosures: list[dict[str, Any]], disclosure_type_label: str) -> str:
    count = len(disclosures)
    titles = [str(d.get("title") or "").strip() for d in disclosures if str(d.get("title") or "").strip()]
    lead_titles = " / ".join(titles[:3]) if titles else "個別タイトル未取得"
    if count == 1:
        return f"同銘柄で1件の開示。分類は{disclosure_type_label}。"
    return f"同銘柄で{count}件の開示。分類は{disclosure_type_label}。主な内訳は {lead_titles}。"


def group_disclosures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip() or "code不明"
        if ticker not in grouped:
            order.append(ticker)
            grouped[ticker] = {
                "code": ticker,
                "company": str(row.get("company") or "").strip() or "会社名不明",
                "disclosures": [],
            }
        grouped[ticker]["disclosures"].append(
            {
                "title": str(row.get("title") or "").strip(),
                "category": str(row.get("category") or "").strip(),
                "category_label": category_label(str(row.get("category") or "").strip()),
                "published_at": str(row.get("disclosed_at") or row.get("date") or ""),
                "source_url": str(row.get("tdnet_url") or ""),
                "source_kind": str(row.get("source_kind") or ""),
                "source_path": str(row.get("source_path") or ""),
            }
        )
    return [grouped[ticker] for ticker in order]


def build_item(conn: sqlite3.Connection, target_date: str, lookback_days: int, group: dict[str, Any]) -> dict[str, Any]:
    disclosures = list(group["disclosures"])
    categories = [str(d.get("category") or "") for d in disclosures if str(d.get("category") or "")]
    primary_category, disclosure_type_label = pick_disclosure_type(categories)
    ticker = str(group["code"])
    signals = fetch_signal_context(conn, target_date, ticker)
    candidates = fetch_entry_candidate_context(conn, target_date, ticker)
    latest_price = fetch_signal_price_snapshot(conn, target_date, ticker) or fetch_latest_price_context(conn, target_date, ticker)
    past_reaction = fetch_past_price_reaction(conn, target_date, ticker, sorted(set(categories)), lookback_days)
    item = {
        "code": ticker,
        "company": str(group["company"]),
        "disclosure_type": primary_category,
        "disclosure_type_label": disclosure_type_label,
        "published_at": max((str(d.get("published_at") or "") for d in disclosures), default=""),
        "summary": build_summary(disclosures, disclosure_type_label),
        "price_note": build_price_note(latest_price, past_reaction, target_date),
        "signal_note": build_signal_note(signals, candidates),
        "signal_bias": signal_bias(categories, signals, candidates),
        "signals": signals,
        "entry_candidates": candidates,
        "disclosures": disclosures,
        "latest_price": latest_price,
        "past_reaction": past_reaction,
    }
    return item


def build_payload(conn: sqlite3.Connection, target_date: str, lookback_days: int, limit: int) -> dict[str, Any]:
    disclosures = fetch_disclosures(conn, target_date, limit)
    groups = group_disclosures(disclosures)
    items = [build_item(conn, target_date, lookback_days, group) for group in groups]
    counts = Counter()
    for item in items:
        counts[str(item.get("disclosure_type_label") or "未分類")] += len(item.get("disclosures") or [])
    signal_bias_counts = Counter(str(item.get("signal_bias") or "材料のみ") for item in items)
    signal_items = [item for item in items if item.get("signals") or item.get("entry_candidates")]
    aligned_items = [item for item in items if str(item.get("signal_bias") or "") not in {"材料のみ", "シグナル要確認"}]
    artifacts = fetch_artifact_context(conn, target_date)
    return {
        "date": target_date,
        "lookback_days": int(lookback_days),
        "limit": int(limit),
        "items": items,
        "raw_disclosure_count": len(disclosures),
        "counts": dict(counts.most_common()),
        "signal_bias_counts": dict(signal_bias_counts.most_common()),
        "signal_items": signal_items,
        "aligned_items": aligned_items,
        "artifacts": artifacts,
        "source": {
            "db": str(conn.execute("PRAGMA database_list").fetchone()[2] or ""),
            "window": f"{target_date} (lookback={lookback_days})",
        },
    }


def overview_lines(payload: dict[str, Any]) -> list[str]:
    items = payload.get("items") or []
    counts = payload.get("counts") or {}
    lines: list[str] = []
    if counts:
        count_text = "、".join(f"{k}:{v}" for k, v in counts.items()) or "未分類のみ"
        lines.append(f"開示件数ベースでは {count_text} が中心。")
    if items:
        lines.append(
            f"対象は {len(items)} 銘柄 / {int(payload.get('raw_disclosure_count') or 0)} 件。銘柄単位で開示をまとめ、価格反応を優先して確認。"
        )
    else:
        lines.append("対象開示が見つからなかったため、空の下書きを生成。")
    return lines


def render_disclosure_lines(item: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for disclosure in item.get("disclosures") or []:
        title = str(disclosure.get("title") or "").strip() or "タイトル未取得"
        url = str(disclosure.get("source_url") or "").strip()
        if url:
            lines.append(f"  - {title} ({url})")
        else:
            lines.append(f"  - {title}")
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    title = f"適時開示ダイジェスト {payload['date']}"
    parts = [f"# {title}", "", f"対象: 前営業日後から {payload['date']} 朝までの確認用", "", "## 今日の主要開示", ""]
    items = payload.get("items") or []
    if not items:
        parts.extend(["- 対象開示が見つかりませんでした。", ""])
        for item in items:
            parts.extend(
                [
                    f"### {item['company']} ({item['code']}) | {item['disclosure_type_label']}",
                    f"- 要約: {item['summary']}",
                    f"- 価格反応: {item['price_note']}",
                    f"- シグナル接続: {item['signal_note']}",
                    f"- シグナル: {item['signal_bias']}",
                    "- 開示一覧:",
                    *render_disclosure_lines(item),
                    "",
                ]
        )
    parts.extend(["## 全体メモ", ""])
    for line in overview_lines(payload):
        parts.append(f"- {line}")
    parts.extend(["", "## 注意", "", "本稿は公開情報の整理であり、売買推奨ではありません。", ""])
    return "\n".join(parts)


def render_note_markdown(payload: dict[str, Any]) -> str:
    title = f"適時開示ダイジェスト {payload['date']}"
    overview = (((payload.get("artifacts") or {}).get("us_market_overview")) or {})
    parts = [
        title,
        "",
        f"対象: 前営業日後から {payload['date']} 朝までの確認用",
        "",
        "前営業日の引け後から当日朝までの適時開示を、銘柄ごとにまとめて整理しました。",
        "",
    ]
    us_lines = format_us_market_overview_lines(overview if isinstance(overview, dict) else {})
    if us_lines:
        parts.extend(["## 朝の地合い", "", *us_lines, ""])
    parts.extend([
        "## 今日の主要開示",
        "",
    ])
    items = payload.get("items") or []
    if not items:
        parts.extend(["- 対象開示が見つかりませんでした。", ""])
    for item in items:
        parts.extend(
            [
                f"### {item['company']} ({item['code']}) | {item['disclosure_type_label']}",
                f"- 要約: {item['summary']}",
                f"- 価格反応: {item['price_note']}",
                "- 開示一覧:",
                *render_disclosure_lines(item),
                "",
            ]
        )
    parts.extend(["## 全体メモ", ""])
    for line in overview_lines(payload):
        parts.append(f"- {line}")
    parts.extend(["", "## 注意", "", "本稿は公開情報の整理であり、売買推奨ではありません。", ""])
    return "\n".join(parts)


def write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def save_artifacts(
    conn: sqlite3.Connection,
    target_date: str,
    payload: dict[str, Any],
    article_path: Path,
    article_text: str,
    note_path: Path,
    note_text: str,
) -> None:
    if table_exists(conn, "collection_artifacts"):
        conn.execute(
            """
            INSERT INTO collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at)
            VALUES(?,?,?,?,datetime('now'))
            ON CONFLICT(artifact_key,artifact_date) DO UPDATE SET
              artifact_type=excluded.artifact_type,
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (
                "disclosure_digest",
                target_date,
                "daily_digest",
                json.dumps(
                    {
                        "payload": payload,
                        "article_markdown": article_text,
                        "note_markdown": note_text,
                        "article_path": display_path(article_path),
                        "note_path": display_path(note_path),
                    },
                    ensure_ascii=False,
                ),
            ),
        )
    if table_exists(conn, "daily_digest"):
        conn.execute(
            """
            INSERT INTO daily_digest(topic,date,path,summary,updated_at)
            VALUES(?,?,?,?,datetime('now'))
            ON CONFLICT(topic,date) DO UPDATE SET
              path=excluded.path,
              summary=excluded.summary,
              updated_at=excluded.updated_at
            """,
            ("disclosure-digest-article", target_date, display_path(article_path), article_text),
        )
        conn.execute(
            """
            INSERT INTO daily_digest(topic,date,path,summary,updated_at)
            VALUES(?,?,?,?,datetime('now'))
            ON CONFLICT(topic,date) DO UPDATE SET
              path=excluded.path,
              summary=excluded.summary,
              updated_at=excluded.updated_at
            """,
            ("disclosure-digest-note", target_date, display_path(note_path), note_text),
        )


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    if args.db.suffix and not args.db.parent.exists():
        args.db.parent.mkdir(parents=True, exist_ok=True)
    article_path = args.output_dir / f"{args.date}-daily-disclosure-digest.md"
    note_path = args.output_dir / f"{args.date}-note-ready.md"
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        ensure_storage_schema(conn)
        payload = build_payload(conn, args.date, args.lookback_days, args.limit)
        article_text = render_markdown(payload)
        note_text = render_note_markdown(payload)
        write_text_file(article_path, article_text)
        write_text_file(note_path, note_text)
        save_artifacts(conn, args.date, payload, article_path, article_text, note_path, note_text)
        conn.commit()
    finally:
        conn.close()
    print(f"saved: {display_path(article_path)} {display_path(note_path)} disclosure_digest {args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
