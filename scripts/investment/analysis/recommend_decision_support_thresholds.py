#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Recommend thresholds for decision-support-diff warning rate")
    p.add_argument("--month", required=True, help="YYYY-MM")
    p.add_argument("--target-min-rate", type=float, default=5.0)
    p.add_argument("--target-max-rate", type=float, default=15.0)
    p.add_argument("--out", type=Path, default=None)
    return p.parse_args()


def _load_rows(month: str) -> list[dict]:
    files = sorted(glob.glob(str(INBOX / f"{month}-*-decision-support-diff.json")))
    rows: list[dict] = []
    for f in files:
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(d)
    return rows


def _simulate(rows: list[dict], min_prev: int) -> tuple[int, int, float]:
    warn = 0
    total = len(rows)
    for d in rows:
        diff = d.get("diff", {})
        prev = d.get("previous", {})
        win_delta = float(diff.get("winRateDeltaPp", 0.0) or 0.0)
        dd_delta = float(diff.get("ddApproxDeltaPp", 0.0) or 0.0)
        drop = float(diff.get("acceptedDropRatio", 0.0) or 0.0)
        prev_n = int(prev.get("acceptedCount", 0) or 0)
        is_warn = (win_delta <= -3.0) or (dd_delta <= -2.0) or (prev_n >= min_prev and drop >= 0.2)
        if is_warn:
            warn += 1
    rate = (warn / total * 100.0) if total > 0 else 0.0
    return warn, total, rate


def main() -> int:
    args = parse_args()
    rows = _load_rows(args.month)
    cands = []
    for min_prev in (2, 3, 4, 5, 6):
        w, n, r = _simulate(rows, min_prev)
        cands.append({"minPrev": min_prev, "warningDays": w, "totalDays": n, "warningRatePct": round(r, 2)})
    in_range = [c for c in cands if args.target_min_rate <= c["warningRatePct"] <= args.target_max_rate]
    if in_range:
        rec = sorted(
            in_range,
            key=lambda x: (
                abs((args.target_min_rate + args.target_max_rate) / 2 - x["warningRatePct"]),
                -x["minPrev"],
            ),
        )[0]
    else:
        rec = sorted(cands, key=lambda x: (0 if x["warningRatePct"] > 0 else 1, abs((args.target_min_rate + args.target_max_rate) / 2 - x["warningRatePct"])))[0]
    out = {
        "month": args.month,
        "targetWarningRatePct": {"min": args.target_min_rate, "max": args.target_max_rate},
        "candidates": cands,
        "recommended": rec,
    }
    out_path = args.out or (INBOX / f"{args.month}-decision-support-threshold-recommendation.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path.relative_to(ROOT)}")
    print(f"recommended warn_accepted_drop_min_prev={rec['minPrev']} (warningRate={rec['warningRatePct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
