#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOPICS_DIR = ROOT / "topics"
DEFAULT_DB = ROOT / "data" / "topics.db"

DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
URL_RE = re.compile(r"https?://[^\s\])>]+")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest non-investment topic inbox markdown into SQLite")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--date", help="target date YYYY-MM-DD (optional)")
    p.add_argument("--include-kinds", default="daily-watch,notification-watch", help="comma separated topic kinds")
    return p.parse_args()


def load_topic_manifests(include_kinds: set[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for topic_dir in sorted(TOPICS_DIR.iterdir()):
        if not topic_dir.is_dir():
            continue
        if topic_dir.name == "investment-research":
            continue
        manifest = topic_dir / "topic-manifest.json"
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        kind = str(data.get("kind", ""))
        if kind in include_kinds:
            out.append((topic_dir.name, kind))
    return out


def target_files(topic: str, date: str | None) -> list[Path]:
    inbox = TOPICS_DIR / topic / "inbox"
    if not inbox.exists():
        return []
    files = sorted(p for p in inbox.glob("*.md") if p.is_file())
    out: list[Path] = []
    for p in files:
        m = DATE_FILE_RE.match(p.name)
        if not m:
            continue
        d, suffix = m.group(1), m.group(2)
        if date and d != date:
            continue
        if "daily" not in suffix:
            continue
        out.append(p)
    return out


def summarize(text: str, max_lines: int = 8) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    preferred: list[str] = []
    in_headlines = False
    for ln in lines:
        low = ln.lower()
        if low.startswith("## headlines"):
            in_headlines = True
            continue
        if in_headlines:
            if re.match(r"^\d+\.\s+", ln):
                preferred.append(ln)
                continue
            if ln.startswith("- 要約:"):
                preferred.append(ln)
                continue
            if ln.startswith("- 掲載時刻:"):
                preferred.append(ln)
                continue
            if ln.startswith("- http") or ln.startswith("http"):
                preferred.append(ln)
                continue
        # Fallback summary lines (exclude topic metadata)
        if ln.startswith("- slug:") or ln.startswith("- date:") or ln.startswith("- mode:") or ln.startswith("- caution:") or ln.startswith("- collectedAt:"):
            continue
        if ln.startswith("## Topic") or ln.startswith("# "):
            continue
        preferred.append(ln)
    return "\n".join(preferred[:max_lines])


def extract_links(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for ln in text.splitlines():
        urls = URL_RE.findall(ln)
        if not urls:
            continue
        label = ln.strip()
        for u in urls:
            rows.append((u, label[:220]))
    # unique by URL while keeping first label
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for u, label in rows:
        if u in seen:
            continue
        seen.add(u)
        uniq.append((u, label))
    return uniq


def upsert_digest(conn: sqlite3.Connection, topic: str, date: str, rel_path: str, summary: str) -> None:
    conn.execute(
        """
        INSERT INTO topic_daily_digest(topic,date,path,summary,updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(topic,date) DO UPDATE SET
        path=excluded.path,summary=excluded.summary,updated_at=excluded.updated_at
        """,
        (topic, date, rel_path, summary, now()),
    )


def replace_links(conn: sqlite3.Connection, topic: str, date: str, rel_path: str, links: list[tuple[str, str]]) -> int:
    conn.execute("DELETE FROM topic_links WHERE topic=? AND date=? AND path=?", (topic, date, rel_path))
    rows = 0
    for url, label in links:
        conn.execute(
            """
            INSERT INTO topic_links(topic,date,path,url,label,updated_at)
            VALUES(?,?,?,?,?,?)
            """,
            (topic, date, rel_path, url, label, now()),
        )
        rows += 1
    return rows


def main() -> int:
    args = parse_args()
    include_kinds = {k.strip() for k in args.include_kinds.split(",") if k.strip()}
    targets = load_topic_manifests(include_kinds)
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        for topic, _kind in targets:
            for p in target_files(topic, args.date):
                text = p.read_text(encoding="utf-8")
                m = DATE_FILE_RE.match(p.name)
                if not m:
                    continue
                date = m.group(1)
                rel = str(p.relative_to(ROOT))
                upsert_digest(conn, topic, date, rel, summarize(text))
                links = extract_links(text)
                link_rows = replace_links(conn, topic, date, rel, links)
                conn.execute(
                    "INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)",
                    (now(), "topic_daily", rel, 1 + link_rows),
                )
        conn.commit()
    finally:
        conn.close()
    print(f"ingested into {db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
