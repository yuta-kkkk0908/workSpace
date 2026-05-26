#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def run(cmd: list[str], allow_fail: bool = False) -> int:
    print("[run]", " ".join(cmd))
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0 and allow_fail:
        print(f"[warn] command failed but continuing (allow_fail): rc={rc}")
        return 0
    return rc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Automated harvest/backfill runner for investment datasets")
    p.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--days", type=int, default=30, help="number of days to process (inclusive end-date)")
    p.add_argument("--discover-latest", type=int, default=60)
    p.add_argument("--max-pages", type=int, default=80)
    p.add_argument("--tdnet-max-items", type=int, default=500)
    p.add_argument("--seed-list", default="rough_backtest_full")
    p.add_argument("--max-signals", type=int, default=12)
    p.add_argument("--max-long", type=int, default=6)
    p.add_argument("--max-short", type=int, default=6)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--min-outcomes-target", type=int, default=500, help="if reached, reduce Kabutan crawl depth")
    p.add_argument("--min-new-rate", type=float, default=0.02, help="early-stop threshold for new_rows/scanned_rows")
    p.add_argument("--low-rate-streak-stop", type=int, default=3, help="stop after this many consecutive low-rate days")
    p.add_argument("--jpx-max-links", type=int, default=300)
    p.add_argument("--jpx-process-max-files", type=int, default=20)
    p.add_argument("--price-max-tickers", type=int, default=60)
    p.add_argument("--price-target-bars", type=int, default=200, choices=[200, 500])
    p.add_argument("--signal-coverage-window-days", type=int, default=30)
    p.add_argument("--material-min-count-per-type", type=int, default=20)
    p.add_argument(
        "--material-shortage-ratio",
        type=float,
        default=0.95,
        help="shortage判定に使う比率。count < min_count * ratio のとき不足扱い",
    )
    return p.parse_args()


def fetch_day_metrics(db_path: Path, date_str: str) -> tuple[int, int]:
    if not db_path.exists():
        return (0, 0)
    conn = sqlite3.connect(db_path)
    try:
        tdnet = int(conn.execute("SELECT COUNT(*) FROM tdnet_disclosures WHERE date=?", (date_str,)).fetchone()[0] or 0)
        outcomes = int(conn.execute("SELECT COUNT(*) FROM backtest_outcomes WHERE date=?", (date_str,)).fetchone()[0] or 0)
        return (tdnet, outcomes)
    finally:
        conn.close()


def fetch_progress_metrics(db_path: Path, date_str: str, target_bars: int) -> tuple[int, int, int]:
    if not db_path.exists():
        return (0, 0, 0)
    conn = sqlite3.connect(db_path)
    try:
        jpx_today = int(
            conn.execute(
                "SELECT COUNT(*) FROM raw_events WHERE source_kind='jpx_daily' AND ingest_date=?",
                (date_str,),
            ).fetchone()[0]
            or 0
        )
        row = conn.execute(
            """
            SELECT
              SUM(CASE WHEN bars_collected>=? THEN 1 ELSE 0 END),
              COUNT(*)
            FROM collection_progress
            WHERE source='price_backfill_yahoo'
            """,
            (target_bars,),
        ).fetchone()
        ready = int((row[0] if row and row[0] is not None else 0) or 0)
        total = int((row[1] if row and row[1] is not None else 0) or 0)
        return (jpx_today, ready, total)
    finally:
        conn.close()


def fetch_material_signal_coverage(
    db_path: Path, window_days: int, min_count_per_type: int, shortage_ratio: float = 0.95
) -> tuple[dict[str, int], list[str]]:
    """
    Return recent counts for material-oriented signal types and shortage list.
    """
    targets = [
        "upward_revision_highest_profit",
        "highest_profit_guidance_dividend_revision",
        "downward_revision_to_loss",
        "downward_revision_dividend_cut",
        "weak_earnings_or_guidance",
        "offering_or_dilution",
    ]
    if not db_path.exists():
        return ({t: 0 for t in targets}, list(targets))
    shortage_threshold = max(1, int(round(max(0.1, min(shortage_ratio, 1.0)) * max(1, min_count_per_type))))
    conn = sqlite3.connect(db_path)
    try:
        rows_cov = conn.execute(
            """
            SELECT signal_type, signal_count, is_shortage
            FROM signal_type_coverage_rows
            WHERE date=(SELECT MAX(date) FROM signal_type_coverage_rows)
              AND window_days=?
              AND is_material=1
            """,
            (int(window_days),),
        ).fetchall()
        if rows_cov:
            out = {str(t): int(n or 0) for t, n, _ in rows_cov}
            for t in targets:
                out.setdefault(t, 0)
            shortages = [str(t) for t, _n, s in rows_cov if int(s or 0) == 1]
            if not shortages:
                shortages = [t for t, n in out.items() if n < shortage_threshold]
            return out, shortages
        rows = conn.execute(
            """
            SELECT COALESCE(signal_type,''), COUNT(*)
            FROM signals
            WHERE date >= date('now', ?)
            GROUP BY signal_type
            """,
            (f"-{max(1, window_days)} day",),
        ).fetchall()
    finally:
        conn.close()
    cnt = {str(k or ""): int(v or 0) for k, v in rows}
    out = {t: cnt.get(t, 0) for t in targets}
    shortages = [t for t, n in out.items() if n < shortage_threshold]
    return out, shortages


