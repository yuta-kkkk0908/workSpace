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
SECTION_RE = re.compile(r"^##\s+(.*)$")
ITEM_RE = re.compile(r"^(?:###\s+)?(?:(?P<item_key>[A-Za-z0-9_:-]+)\s*:\s*)?(?P<title>.+?)\s*$")
NUMBERED_RE = re.compile(r"^\d+\.\s+(?P<title>.+?)\s*$")
FIELD_RE = re.compile(r"^\s*-\s+([^:：]+)[:：]\s*(.*)$")


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
        if topic == "pokemon-card-watch":
            if "daily" not in suffix and "source-plan" not in suffix:
                continue
        elif "daily" not in suffix:
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


def normalize_section(section: str) -> str:
    return re.sub(r"\s+", " ", section).strip()


def file_kind_from_path(path: Path) -> str:
    stem = path.stem
    if stem.endswith("source-plan"):
        return "source-plan"
    if stem.endswith("daily"):
        return "daily"
    return "note"


def parse_pokemon_watch_rows(text: str, topic: str, date: str, source_path: str, file_kind: str) -> list[dict]:
    if file_kind == "source-plan":
        return []

    rows: list[dict] = []
    section = ""
    current: dict | None = None
    raw_lines: list[str] = []

    def flush() -> None:
        nonlocal current, raw_lines
        if not current:
            return
        current["raw_text"] = "\n".join(raw_lines).strip()
        rows.append(current)
        current = None
        raw_lines = []

    def start_item(title: str, item_key: str = "", kind: str = "") -> None:
        nonlocal current, raw_lines
        flush()
        title = title.strip()
        current = {
            "topic": topic,
            "date": date,
            "source_path": source_path,
            "file_kind": file_kind,
            "section": section,
            "item_key": item_key or title[:64],
            "title": title.strip(),
            "kind": kind or "item",
            "status": "unknown",
            "source_name": "",
            "media": "",
            "url": "",
            "product": "",
            "release_date": "",
            "start_text": "",
            "end_text": "",
            "deadline_text": "",
            "condition_text": "",
            "rank_text": "",
            "summary": "",
            "why_it_matters": "",
            "action_text": "",
            "notes": "",
        }
        if title.startswith("商品名:"):
            current["product"] = title.split(":", 1)[1].strip()
        elif title.startswith("テーマ:"):
            current["summary"] = title.split(":", 1)[1].strip()
        raw_lines = [title.strip()]

    def set_field(key: str, value: str) -> None:
        if current is None:
            return
        key = key.strip().lower()
        value = value.strip()
        raw_lines.append(f"- {key}: {value}")
        if key in {"source", "媒体", "media"}:
            current["source_name"] = value
            if key == "media":
                current["media"] = value
        elif key in {"url", "urls"}:
            if not current["url"] and value:
                current["url"] = value
        elif key in {"product", "商品名"}:
            current["product"] = value
        elif key in {"releasedate", "release date"}:
            current["release_date"] = value
        elif key in {"受付", "区分", "受付区分"}:
            current["status"] = value
        elif key in {"締切", "deadline"}:
            current["deadline_text"] = value
        elif key in {"条件", "応募条件"}:
            current["condition_text"] = value
        elif key in {"start", "startat", "受付開始"}:
            current["start_text"] = value
        elif key in {"end", "endat", "受付終了"}:
            current["end_text"] = value
        elif key in {"順位", "rank"}:
            current["rank_text"] = value
        elif key in {"summary", "要約", "read"}:
            current["summary"] = value
        elif key in {"whyitmatters", "why it matters"}:
            current["why_it_matters"] = value
        elif key in {"action", "nextcheck", "next check"}:
            current["action_text"] = value
        elif key in {"notes", "note", "備考"}:
            current["notes"] = value
        elif key in {"status"}:
            current["status"] = value
        else:
            if value:
                current["notes"] = (current["notes"] + "\n" + f"{key}: {value}").strip() if current["notes"] else f"{key}: {value}"

    def handle_nc(line: str) -> None:
        nonlocal current
        flush()
        current = {
            "topic": topic,
            "date": date,
            "source_path": source_path,
            "file_kind": file_kind,
            "section": section,
            "item_key": "nc",
            "title": "N/C",
            "kind": "check",
            "status": "N/C",
            "source_name": "",
            "media": "",
            "url": "",
            "product": "",
            "release_date": "",
            "start_text": "",
            "end_text": "",
            "deadline_text": "",
            "condition_text": "",
            "rank_text": "",
            "summary": line.strip(),
            "why_it_matters": "",
            "action_text": "",
            "notes": "",
            "raw_text": line.strip(),
        }
        rows.append(current)
        current = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current is not None:
                raw_lines.append("")
            continue
        m = SECTION_RE.match(line)
        if m:
            flush()
            section = normalize_section(m.group(1))
            continue
        if stripped.startswith("# "):
            continue
        if stripped.startswith("- N/C"):
            handle_nc(stripped)
            continue
        item_match = None
        if stripped.startswith("### "):
            item_match = ITEM_RE.match(stripped)
        elif NUMBERED_RE.match(stripped):
            item_match = NUMBERED_RE.match(stripped)
        if item_match:
            title = item_match.groupdict().get("title") or stripped
            item_key = item_match.groupdict().get("item_key") or ""
            kind = (
                "lottery"
                if ("Lottery" in section or "抽選" in section or "再販" in section or "販売" in section)
                else "deck"
                if ("Deck" in section or "デッキ" in section or "環境" in section)
                else "item"
            )
            start_item(title=title, item_key=item_key, kind=kind)
            continue
        field_match = FIELD_RE.match(line)
        if field_match and current is not None:
            set_field(field_match.group(1), field_match.group(2))
            continue
        if current is not None:
            raw_lines.append(stripped)
            if not current["summary"] and stripped and not stripped.startswith("-"):
                current["summary"] = stripped
            if not current["url"]:
                urls = URL_RE.findall(stripped)
                if urls:
                    current["url"] = urls[0]

    flush()
    return rows


