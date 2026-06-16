#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db
from utils.paper_trade_mode import normalize_paper_trade_mode
from utils.terminology import glossary_line
from investment.analysis.exit_horizon_utils import avg, collect_price_path_returns, win_rate

INBOX = ROOT / "topics" / "investment-research" / "inbox"
OUT_DIR = ROOT / "prompts"
DEFAULT_DB = resolve_investment_db()

SECTION_RE = re.compile(r"^###\s+(paper_history|watch|live|paper|all)\s*$")
SAMPLE_RE = re.compile(r"^- sampleTrades:\s*(\d+)\s*$")
HORIZON_RE = re.compile(r"^- T\+(\d+)(?:\(ref\))?:\s*n=(\d+)\s+winRate=([0-9.]+)%\s+avgRet=([\-0-9.]+)%")
SIDE_RE = re.compile(r"^- (long|short):\s*n=(\d+)\s+winRate=([0-9.]+)%\s+avgRet=([\-0-9.]+)%")
RANK_RE = re.compile(r"^- ([A-Z0-9+\-]+|UNKNOWN):\s*n=(\d+)\s+winRate=([0-9.]+)%\s+avgRet=([\-0-9.]+)%")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render paper-stats into Discord-ready message")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def find_stats_file(date_str: str, fallback_days: int) -> tuple[Path, str]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-paper-trade-stats.md"
        if p.exists():
            return p, d
    raise SystemExit(f"paper-trade-stats not found for {date_str} (fallback_days={fallback_days})")


def find_weekly_review_file(date_str: str, fallback_days: int) -> tuple[Path | None, str | None]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-weekly-trade-watch-review.md"
        if p.exists():
            return p, d
    return None, None


def find_weekly_ai_review_file(date_str: str, fallback_days: int) -> tuple[Path | None, str | None]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-weekly-tuning-ai-review.md"
        if p.exists():
            return p, d
    return None, None


def load_weekly_ai_review_lines(review_path: Path | None) -> list[str]:
    if not review_path or not review_path.exists():
        return []
    try:
        review = review_path.read_text(encoding="utf-8")
    except Exception:
        return []
    lines = [ln.rstrip() for ln in review.splitlines() if ln.strip()]
    return lines[:8]


