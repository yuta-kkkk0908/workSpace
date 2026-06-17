#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db
from utils.pipeline_events import write_pipeline_event
# Phase-2 step1 (+25% class): expand collection breadth before weekly re-tune.
KABUTAN_DISCOVER_LATEST = "35"
KABUTAN_MAX_PAGES_NIGHT = "50"
KABUTAN_MAX_PAGES_MORNING = "45"
KABUTAN_MAX_PAGES_EVENING = "35"
KABUTAN_SLEEP_SEC = "1.6"
KABUTAN_JITTER_SEC = "0.6"
KABUTAN_RETRIES = "3"
KABUTAN_RETRY_WAIT_SEC = "2.0"
TDNET_LOOKBACK_DAYS = "7"
WATCH_PROMOTION_MIN_AVG_TURNOVER_MIL = "700"
MARKET_SIGNALS_MAX = "12"
MARKET_SIGNALS_MAX_LONG = "6"
MARKET_SIGNALS_MAX_SHORT = "6"
OPENING_SCENARIOS_MAX_CANDIDATES = "12"
LOCK_DIR = ROOT / "tmp" / "scheduler-locks"
LOCK_STALE_SEC = 6 * 60 * 60
LOCK_ACQUIRE_RETRIES = 8
LOCK_ACQUIRE_WAIT_SEC = 1.0
SIGNAL_UNCHANGED_STREAK_FILE = ROOT / "tmp" / "prompts" / ".signal-unchanged-streak.txt"
CURRENT_SLOT: str | None = None
CURRENT_DATE: str | None = None
INVESTMENT_DB = resolve_investment_db()


def classify_error_category(stage: str | None, cmd: list[str], rc: int) -> str:
    if rc == 0:
        return "ok"
    text = " ".join(([stage or ""] + cmd)).lower()
    if any(k in text for k in ["discord", "webhook", "post_", "sync_scenario_replies"]):
        return "discord_delivery"
    if any(k in text for k in ["collect_", "fetch", "snapshot", "tdnet", "kabutan", "rakuten", "sbi"]):
        return "source_fetch"
    if any(k in text for k in ["ingest_", "init_", "sqlite", "db"]):
        return "db_error"
    if any(k in text for k in ["auth", "token", "credential"]):
        return "auth_error"
    return "process_error"


def scenario_credit_max_tickers(db_path: Path, event_date: str, base: int = 80) -> int:
    """
    Expand credit collection breadth when recent quality alerts indicate CREDIT_THIN.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT payload_json
            FROM pipeline_events
            WHERE event_date BETWEEN date(?, '-3 day') AND ?
              AND stage='check_signal_quality.py'
              AND status='alert'
            ORDER BY id DESC
            LIMIT 12
            """,
            (event_date, event_date),
        ).fetchall()
    except Exception:
        return base
    finally:
        try:
            conn.close()
        except Exception:
            pass
    for r in rows:
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except Exception:
            payload = {}
        codes = payload.get("qualityReasonCodes") or []
        if isinstance(codes, list) and any(str(c) == "CREDIT_THIN" for c in codes):
            return max(base, 120)
    return base


def run(
    cmd: list[str],
    allow_fail: bool = False,
    *,
    slot: str | None = None,
    event_date: str | None = None,
    stage: str | None = None,
    retries: int = 0,
    retry_wait_sec: float = 3.0,
) -> int:
    slot = slot or CURRENT_SLOT
    event_date = event_date or CURRENT_DATE
    if not stage and len(cmd) >= 2:
        stage = Path(cmd[1]).name
    attempt = 0
    last_rc = 0
    while True:
        prefix = f"[run retry {attempt}/{retries}]" if attempt else "[run]"
        print(prefix, ' '.join(cmd))
        started = time.perf_counter()
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        write_pipeline_event(
            pipeline="ops_scheduler",
            slot=slot,
            stage=stage,
            status="ok" if rc == 0 else "error",
            command=cmd,
            return_code=rc,
            duration_ms=elapsed_ms,
            event_date=event_date,
            payload={
                "allow_fail": bool(allow_fail),
                "error_category": classify_error_category(stage, cmd, rc),
                "attempt": attempt,
                "retries": retries,
            },
        )
        last_rc = rc
        if rc == 0 or attempt >= retries:
            break
        attempt += 1
        time.sleep(max(0.0, retry_wait_sec))
    if last_rc != 0 and allow_fail:
        return 0
    return last_rc


