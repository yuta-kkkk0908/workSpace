#!/usr/bin/env python3
"""Summarize quality/completeness of investment research generated files."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
INBOX = ROOT / "topics/investment-research/inbox"
DEFAULT_MD = INBOX / "{date}-quality-report.md"
DEFAULT_JSON = INBOX / "{date}-quality-report.json"

FILE_SPECS = {
    "outcomes": "{date}-rough-backtest-outcomes-batch-1.md",
    "technical": "{date}-technical-context-data.json",
    "borrow": "{date}-borrow-context-data.json",
    "market": "{date}-market-context-data.json",
    "sector_market": "{date}-sector-market-context-data.json",
    "stratified": "{date}-rough-backtest-stratified-analysis.md",
    "rule_check": "{date}-rule-check-data.json",
    "short_readiness": "{date}-short-readiness-data.json",
    "rule_dashboard": "{date}-rule-dashboard.json",
}
UNKNOWN_RE = re.compile(r"unknown|fetch_failed|cache_only|unavailable|insufficient|pending", re.I)


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def rows_from_json(path: Path) -> list[dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, dict):
        return []
    rows = data.get("rows")
    return rows if isinstance(rows, list) else []


def count_unknown_values(rows: list[dict[str, Any]], keys: list[str] | None = None) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        items = row.items() if keys is None else ((k, row.get(k)) for k in keys)
        for key, value in items:
            if value is None:
                counts[f"{key}.none"] += 1
            elif isinstance(value, str) and UNKNOWN_RE.search(value):
                counts[f"{key}.{value}"] += 1
    return counts


def parse_md_field_counts(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- ([A-Za-z0-9_+./ -]+):\s*(.+)$", line)
        if not m:
            continue
        key = m.group(1).strip()
        value = m.group(2).strip()
        if UNKNOWN_RE.search(value):
            counts[f"{key}.{value}"] += 1
    return counts


def quality_label(score: float) -> str:
    if score >= 90:
        return "good"
    if score >= 70:
        return "usable_with_caution"
    if score >= 50:
        return "thin"
    return "weak"


def json_meta(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def summarize_date(date: str) -> dict[str, Any]:
    files = {name: INBOX / pattern.format(date=date) for name, pattern in FILE_SPECS.items()}
    file_status = {name: {"path": rel(path), "exists": path.exists(), "sizeBytes": path.stat().st_size if path.exists() else 0} for name, path in files.items()}

    rows = {
        "technical": rows_from_json(files["technical"]),
        "borrow": rows_from_json(files["borrow"]),
        "market": rows_from_json(files["market"]),
        "sector_market": rows_from_json(files["sector_market"]),
        "rule_check": (load_json(files["rule_check"]) or {}).get("ruleCandidates", []) if files["rule_check"].exists() else [],
        "short_readiness": rows_from_json(files["short_readiness"]),
        "rule_dashboard": rows_from_json(files["rule_dashboard"]),
    }

    critical_unknowns = {
        "technical": dict(count_unknown_values(rows["technical"], ["technicalStatus", "technicalPattern"])),
        "borrow": dict(count_unknown_values(rows["borrow"], ["borrowStatus", "jpxAsOf", "jpxSourceUrl"])),
        "market": dict(count_unknown_values(rows["market"], ["marketContext"])),
        "sector_market": dict(count_unknown_values(rows["sector_market"], ["sectorMarketContext"])),
        "short_readiness": dict(count_unknown_values(rows["short_readiness"], ["shortReadiness", "borrowCheck", "borrow_borrowStatus", "liquidityBucket"])),
    }
    informational_unknowns = {
        "outcomes": dict(parse_md_field_counts(files["outcomes"])),
        "technical": dict(count_unknown_values(rows["technical"], ["technicalStatus", "technicalPattern", "maTrend", "rsi14Bucket", "macdBucket", "bollingerBucket", "breakout20"])),
        "borrow": dict(count_unknown_values(rows["borrow"], ["borrowStatus", "jpxAsOf", "jpxSourceUrl", "reverseStockLoanFee", "sellRestriction", "brokerGeneralShort"])),
        "market": dict(count_unknown_values(rows["market"], ["marketContext", "nikkei225Pct", "topixPct", "sp500PrevPct", "nasdaqPrevPct", "usdjpyPrevPct"])),
        "sector_market": dict(count_unknown_values(rows["sector_market"], ["sectorMarketContext", "proxyPct", "topixPct", "relativeToTopixPct"])),
        "short_readiness": dict(count_unknown_values(rows["short_readiness"], ["shortReadiness", "borrowCheck", "borrow_borrowStatus", "liquidityBucket"])),
    }

    row_counts = {name: len(value) for name, value in rows.items()}
    missing_files = [name for name, status in file_status.items() if not status["exists"]]
    total_expected = sum(row_counts.get(name, 0) for name in ["technical", "borrow", "market", "sector_market", "short_readiness"])
    total_critical_unknown = sum(sum(group.values()) for group in critical_unknowns.values())
    total_informational_unknown = sum(sum(group.values()) for group in informational_unknowns.values())
    completeness = 100.0 if total_expected == 0 else max(0.0, 100.0 - (total_critical_unknown / max(total_expected, 1) * 100.0))
    cache_only_flags = {
        name: bool(json_meta(files[name]).get("cacheOnly"))
        for name in ["technical", "borrow", "market", "sector_market"]
    }

    return {
        "date": date,
        "mode": "investment-quality-report",
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "qualityLabel": quality_label(completeness),
        "completenessScore": round(completeness, 1),
        "missingFiles": missing_files,
        "fileStatus": file_status,
        "rowCounts": row_counts,
        "cacheOnlyFlags": cache_only_flags,
        "criticalUnknownCounts": critical_unknowns,
        "informationalUnknownCounts": informational_unknowns,
        "totalCriticalUnknownSignals": total_critical_unknown,
        "totalInformationalUnknownSignals": total_informational_unknown,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize investment generated output quality.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--output-md", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    report = summarize_date(args.date)
    output_json = args.output_json or Path(str(DEFAULT_JSON).format(date=args.date))
    output_md = args.output_md or Path(str(DEFAULT_MD).format(date=args.date))
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Investment Quality Report",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: investment-quality-report",
        "- caution: 欠損/unknownの機械的な棚卸し。売買助言ではない。",
        "",
        "## Summary",
        f"- qualityLabel: {report['qualityLabel']}",
        f"- completenessScore: {report['completenessScore']}",
        f"- totalCriticalUnknownSignals: {report['totalCriticalUnknownSignals']}",
        f"- totalInformationalUnknownSignals: {report['totalInformationalUnknownSignals']}",
        f"- missingFiles: {len(report['missingFiles'])}",
    ]
    for name, flag in report["cacheOnlyFlags"].items():
        lines.append(f"- cacheOnly.{name}: {flag}")
    lines.extend(["", "## Missing Files"])
    if report["missingFiles"]:
        for name in report["missingFiles"]:
            lines.append(f"- {name}: {report['fileStatus'][name]['path']}")
    else:
        lines.append("- none")
    lines.extend(["", "## Row Counts"])
    for name, count in sorted(report["rowCounts"].items()):
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Critical Unknown Counts"])
    for group, counts in report["criticalUnknownCounts"].items():
        lines.append(f"### {group}")
        if not counts:
            lines.append("- none")
            continue
        for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:30]:
            lines.append(f"- {key}: {count}")
    lines.extend(["", "## Informational Unknown Counts"])
    for group, counts in report["informationalUnknownCounts"].items():
        lines.append(f"### {group}")
        if not counts:
            lines.append("- none")
            continue
        for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:30]:
            lines.append(f"- {key}: {count}")
    lines.extend([
        "",
        "## How To Use",
        "- `good`: 日次表示に使いやすい。",
        "- `usable_with_caution`: 主要欄は使えるが、unknownの多い項目は未確認として扱う。",
        "- `thin` / `weak`: lightweight/cache-only結果として読み、deep補完候補に回す。",
    ])
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_md.relative_to(ROOT)} quality={report['qualityLabel']} criticalUnknown={report['totalCriticalUnknownSignals']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