def parse_stats(text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    cur = ""
    for raw in text.splitlines():
        line = raw.strip()
        sec = SECTION_RE.match(line)
        if sec:
            cur = sec.group(1)
            rows.setdefault(cur, {})
            continue
        if not cur:
            continue
        m = SAMPLE_RE.match(line)
        if m:
            rows[cur]["sample"] = m.group(1)
            continue
        m = HORIZON_RE.match(line)
        if m:
            horizon = m.group(1)
            rows[cur][f"t{horizon}_n"] = m.group(2)
            rows[cur][f"t{horizon}_wr"] = m.group(3)
            rows[cur][f"t{horizon}_ret"] = m.group(4)
            continue
        m = SIDE_RE.match(line)
        if m:
            side = m.group(1)
            rows[cur][f"{side}_n"] = m.group(2)
            rows[cur][f"{side}_wr"] = m.group(3)
            rows[cur][f"{side}_ret"] = m.group(4)
            continue
        m = RANK_RE.match(line)
        if m:
            rk = m.group(1)
            rows[cur][f"rank_{rk}_n"] = m.group(2)
            rows[cur][f"rank_{rk}_wr"] = m.group(3)
            rows[cur][f"rank_{rk}_ret"] = m.group(4)
    return rows


def load_stats_from_db(db_path: Path, date_str: str) -> dict[str, dict[str, str]]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        out: dict[str, dict[str, str]] = {}
        rows = conn.execute(
            """
            SELECT mode, side, t1_return_pct, t5_return_pct, t20_return_pct, price_path_json
            FROM paper_trades
            WHERE entry_date<=?
            """,
            (date_str,),
        ).fetchall()

        def build_summary(target_rows: list[sqlite3.Row]) -> dict[str, str]:
            sample = len(target_rows)
            t1 = [float(r["t1_return_pct"]) for r in target_rows if r["t1_return_pct"] is not None]
            t3 = collect_price_path_returns(target_rows, offset=3)
            t5 = [float(r["t5_return_pct"]) for r in target_rows if r["t5_return_pct"] is not None]
            t10 = collect_price_path_returns(target_rows, offset=10)
            t20 = [float(r["t20_return_pct"]) for r in target_rows if r["t20_return_pct"] is not None]
            out_row = {
                "sample": str(sample),
                "t1_n": str(len(t1)),
                "t1_wr": f"{win_rate(t1):.1f}",
                "t1_ret": f"{avg(t1):.2f}",
                "t3_n": str(len(t3)),
                "t3_wr": f"{win_rate(t3):.1f}",
                "t3_ret": f"{avg(t3):.2f}",
                "t5_n": str(len(t5)),
                "t5_wr": f"{win_rate(t5):.1f}",
                "t5_ret": f"{avg(t5):.2f}",
                "t10_n": str(len(t10)),
                "t10_wr": f"{win_rate(t10):.1f}",
                "t10_ret": f"{avg(t10):.2f}",
                "t20_n": str(len(t20)),
                "t20_wr": f"{win_rate(t20):.1f}",
                "t20_ret": f"{avg(t20):.2f}",
            }
            return out_row

        for mode in ("paper_history", "watch", "live", "paper"):
            subset = [r for r in rows if normalize_paper_trade_mode(r["mode"]) == mode]
            out[mode] = build_summary(subset)
        out["all"] = build_summary(rows)
        return out
    finally:
        conn.close()


def parse_next_actions(text: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "## Next Week Actions (Auto)":
            start = i + 1
            break
    if start is None:
        return []
    out: list[str] = []
    for line in lines[start:]:
        s = line.strip()
        if s.startswith("## "):
            break
        if s.startswith("- "):
            out.append(s[2:].strip())
        if len(out) >= 3:
            break
    return out


def parse_ops_throughput(text: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "## Scenario Ops Throughput":
            start = i + 1
            break
    if start is None:
        return []
    out: list[str] = []
    for line in lines[start:]:
        s = line.strip()
        if s.startswith("## "):
            break
        if s.startswith("- "):
            out.append(s[2:].strip())
    return out


def to_line(mode: str, row: dict[str, str]) -> str:
    sample = row.get("sample", "0")
    t3n = row.get("t3_n", "0")
    t3wr = row.get("t3_wr", "0.0")
    t3ret = row.get("t3_ret", "0.00")
    t5n = row.get("t5_n", "0")
    t5wr = row.get("t5_wr", "0.0")
    t5ret = row.get("t5_ret", "0.00")
    t10n = row.get("t10_n", "0")
    t10wr = row.get("t10_wr", "0.0")
    t10ret = row.get("t10_ret", "0.00")
    display_mode = {
        "live": "trade実績(live)",
        "watch": "watch",
        "paper": "paper",
        "paper_history": "paper_history",
    }.get(mode, mode)
    return (
        f"- {display_mode}: サンプル={sample} / "
        f"T+5 n={t5n} 勝率={t5wr}% 平均={t5ret}% / "
        f"参考 T+3 n={t3n} 勝率={t3wr}% 平均={t3ret}% / "
        f"T+10 n={t10n} 勝率={t10wr}% 平均={t10ret}%"
    )


def build_message(
    target_date: str,
    source_date: str,
    rows: dict[str, dict[str, str]],
    actions: list[str],
    action_source_date: str | None,
    ops_lines: list[str],
    ai_review_lines: list[str],
    ai_review_source_date: str | None,
) -> str:
    def rank_lines(row: dict[str, str], max_lines: int = 2) -> list[str]:
        items: list[tuple[str, int, float, float]] = []
        for k, v in row.items():
            if not k.startswith("rank_") or not k.endswith("_n"):
                continue
            rk = k[len("rank_") : -len("_n")]
            try:
                n = int(v)
                wr = float(row.get(f"rank_{rk}_wr", "0"))
                avg = float(row.get(f"rank_{rk}_ret", "0"))
            except ValueError:
                continue
            if n <= 0:
                continue
            items.append((rk, n, wr, avg))
        items.sort(key=lambda x: (-x[1], -x[2], -x[3], x[0]))
        out: list[str] = []
        for rk, n, wr, avg in items[:max_lines]:
            out.append(f"- rank {rk}: n={n} 勝率={wr:.1f}% 平均={avg:.2f}%")
        return out

    lines = [
        f"トレード統計 {target_date}",
        f"- 参照日: {source_date}",
        "",
    ]
    if source_date != target_date:
        lines.insert(2, f"- 注意: 当日未生成のため {source_date} を参照")
    lines.append("【モード比較（T+5中心、T+3/T+10は参考）】")
    for mode in ("paper_history", "watch", "live", "paper"):
        lines.append(to_line(mode, rows.get(mode, {})))
    lines.append("")
    lines.append("【補足】")
    all_row = rows.get("all", {})
    if all_row:
        lines.append(to_line("all", all_row))
        rank_top = rank_lines(all_row, max_lines=2)
        if rank_top:
            lines.extend(rank_top)
    lines.append("- caution: 仮想検証データ。売買助言ではありません。")
    lines.append(f"- {glossary_line()}")
    if ops_lines:
        lines.append("")
        lines.append("【運用実績（シナリオ）】")
        # Keep Discord payload small; show up to 2 lines.
        for x in ops_lines[:2]:
            lines.append(f"- {x}")
    if actions:
        lines.append("")
        lines.append("【次週アクション（ルールベース）】")
        if action_source_date and action_source_date != target_date:
            lines.append(f"- 注意: 参照レビュー日={action_source_date}")
        for a in actions[:3]:
            lines.append(f"- {a}")
    if ai_review_lines:
        lines.append("")
        lines.append("【AIレビュー】")
        if ai_review_source_date and ai_review_source_date != target_date:
            lines.append(f"- 注意: 参照レビュー日={ai_review_source_date}")
        for a in ai_review_lines[:8]:
            lines.append(f"- {a}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    rows = load_stats_from_db(args.db, args.date)
    src_date = args.date
    if not rows or int((rows.get("all", {}) or {}).get("sample", "0")) == 0:
        src, src_date = find_stats_file(args.date, args.fallback_days)
        rows = parse_stats(src.read_text(encoding="utf-8"))
    review_path, review_date = find_weekly_review_file(args.date, args.fallback_days)
    actions: list[str] = []
    ops_lines: list[str] = []
    ai_review_lines: list[str] = []
    ai_review_source_date: str | None = None
    if review_path:
        review_text = review_path.read_text(encoding="utf-8")
        actions = parse_next_actions(review_text)
        ops_lines = parse_ops_throughput(review_text)
    ai_review_path, ai_review_source_date = find_weekly_ai_review_file(args.date, args.fallback_days)
    ai_review_lines = load_weekly_ai_review_lines(ai_review_path)
    msg = build_message(args.date, src_date, rows, actions, review_date, ops_lines, ai_review_lines, ai_review_source_date)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_txt = OUT_DIR / "paper-stats-discord-message.txt"
    out_md = OUT_DIR / "paper-stats-discord-message.md"
    out_txt.write_text(msg, encoding="utf-8")
    out_md.write_text("```text\n" + msg + "```\n", encoding="utf-8")
    print(f"wrote {_display_path(out_txt)}")
    print(f"wrote {_display_path(out_md)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
