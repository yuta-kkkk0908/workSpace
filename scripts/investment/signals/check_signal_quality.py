#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
PROMPTS = ROOT / "prompts"

HEAD_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$")
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Quality gate for daily investment market signals")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--max-material-age-business-days", type=int, default=2)
    p.add_argument("--min-signals", type=int, default=4)
    p.add_argument("--max-side-imbalance", type=int, default=4)
    p.add_argument("--max-watch-share", type=float, default=0.7, help="alert when watch share exceeds this ratio")
    p.add_argument("--fallback-days", type=int, default=3, help="fallback window for opening-scenarios json")
    p.add_argument("--out-json", default=str(PROMPTS / "signal-quality-metrics.json"))
    p.add_argument("--out-alert", default=str(PROMPTS / "signal-quality-alert.txt"))
    return p.parse_args()


def business_days_diff(start: datetime.date, end: datetime.date) -> int:
    sign = 1
    if start > end:
        start, end = end, start
        sign = -1
    d = start
    n = 0
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n * sign


def parse_signals(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    for raw in text.splitlines():
        s = raw.strip()
        hm = HEAD_RE.match(s)
        if hm:
            if cur:
                rows.append(cur)
            cur = {"signalId": hm.group(1), "title": hm.group(2)}
            continue
        if cur is None:
            continue
        fm = FIELD_RE.match(s)
        if fm:
            cur[fm.group(1)] = fm.group(2)
    if cur:
        rows.append(cur)
    return rows


def find_opening_scenarios(date_str: str, fallback_days: int) -> tuple[Path | None, str | None]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-opening-scenarios.json"
        if p.exists():
            return p, d
    return None, None


def main() -> int:
    args = parse_args()
    target = datetime.strptime(args.date, "%Y-%m-%d").date()
    path = INBOX / f"{args.date}-market-signals.md"
    alerts: list[str] = []
    metrics: dict[str, object] = {"date": args.date, "path": str(path.relative_to(ROOT))}

    if not path.exists():
        alerts.append("market-signals ファイルが存在しない")
        metrics["exists"] = False
    else:
        metrics["exists"] = True
        rows = parse_signals(path)
        metrics["signalCount"] = len(rows)
        if len(rows) < args.min_signals:
            alerts.append(f"シグナル件数不足: {len(rows)} < {args.min_signals}")

        up = 0
        down = 0
        stale: list[str] = []
        new_count = 0
        tickers: list[str] = []
        for r in rows:
            exp = (r.get("expectedDirection", "") or "").lower()
            if exp.startswith("up"):
                up += 1
            elif exp.startswith("down"):
                down += 1
            tickers.append(r.get("ticker", ""))
            pub = (r.get("publishedAt", "") or "")[:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", pub):
                pub_d = datetime.strptime(pub, "%Y-%m-%d").date()
                age = business_days_diff(pub_d, target)
                if age == 0:
                    new_count += 1
                if age > args.max_material_age_business_days:
                    stale.append(f"{r.get('ticker','?')} pub={pub} age={age}bd")
        metrics["upCount"] = up
        metrics["downCount"] = down
        metrics["newMaterialCount"] = new_count
        metrics["tickers"] = tickers
        if abs(up - down) > args.max_side_imbalance:
            alerts.append(f"方向偏り過大: up={up}, down={down}, diff={abs(up-down)}")
        if stale:
            alerts.append("材料日付が古い(2営業日超): " + "; ".join(stale[:6]))
        if new_count == 0:
            alerts.append("当日材料の新規シグナルが0件")

    opening_path, opening_date = find_opening_scenarios(args.date, args.fallback_days)
    if opening_path:
        try:
            opening = json.loads(opening_path.read_text(encoding="utf-8"))
        except Exception:
            opening = {}
        scenarios = opening.get("scenarios", []) or []
        rejected = opening.get("rejectedScenarios", []) or []
        trade_count = len(scenarios)
        watch_count = len(rejected)
        total = trade_count + watch_count
        watch_share = (watch_count / total) if total > 0 else 0.0
        metrics["openingScenariosPath"] = str(opening_path.relative_to(ROOT))
        metrics["openingScenariosDate"] = opening_date
        metrics["tradeScenarioCount"] = trade_count
        metrics["watchScenarioCount"] = watch_count
        metrics["watchShare"] = round(watch_share, 4)
        if trade_count == 0 and watch_count > 0:
            alerts.append("tradeシナリオが0件（watch偏重）")
        if watch_share > float(args.max_watch_share):
            alerts.append(
                f"watch比率が高い: watchShare={watch_share:.0%} > {float(args.max_watch_share):.0%}"
            )
    else:
        metrics["openingScenariosPath"] = ""
        metrics["openingScenariosDate"] = ""
        metrics["tradeScenarioCount"] = 0
        metrics["watchScenarioCount"] = 0
        metrics["watchShare"] = 0.0

    status = "ALERT" if alerts else "OK"
    metrics["status"] = status
    metrics["alerts"] = alerts

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    out_alert = Path(args.out_alert)
    if alerts:
        lines = [f"Signal Quality Alert {args.date}", f"- status: {status}"]
        for a in alerts:
            lines.append(f"- {a}")
        lines.append(f"- metrics: {out_json.relative_to(ROOT)}")
        out_alert.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"ALERT: {out_alert}")
        return 2
    else:
        out_alert.write_text("", encoding="utf-8")
        print("OK: signal quality")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
