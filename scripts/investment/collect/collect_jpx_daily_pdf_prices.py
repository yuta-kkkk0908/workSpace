#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()
DEFAULT_INDEX_URL = "https://www.jpx.co.jp/markets/statistics-equities/daily/index.html"
DEFAULT_OUT_DIR = ROOT / "resource" / "invest"

LINK_RE = re.compile(r'href="([^"]*stq_(\d{8})\.pdf[^"]*)"', re.I)
ROW_RE = re.compile(r"^((?:\d{4})|(?:\d{3}[A-Z]))\s+([0-9,]+)(.+?)\s+([0-9,\.\-－].+)$")
NUM_RE = re.compile(r"(?:-?\d[\d,]*(?:\.\d+)?)|(?:－)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect daily OHLCV from JPX stock quotations PDF (stq_YYYYMMDD.pdf).")
    p.add_argument("--date", default=None, help="Target trading date YYYY-MM-DD (default: JST yesterday)")
    p.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    p.add_argument("--pdf-url", default=None, help="Direct PDF URL override")
    p.add_argument("--pdf-path", type=Path, default=None, help="Local PDF path override")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--max-pages", type=int, default=0, help="0 means all pages")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def target_date_yyyymmdd(date_arg: str | None) -> str:
    if date_arg:
        return datetime.strptime(date_arg, "%Y-%m-%d").strftime("%Y%m%d")
    return (datetime.now(JST).date() - timedelta(days=1)).strftime("%Y%m%d")


def month_delta(base_yyyymm: str, target_yyyymm: str) -> int:
    by, bm = int(base_yyyymm[:4]), int(base_yyyymm[4:6])
    ty, tm = int(target_yyyymm[:4]), int(target_yyyymm[4:6])
    return (by - ty) * 12 + (bm - tm)


def candidate_index_pages(index_url: str, target_yyyymmdd: str, max_archive_pages: int = 24) -> list[str]:
    parsed = urllib.parse.urlparse(index_url)
    base_path = parsed.path.rsplit("/", 1)[0] + "/"
    base_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, base_path, "", "", ""))
    today_yyyymm = datetime.now(JST).strftime("%Y%m")
    target_yyyymm = target_yyyymmdd[:6]
    delta = max(0, month_delta(today_yyyymm, target_yyyymm))
    pages: list[str] = [urllib.parse.urljoin(base_url, "index.html")]
    if delta >= 1:
        pages.insert(0, urllib.parse.urljoin(base_url, f"00-archives-{delta:02d}.html"))
        # Some pages use singular "archive" in navigation/query values.
        pages.insert(1, urllib.parse.urljoin(base_url, f"00-archive-{delta:02d}.html"))
    # Add neighboring archive pages as fallback when month boundaries are tricky.
    start = max(1, delta - 1)
    end = min(max_archive_pages, max(delta + 2, 4))
    for i in range(start, end + 1):
        pages.append(urllib.parse.urljoin(base_url, f"00-archives-{i:02d}.html"))
        pages.append(urllib.parse.urljoin(base_url, f"00-archive-{i:02d}.html"))
    # De-dup while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for p in pages:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def pick_pdf_url(index_url: str, target_yyyymmdd: str) -> tuple[str, str]:
    matches: list[tuple[str, str]] = []
    pages = candidate_index_pages(index_url, target_yyyymmdd)
    for page in pages:
        try:
            raw = urllib.request.urlopen(page, timeout=20).read().decode("utf-8", "ignore")
        except Exception:
            continue
        for m in LINK_RE.finditer(raw):
            href, ymd = m.group(1), m.group(2)
            matches.append((urllib.parse.urljoin(page, href), ymd))
        # If exact date was found on this page, stop early.
        if any(ymd == target_yyyymmdd for _, ymd in matches):
            break
    if not matches:
        raise RuntimeError("stq PDF link not found on JPX index page")
    # Prefer exact date; fallback to latest available not newer than target.
    exact = [m for m in matches if m[1] == target_yyyymmdd]
    if exact:
        pdf_url, ymd = exact[0]
    else:
        older = sorted((m for m in matches if m[1] <= target_yyyymmdd), key=lambda x: x[1], reverse=True)
        if older:
            pdf_url, ymd = older[0]
        else:
            pdf_url, ymd = sorted(matches, key=lambda x: x[1], reverse=True)[0]
    return pdf_url, ymd


