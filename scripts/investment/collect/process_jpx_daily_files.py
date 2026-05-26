#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
USER_AGENT = "AIOSResearchBot/1.0 (JPX file processor)"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Process JPX daily manifest links (non-PDF preferred; PDF to backfill lane)")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--max-files", type=int, default=20)
    p.add_argument("--timeout", type=float, default=20.0)
    return p.parse_args()


def ext_kind(url: str) -> str:
    m = re.search(r"\.([A-Za-z0-9]+)(?:\?|$)", url)
    if not m:
        return ""
    return m.group(1).lower()


def fetch_bytes(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def decode_text(b: bytes) -> str:
    for enc in ("utf-8-sig", "cp932", "shift_jis", "utf-8"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode("latin1", "ignore")


def normalize_header(h: str) -> str:
    s = h.strip().lower()
    s = s.replace(" ", "").replace("_", "")
    s = s.replace("日付", "date").replace("銘柄コード", "ticker").replace("コード", "ticker")
    s = s.replace("始値", "open").replace("高値", "high").replace("安値", "low").replace("終値", "close")
    s = s.replace("出来高", "volume")
    return s


def parse_price_csv(text: str) -> list[dict]:
    rdr = csv.reader(io.StringIO(text))
    rows = list(rdr)
    if not rows:
        return []
    header = [normalize_header(x) for x in rows[0]]
    idx = {k: i for i, k in enumerate(header)}
    required = ("ticker", "date", "open", "high", "low", "close")
    if not all(k in idx for k in required):
        return []
    out: list[dict] = []
    for r in rows[1:]:
        try:
            ticker = str(r[idx["ticker"]]).strip()
            date_raw = str(r[idx["date"]]).strip()
            d = normalize_date(date_raw)
            if not ticker or not d:
                continue
            out.append(
                {
                    "ticker": ticker[:5],
                    "date": d,
                    "open": to_float(r[idx["open"]]),
                    "high": to_float(r[idx["high"]]),
                    "low": to_float(r[idx["low"]]),
                    "close": to_float(r[idx["close"]]),
                    "volume": to_int(r[idx["volume"]]) if "volume" in idx else None,
                }
            )
        except Exception:
            continue
    return [r for r in out if None not in (r["open"], r["high"], r["low"], r["close"])]


def normalize_date(v: str) -> str:
    s = v.strip().replace("/", "-").replace(".", "-")
    m = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if re.match(r"^\d{8}$", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return ""


def to_float(v: str) -> float | None:
    s = str(v).strip().replace(",", "")
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def to_int(v: str) -> int | None:
    s = str(v).strip().replace(",", "")
    if s == "":
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def parse_pdf_numbers(raw: bytes) -> dict:
    text = raw.decode("latin1", "ignore")
    nums = [int(x.replace(",", "")) for x in re.findall(r"\b\d[\d,]{0,14}\b", text)]
    nums = [n for n in nums if 0 <= n < 10**13]
    digit_check_pass = len(nums) > 0
    sum_check_pass = False
    sum_check_detail = "no_total_pair"
    if len(nums) >= 3:
        top = sorted(nums, reverse=True)[:12]
        declared = top[0]
        subtotal = sum(top[1:])
        # permissive check: subtotal near declared within 5%
        if declared > 0:
            diff = abs(subtotal - declared) / declared
            sum_check_pass = diff <= 0.05
            sum_check_detail = f"declared={declared} subtotal={subtotal} diff={diff:.4f}"
    return {
        "numbers_count": len(nums),
        "sample_numbers": nums[:30],
        "digit_check_pass": digit_check_pass,
        "sum_check_pass": sum_check_pass,
        "sum_check_detail": sum_check_detail,
    }


def main() -> int:
    args = parse_args()
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = sqlite3.connect(args.db)
    try:
        rows = conn.execute(
            """
            SELECT source_url,payload_json
            FROM raw_events
            WHERE source_kind='jpx_daily' AND ingest_date=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (args.date, args.max_files),
        ).fetchall()
        csv_like = []
        pdf_like = []
        for url, payload in rows:
            kind = ext_kind(str(url or ""))
            if kind in ("csv", "xls", "xlsx", "zip"):
                csv_like.append((str(url), str(payload or "")))
            elif kind == "pdf":
                pdf_like.append((str(url), str(payload or "")))

        facts_upserted = 0
        pdf_processed = 0
        for url, _payload in csv_like:
            kind = ext_kind(url)
            if kind != "csv":
                # xls/xlsx/zip are kept as non-pdf preferred lane manifest for now.
                continue
            try:
                body = fetch_bytes(url, args.timeout)
                parsed = parse_price_csv(decode_text(body))
            except Exception:
                parsed = []
            for r in parsed:
                conn.execute(
                    """
                    INSERT INTO facts_price_daily(
                      date,ticker,open,high,low,close,volume,source_kind,source_url,fetched_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
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
                        r["date"],
                        r["ticker"],
                        r["open"],
                        r["high"],
                        r["low"],
                        r["close"],
                        r["volume"],
                        "jpx_daily_csv",
                        url,
                        now_utc,
                        now_utc,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO instruments(ticker,source_kind,updated_at)
                    VALUES(?,?,?)
                    ON CONFLICT(ticker) DO UPDATE SET
                      updated_at=excluded.updated_at
                    """,
                    (r["ticker"], "jpx_daily_csv", now_utc),
                )
                facts_upserted += 1

        for url, _payload in pdf_like:
            try:
                raw = fetch_bytes(url, args.timeout)
                check = parse_pdf_numbers(raw)
            except Exception as e:
                check = {
                    "numbers_count": 0,
                    "sample_numbers": [],
                    "digit_check_pass": False,
                    "sum_check_pass": False,
                    "sum_check_detail": f"fetch_error:{type(e).__name__}",
                }
            payload = {
                "date": args.date,
                "source_url": url,
                "validation": check,
                "lane": "pdf_backfill",
            }
            event_hash = hashlib.sha256(f"{args.date}|pdf|{url}".encode("utf-8")).hexdigest()
            conn.execute(
                """
                INSERT INTO raw_events(
                  event_hash,source_kind,source_url,event_time,ticker,ingest_date,fetched_at,payload_json,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_kind,event_hash) DO UPDATE SET
                  fetched_at=excluded.fetched_at,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    event_hash,
                    "jpx_pdf_backfill",
                    url,
                    f"{args.date}T00:00:00+09:00",
                    "",
                    args.date,
                    now_utc,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    "scripts/investment/collect/process_jpx_daily_files.py",
                    now_utc,
                ),
            )
            pdf_processed += 1

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
            ("jpx_daily_process", "03.html", args.date, "ok", now_utc, "", now_utc),
        )
        conn.commit()
    finally:
        conn.close()

    print(
        f"jpx_process date={args.date} csv_like={len(csv_like)} pdf_like={len(pdf_like)} "
        f"facts_upserted={facts_upserted} pdf_processed={pdf_processed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

