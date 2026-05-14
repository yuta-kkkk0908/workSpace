#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / 'data' / 'investment.db'
DEFAULT_OUT = ROOT / 'prompts' / 'today-db-brief.md'


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Build compact prompt context from investment DB')
    p.add_argument('--date', default=date.today().isoformat())
    p.add_argument('--db', default=str(DEFAULT_DB))
    p.add_argument('--out', default=str(DEFAULT_OUT))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    cur = conn.cursor()

    sig = cur.execute(
        """select signal_id,ticker,company,expected_direction,long_rank,short_rank
           from signals where date=? order by signal_id""",
        (args.date,),
    ).fetchall()
    long_c = cur.execute(
        """select ticker,company,rank,expected_direction from entry_candidates
           where date=? and side='long' order by ticker""",
        (args.date,),
    ).fetchall()
    short_c = cur.execute(
        """select ticker,company,rank,expected_direction from entry_candidates
           where date=? and side='short' order by ticker""",
        (args.date,),
    ).fetchall()
    conn.close()

    lines = [
        f"# DB Brief {args.date}",
        "",
        "この内容を参考に「今日の情報」を要約してください。",
        "投資は売買助言ではなく材料整理。",
        "",
        f"- signals: {len(sig)}",
        f"- long_candidates: {len(long_c)}",
        f"- short_candidates: {len(short_c)}",
        "",
        "## Long Candidates",
    ]
    if long_c:
        lines.extend([f"- {t} {c} rank={r} dir={d}" for t, c, r, d in long_c])
    else:
        lines.append('- N/C')

    lines.extend(['', '## Short Candidates'])
    if short_c:
        lines.extend([f"- {t} {c} rank={r} dir={d}" for t, c, r, d in short_c])
    else:
        lines.append('- N/C')

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'wrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
