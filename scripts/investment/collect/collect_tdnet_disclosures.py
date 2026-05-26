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
INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = ROOT / "data" / "investment.db"
JST = timezone(timedelta(hours=9))
USER_AGENT = "AIOSResearchBot/1.0 (tdnet collector)"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect TDnet disclosures (best-effort) and persist to DB")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--max-items", type=int, default=120)
    p.add_argument("--lookback-days", type=int, default=0, help="also collect past N days")
    return p.parse_args()


def fetch_html(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def discover_tdnet_pages(target_date: str) -> list[str]:
    ymd = target_date.replace("-", "")
    return [
        f"https://www.release.tdnet.info/inbs/I_list_001_{ymd}.html",
        f"https://www.release.tdnet.info/inbs/I_list_002_{ymd}.html",
    ]


def classify_tdnet_title(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return ""
    has_highest_profit = any(k in t for k in ["最高益", "過去最高益", "最高益更新"])
    has_downward = ("下方修正" in t) or ("業績予想の修正" in t and "上方修正" not in t)
    has_dividend_cut = any(k in t for k in ["減配", "無配", "配当予想の修正", "配当予想の取り下げ", "配当予想を未定"])
    # Positive
    if "上方修正" in t and has_highest_profit:
        return "upward_revision_highest_profit"
    if "上方修正" in t and ("増配" in t or "配当予想の修正" in t):
        return "upward_revision_plus_dividend"
    if "増配" in t and "配当予想の修正" in t:
        return "dividend_revision"
    if "上方修正" in t:
        return "upward_revision"
    # Dilution / offering
    if any(k in t for k in ["売出し", "売出", "自己株式処分", "公募", "第三者割当", "新株予約権"]):
        return "offering_or_dilution"
    # Downward + dividend cut
    if has_downward and has_dividend_cut:
        return "downward_revision_dividend_cut"
    # Weak earnings/guidance
    if any(k in t for k in ["下方修正", "赤字", "減益", "未達", "下振れ", "営業損失", "経常損失", "最終損失", "最終赤字", "業績予想の修正"]):
        return "weak_earnings_or_guidance"
    return ""


def refresh_tdnet_categories(db_path: Path, date_str: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT rowid,title,category FROM tdnet_disclosures WHERE date=?",
            (date_str,),
        ).fetchall()
        updated = 0
        for rowid, title, cat in rows:
            inferred = classify_tdnet_title(str(title or ""))
            cur = str(cat or "").strip()
            if inferred and inferred != cur:
                conn.execute(
                    "UPDATE tdnet_disclosures SET category=?, updated_at=? WHERE rowid=?",
                    (
                        inferred,
                        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                        rowid,
                    ),
                )
                updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


def parse_rows(html_text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    tr_pat = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
    td_pat = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
    href_pat = re.compile(r'href="([^"]+)"', re.I)
    for tr in tr_pat.findall(html_text):
        tds = td_pat.findall(tr)
        if len(tds) < 4:
            continue
        time_txt = re.sub(r"<[^>]+>", " ", tds[0])
        time_txt = re.sub(r"\s+", "", time_txt)
        if not re.match(r"^\d{2}:\d{2}$", time_txt):
            continue
        ticker_txt = re.sub(r"<[^>]+>", " ", tds[1])
        ticker_txt = re.sub(r"\s+", "", ticker_txt)
        m_ticker = re.search(r"\b(\d{4,5}[A-Z]?)\b", ticker_txt)
        ticker = m_ticker.group(1) if m_ticker else ""
        if re.match(r"^\d{5}$", ticker):
            # TDnet often uses 5-digit security code; normalize to 4-digit issue code.
            ticker = ticker[:4]
        company = re.sub(r"<[^>]+>", " ", tds[2])
        company = re.sub(r"\s+", " ", company).strip()
        title = re.sub(r"<[^>]+>", " ", tds[3])
        title = re.sub(r"\s+", " ", title).strip()
        href_match = href_pat.search(tds[3])
        href = href_match.group(1).strip() if href_match else ""
        if href and not href.startswith("http"):
            if href.startswith("./"):
                href = "https://www.release.tdnet.info/inbs/" + href[2:]
            elif href.startswith("/"):
                href = "https://www.release.tdnet.info" + href
            else:
                href = "https://www.release.tdnet.info/inbs/" + href
        if not ticker or not title:
            continue
        rows.append(
            {
                "time": time_txt,
                "ticker": ticker,
                "company": company,
                "title": title,
                "url": href,
                "category": classify_tdnet_title(title),
            }
        )
    return rows


def fetch_json(url: str, timeout: float) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    return json.loads(raw)


def parse_unofficial_api_rows(obj: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if isinstance(obj, dict):
        items = obj.get("items") or obj.get("TDnet") or []
    elif isinstance(obj, list):
        items = obj
    else:
        items = []
    for it in items:
        if not isinstance(it, dict):
            continue
        ticker = str(it.get("code") or it.get("ticker") or "").strip()
        title = str(it.get("title") or "").strip()
        url = str(it.get("document_url") or it.get("url") or "").strip()
        tm = str(it.get("time") or it.get("release_time") or "").strip()
        company = str(it.get("company_name") or it.get("name") or "").strip()
        cat = str(it.get("category") or "").strip()
        if not ticker or not title:
            continue
        rows.append(
            {
                "time": tm,
                "ticker": ticker,
                "company": company,
                "title": title,
                "url": url,
                "category": cat or classify_tdnet_title(title),
                "source_kind": "tdnet_webapi_unofficial",
            }
        )
    return rows


def upsert_db(db_path: Path, date_str: str, source_path: str, rows: list[dict[str, str]]) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        inserted = 0
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        for r in rows:
            disclosed_at = f"{date_str}T{r.get('time','00:00')}:00+09:00" if r.get("time") else ""
            payload = json.dumps(r, ensure_ascii=False, separators=(",", ":"))
            event_hash = hashlib.sha256(
                f"{r.get('ticker','')}|{r.get('title','')}|{r.get('url','')}|{date_str}".encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO tdnet_disclosures(
                  date,disclosed_at,ticker,company,title,category,tdnet_url,source_kind,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(date,ticker,title,tdnet_url) DO UPDATE SET
                  disclosed_at=excluded.disclosed_at,
                  company=excluded.company,
                  category=excluded.category,
                  source_path=excluded.source_path,
                  updated_at=excluded.updated_at
                """,
                (
                    date_str,
                    disclosed_at,
                    r.get("ticker", ""),
                    r.get("company", ""),
                    r.get("title", ""),
                    r.get("category", ""),
                    r.get("url", ""),
                    r.get("source_kind", "tdnet_web"),
                    source_path,
                    fetched_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO raw_events(
                  event_hash,source_kind,source_url,event_time,ticker,ingest_date,fetched_at,payload_json,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_kind,event_hash) DO UPDATE SET
                  source_url=excluded.source_url,
                  event_time=excluded.event_time,
                  ticker=excluded.ticker,
                  ingest_date=excluded.ingest_date,
                  fetched_at=excluded.fetched_at,
                  payload_json=excluded.payload_json,
                  source_path=excluded.source_path,
                  updated_at=excluded.updated_at
                """,
                (
                    event_hash,
                    r.get("source_kind", "tdnet_web"),
                    r.get("url", ""),
                    disclosed_at,
                    r.get("ticker", ""),
                    date_str,
                    fetched_at,
                    payload,
                    source_path,
                    fetched_at,
                ),
            )
            inserted += 1
        # Also update credit-status rows in the same batch for the same ticker universe.
        tickers = sorted({str(r.get("ticker", "")).strip() for r in rows if str(r.get("ticker", "")).strip()})
        for t in tickers:
            prev = conn.execute(
                """
                SELECT credit_status, source_kind
                FROM credit_status_rows
                WHERE ticker=?
                ORDER BY date DESC
                LIMIT 1
                """,
                (t,),
            ).fetchone()
            if prev:
                credit_status = str(prev[0] or "").strip() or "unknown"
                source_kind = str(prev[1] or "").strip() or "carry_forward"
                detail = "carried from latest known status"
            else:
                # Until direct credit-source connector is added, mark explicit unknown.
                credit_status = "unknown"
                source_kind = "pending_credit_source"
                detail = "no credit source connected yet"
            conn.execute(
                """
                INSERT INTO credit_status_rows(date,ticker,credit_status,source_kind,source_detail,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(date,ticker) DO UPDATE SET
                  credit_status=excluded.credit_status,
                  source_kind=excluded.source_kind,
                  source_detail=excluded.source_detail,
                  updated_at=excluded.updated_at
                """,
                (
                    date_str,
                    t,
                    credit_status,
                    source_kind,
                    detail,
                    datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                ),
            )
        cutoff = (datetime.strptime(date_str, "%Y-%m-%d").date() - timedelta(days=14)).strftime("%Y-%m-%d")
        conn.execute("DELETE FROM raw_events WHERE source_kind IN ('tdnet_web','tdnet_webapi_unofficial') AND ingest_date < ?", (cutoff,))
        conn.commit()
        return inserted
    finally:
        conn.close()


def collect_one_day(date_str: str, timeout: float, max_items: int) -> list[dict[str, str]]:
    pages = discover_tdnet_pages(date_str)
    all_rows: list[dict[str, str]] = []
    for u in pages:
        try:
            html = fetch_html(u, timeout)
        except Exception:
            continue
        parsed = parse_rows(html)
        for r in parsed:
            r["source_kind"] = "tdnet_web"
        all_rows.extend(parsed)

    if not all_rows:
        api_url = f"https://webapi.yanoshin.jp/webapi/tdnet/list/{date_str.replace('-', '')}.json?limit={max_items}"
        try:
            obj = fetch_json(api_url, timeout)
            all_rows.extend(parse_unofficial_api_rows(obj))
        except Exception:
            pass

    uniq: dict[tuple[str, str, str], dict[str, str]] = {}
    for r in all_rows:
        key = (r.get("ticker", ""), r.get("title", ""), r.get("url", ""))
        if not all(key):
            continue
        uniq[key] = r
    return list(uniq.values())[: max(1, max_items)]


def main() -> int:
    args = parse_args()
    base = datetime.strptime(args.date, "%Y-%m-%d").date()
    total_rows = 0
    total_upserted = 0
    for d in range(max(0, args.lookback_days), -1, -1):
        day = (base - timedelta(days=d)).strftime("%Y-%m-%d")
        rows = collect_one_day(day, args.timeout, args.max_items)
        out = {
            "date": day,
            "source": "tdnet_web",
            "count": len(rows),
            "rows": rows,
        }
        out_path = INBOX / f"{day}-tdnet-disclosures.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        upserted = upsert_db(args.db, day, str(out_path.relative_to(ROOT)), rows)
        recat = refresh_tdnet_categories(args.db, day)
        print(f"wrote {out_path.relative_to(ROOT)} rows={len(rows)} upserted={upserted} recategorized={recat}")
        total_rows += len(rows)
        total_upserted += upserted
    print(f"summary: days={args.lookback_days + 1} rows={total_rows} upserted={total_upserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
