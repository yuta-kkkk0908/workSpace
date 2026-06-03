#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable

ensure_platform_core_importable()
from platform_core.model_router import resolve_model
from platform_core.openai_client import call_openai_text

DEFAULT_DB = ROOT / "data" / "topics.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI dedupe/consolidation for pokemon collection links")
    p.add_argument("--date", required=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--topic", default="pokemon-card-watch")
    p.add_argument("--model-route", default="pokemon_collection_dedupe")
    p.add_argument("--max-links", type=int, default=20)
    return p.parse_args()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS topic_ai_summaries (
          topic TEXT NOT NULL,
          date TEXT NOT NULL,
          kind TEXT NOT NULL,
          provider TEXT,
          model TEXT,
          summary TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(topic, date, kind)
        )
        """
    )


def main() -> int:
    args = parse_args()
    provider, model = resolve_model(args.model_route)
    if provider != "openai":
        print(f"skip: provider unsupported {provider}")
        return 0
    conn = sqlite3.connect(args.db)
    try:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT url,label
            FROM topic_links
            WHERE topic=? AND date=?
            ORDER BY url
            LIMIT ?
            """,
            (args.topic, args.date, args.max_links),
        ).fetchall()
        if not rows:
            print("skip: no topic_links")
            return 0
        payload = [{"url": r[0], "label": r[1]} for r in rows]
        text, _raw = call_openai_text(
            model=model,
            system_text="あなたは情報収集オペレーター。重複統合と一次情報優先を行う。",
            user_text=(
                "以下のポケカ記事リンクを重複統合し、"
                "1) 直近1週間の優勝デッキ/環境記事 2) 抽選/再販/予約情報 に分類して、"
                "各項目に代表URLを付けて短く出してください。"
                f"\n\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
            ),
        )
        conn.execute(
            """
            INSERT INTO topic_ai_summaries(topic,date,kind,provider,model,summary,updated_at)
            VALUES(?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(topic,date,kind) DO UPDATE SET
              provider=excluded.provider,
              model=excluded.model,
              summary=excluded.summary,
              updated_at=excluded.updated_at
            """,
            (args.topic, args.date, "dedupe_summary", provider, model, text),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"saved: topic_ai_summaries {args.topic} {args.date} dedupe_summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
