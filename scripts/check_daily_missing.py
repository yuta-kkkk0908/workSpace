#!/usr/bin/env python3
"""Check whether daily-watch topic files exist for a target date.

This script does not run Codex or collect information by itself. It is a
lightweight reminder helper: if daily files are missing, it generates a prompt
that can be pasted into Codex to backfill the date.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TOPICS_DIR = ROOT / "topics"
PENDING_DIR = ROOT / "prompts" / "pending-daily"
PROMPT_PATH = PENDING_DIR / "latest.prompt.md"
STATUS_PATH = PENDING_DIR / "latest.status.txt"
JST = timezone(timedelta(hours=9))
DEFAULT_TOPICS_DB = ROOT / "data" / "topics.db"
DEFAULT_INVESTMENT_DB = ROOT / "data" / "investment.db"
DEFAULT_NEEDS_DB = ROOT / "data" / "needs.db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check missing daily files and generate a Codex backfill prompt."
    )
    parser.add_argument(
        "--date",
        default="today",
        help="Target date in YYYY-MM-DD, or one of: today, yesterday. Default: today.",
    )
    parser.add_argument(
        "--prompt-path",
        default=str(PROMPT_PATH.relative_to(ROOT)),
        help="Path to write the latest generated prompt. Default: prompts/pending-daily/latest.prompt.md",
    )
    parser.add_argument(
        "--status-path",
        default=str(STATUS_PATH.relative_to(ROOT)),
        help="Path to write the latest short notification status. Default: prompts/pending-daily/latest.status.txt",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days to check ending at --date, inclusive. Default: 1.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Only print the status; do not write the prompt file.",
    )
    parser.add_argument(
        "--check-db",
        action="store_true",
        help="Also check db ingestion status for target dates (topics.db / investment.db).",
    )
    parser.add_argument(
        "--topics-db",
        default=str(DEFAULT_TOPICS_DB.relative_to(ROOT)),
        help="Path to topics sqlite db. Default: data/topics.db",
    )
    parser.add_argument(
        "--investment-db",
        default=str(DEFAULT_INVESTMENT_DB.relative_to(ROOT)),
        help="Path to investment sqlite db. Default: data/investment.db",
    )
    parser.add_argument(
        "--needs-db",
        default=str(DEFAULT_NEEDS_DB.relative_to(ROOT)),
        help="Path to needs sqlite db. Default: data/needs.db",
    )
    parser.add_argument(
        "--check-discord-posts",
        action="store_true",
        help="Also check daily presence in discord post logs (signal/generic).",
    )
    parser.add_argument(
        "--warn-only-soft",
        action="store_true",
        help="Do not fail exit code for soft warnings.",
    )
    return parser.parse_args()


def resolve_target_date(value: str) -> date:
    today = datetime.now(JST).date()
    if value == "today":
        return today
    if value == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid --date value: {value}") from exc


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def daily_watch_topics() -> list[str]:
    topics: list[str] = []
    for manifest_path in sorted(TOPICS_DIR.glob("*/topic-manifest.json")):
        manifest = load_json(manifest_path)
        if manifest.get("kind") == "daily-watch":
            topics.append(manifest_path.parent.name)
    return topics


def expected_files(target: date) -> list[Path]:
    date_str = target.isoformat()
    files = [
        TOPICS_DIR / topic / "inbox" / f"{date_str}-daily.md"
        for topic in daily_watch_topics()
    ]

    # investment-research is DB-first; market-signals.md is audit artifact and is not required for completeness.
    files.append(
        TOPICS_DIR
        / "product-idea-watch"
        / "inbox"
        / f"{date_str}-daily-background-need-watch.md"
    )
    return files


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def build_prompt(target: date, missing: list[Path], existing: list[Path]) -> str:
    return build_range_prompt([target], {target: missing}, {target: existing})


def build_status_text(
    targets: list[date],
    missing_by_date: dict[date, list[Path]],
    existing_by_date: dict[date, list[Path]],
    warnings: list[str] | None = None,
) -> str:
    total_expected = sum(len(missing_by_date[target]) + len(existing_by_date[target]) for target in targets)
    total_existing = sum(len(paths) for paths in existing_by_date.values())
    total_missing = sum(len(paths) for paths in missing_by_date.values())
    missing_dates = [target for target in targets if missing_by_date[target]]

    data_hard = [w for w in (warnings or []) if w.startswith("[HARD]")]
    delivery_soft = [w for w in (warnings or []) if w.startswith("[SOFT]")]

    if missing_dates:
        date_text = ", ".join(target.isoformat() for target in missing_dates)
        first_missing = missing_dates[0].isoformat()
        lines = [
            f"AIOS daily missing: {len(missing_dates)}日 / {total_missing}ファイル不足\n"
            f"対象: {targets[0].isoformat()}..{targets[-1].isoformat()}\n"
            f"不足日: {date_text}\n"
            f"Codexに貼る: {first_missing} 分の今日の情報を補完して。"
        ]
        if data_hard:
            lines.append("DATA_INGEST(ERROR)")
            lines.extend(f"- {w.replace('[HARD] ', '')}" for w in data_hard)
        if delivery_soft:
            lines.append("DELIVERY_SOFT(INFO)")
            lines.extend(f"- {w.replace('[SOFT] ', '')}" for w in delivery_soft)
        return "\n".join(lines)

    lines = [
        "AIOS daily OK\n"
        f"対象: {targets[0].isoformat()}..{targets[-1].isoformat()}\n"
        f"{total_existing}/{total_expected} ファイル確認済み。"
    ]
    if data_hard:
        lines.append("DATA_INGEST(ERROR)")
        lines.extend(f"- {w.replace('[HARD] ', '')}" for w in data_hard)
    if delivery_soft:
        lines.append("DELIVERY_SOFT(INFO)")
        lines.extend(f"- {w.replace('[SOFT] ', '')}" for w in delivery_soft)
    return "\n".join(lines)


def db_warnings(targets: list[date], topics_db: Path, investment_db: Path, needs_db: Path) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    dates = [d.isoformat() for d in targets]

    expected_topics: list[str] = []
    for mf in TOPICS_DIR.glob("*/topic-manifest.json"):
        try:
            data = load_json(mf)
        except Exception:
            continue
        if data.get("kind") == "daily-watch" and mf.parent.name != "investment-research":
            expected_topics.append(mf.parent.name)

    if topics_db.exists():
        try:
            conn = sqlite3.connect(topics_db)
            for ds in dates:
                for topic in expected_topics:
                    row = conn.execute(
                        "select 1 from topic_daily_digest where topic=? and date=? limit 1",
                        (topic, ds),
                    ).fetchone()
                    if not row:
                        hard.append(f"topics.db 未投入: {topic} {ds}")
            conn.close()
        except Exception as exc:
            hard.append(f"topics.db チェック失敗: {exc}")
    else:
        hard.append(f"topics.db が存在しない: {topics_db}")

    if investment_db.exists():
        try:
            conn = sqlite3.connect(investment_db)
            for ds in dates:
                row_daily = conn.execute(
                    "select 1 from daily_digest where topic='investment-research' and date=? limit 1",
                    (ds,),
                ).fetchone()
                if not row_daily:
                    hard.append(f"investment.db daily_digest 未投入: {ds}")
                row_sig = conn.execute(
                    "select count(1) from signals where date=?",
                    (ds,),
                ).fetchone()
                cnt_sig = int(row_sig[0]) if row_sig and row_sig[0] is not None else 0
                if cnt_sig == 0:
                    hard.append(f"investment.db signals 未投入: {ds}")
            conn.close()
        except Exception as exc:
            hard.append(f"investment.db チェック失敗: {exc}")
    else:
        hard.append(f"investment.db が存在しない: {investment_db}")

    if needs_db.exists():
        try:
            conn = sqlite3.connect(needs_db)
            row_last = conn.execute("select max(date) from need_items").fetchone()
            last_need_date = str(row_last[0]) if row_last and row_last[0] else ""
            target_end = targets[-1].isoformat()
            if (not last_need_date) or (last_need_date < target_end):
                hard.append(f"needs.db 最終投入日: {last_need_date or '(none)'}")
            conn.close()
        except Exception as exc:
            hard.append(f"needs.db チェック失敗: {exc}")
    else:
        hard.append(f"needs.db が存在しない: {needs_db}")

    return hard, soft


def discord_log_warnings(targets: list[date]) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    date_keys = [d.isoformat() for d in targets]
    signal_log = ROOT / "logs" / "discord-signal.log"
    generic_log = ROOT / "logs" / "discord-generic.log"
    pairs = [("signal", signal_log), ("generic", generic_log)]
    for name, p in pairs:
        if not p.exists():
            soft.append(f"{name} logなし: {p}")
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for ds in date_keys:
            # Keep discord check soft and avoid false positives for "today".
            if ds == datetime.now(JST).date().isoformat():
                continue
            if ds not in txt:
                soft.append(f"{name} log 日付未検知: {ds}")
    return hard, soft


def build_range_prompt(
    targets: list[date],
    missing_by_date: dict[date, list[Path]],
    existing_by_date: dict[date, list[Path]],
) -> str:
    generated_at = datetime.now(JST).isoformat(timespec="seconds")
    total_missing = sum(len(paths) for paths in missing_by_date.values())
    missing_dates = [target for target in targets if missing_by_date[target]]
    first_missing = missing_dates[0] if missing_dates else None

    def file_lines(paths: list[Path]) -> str:
        return "\n".join(f"- `{rel(path)}`" for path in paths) or "- なし"

    date_blocks: list[str] = []
    for target in targets:
        missing = missing_by_date[target]
        existing = existing_by_date[target]
        date_blocks.append(
            f"""### {target.isoformat()}
