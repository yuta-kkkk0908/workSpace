#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import html
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
JST = timezone(timedelta(hours=9))
USER_AGENT = "AIOSResearchBot/1.0 (credit auto collector)"
RAKUTEN_MARGIN_URL = "https://www.rakuten-sec.co.jp/ITS/Companyfile/margin_restriction.html"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect credit/loan availability from SBI stock pages for active tickers")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--fallback-days", type=int, default=1, help="look back N days when same-day signals are missing")
    p.add_argument("--max-tickers", type=int, default=30)
    p.add_argument("--timeout", type=float, default=12.0)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def pick_tickers(conn: sqlite3.Connection, date_str: str, fallback_days: int, max_tickers: int) -> tuple[list[str], str | None]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        rows = conn.execute(
            """
            WITH c AS (
              SELECT ticker, MAX(COALESCE(score,0)) AS score
              FROM entry_candidates
              WHERE date=? AND COALESCE(ticker,'')<>''
              GROUP BY ticker
            ),
            s AS (
              SELECT ticker, 0 AS score
              FROM signals
              WHERE date=? AND COALESCE(ticker,'')<>''
            )
            SELECT ticker
            FROM (
              SELECT ticker, score FROM c
              UNION ALL
              SELECT ticker, score FROM s
            )
            GROUP BY ticker
            ORDER BY MAX(score) DESC, ticker
            LIMIT ?
            """,
            (d, d, max(1, max_tickers)),
        ).fetchall()
        tks = [str(r[0]).strip() for r in rows if str(r[0]).strip()]
        if tks:
            return tks, d
    return [], None


def fetch_html(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = str(resp.headers.get("Content-Type", "") or "")
    # Try charset from header first, then common JP encodings.
    m = re.search(r"charset=([a-zA-Z0-9_\-]+)", ctype, re.I)
    encodings = []
    if m:
        encodings.append(m.group(1).strip().lower())
    encodings.extend(["cp932", "shift_jis", "utf-8", "euc_jp"])
    seen = set()
    for enc in encodings:
        if enc in seen:
            continue
        seen.add(enc)
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def strip_tags(text: str) -> str:
    s = re.sub(r"<[^>]+>", "", text or "")
    s = html.unescape(s)
    s = " ".join(s.split())
    return s.strip()


def parse_table_rows_with_rowspan(table_html: str) -> list[list[str]]:
    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.I | re.S)
    out: list[list[str]] = []
    pending: dict[int, tuple[int, str]] = {}
    for row_html in rows_html:
        cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", row_html, re.I | re.S)
        if not cells and not pending:
            continue
        row_vals: list[str] = []
        pos = 0
        ci = 0
        while ci < len(cells) or pending:
            while pos in pending:
                remain, val = pending[pos]
                row_vals.append(val)
                if remain <= 1:
                    del pending[pos]
                else:
                    pending[pos] = (remain - 1, val)
                pos += 1
            if ci >= len(cells):
                break
            attrs, body = cells[ci]
            ci += 1
            val = strip_tags(body)
            row_vals.append(val)
            m = re.search(r'rowspan\s*=\s*["\']?(\d+)', attrs or "", re.I)
            if m:
                span = max(1, int(m.group(1)))
                if span > 1:
                    pending[pos] = (span - 1, val)
            pos += 1
        out.append(row_vals)
    return out


def parse_rakuten_margin_map(timeout: float) -> dict[str, list[str]]:
    html_text = fetch_html(RAKUTEN_MARGIN_URL, timeout)
    tables = re.findall(r"<table[^>]*>.*?</table>", html_text, re.I | re.S)
    target_rows: list[list[str]] = []
    for t in tables:
        rows = parse_table_rows_with_rowspan(t)
        if not rows:
            continue
        header = rows[0]
        if any("銘柄コード" in c for c in header) and any("摘要" in c for c in header):
            target_rows = rows
            break
    if not target_rows:
        return {}

    header = target_rows[0]
    code_idx = next((i for i, c in enumerate(header) if "銘柄コード" in c), 0)
    note_idx = next((i for i, c in enumerate(header) if "摘要" in c), 3 if len(header) > 3 else 0)
    out: dict[str, list[str]] = {}
    for row in target_rows[1:]:
        if code_idx >= len(row) or note_idx >= len(row):
            continue
        code_raw = row[code_idx]
        note = row[note_idx]
        m = re.search(r"\b(\d{4})\b", code_raw or "")
        if not m:
            continue
        code = m.group(1)
        note = (note or "").strip()
        if not note:
            continue
        out.setdefault(code, []).append(note)
    return out