def replace_pokemon_items(
    conn: sqlite3.Connection,
    topic: str,
    date: str,
    rel_path: str,
    file_kind: str,
    items: list[dict],
) -> int:
    conn.execute(
        "DELETE FROM pokemon_watch_items WHERE topic=? AND date=? AND source_path=? AND file_kind=?",
        (topic, date, rel_path, file_kind),
    )
    rows = 0
    for item in items:
        conn.execute(
            """
            INSERT INTO pokemon_watch_items(
              topic,date,source_path,file_kind,section,item_key,title,kind,status,source_name,media,url,
              product,release_date,start_text,end_text,deadline_text,condition_text,rank_text,summary,
              why_it_matters,action_text,notes,raw_text,collected_at,updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item.get("topic", topic),
                item.get("date", date),
                item.get("source_path", rel_path),
                item.get("file_kind", file_kind),
                item.get("section", ""),
                item.get("item_key", ""),
                item.get("title", ""),
                item.get("kind", "item"),
                item.get("status", "unknown"),
                item.get("source_name", ""),
                item.get("media", ""),
                item.get("url", ""),
                item.get("product", ""),
                item.get("release_date", ""),
                item.get("start_text", ""),
                item.get("end_text", ""),
                item.get("deadline_text", ""),
                item.get("condition_text", ""),
                item.get("rank_text", ""),
                item.get("summary", ""),
                item.get("why_it_matters", ""),
                item.get("action_text", ""),
                item.get("notes", ""),
                item.get("raw_text", ""),
                now(),
                now(),
            ),
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
                file_kind = file_kind_from_path(p)
                if file_kind != "source-plan":
                    upsert_digest(conn, topic, date, rel, summarize(text))
                links = extract_links(text)
                link_rows = replace_links(conn, topic, date, rel, links)
                pokemon_rows = 0
                if topic == "pokemon-card-watch":
                    items = parse_pokemon_watch_rows(text, topic, date, rel, file_kind)
                    pokemon_rows = replace_pokemon_items(conn, topic, date, rel, file_kind, items)
                ingest_kind = "topic_source_plan" if file_kind == "source-plan" else "topic_daily"
                conn.execute(
                    "INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)",
                    (now(), ingest_kind, rel, 1 + link_rows + pokemon_rows),
                )
        conn.commit()
    finally:
        conn.close()
    print(f"ingested into {db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