def download_pdf(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = urllib.request.urlopen(url, timeout=30).read()
    out_path.write_bytes(data)


def parse_num(s: str) -> float | None:
    t = s.strip()
    if t in {"－", ""}:
        return None
    return float(t.replace(",", ""))


def parse_pdf_rows(pdf_path: Path, max_pages: int = 0) -> list[dict]:
    rows: list[dict] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = pdf.pages if max_pages <= 0 else pdf.pages[:max_pages]
        for page in pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                m = ROW_RE.match(line)
                if not m:
                    continue
                ticker = m.group(1)
                company = m.group(3).strip()
                rest = m.group(4)
                nums = NUM_RE.findall(rest)
                if len(nums) < 13:
                    continue
                vals = [parse_num(x) for x in nums[-13:]]
                mo, mh, ml, mc, ao, ah, al, ac = vals[0], vals[1], vals[2], vals[3], vals[4], vals[5], vals[6], vals[7]
                vol_k = vals[11]
                if mo is None or ac is None:
                    continue
                highs = [x for x in [mh, ah, mo, ac] if x is not None]
                lows = [x for x in [ml, al, mo, ac] if x is not None]
                if not highs or not lows or vol_k is None:
                    continue
                rows.append(
                    {
                        "ticker": ticker,
                        "company": company,
                        "open": float(mo),
                        "high": float(max(highs)),
                        "low": float(min(lows)),
                        "close": float(ac),
                        "volume": int(round(float(vol_k) * 1000)),
                    }
                )
    # Dedup by ticker (keep first appearance)
    out: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        t = r["ticker"]
        if t in seen:
            continue
        seen.add(t)
        out.append(r)
    return out


def upsert_prices(db: Path, trade_date: str, rows: list[dict], source_url: str) -> int:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS facts_price_daily (
              date TEXT NOT NULL,
              ticker TEXT NOT NULL,
              open REAL,
              high REAL,
              low REAL,
              close REAL,
              volume INTEGER,
              source_kind TEXT NOT NULL,
              source_url TEXT,
              fetched_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(date, ticker)
            )
            """
        )
        n = 0
        for r in rows:
            conn.execute(
                """
                INSERT INTO facts_price_daily(date,ticker,open,high,low,close,volume,source_kind,source_url,fetched_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(date,ticker) DO UPDATE SET
                  open=excluded.open,
                  high=excluded.high,
                  low=excluded.low,
                  close=excluded.close,
                  volume=excluded.volume,
                  source_kind=excluded.source_kind,
                  source_url=excluded.source_url,
                  fetched_at=excluded.fetched_at,
                  updated_at=excluded.updated_at
                """,
                (
                    trade_date,
                    r["ticker"],
                    r["open"],
                    r["high"],
                    r["low"],
                    r["close"],
                    r["volume"],
                    "jpx_stq_pdf",
                    source_url,
                    now,
                    now,
                ),
            )
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    target = target_date_yyyymmdd(args.date)
    if args.pdf_path:
        pdf_path = args.pdf_path
        trade_ymd = re.search(r"(\d{8})", pdf_path.name)
        ymd = trade_ymd.group(1) if trade_ymd else target
        source_url = args.pdf_url or f"file:{pdf_path}"
    else:
        pdf_url, ymd = (args.pdf_url, target) if args.pdf_url else pick_pdf_url(args.index_url, target)
        if not pdf_url:
            raise RuntimeError("pdf url not resolved")
        pdf_path = args.out_dir / f"stq_{ymd}.pdf"
        download_pdf(pdf_url, pdf_path)
        source_url = pdf_url
    trade_date = datetime.strptime(ymd, "%Y%m%d").strftime("%Y-%m-%d")
    rows = parse_pdf_rows(pdf_path, max_pages=args.max_pages)
    if args.dry_run:
        print(f"dry_run trade_date={trade_date} rows={len(rows)} pdf={pdf_path}")
        return 0
    upserted = upsert_prices(args.db, trade_date, rows, source_url)
    print(f"trade_date={trade_date} pdf={pdf_path} rows={len(rows)} upserted={upserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