def main() -> int:
    args = parse_args()
    end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=max(0, args.days - 1))
    py = args.python

    # Ensure schema includes latest tables before harvesting.
    run([py, "scripts/data/init_investment_db.py", "--db", "data/investment.db"])

    total_days = 0
    failed_days = 0
    low_rate_streak = 0
    db_path = Path(args.db)
    d = start
    while d <= end:
        ds = d.strftime("%Y-%m-%d")
        total_days += 1
        print(f"[day] {ds}")
        tdnet_before, outcomes_before = fetch_day_metrics(db_path, ds)
        effective_discover_latest = args.discover_latest
        effective_max_pages = args.max_pages
        if outcomes_before >= args.min_outcomes_target:
            effective_discover_latest = max(10, args.discover_latest // 2)
            effective_max_pages = max(20, args.max_pages // 2)
            print(
                f"[planner] reduce_kabutan_depth date={ds} outcomes={outcomes_before} "
                f"discover_latest={effective_discover_latest} max_pages={effective_max_pages}"
            )
        # Coverage-aware boost: if material signal types are thin, expand Kabutan crawl depth.
        cov, shortages = fetch_material_signal_coverage(
            db_path,
            window_days=int(args.signal_coverage_window_days),
            min_count_per_type=int(args.material_min_count_per_type),
            shortage_ratio=float(args.material_shortage_ratio),
        )
        if shortages:
            shortage_ratio = len(shortages) / max(1, len(cov))
            boost_discover = int(round(args.discover_latest * (0.5 + shortage_ratio)))
            boost_pages = int(round(args.max_pages * (0.4 + shortage_ratio)))
            effective_discover_latest = max(effective_discover_latest, args.discover_latest + boost_discover)
            effective_max_pages = max(effective_max_pages, args.max_pages + boost_pages)
            effective_discover_latest = min(effective_discover_latest, 180)
            effective_max_pages = min(effective_max_pages, 180)
            short_text = ", ".join(f"{k}:{cov.get(k,0)}" for k in shortages)
            print(
                f"[planner] boost_material_coverage date={ds} shortages={len(shortages)}/{len(cov)} "
                f"discover_latest={effective_discover_latest} max_pages={effective_max_pages} shortage_types=[{short_text}]"
            )
        extra_shortage_pass = len(shortages) >= 2
        rc = 0
        rc |= run([py, "scripts/investment/collect/ingest_jpx_resource_files.py", "--date", ds, "--post-action", "archive"])
        rc |= run([py, "scripts/investment/collect/plan_collection_coverage.py", "--date", ds, "--target-bars", str(args.price_target_bars), "--max-items", "300"])
        rc |= run([py, "scripts/investment/collect/collect_jpx_daily_stats.py", "--date", ds, "--max-links", str(args.jpx_max_links)])
        rc |= run([py, "scripts/investment/collect/process_jpx_daily_files.py", "--date", ds, "--max-files", str(args.jpx_process_max_files)])
        rc |= run([py, "scripts/investment/collect/collect_tdnet_disclosures.py", "--date", ds, "--lookback-days", "0", "--max-items", str(args.tdnet_max_items)])
        rc |= run([py, "scripts/investment/collect/collect_kabutan_surprise_signals.py", "--date", ds, "--discover-latest", str(effective_discover_latest), "--max-pages", str(effective_max_pages), "--sleep", "1.6", "--jitter", "0.6", "--retries", "3", "--retry-wait", "2.0"])
        rc |= run([py, "scripts/investment/collect/collect_kabutan_short_signals.py", "--date", ds, "--discover-latest", str(effective_discover_latest), "--max-pages", str(effective_max_pages), "--sleep", "1.6", "--jitter", "0.6", "--retries", "3", "--retry-wait", "2.0"])
        # Shortage-driven extra pass: deepen collection for under-covered material signal types.
        if extra_shortage_pass:
            deep_discover = min(220, int(round(effective_discover_latest * 1.4)))
            deep_pages = min(220, int(round(effective_max_pages * 1.4)))
            deep_tdnet_max_items = min(1200, int(round(args.tdnet_max_items * 1.5)))
            print(
                f"[planner] shortage_extra_pass date={ds} discover_latest={deep_discover} "
                f"max_pages={deep_pages} tdnet_max_items={deep_tdnet_max_items}"
            )
            rc |= run([py, "scripts/investment/collect/collect_tdnet_disclosures.py", "--date", ds, "--lookback-days", "0", "--max-items", str(deep_tdnet_max_items)], allow_fail=True)
            rc |= run([py, "scripts/investment/collect/collect_kabutan_surprise_signals.py", "--date", ds, "--discover-latest", str(deep_discover), "--max-pages", str(deep_pages), "--sleep", "1.4", "--jitter", "0.5", "--retries", "3", "--retry-wait", "2.0"], allow_fail=True)
            rc |= run([py, "scripts/investment/collect/collect_kabutan_short_signals.py", "--date", ds, "--discover-latest", str(deep_discover), "--max-pages", str(deep_pages), "--sleep", "1.4", "--jitter", "0.5", "--retries", "3", "--retry-wait", "2.0"], allow_fail=True)
        rc |= run(
            [
                py,
                "scripts/investment/collect/backfill_price_daily.py",
                "--date",
                ds,
                "--target-bars",
                str(args.price_target_bars),
                "--max-tickers",
                str(args.price_max_tickers),
            ]
        )
        rc |= run([py, "scripts/investment/backtest/fill_market_outcomes.py", "--date", ds, "--seed-list", args.seed_list])
        rc |= run([py, "scripts/investment/signals/build_market_signals_from_batches.py", "--date", ds, "--lookback-days", "2", "--max-signals", str(args.max_signals), "--max-long", str(args.max_long), "--max-short", str(args.max_short)])
        rc |= run([py, "scripts/data/ingest_investment_db.py", "--date", ds])
        rc |= run([py, "scripts/data/cleanup_raw_events.py", "--as-of-date", ds, "--keep-days", "14"])
        rc |= run([py, "scripts/investment/collect/build_collection_kpi_alert.py", "--date", ds, "--target-bars", str(args.price_target_bars)], allow_fail=True)
        rc |= run(
            [
                py,
                "scripts/investment/analysis/report_signal_type_coverage.py",
                "--date",
                ds,
                "--window-days",
                str(args.signal_coverage_window_days),
                "--min-material-count",
                str(args.material_min_count_per_type),
                "--shortage-ratio",
                str(args.material_shortage_ratio),
            ],
            allow_fail=True,
        )
        tdnet_after, outcomes_after = fetch_day_metrics(db_path, ds)
        new_rows = max(0, tdnet_after - tdnet_before) + max(0, outcomes_after - outcomes_before)
        scanned_rows = max(1, args.tdnet_max_items + effective_max_pages * 2)
        new_rate = new_rows / scanned_rows
        if new_rate < args.min_new_rate:
            low_rate_streak += 1
        else:
            low_rate_streak = 0
        print(
            f"[metrics] date={ds} new_rows={new_rows} scanned_rows~={scanned_rows} "
            f"new_rate={new_rate:.4f} low_rate_streak={low_rate_streak}"
        )
        jpx_rows, ready_tickers, total_tickers = fetch_progress_metrics(db_path, ds, args.price_target_bars)
        jpx_coverage_pct = 100.0 if jpx_rows > 0 else 0.0
        bars_coverage_pct = (ready_tickers / total_tickers * 100.0) if total_tickers > 0 else 0.0
        print(
            f"[coverage] date={ds} jpx_rows={jpx_rows} jpx_coverage_pct={jpx_coverage_pct:.1f} "
            f"bars_target={args.price_target_bars} ready={ready_tickers}/{total_tickers} bars_coverage_pct={bars_coverage_pct:.1f}"
        )
        if rc != 0:
            failed_days += 1
            print(f"[warn] failed day: {ds}")
        if low_rate_streak >= args.low_rate_streak_stop:
            print(
                f"[stop] low new-rate streak reached: {low_rate_streak} "
                f"(threshold={args.min_new_rate:.4f}). stop looping."
            )
            break
        d += timedelta(days=1)

    print(f"[summary] days={total_days} failed_days={failed_days}")
    return 0 if failed_days == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