def infer_credit_from_rakuten_notes(notes: list[str]) -> tuple[str, str, str, dict]:
    txt = " | ".join(notes)
    buy = "unknown"
    sell = "unknown"

    sell_ng_keys = [
        "新規売停止",
        "一般信用新規売停止",
        "全取引停止",
        "売建停止",
        "売停止",
        "売禁",
    ]
    buy_ng_keys = [
        "現物買付停止",
        "新規買停止",
        "全取引停止",
        "買停止",
    ]
    if any(k in txt for k in sell_ng_keys):
        sell = "ng"
    if any(k in txt for k in buy_ng_keys):
        buy = "ng"

    # Positive inference for margin-buy when only short-side restriction is shown.
    if buy == "unknown" and any(k in txt for k in ["新規売停止", "売禁", "一般信用新規売停止"]):
        buy = "ok"

    if buy == "ok" and sell == "ok":
        status = "auto_marginable"
    elif buy == "ng" or sell == "ng":
        status = "auto_non_marginable"
    else:
        status = "auto_unknown"
    return status, buy, sell, {"notes": notes[:20], "summary": txt[:500], "url": RAKUTEN_MARGIN_URL}


def infer_flag(text: str) -> str:
    s = (text or "").strip().lower()
    if not s:
        return "unknown"
    bad_tokens = ["不可", "対象外", "なし", "停止", "×", "✕", "ng", "no"]
    good_tokens = ["可", "対象", "あり", "○", "ok", "yes"]
    if any(x in s for x in bad_tokens):
        return "ng"
    if any(x in s for x in good_tokens):
        return "ok"
    return "unknown"


def parse_credit_from_html(html: str) -> tuple[str, str, str, dict]:
    txt = re.sub(r"\s+", " ", html)

    # SBI page often has labels like 「信用区分」「貸借区分」「信用」「貸借」 near table cells.
    m_credit = re.search(r"(信用(?:区分)?)\s*</[^>]+>\s*<[^>]*>\s*([^<]{1,40})<", txt)
    m_loan = re.search(r"(貸借(?:区分)?)\s*</[^>]+>\s*<[^>]*>\s*([^<]{1,40})<", txt)

    raw_credit = m_credit.group(2).strip() if m_credit else ""
    raw_loan = m_loan.group(2).strip() if m_loan else ""

    buy = infer_flag(raw_credit)
    sell = infer_flag(raw_loan if raw_loan else raw_credit)
    if sell == "unknown" and "貸借銘柄" in txt:
        sell = "ok"
    if sell == "unknown" and "非貸借銘柄" in txt:
        sell = "ng"

    # Conservative override:
    # If page text indicates today's caution/restriction on margin/loan,
    # force short availability to NG.
    regulation_hits = []
    regulation_keys = [
        "本日の注意銘柄",
        "規制銘柄",
        "増担保",
        "日々公表",
        "売禁",
        "貸株注意喚起",
        "信用規制",
    ]
    for k in regulation_keys:
        if k in txt:
            regulation_hits.append(k)
    if regulation_hits:
        sell = "ng"

    if buy == "ok" and sell == "ok":
        credit_status = "auto_marginable"
    elif buy == "ng" or sell == "ng":
        credit_status = "auto_non_marginable"
    else:
        credit_status = "auto_unknown"

    detail = {
        "credit_raw": raw_credit,
        "loan_raw": raw_loan,
        "regulation_hits": regulation_hits,
    }
    return credit_status, buy, sell, detail