def read_int_file(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        return 0


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            cp = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            out = (cp.stdout or "").strip()
            if not out or "No tasks are running" in out:
                return False
            return str(pid) in out
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True


def cleanup_lock_dir(lock_path: Path) -> None:
    for p in lock_path.glob("*"):
        p.unlink(missing_ok=True)
    os.rmdir(lock_path)


def lock_pid_is_stale(lock_path: Path) -> bool:
    meta_path = lock_path / "meta.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    try:
        pid = int(meta.get("pid") or 0)
    except Exception:
        return False
    return not is_pid_running(pid)


def kabutan_collection_profile(slot: str) -> tuple[str, str]:
    """
    Raise collection breadth when signal unchanged streak grows.
    streak>=2: boost max-pages/discover-latest to recover from DATA_THIN.
    """
    streak = read_int_file(SIGNAL_UNCHANGED_STREAK_FILE)
    base_pages = {
        "night": KABUTAN_MAX_PAGES_NIGHT,
        "inv-morning": KABUTAN_MAX_PAGES_MORNING,
        "inv-evening": KABUTAN_MAX_PAGES_EVENING,
    }.get(slot, KABUTAN_MAX_PAGES_NIGHT)
    discover = KABUTAN_DISCOVER_LATEST
    pages = base_pages
    if streak >= 2:
        discover = "40"
        pages = str(max(int(base_pages), 56))
        print(f"[boost] collection profile enabled slot={slot} unchanged_streak={streak} discover={discover} max_pages={pages}")
    return discover, pages


@contextmanager
def slot_lock(slot: str):
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCK_DIR / f"{slot}.lock"
    acquired = False
    try:
        for _ in range(LOCK_ACQUIRE_RETRIES):
            now = datetime.now().timestamp()
            try:
                os.mkdir(lock_path)
                acquired = True
                break
            except FileExistsError:
                # stale lock cleanup
                try:
                    if lock_pid_is_stale(lock_path):
                        cleanup_lock_dir(lock_path)
                        continue
                    st = lock_path.stat()
                    if (now - st.st_mtime) > LOCK_STALE_SEC:
                        cleanup_lock_dir(lock_path)
                        continue
                except FileNotFoundError:
                    continue
                time.sleep(LOCK_ACQUIRE_WAIT_SEC)
        if not acquired:
            print(f"[skip] slot lock exists: {slot}")
            yield False
            return
        meta = {"slot": slot, "pid": os.getpid(), "started_at": datetime.now().isoformat(timespec="seconds")}
        (lock_path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        yield True
    finally:
        if acquired:
            try:
                cleanup_lock_dir(lock_path)
            except FileNotFoundError:
                pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Scheduler orchestration for AIOS ops')
    p.add_argument('--slot', required=True, choices=['night', 'improvement', 'inv-morning', 'inv-noon', 'inv-evening', 'inv-heavy', 'inv-scenario'])
    p.add_argument('--date', default=date.today().isoformat())
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--backtest', action='store_true', help='disable non-backtest side effects and today-dependent checks')
    return p.parse_args()


def is_jp_market_weekend(d: str) -> bool:
    try:
        return datetime.strptime(d, "%Y-%m-%d").weekday() >= 5
    except Exception:
        return False


def next_jp_market_day(d: str) -> str:
    try:
        next_day = datetime.strptime(d, "%Y-%m-%d").date() + timedelta(days=1)
    except Exception:
        return d
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.isoformat()


def run_investment_cycle(py: str, d: str, backtest: bool = False) -> int:
    rc = 0
    discover_latest, max_pages = kabutan_collection_profile("night")
    rc |= run([py, 'scripts/investment/collect/collect_jpx_daily_pdf_prices.py', '--date', d], allow_fail=True)
    # 1) Python-only collection from external sources (raw temp artifacts in inbox)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_surprise_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_short_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    # 2) Build daily market-signals from collected artifacts (no stale carry-over by default)
    rc |= run([py, 'scripts/investment/signals/build_market_signals_from_batches.py', '--date', d, '--lookback-days', '2', '--max-signals', MARKET_SIGNALS_MAX, '--max-long', MARKET_SIGNALS_MAX_LONG, '--max-short', MARKET_SIGNALS_MAX_SHORT], allow_fail=True)
    # 3) Fallback only when builder could not produce a valid file
    rc |= run([py, 'scripts/investment/signals/prepare_morning_market_signals.py', '--date', d, '--fallback-days', '1'], allow_fail=True)
    # 4) Persist signals first (DB-first downstream)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    # 5) Validate/derive and persist candidates
    rc |= run([py, 'scripts/investment/signals/check_investment_signal_missing.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/analysis/materialize_signal_type_aggressiveness.py', '--date', d, '--window-days', '365'], allow_fail=True)
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    return rc


def run_rule_repro_refresh(py: str, d: str) -> int:
    """Refresh rule reproducibility artifacts so scenario generation can use win-rate context."""
    rc = 0
    # 1) Expand outcomes for the day (allow fetch to avoid empty-cache stagnation)
    rc |= run(
        [
            py,
            'scripts/investment/backtest/fill_market_outcomes.py',
            '--date',
            d,
            '--seed-list',
            'rough_backtest_light',
            '--include-db-signals',
        ],
        allow_fail=True,
    )
    # 2) Build rule analysis artifacts
    rc |= run([py, 'scripts/investment/analysis/analyze_market_outcomes.py', '--date', d, '--db-only'], allow_fail=True)
    rc |= run(
        [
            py,
            'scripts/investment/analysis/rule_check_market_outcomes.py',
            '--date',
            d,
            '--seed-list',
            'rough_backtest_light',
            '--min-count',
            '8',
            '--db-only',
        ],
        allow_fail=True,
    )
    rc |= run([py, 'scripts/investment/analysis/analyze_long_rule_reproducibility.py', '--date', d, '--min-count', '8'], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/classify_short_readiness.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/analyze_short_chart_windows.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/analyze_short_rebound_risk.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/classify_short_conviction.py', '--date', d], allow_fail=True)
    # 3) Dashboard + history
    rc |= run([py, 'scripts/investment/analysis/generate_rule_dashboard.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/update_rule_history.py', '--date', d], allow_fail=True)
    return rc


def run_recent_outcome_backfill(py: str, d: str) -> int:
    """Nightly backfill for recent outcomes (C-2)."""
    rc = 0
    # Daily: keep the recent 30-day window warm.
    rc |= run(
        [
            py,
            'scripts/investment/backtest/backfill_recent_outcomes_window.py',
            '--as-of',
            d,
            '--window-days',
            '30',
            '--db-lookback-days',
            '30',
            '--seed-list',
            'rough_backtest_light',
        ],
        allow_fail=True,
    )
    # Weekly (Monday night): extend to 90-day window.
    try:
        d_obj = datetime.strptime(d, "%Y-%m-%d").date()
        wd = d_obj.weekday()
    except Exception:
        d_obj = None
        wd = -1
    if wd == 0:
        rc |= run(
            [
                py,
                'scripts/investment/backtest/backfill_recent_outcomes_window.py',
                '--as-of',
                d,
                '--window-days',
                '90',
                '--db-lookback-days',
                '90',
                '--seed-list',
                'rough_backtest_light',
            ],
            allow_fail=True,
        )
    # Monthly (1st night): extend to 180-day window.
    if d_obj and d_obj.day == 1:
        rc |= run(
            [
                py,
                'scripts/investment/backtest/backfill_recent_outcomes_window.py',
                '--as-of',
                d,
                '--window-days',
                '180',
                '--db-lookback-days',
                '180',
                '--seed-list',
                'rough_backtest_light',
            ],
            allow_fail=True,
        )
    # Prioritize mature pending outcomes so scenario promotion uses judged samples.
    rc |= run(
        [
            py,
            'scripts/investment/backtest/backfill_pending_outcomes.py',
            '--as-of',
            d,
            '--window-days',
            '90',
            '--max-dates',
            '8',
        ],
        allow_fail=True,
    )
    return rc


def run_decision_support_threshold_recommendation_weekly(py: str, d: str) -> int:
    """
    Weekly threshold recommendation for decision-support warnings.
    Runs on Monday night against the current YYYY-MM bucket.
    """
    try:
        d_obj = datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return 0
    if d_obj.weekday() != 0:
        return 0
    month = d_obj.strftime("%Y-%m")
    return run(
        [
            py,
            "scripts/investment/analysis/recommend_decision_support_thresholds.py",
            "--month",
            month,
            "--target-min-rate",
            "5",
            "--target-max-rate",
            "15",
        ],
        allow_fail=True,
    )


def run_improvement_cycle(py: str, d: str, *, allow_execution: bool = False) -> int:
    """Daily improvement loop: audit -> proposal -> materialize -> claim -> optional execute."""
    rc = 0
    rc |= run([py, 'scripts/investment/analysis/generate_improvement_audit.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/generate_improvement_proposals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/materialize_improvement_work_items.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/claim_improvement_work_items.py', '--date', d, '--limit', '3'], allow_fail=True)
    if allow_execution:
        rc |= run([py, 'scripts/investment/analysis/execute_improvement_work_items.py', '--date', d, '--limit', '1'], allow_fail=True)
    return rc


def run_investment_cycle_morning(py: str, d: str, backtest: bool = False, weekend_collect_only: bool = False) -> int:
    """Morning: refresh sources + rebuild signals with overnight context."""
    rc = 0
    discover_latest, max_pages = kabutan_collection_profile("inv-morning")
    rc |= run([py, 'scripts/investment/collect/collect_tdnet_disclosures.py', '--date', d, '--lookback-days', TDNET_LOOKBACK_DAYS], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_surprise_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_short_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    if weekend_collect_only:
        print(f"[weekend-collect-only] inv-morning: {d}")
        return rc
    rc |= run([py, 'scripts/investment/signals/build_market_signals_from_batches.py', '--date', d, '--lookback-days', '2', '--max-signals', MARKET_SIGNALS_MAX, '--max-long', MARKET_SIGNALS_MAX_LONG, '--max-short', MARKET_SIGNALS_MAX_SHORT], allow_fail=True)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/collect/backfill_instrument_names.py', '--date', d], allow_fail=True, retries=2, retry_wait_sec=5.0)
    rc |= run([py, 'scripts/investment/analysis/backfill_signal_company_names.py', '--date', d], allow_fail=True, retries=2, retry_wait_sec=5.0)
    rc |= run([py, 'scripts/investment/signals/check_investment_signal_missing.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_signal_quality.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/analyze_signal_quality_alert_ai.py', '--date', d], allow_fail=True)
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d, '--slot', 'inv-evening'], allow_fail=True)
    return rc


def run_morning_disclosure_digest_and_note(py: str, d: str) -> int:
    """Build the morning disclosure digest and, when configured, save a note draft."""
    rc = 0
    disclosure_out_dir = ROOT / "topics" / "investment-research" / "inbox"
    note_config = ROOT / "configs" / "note.local.json"
    note_markdown = disclosure_out_dir / f"{d}-note-ready.md"
    note_log = ROOT / "logs" / f"disclosure-note-post-{d}.json"
    note_shot = ROOT / "logs" / f"disclosure-note-post-{d}.png"

    rc |= run(
        [
            py,
            "scripts/investment/analysis/run_morning_disclosure_digest.py",
            "--date",
            d,
            "--db",
            str(INVESTMENT_DB),
            "--output-dir",
            str(disclosure_out_dir),
            "--limit",
            "20",
            "--lookback-days",
            "90",
            "--max-items",
            "120",
        ],
        allow_fail=True,
    )
    if rc == 0 and note_config.exists():
        rc |= run(
            [
                py,
                "scripts/notify/post_note_draft.py",
                "--markdown-path",
                str(note_markdown),
                "--db",
                str(INVESTMENT_DB),
                "--note-config",
                str(note_config),
                "--log-path",
                str(note_log),
                "--screenshot-path",
                str(note_shot),
            ],
            allow_fail=True,
        )
    elif rc == 0:
        print("[skip] note draft post: config not found")
    return rc


def run_investment_cycle_noon(py: str, d: str, backtest: bool = False, weekend_collect_only: bool = False) -> int:
    """Noon: avoid heavy recollection; focus on re-ranking/re-candidates from intraday state."""
    rc = 0
    rc |= run([py, 'scripts/investment/collect/collect_tdnet_disclosures.py', '--date', d, '--lookback-days', TDNET_LOOKBACK_DAYS], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_intraday_signal_snapshots.py', '--date', d, '--slot', 'inv-noon'], allow_fail=True)
    if weekend_collect_only:
        print(f"[weekend-collect-only] inv-noon: {d}")
        return rc
    rc |= run([py, 'scripts/investment/signals/reevaluate_market_signals_noon.py', '--date', d, '--slot', 'inv-noon'], allow_fail=True)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run(
        [
            py,
            'scripts/investment/collect/snapshot_signal_prices.py',
            '--date',
            d,
            '--snapshot-date',
            next_jp_market_day(d),
            '--db',
            str(INVESTMENT_DB),
        ],
        allow_fail=True,
    )
    rc |= run([py, 'scripts/investment/collect/backfill_instrument_names.py', '--date', d], allow_fail=True, retries=2, retry_wait_sec=5.0)
    rc |= run([py, 'scripts/investment/analysis/backfill_signal_company_names.py', '--date', d], allow_fail=True, retries=2, retry_wait_sec=5.0)
    rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_signal_quality.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/analyze_signal_quality_alert_ai.py', '--date', d], allow_fail=True)
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d, '--slot', 'inv-noon'], allow_fail=True)
    return rc


def run_morning_market_signals_report(py: str, d: str) -> int:
    """Morning Discord signal report with overnight US market overview."""
    rc = 0
    rc |= run([py, 'scripts/investment/collect/collect_us_market_overview.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d, '--slot', 'inv-morning'], allow_fail=True)
    return rc


def run_investment_cycle_evening(py: str, d: str, backtest: bool = False, weekend_collect_only: bool = False) -> int:
    """Evening: include technical context after close and final re-evaluation."""
    rc = 0
    discover_latest, max_pages = kabutan_collection_profile("inv-evening")
    rc |= run([py, 'scripts/investment/collect/collect_tdnet_disclosures.py', '--date', d, '--lookback-days', TDNET_LOOKBACK_DAYS], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_surprise_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_short_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    if weekend_collect_only:
        print(f"[weekend-collect-only] inv-evening: {d}")
        return rc
    # Daily backtest outcome refresh so DB is not dependent on weekly-only updates.
    rc |= run([py, 'scripts/investment/backtest/fill_market_outcomes.py', '--date', d, '--seed-list', 'rough_backtest_full', '--include-db-signals'], allow_fail=True)
    rc |= run([py, 'scripts/investment/backtest/fill_sector_context.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/build_market_signals_from_batches.py', '--date', d, '--lookback-days', '2', '--max-signals', MARKET_SIGNALS_MAX, '--max-long', MARKET_SIGNALS_MAX_LONG, '--max-short', MARKET_SIGNALS_MAX_SHORT], allow_fail=True)
    rc |= run([py, 'scripts/investment/backtest/fill_technical_context.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/reevaluate_market_signals.py', '--date', d, '--fallback-days', '1'], allow_fail=True)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/collect/backfill_instrument_names.py', '--date', d], allow_fail=True, retries=2, retry_wait_sec=5.0)
    rc |= run([py, 'scripts/investment/analysis/backfill_signal_company_names.py', '--date', d], allow_fail=True, retries=2, retry_wait_sec=5.0)
    rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_signal_quality.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/analyze_signal_quality_alert_ai.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/report_signal_pipeline_kpi.py', '--date', d], allow_fail=True)
    # Strengthen next scenario quality by refreshing rule reproducibility artifacts nightly/evening.
    rc |= run_rule_repro_refresh(py, d)
    # Keep backtest outcomes warm so promotion and aggressiveness analysis have fresh judges.
    rc |= run_recent_outcome_backfill(py, d)
    # Daily operational hint: refresh exit timing analysis from accumulated trades.
    rc |= run([py, 'scripts/investment/backtest/analyze_exit_timing.py', '--out-date', d, '--mode', 'all'], allow_fail=True)
    # Daily mode comparison: backtest/watch/live performance snapshot.
    rc |= run([py, 'scripts/investment/backtest/analyze_paper_trade_stats.py', '--out-date', d, '--mode', 'all'], allow_fail=True)
    # Keep watch outcomes fresh before promotion analysis.
    rc |= run([py, 'scripts/investment/backtest/fill_paper_trade_outcomes.py', '--mode', 'watch', '--as-of', d], allow_fail=True)
    # E-1: paper_trade_only cohort KPI (after outcomes refresh).
    rc |= run([py, 'scripts/investment/analysis/report_paper_trade_only_kpi.py', '--date', d, '--window-days', '30'], allow_fail=True)
    # E-3: failure-factor aggregation for paper_trade_only losses.
    rc |= run(
        [
            py,
            'scripts/investment/analysis/report_paper_trade_only_failure_factors.py',
            '--date',
            d,
            '--window-days',
            '30',
            '--loss-threshold-pct',
            '-0.5',
        ],
        allow_fail=True,
    )
    # Render short Discord message for paper stats.
    if not backtest:
        rc |= run([py, 'scripts/notify/render_paper_stats_discord_message.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
    # Daily watch->trade promotion candidates from accumulated watch entries.
    rc |= run(
        [
            py,
            'scripts/investment/backtest/analyze_watch_promotion.py',
            '--out-date',
            d,
            '--ladder',
            '--min-avg-turnover-mil',
            WATCH_PROMOTION_MIN_AVG_TURNOVER_MIL,
        ],
        allow_fail=True,
    )
    # Daily technical-signal effectiveness snapshot (recent 30 trading days).
    rc |= run([py, 'scripts/investment/analysis/analyze_technical_signal_performance.py', '--out-date', d, '--window-days', '30', '--min-samples', '5'], allow_fail=True)
    # Daily consolidated review snapshot for trade/watch quality gap.
    rc |= run([py, 'scripts/investment/backtest/generate_trade_watch_weekly_review.py', '--out-date', d], allow_fail=True)
    if not backtest:
        # sync_scenario_replies_bot.py loads .env by itself.
        rc |= run([py, 'scripts/notify/sync_scenario_replies_bot.py', '--limit', '100'], allow_fail=True)
    # ExitAnalyzer: collection / analysis / processing bottleneck snapshot.
    rc |= run([py, 'scripts/investment/analysis/report_exit_analyzer.py', '--date', d, '--window-days', '30'], allow_fail=True)
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d], allow_fail=True)
    return rc


def main() -> int:
    global CURRENT_SLOT, CURRENT_DATE
    args = parse_args()
    py = args.python
    d = args.date
    CURRENT_SLOT = args.slot
    CURRENT_DATE = d
    rc = 0

    write_pipeline_event(
        pipeline="ops_scheduler",
        slot=args.slot,
        stage="slot",
        status="start",
        event_date=d,
        payload={"backtest": bool(args.backtest)},
    )

    try:
        with slot_lock(args.slot) as ok_to_run:
            if not ok_to_run:
                write_pipeline_event(
                    pipeline="ops_scheduler",
                    slot=args.slot,
                    stage="slot",
                    level="warning",
                    status="skipped_lock_exists",
                    event_date=d,
                )
                return 0

            if args.slot == 'night':
        # Whole repository health + generic/topic/needs pipeline only.
        # Investment pipeline is intentionally detached from night slot.
                rc |= run([py, 'scripts/data/init_ops_db.py'])
                rc |= run([py, 'scripts/data/ingest_ops_logs.py'], allow_fail=True)
                if not args.backtest:
                    rc |= run([py, 'scripts/check_daily_missing.py', '--date', 'today', '--days', '7'], allow_fail=True)
                    rc |= run([py, 'scripts/investment/collect/collect_generic_daily_topics.py', '--date', d, '--overwrite'], allow_fail=True)
                    rc |= run([py, 'scripts/topics/enrich_pokemon_daily_with_ai.py', '--date', d], allow_fail=True)
                    rc |= run([py, 'scripts/topics/consolidate_pokemon_sources_ai.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/data/init_topics_db.py'])
                rc |= run([py, 'scripts/data/ingest_topics_db.py', '--date', d])
                rc |= run([py, 'scripts/data/build_today_topics_brief_from_db.py', '--date', d], allow_fail=True)
                if not args.backtest:
                    rc |= run(
                        [
                            py,
                            'scripts/notify/render_generic_topics_discord_message.py',
                            '--date',
                            d,
                            '--items-per-topic',
                            '3',
                            '--include-urls',
                            '--max-message-len',
                            '3400',
                        ],
                        allow_fail=True,
                    )
                rc |= run([py, 'scripts/data/init_needs_db.py'])
                rc |= run([py, 'scripts/data/ingest_needs_db.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/build_needs_ai_queue.py', '--limit', '20'], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_ops_post_daily.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_ops_quality_weekly.py', '--date', d, '--window-days', '7'], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_weekly_tuning_review.py', '--date', d, '--window-days', '7'], allow_fail=True)
                if datetime.strptime(d, "%Y-%m-%d").weekday() == 0:
                    rc |= run([py, 'scripts/investment/analysis/generate_weekly_tuning_ai_review.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/decide_collection_intensity.py', '--date', d, '--window-days', '3'], allow_fail=True)
                print("[skip] investment pipeline detached from night slot; use inv-morning/inv-noon/inv-evening/inv-scenario.")

            if args.slot == 'improvement':
                allow_execution = os.getenv("ENABLE_IMPROVEMENT_EXECUTION", "").strip().lower() in {"1", "true", "yes"}
                rc |= run_improvement_cycle(py, d, allow_execution=allow_execution)

            if args.slot == 'inv-morning':
                rc |= run_investment_cycle_morning(
                    py,
                    d,
                    backtest=args.backtest,
                    weekend_collect_only=is_jp_market_weekend(d),
                )
                if not args.backtest and not is_jp_market_weekend(d):
                    rc |= run_morning_market_signals_report(py, d)
                    rc |= run_morning_disclosure_digest_and_note(py, d)

            if args.slot == 'inv-noon':
                rc |= run_investment_cycle_noon(
                    py,
                    d,
                    backtest=args.backtest,
                    weekend_collect_only=is_jp_market_weekend(d),
                )

            if args.slot == 'inv-evening':
                rc |= run_investment_cycle_evening(
                    py,
                    d,
                    backtest=args.backtest,
                    weekend_collect_only=is_jp_market_weekend(d),
                )

            if args.slot == 'inv-heavy':
                if is_jp_market_weekend(d):
                    print(f"[skip] inv-heavy weekend: {d}")
                    return rc
                # Detached heavy investment maintenance that used to run in night slot.
                rc |= run([py, 'scripts/data/init_investment_db.py'])
                rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
                rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d], allow_fail=True)
                rc |= run_investment_cycle(py, d, backtest=args.backtest)
                rc |= run_rule_repro_refresh(py, d)
                rc |= run_recent_outcome_backfill(py, d)
                rc |= run(
                    [
                        py,
                        'scripts/investment/signals/backfill_opening_scenarios_window.py',
                        '--as-of',
                        d,
                        '--window-days',
                        '90',
                        '--max-days-per-run',
                        '10',
                    ],
                    allow_fail=True,
                )
                rc |= run([py, 'scripts/investment/backtest/fill_technical_context.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/investment/signals/reevaluate_market_signals.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
                rc |= run([py, 'scripts/data/init_investment_db.py'])
                rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
                rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
                rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_signal_pipeline_kpi.py', '--date', d], allow_fail=True)
                rc |= run_decision_support_threshold_recommendation_weekly(py, d)
                if not args.backtest:
                    rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d, '--slot', 'inv-evening'], allow_fail=True)

            if args.slot == 'inv-scenario':
                # JP market is closed on weekends.
                if is_jp_market_weekend(d):
                    print(f"[skip] inv-scenario weekend: {d}")
                    return rc
                max_tickers = str(scenario_credit_max_tickers(INVESTMENT_DB, d, base=80))
                rc |= run(
                    [
                        py,
                        'scripts/investment/collect/collect_credit_status_auto.py',
                        '--date',
                        d,
                        '--fallback-days',
                        '3',
                        '--max-tickers',
                        max_tickers,
                    ],
                    allow_fail=True,
                )
                rc |= run([py, 'scripts/investment/analysis/report_credit_auto_quality.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/review_scenario_promotion_ai.py', '--date', d], allow_fail=True)
                rc |= run(
                    [
                        py,
                        'scripts/investment/signals/build_opening_scenarios.py',
                        '--date',
                        d,
                        '--fallback-days',
                        '30',
                        '--max-candidates',
                        OPENING_SCENARIOS_MAX_CANDIDATES,
                        '--auto-relax-gate',
                        '--allow-unknown-winrate',
                        '--soft-gate',
                        '--adaptive-side-minimum',
                    ],
                    allow_fail=True,
                )
                rc |= run([py, 'scripts/investment/analysis/generate_ai_analyst_report.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_rule_thin_diagnostics.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_phase_a_score_sensitivity.py', '--date', d, '--window-days', '90'], allow_fail=True)
                rc |= run([py, 'scripts/investment/signals/build_execution_plan.py', '--date', d, '--fallback-days', '30'], allow_fail=True)
                rc |= run([py, 'scripts/investment/signals/fill_execution_plan_metrics.py', '--start-date', d, '--end-date', d], allow_fail=True)
                # Accumulate watch-mode paper rows for watch->trade promotion analysis.
                # Use tier=all to keep a larger shadow sample while watch-only volume is still small.
                rc |= run(
                    [
                        py,
                        'scripts/investment/backtest/register_paper_trades.py',
                        '--date',
                        d,
                        '--mode',
                        'watch',
                        '--tier',
                        'all',
                        '--rejected-policy',
                        'weak_only',
                        '--max-trades',
                        '60',
                        '--fallback-days',
                        '30',
                    ],
                    allow_fail=True,
                )
                rc |= run(
                    [
                        py,
                        'scripts/investment/backtest/register_paper_trades.py',
                        '--date',
                        d,
                        '--mode',
                        'watch',
                        '--tier',
                        'all',
                        '--rejected-policy',
                        'data_quality_only',
                        '--max-trades',
                        '60',
                        '--fallback-days',
                        '30',
                    ],
                    allow_fail=True,
                )
                rc |= run([py, 'scripts/investment/analysis/check_inv_scenario_acceptance.py', '--date', d], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_samplecount_trade_trend.py', '--date', d, '--window-days', '14', '--min-sample-for-trade', '3'], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_sample_health_kpi.py', '--date', d, '--window-days', '30', '--min-effective-sample', '3'], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_decision_support_kpi.py', '--date', d, '--window-days', '30'], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_scenario_tracking_card.py', '--date', d, '--window-days', '7'], allow_fail=True)
                rc |= run([py, 'scripts/investment/analysis/report_decision_support_diff.py', '--date', d, '--window-days', '30'], allow_fail=True)
                # Persist scenario/execution artifacts to DB in the same slot.
                rc |= run([py, 'scripts/data/init_investment_db.py'])
                rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
                rc |= run([py, 'scripts/investment/collect/backfill_instrument_names.py', '--date', d], allow_fail=True, retries=2, retry_wait_sec=5.0)
                rc |= run([py, 'scripts/investment/analysis/backfill_signal_company_names.py', '--date', d], allow_fail=True, retries=2, retry_wait_sec=5.0)
                rc |= run([py, 'scripts/investment/analysis/cleanup_investment_inbox.py', '--date', d, '--keep-days', '14'], allow_fail=True)
                if not args.backtest:
                    rc |= run([py, 'scripts/notify/render_opening_scenarios_discord_message.py', '--date', d], allow_fail=True)
                    # post_scenarios_bot.py loads .env by itself.
                    rc |= run([py, 'scripts/notify/post_scenarios_bot.py', '--date', d, '--fallback-days', '30', '--max-posts', '12'], allow_fail=True)
    finally:
        write_pipeline_event(
            pipeline="ops_scheduler",
            slot=args.slot,
            stage="slot",
            status="done" if rc == 0 else "done_with_error",
            event_date=d,
            payload={"final_rc": rc, "backtest": bool(args.backtest)},
        )

    return rc


if __name__ == '__main__':
    raise SystemExit(main())
