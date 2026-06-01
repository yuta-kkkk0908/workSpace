#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.pipeline_events import write_pipeline_event


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Log pipeline event from ops wrapper scripts")
    p.add_argument("--pipeline", required=True)
    p.add_argument("--slot", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--return-code", type=int, default=0)
    p.add_argument("--event-date", required=True)
    p.add_argument("--category", default="")
    p.add_argument("--detail", default="")
    p.add_argument("--source-path", default="scripts/ops")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    payload = {}
    if args.category:
        payload["error_category"] = args.category
    if args.detail:
        payload["detail"] = args.detail
    write_pipeline_event(
        pipeline=args.pipeline,
        slot=args.slot,
        stage=args.stage,
        status=args.status,
        return_code=int(args.return_code),
        event_date=args.event_date,
        payload=payload if payload else None,
        source_path=args.source_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