def upsert_credit(
    conn: sqlite3.Connection,
    date_str: str,
    ticker: str,
    credit_status: str,
    buy: str,
    sell: str,
    detail: dict,
    source_kind: str = "auto_sbi",
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    detail_json = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
    conn.execute(
        """
        INSERT INTO credit_status_rows(date,ticker,credit_status,buy_status,sell_status,source_kind,source_detail,updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(date,ticker) DO UPDATE SET
          credit_status=CASE WHEN credit_status_rows.source_kind LIKE 'manual_%' THEN credit_status_rows.credit_status ELSE excluded.credit_status END,
          buy_status=CASE WHEN credit_status_rows.source_kind LIKE 'manual_%' THEN credit_status_rows.buy_status ELSE excluded.buy_status END,
          sell_status=CASE WHEN credit_status_rows.source_kind LIKE 'manual_%' THEN credit_status_rows.sell_status ELSE excluded.sell_status END,
          source_kind=CASE WHEN credit_status_rows.source_kind LIKE 'manual_%' THEN credit_status_rows.source_kind ELSE excluded.source_kind END,
          source_detail=CASE WHEN credit_status_rows.source_kind LIKE 'manual_%' THEN credit_status_rows.source_detail ELSE excluded.source_detail END,
          updated_at=excluded.updated_at
        """,
        (
            date_str,
            ticker,
            credit_status,
            buy,
            sell,
            source_kind,
            detail_json,
            now,
        ),
    )


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    try:
        tickers, src_date = pick_tickers(conn, args.date, args.fallback_days, args.max_tickers)
        if not tickers:
            print("credit_auto_update tickers=0 updated=0 source_date=none")
            return 0
        updated = 0
        errors = 0
        rakuten_map: dict[str, list[str]] = {}
        try:
            rakuten_map = parse_rakuten_margin_map(args.timeout)
        except Exception:
            rakuten_map = {}
        for t in tickers:
            try:
                notes = rakuten_map.get(t, [])
                if rakuten_map:
                    if notes:
                        cs, buy, sell, detail = infer_credit_from_rakuten_notes(notes)
                        if not args.dry_run:
                            upsert_credit(
                                conn,
                                args.date,
                                t,
                                cs,
                                buy,
                                sell,
                                {**detail, "source": "rakuten_margin_restriction"},
                                source_kind="auto_rakuten",
                            )
                    else:
                        # "信用取引規制銘柄一覧" is a restriction list.
                        # If ticker is not listed, treat as not restricted by this source.
                        cs, buy, sell = "auto_marginable", "ok", "ok"
                        detail = {
                            "url": RAKUTEN_MARGIN_URL,
                            "source": "rakuten_margin_restriction",
                            "summary": "not_listed_in_restriction_table",
                        }
                        if not args.dry_run:
                            upsert_credit(
                                conn,
                                args.date,
                                t,
                                cs,
                                buy,
                                sell,
                                detail,
                                source_kind="auto_rakuten",
                            )
                else:
                    url = f"https://site2.sbisec.co.jp/ETGate/?_ControlID=WPLETsiR001Control&_PageID=WPLETsiR001Mdtl20&_DataStoreID=DSWPLETsiR001Control&_ActionID=DefaultAID&s_rkbn=2&i_stock_sec={t}&i_dom_flg=1&i_exchange_code=TKY&i_output_type=1"
                    html = fetch_html(url, args.timeout)
                    cs, buy, sell, detail = parse_credit_from_html(html)
                    detail["url"] = url
                    detail["source"] = "sbi_stock_detail"
                    if not args.dry_run:
                        upsert_credit(conn, args.date, t, cs, buy, sell, detail, source_kind="auto_sbi")
                updated += 1
            except urllib.error.HTTPError as e:
                errors += 1
                if not args.dry_run:
                    upsert_credit(
                        conn,
                        args.date,
                        t,
                        "auto_unknown",
                        "unknown",
                        "unknown",
                        {"url": url, "error": f"http:{e.code}"},
                    )
            except Exception as e:
                errors += 1
                if not args.dry_run:
                    upsert_credit(
                        conn,
                        args.date,
                        t,
                        "auto_unknown",
                        "unknown",
                        "unknown",
                        {"url": url, "error": str(e)},
                    )
        if not args.dry_run:
            conn.commit()
        print(
            "credit_auto_update tickers={0} updated={1} errors={2} source_date={3}".format(
                len(tickers), updated, errors, src_date or "none"
            )
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
