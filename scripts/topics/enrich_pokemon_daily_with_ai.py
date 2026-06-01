#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import urllib.request
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.ai_model_router import resolve_model

DEFAULT_TOPIC = "pokemon-card-watch"
AI_HEADER = "## AI Collection Summary"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Append AI summary section to pokemon daily collection note.")
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--topic", default=DEFAULT_TOPIC)
    p.add_argument("--model", default="", help="Optional explicit model override.")
    p.add_argument("--model-route", default="pokemon_collection_summary")
    p.add_argument("--db", type=Path, default=ROOT / "data" / "topics.db")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_daily(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"daily note not found: {path}")
    return path.read_text(encoding="utf-8")


def build_prompt(md: str, target_date: str) -> str:
    trimmed = md
    if len(trimmed) > 10000:
        trimmed = trimmed[:10000]
    return (
        f"以下は {target_date} のポケカ収集メモです。\n"
        "売買助言はせず、収集オペレーション向けに要点を日本語で短くまとめてください。\n"
        "出力ルール:\n"
        "- 5行以内の全体要約\n"
        "- 直近1週間の優勝デッキ/環境デッキ注目点（最大3件、記事URLつき）\n"
        "- 抽選/再販トピックの重要更新（最大4件、記事URLつき）\n"
        "- 追加収集すべき観点2件\n\n"
        f"{trimmed}"
    )


def call_openai(model: str, prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is empty")
    req_body = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": "あなたはポケカ情報収集アナリストです。"}]},
            {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
        ],
    }
    data = json.dumps(req_body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "aios-pokemon-collection-summary/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    parsed = json.loads(raw)
    text = (parsed.get("output_text") or "").strip()
    if not text:
        out = parsed.get("output") or []
        chunks: list[str] = []
        if isinstance(out, list):
            for item in out:
                if not isinstance(item, dict):
                    continue
                content = item.get("content") or []
                if not isinstance(content, list):
                    continue
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "output_text":
                        t = str(c.get("text") or "").strip()
                        if t:
                            chunks.append(t)
        text = "\n".join(chunks).strip()
    if not text:
        err = parsed.get("error")
        if err:
            raise RuntimeError(f"OpenAI API error: {err}")
        raise RuntimeError("empty response text from OpenAI")
    return text


def remove_existing_ai_block(md: str) -> str:
    pattern = rf"\n{re.escape(AI_HEADER)}\n[\s\S]*$"
    return re.sub(pattern, "", md).rstrip() + "\n"


def ensure_topics_schema(conn: sqlite3.Connection) -> None:
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


def save_to_topics_db(db_path: Path, topic: str, target_date: str, provider: str, model: str, summary: str) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        ensure_topics_schema(conn)
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
            (topic, target_date, "collection_summary", provider, model, summary),
        )
        conn.commit()
    finally:
        conn.close()


def dry_run_text(target_date: str) -> str:
    return (
        f"[DRY RUN] {target_date} ポケカ収集AI要約\n"
        "- 全体要約: DRY RUNのためAI本文生成は未実行。\n"
        "- 重要ニュース: 収集記事の媒体分散と鮮度を優先確認。\n"
        "- 追加収集観点: 再販/抽選期限の一次情報URLを優先。\n"
    )


def main() -> int:
    args = parse_args()
    load_dotenv()
    note_path = ROOT / "topics" / args.topic / "inbox" / f"{args.date}-daily.md"
    md = load_daily(note_path)

    provider, route_model = resolve_model(args.model_route)
    model = args.model.strip() or route_model
    if provider != "openai":
        print(f"[skip] unsupported provider for this script: {provider}")
        return 0

    if args.dry_run:
        summary = dry_run_text(args.date)
    else:
        if not os.getenv("OPENAI_API_KEY", "").strip():
            print("[skip] OPENAI_API_KEY is empty")
            return 0
        summary = call_openai(model, build_prompt(md, args.date))

    db_saved = False
    try:
        save_to_topics_db(args.db, args.topic, args.date, provider, model, summary.strip())
        db_saved = True
        print(f"saved_to_db: {args.db} topic={args.topic} date={args.date}")
    except Exception as e:
        print(f"[warn] db_save_failed: {e}")

    if not db_saved:
        base = remove_existing_ai_block(md)
        updated = base + f"\n{AI_HEADER}\n- provider: {provider}\n- model: {model}\n\n{summary.strip()}\n"
        note_path.write_text(updated, encoding="utf-8")
        print(f"fallback_updated_file: {note_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
