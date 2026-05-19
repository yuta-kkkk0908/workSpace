#!/usr/bin/env python3
"""Fill JPX standardized margin / loan margin context for investment rows.

Data source: JPX official "制度信用・貸借銘柄一覧" Excel. This is a current/as-of
eligibility layer, not a historical backtest reconstruction. Broker-specific
general margin availability, sell restrictions, and reverse stock loan fees are
not covered and remain check-required.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import zipfile
import io
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
JPX_PAGE = "https://www.jpx.co.jp/listing/others/margin/index.html"
DEFAULT_OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-borrow-context-data.json"
DEFAULT_OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-borrow-context-summary.md"

sys.path.insert(0, str(ROOT / "scripts/investment/analysis"))
import analyze_market_outcomes as outcomes  # noqa: E402

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def find_xlsx_url(page_html: str) -> str:
    m = re.search(r'href="([^"]+_list\.xlsx)"', page_html)
    if not m:
        raise RuntimeError("JPX list xlsx link not found")
    href = m.group(1)
    if href.startswith("http"):
        return href
    return "https://www.jpx.co.jp" + href


def shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    values = []
    for si in root.findall("a:si", NS):
        texts = [t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
        values.append("".join(texts))
    return values


def cell_value(c: ET.Element, ss: list[str]) -> str:
    v = c.find("a:v", NS)
    if v is None or v.text is None:
        return ""
    value = v.text
    if c.get("t") == "s":
        return ss[int(value)]
    return value


def parse_xlsx(data: bytes) -> tuple[str, dict[str, dict[str, str]]]:
    z = zipfile.ZipFile(io.BytesIO(data))
    ss = shared_strings(z)
    root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    as_of = "unknown"
    table: dict[str, dict[str, str]] = {}
    for row in root.findall(".//a:row", NS):
        cells = {}
        for c in row.findall("a:c", NS):
            ref = c.get("r", "")
            col = re.match(r"[A-Z]+", ref).group(0) if re.match(r"[A-Z]+", ref) else ref
            cells[col] = cell_value(c, ss).strip()
        if row.get("r") == "1" and cells.get("A"):
            as_of = cells["A"].replace("現在", "").strip()
        code = cells.get("A", "")
        if not re.match(r"^[0-9]{4}$|^[0-9]{3}[A-Z]$", code):
            continue
        table[code] = {
            "code": code,
            "name": cells.get("B", ""),
            "market": cells.get("C", ""),
            "creditCategory": cells.get("D", ""),
        }
    return as_of, table


def borrow_status(entry: dict[str, str] | None) -> str:
    if not entry:
        return "not_in_jpx_current_list"
    category = entry.get("creditCategory", "")
    if "貸借" in category:
        return "loan_margin"
    if "制度信用" in category:
        return "standardized_margin_only"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill JPX standardized margin / loan margin context.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--cache-only", action="store_true", help="Do not fetch JPX data; emit unknown borrow context.")
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()
    output_json = args.output_json or Path(str(DEFAULT_OUTPUT_JSON).format(date=args.date))
    output_md = args.output_md or Path(str(DEFAULT_OUTPUT_MD).format(date=args.date))
    outcomes.OUTCOME = args.outcome or Path(str(outcomes.DEFAULT_OUTCOME).format(date=args.date))

    if args.cache_only:
        xlsx_url = "unavailable_cache_only"
        as_of = "unknown_cache_only"
        table = {}
        fetch_error = "cache_only"
    else:
        try:
            page = fetch(JPX_PAGE).decode("utf-8", "ignore")
            xlsx_url = find_xlsx_url(page)
            as_of, table = parse_xlsx(fetch(xlsx_url))
        except Exception as exc:
            xlsx_url = "unavailable_fetch_failed"
            as_of = "unknown_fetch_failed"
            table = {}
            fetch_error = str(exc)
        else:
            fetch_error = ""
    rows = outcomes.parse_outcomes()
    out_rows = []
    for row in rows:
        entry = table.get(row["ticker"])
        status = borrow_status(entry)
        out_rows.append({
            "ticker": row["ticker"],
            "signalDate": row["signalDate"],
            "category": row.get("category", "unknown"),
            "signalType": row.get("signalType", "unknown"),
            "shortRank": row.get("shortRank", "unknown"),
            "jpxAsOf": as_of,
            "jpxSourceUrl": xlsx_url,
            "jpxCreditCategory": entry.get("creditCategory") if entry else "not_listed_current_asof",
            "jpxMarket": entry.get("market") if entry else "unknown",
            "borrowStatus": status,
            "standardizedMarginEligible": status in {"loan_margin", "standardized_margin_only"},
            "standardizedShortEligible": status == "loan_margin",
            "brokerGeneralShort": "unknown_broker_specific",
            "reverseStockLoanFee": "unknown_check_daily",
            "sellRestriction": "unknown_check_daily",
            "borrowCheck": "current_jpx_loan_margin" if status == "loan_margin" else "broker_or_jpx_check_required",
            "caution": "JPX current/as-of list, not historical availability. Broker-specific general margin and daily restrictions not included.",
        })
    counts = Counter(row["borrowStatus"] for row in out_rows)
    output_json.write_text(json.dumps({
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "date": args.date,
        "cacheOnly": args.cache_only,
        "mode": "borrow-context-fill",
        "sourcePage": JPX_PAGE,
        "sourceXlsx": xlsx_url,
        "jpxAsOf": as_of,
        "fetchError": fetch_error,
        "caution": "JPX current/as-of list only. Historical borrowability, broker-specific general margin, reverse stock loan fee, and daily restrictions are not covered.",
        "rows": out_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# {args.date} Borrow Context Summary",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: borrow-context-fill",
        f"- sourcePage: {JPX_PAGE}",
        f"- sourceXlsx: {xlsx_url}",
        f"- jpxAsOf: {as_of}",
        "- caution: JPX現時点/as-ofの制度信用・貸借区分。証券会社別の一般信用、日々の売り禁、逆日歩は含まない。売買助言ではない。",
        "",
        "## Summary",
        f"- analyzedRows: {len(out_rows)}",
    ]
    for key, value in counts.most_common():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Loan Margin Candidates"])
    for row in [r for r in out_rows if r["borrowStatus"] == "loan_margin"][:40]:
        lines.append(f"- {row['ticker']} {row['signalDate']} {row['category']} {row['signalType']} shortRank={row['shortRank']} market={row['jpxMarket']}")
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_json.relative_to(ROOT)} rows={len(out_rows)} asOf={as_of}")
    print(f"wrote {output_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