- missingCount: {len(missing)}
- existingCount: {len(existing)}

Missing:
{file_lines(missing)}
"""
        )

    date_status = "\n".join(date_blocks)

    if first_missing:
        missing_date_lines = "\n".join(f"- {target.isoformat()}" for target in missing_dates)
        request = f"""AGENT.md と commands/daily.md を読んで、次の不足日の「今日の情報」を collect-and-present で補完して。

不足日:
{missing_date_lines}

まずは {first_missing.isoformat()} 分から処理して。
対象は topic-manifest.json の kind: daily-watch の topic。
同じ日の既存ファイルがある場合は新規作成せず更新して。
出典URLを付け、未確認事項は未確認として明示して。
投資情報は売買助言ではなく、材料整理と確認観点に限定して。
market_signal と need_watch は skip せず、可能な範囲で background 更新して。
技術記事は各記事に直接URLを添えて。
ポケモンカードは新パック起点の環境デッキ変化を確認し、変化なしは確認済み N/C として扱って。
"""
    else:
        request = f"""対象期間の daily 関連ファイルは揃っています。
必要なら AGENT.md と commands/daily.md を読んで、直近分を present-only で短く再提示して。
"""

    return f"""# Pending Daily Prompt

## Status
- generatedAt: {generated_at}
- targetStart: {targets[0].isoformat()}
- targetEnd: {targets[-1].isoformat()}
- checkedDays: {len(targets)}
- missingDateCount: {len(missing_dates)}
- missingFileCount: {total_missing}

