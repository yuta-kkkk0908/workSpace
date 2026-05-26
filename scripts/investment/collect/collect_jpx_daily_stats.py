#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
JPX_DAILY_URL = "https://www.jpx.co.jp/markets/statistics-equities/daily/03.html"
JST = timezone(timedelta(hours=9))
USER_AGENT = "AIOSResearchBot/1.0 (JPX daily collector)"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect JPX daily-statistics page metadata into DB")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--url", default=JPX_DAILY_URL)
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--max-links", type=int, default=300)
    p.add_argument("--raw-keep-days", type=int, default=14)
    return p.parse_args()


def fetch_html(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def discover_links(base_url: str, html_text: str, max_links: int) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    pat = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
    for href, label_raw in pat.findall(html_text):
        href = href.strip()
        if not href:
            continue
        if not re.search(r"\.(csv|xls|xlsx|zip|pdf)$", href, re.I):
            continue
        label = re.sub(r"<[^>]+>", " ", label_raw)
        label = re.sub(r"\s+", " ", label).strip()
        if href.startswith("/"):
            full = "https://www.jpx.co.jp" + href
        elif href.startswith("http"):
            full = href
        else:
            full = str(Path(base_url).parent).rstrip("/") + "/" + href.lstrip("./")
        kind = re.sub(r"^.*\.([A-Za-z0-9]+)(?:\?.*)?$", r"\1", href).lower()
        lane = "pdf_backfill" if kind == "pdf" else "non_pdf_preferred"
        found.append({"url": full, "label": label, "kind": kind, "lane": lane})
        if len(found) >= max_links:
            break
    return found


def main() -> int:
    args = parse_args()
    html_text = fetch_html(args.url, args.timeout)
    links = discover_links(args.url, html_text, args.max_links)
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    try:
        inserted = 0
        for row in links:
            payload = {
                "date": args.date,
                "page_url": args.url,
                "file_url": row["url"],
                "label": row["label"],
                "kind": row.get("kind", ""),
                "lane": row.get("lane", "non_pdf_preferred"),
            }
            event_hash = hashlib.sha256(
                f"{args.date}|{row['url']}|{row['label']}".encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO raw_events(
                  event_hash,source_kind,source_url,event_time,ticker,ingest_date,fetched_at,payload_json,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_kind,event_hash) DO UPDATE SET
                  source_url=excluded.source_url,
                  event_time=excluded.event_time,
                  ingest_date=excluded.ingest_date,
                  fetched_at=excluded.fetched_at,
                  payload_json=excluded.payload_json,
                  source_path=excluded.source_path,
                  updated_at=excluded.updated_at
                """,
                (
                    event_hash,
                    "jpx_daily",
                    row["url"],
                    f"{args.date}T00:00:00+09:00",
                    "",
                    args.date,
                    now_utc,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    "scripts/investment/collect/collect_jpx_daily_stats.py",
                    now_utc,
                ),
            )
            inserted += 1

        conn.execute(
            """
            INSERT INTO collection_progress(source,partition_key,last_date,status,last_run_at,error_message,updated_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(source,partition_key) DO UPDATE SET
              last_date=excluded.last_date,
              status=excluded.status,
              last_run_at=excluded.last_run_at,
              error_message=excluded.error_message,
              updated_at=excluded.updated_at
            """,
            ("jpx_daily", "03.html", args.date, "ok", now_utc, "", now_utc),
        )
        cutoff = (datetime.strptime(args.date, "%Y-%m-%d").date() - timedelta(days=max(1, args.raw_keep_days))).strftime("%Y-%m-%d")
        conn.execute("DELETE FROM raw_events WHERE source_kind='jpx_daily' AND ingest_date < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()

    print(f"jpx_daily collected date={args.date} links={len(links)} raw_rows_upserted={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
