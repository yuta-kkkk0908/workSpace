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

INBOX = ROOT / "topics" / "investment-research" / "inbox"
OUT_DIR = ROOT / "prompts"
DEFAULT_DB = resolve_investment_db()

SECTION_RE = re.compile(r"^###\s+(paper_history|watch|live|paper|all)\s*$")
SAMPLE_RE = re.compile(r"^- sampleTrades:\s*(\d+)\s*$")
T5_RE = re.compile(r"^- T\+5:\s*n=(\d+)\s+winRate=([0-9.]+)%\s+avgRet=([\-0-9.]+)%")
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
        m = T5_RE.match(line)
        if m:
            rows[cur]["t5_n"] = m.group(1)
            rows[cur]["t5_wr"] = m.group(2)
            rows[cur]["t5_ret"] = m.group(3)
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
    try:
        out: dict[str, dict[str, str]] = {}
        for mode in ("paper_history", "watch", "live", "paper"):
            mode_sql = "mode=?"
            mode_params = (mode,)
            row = conn.execute(
                """
                SELECT
                  COUNT(*) AS sample,
                  SUM(CASE WHEN t5_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS t5_n,
                  AVG(t5_return_pct) AS t5_avg,
                  AVG(CASE WHEN t5_return_pct > 0 THEN 1.0 ELSE 0.0 END) AS t5_wr
                FROM paper_trades
                WHERE {mode_sql} AND entry_date<=?
                """.format(mode_sql=mode_sql),
                (*mode_params, date_str),
            ).fetchone()
            if not row:
                continue
            sample = int(row[0] or 0)
            t5_n = int(row[1] or 0)
            t5_avg = float(row[2] or 0.0)
            t5_wr = float(row[3] or 0.0) * 100.0 if t5_n > 0 else 0.0
            out[mode] = {
                "sample": str(sample),
                "t5_n": str(t5_n),
                "t5_wr": f"{t5_wr:.1f}",
                "t5_ret": f"{t5_avg:.2f}",
            }
        row_all = conn.execute(
            """
            SELECT
              COUNT(*) AS sample,
              SUM(CASE WHEN t5_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS t5_n,
              AVG(t5_return_pct) AS t5_avg,
              AVG(CASE WHEN t5_return_pct > 0 THEN 1.0 ELSE 0.0 END) AS t5_wr
            FROM paper_trades
            WHERE entry_date<=?
            """,
            (date_str,),
        ).fetchone()
        if row_all:
            sample = int(row_all[0] or 0)
            t5_n = int(row_all[1] or 0)
            t5_avg = float(row_all[2] or 0.0)
            t5_wr = float(row_all[3] or 0.0) * 100.0 if t5_n > 0 else 0.0
            out["all"] = {
                "sample": str(sample),
                "t5_n": str(t5_n),
                "t5_wr": f"{t5_wr:.1f}",
                "t5_ret": f"{t5_avg:.2f}",
            }
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
    t5n = row.get("t5_n", "0")
    t5wr = row.get("t5_wr", "0.0")
    t5ret = row.get("t5_ret", "0.00")
    display_mode = {
        "live": "trade実績(live)",
        "watch": "watch",
        "paper": "paper",
        "paper_history": "paper_history",
    }.get(mode, mode)
    return f"- {display_mode}: サンプル={sample} / T+5 n={t5n} 勝率={t5wr}% 平均={t5ret}%"


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
    lines.append("【モード比較（T+5中心）】")
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