## Date Status
{date_status}

## Prompt
このまま Codex に貼ってください。

```text
{request}```
"""


def build_clipboard_prompt(
    targets: list[date],
    missing_by_date: dict[date, list[Path]],
) -> str:
    missing_dates = [target for target in targets if missing_by_date[target]]
    if not missing_dates:
        return (
            "AGENT.md と commands/daily.md を読んで、直近の daily を present-only で短く再提示して。"
        )

    missing_date_lines = "\n".join(f"- {target.isoformat()}" for target in missing_dates)
    first_missing = missing_dates[0].isoformat()
    return f"""AGENT.md と commands/daily.md を読んで、次の不足日の「今日の情報」を collect-and-present で補完して。

不足日:
{missing_date_lines}

まずは {first_missing} 分から処理して。
対象は topic-manifest.json の kind: daily-watch の topic。
同じ日の既存ファイルがある場合は新規作成せず更新して。
出典URLを付け、未確認事項は未確認として明示して。
投資情報は売買助言ではなく、材料整理と確認観点に限定して。
market_signal と need_watch は skip せず、可能な範囲で background 更新して。
技術記事は各記事に直接URLを添えて。
ポケモンカードは新パック起点の環境デッキ変化を確認し、変化なしは確認済み N/C として扱って。"""


def build_single_prompt(target: date, missing: list[Path], existing: list[Path]) -> str:
    target_date = target.isoformat()
    generated_at = datetime.now(JST).isoformat(timespec="seconds")

    missing_lines = "\n".join(f"- `{rel(path)}`" for path in missing) or "- なし"
    existing_lines = "\n".join(f"- `{rel(path)}`" for path in existing) or "- なし"

    if missing:
        request = f"""AGENT.md と commands/daily.md を読んで、{target_date} 分の「今日の情報」を collect-and-present で補完して。

