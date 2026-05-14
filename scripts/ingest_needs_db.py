#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "topics" / "product-idea-watch" / "inbox"
DEFAULT_DB = ROOT / "data" / "needs.db"

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
HEAD_A_RE = re.compile(r"^###\s+(need_\d{8}_\d{3}):\s*(.+)$")
HEAD_B_RE = re.compile(r"^###\s+(\d+)\.\s*(.+)$")
KV_RE = re.compile(r"^-\s+([A-Za-z0-9_]+):\s*(.*)$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest product-idea-watch needs into SQLite")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--date", help="target date YYYY-MM-DD (optional)")
    return p.parse_args()


def iter_files(date: str | None) -> list[Path]:
    out: list[Path] = []
    for p in sorted(INBOX.glob("*.md")):
        if "need-watch" not in p.name and "daily-background-need-watch" not in p.name:
            continue
        m = DATE_RE.match(p.name)
        if not m:
            continue
        if date and m.group(1) != date:
            continue
        out.append(p)
    return out


def parse_blocks(text: str, date: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    rows: list[dict[str, str]] = []
    i = 0
    auto_idx = 1
    while i < len(lines):
        line = lines[i].strip()
        m1 = HEAD_A_RE.match(line)
        m2 = HEAD_B_RE.match(line)
        if not (m1 or m2):
            i += 1
            continue

        if m1:
            need_id = m1.group(1).strip()
            title = m1.group(2).strip()
        else:
            need_id = f"need_{date.replace('-', '')}_bg_{auto_idx:03d}"
            auto_idx += 1
            title = m2.group(2).strip()

        block: dict[str, str] = {
            "need_id": need_id,
            "title": title,
            "category": "",
            "pain": "",
            "request": "",
            "existingAlternative": "",
            "buildability": "",
            "validation": "",
            "source": "",
            "source_url": "",
            "confidence": "",
        }

        j = i + 1
        while j < len(lines):
            nxt = lines[j].strip()
            if HEAD_A_RE.match(nxt) or HEAD_B_RE.match(nxt):
                break
            kv = KV_RE.match(nxt)
            if kv:
                k, v = kv.group(1), kv.group(2).strip()
                if k == "category":
                    block["category"] = v
                elif k == "pain":
                    block["pain"] = v
                elif k == "request":
                    block["request"] = v
                elif k == "existingAlternative":
                    block["existingAlternative"] = v
                elif k == "buildability":
                    block["buildability"] = v
                elif k == "validation":
                    block["validation"] = v
                elif k == "source":
                    block["source"] = v
                elif k == "Source":
                    block["source_url"] = v
                elif k == "Need":
                    if not block["pain"]:
                        block["pain"] = v
                elif k == "Opportunity":
                    if not block["request"]:
                        block["request"] = v
                elif k == "Confidence":
                    block["confidence"] = v.lower()
            else:
                if nxt.startswith("- Source: "):
                    block["source_url"] = nxt.replace("- Source: ", "", 1).strip()
                elif nxt.startswith("- Need: ") and not block["pain"]:
                    block["pain"] = nxt.replace("- Need: ", "", 1).strip()
                elif nxt.startswith("- Opportunity: ") and not block["request"]:
                    block["request"] = nxt.replace("- Opportunity: ", "", 1).strip()
                elif nxt.startswith("- Confidence: "):
                    block["confidence"] = nxt.replace("- Confidence: ", "", 1).strip().lower()
            j += 1
        rows.append(block)
        i = j
    return rows


def upsert(conn: sqlite3.Connection, path: Path, rows: list[dict[str, str]]) -> int:
    date = path.name[:10]
    rel = str(path.relative_to(ROOT))
    inserted = 0
    for r in rows:
        nid = r.get("need_id", "")
        conn.execute(
            """
            INSERT INTO need_items(
              need_id,date,topic,title,category,pain,request,existing_alternative,buildability,validation,
              source_label,source_url,confidence,source_path,updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(need_id,date,source_path) DO UPDATE SET
              title=excluded.title,category=excluded.category,pain=excluded.pain,request=excluded.request,
              existing_alternative=excluded.existing_alternative,buildability=excluded.buildability,
              validation=excluded.validation,source_label=excluded.source_label,source_url=excluded.source_url,
              confidence=excluded.confidence,updated_at=excluded.updated_at
            """,
            (
                nid,
                date,
                "product-idea-watch",
                r.get("title", ""),
                r.get("category", ""),
                r.get("pain", ""),
                r.get("request", ""),
                r.get("existingAlternative", ""),
                r.get("buildability", ""),
                r.get("validation", ""),
                r.get("source", ""),
                r.get("source_url", ""),
                r.get("confidence", ""),
                rel,
                now(),
            ),
        )
        conn.execute(
            """
            INSERT INTO need_item_state(need_id,date,source_path,status,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(need_id,date,source_path) DO NOTHING
            """,
            (nid, date, rel, "new", now()),
        )
        inserted += 1
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "need_items", rel, inserted))
    return inserted


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    files = iter_files(args.date)
    conn = sqlite3.connect(db)
    total = 0
    try:
        for p in files:
            date = p.name[:10]
            rows = parse_blocks(p.read_text(encoding="utf-8"), date)
            total += upsert(conn, p, rows)
        conn.commit()
    finally:
        conn.close()
    print(f"ingested into {db} rows={total} files={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