対象は topic-manifest.json の kind: daily-watch の topic。
同じ日の既存ファイルがある場合は新規作成せず更新して。
出典URLを付け、未確認事項は未確認として明示して。
投資情報は売買助言ではなく、材料整理と確認観点に限定して。
market_signal と need_watch は skip せず、可能な範囲で background 更新して。
技術記事は各記事に直接URLを添えて。
ポケモンカードは新パック起点の環境デッキ変化を確認し、変化なしは確認済み N/C として扱って。
"""
    else:
        request = f"""{target_date} 分の daily 関連ファイルは揃っています。
必要なら AGENT.md と commands/daily.md を読んで、{target_date} 分を present-only で短く再提示して。
"""

    return f"""# Pending Daily Prompt

## Status
- generatedAt: {generated_at}
- targetDate: {target_date}
- missingCount: {len(missing)}

## Missing Files
{missing_lines}

## Existing Files
{existing_lines}

## Prompt
```text
{request}```
"""


def main() -> int:
    args = parse_args()
    if args.days < 1:
        raise SystemExit("--days must be 1 or greater")

    target = resolve_target_date(args.date)
    targets = [target - timedelta(days=offset) for offset in range(args.days - 1, -1, -1)]
    missing_by_date: dict[date, list[Path]] = {}
    existing_by_date: dict[date, list[Path]] = {}

    for item in targets:
        files = expected_files(item)
        missing_by_date[item] = [path for path in files if not path.exists()]
        existing_by_date[item] = [path for path in files if path.exists()]

    total_expected = sum(len(expected_files(item)) for item in targets)
    total_existing = sum(len(paths) for paths in existing_by_date.values())
    total_missing = sum(len(paths) for paths in missing_by_date.values())

    print(f"targetStart: {targets[0].isoformat()}")
    print(f"targetEnd: {targets[-1].isoformat()}")
    print(f"checkedDays: {len(targets)}")
    print(f"expected: {total_expected}")
    print(f"existing: {total_existing}")
    print(f"missing: {total_missing}")
    for item in targets:
        missing = missing_by_date[item]
        if not missing:
            continue
        print(f"- missingDate: {item.isoformat()} ({len(missing)} files)")
        for path in missing:
            print(f"  - {rel(path)}")

    hard_warns: list[str] = []
    soft_warns: list[str] = []
    if args.check_db:
        h, s = db_warnings(
            targets,
            ROOT / args.topics_db,
            ROOT / args.investment_db,
            ROOT / args.needs_db,
        )
        hard_warns.extend(h)
        soft_warns.extend(s)
    if args.check_discord_posts:
        h, s = discord_log_warnings(targets)
        hard_warns.extend(h)
        soft_warns.extend(s)

    warns = [f"[HARD] {w}" for w in hard_warns] + [f"[SOFT] {w}" for w in soft_warns]

    if warns:
        print(f"warnings: {len(warns)}")
        for w in warns:
            print(f"- warning: {w}")

    prompt_text = build_range_prompt(targets, missing_by_date, existing_by_date)
    clipboard_text = build_clipboard_prompt(targets, missing_by_date)
    prompt_path = ROOT / args.prompt_path
    status_path = ROOT / args.status_path
    if not args.no_write:
        generated_at = datetime.now(JST).strftime("%Y%m%d-%H%M%S")
        archive_base = PENDING_DIR / "archive"
        archive_prompt_path = archive_base / f"{generated_at}-{targets[0].isoformat()}-to-{targets[-1].isoformat()}.prompt.md"
        archive_status_path = archive_base / f"{generated_at}-{targets[0].isoformat()}-to-{targets[-1].isoformat()}.status.txt"
        clipboard_path = PENDING_DIR / "latest.clipboard.txt"

        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        status_text = build_status_text(targets, missing_by_date, existing_by_date, warns)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(status_text, encoding="utf-8")
        clipboard_path.write_text(clipboard_text, encoding="utf-8")
        archive_base.mkdir(parents=True, exist_ok=True)
        archive_prompt_path.write_text(prompt_text, encoding="utf-8")
        archive_status_path.write_text(status_text, encoding="utf-8")
        print(f"prompt: {rel(prompt_path)}")
        print(f"status: {rel(status_path)}")
        print(f"clipboard: {rel(clipboard_path)}")
        print(f"archivePrompt: {rel(archive_prompt_path)}")
        print(f"archiveStatus: {rel(archive_status_path)}")

    if total_missing:
        return 1
    if hard_warns:
        return 1
    if soft_warns and (not args.warn_only_soft):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
