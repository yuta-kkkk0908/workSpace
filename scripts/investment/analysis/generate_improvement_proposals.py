#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from investment.analysis.generate_improvement_proposals_impl import main


if __name__ == "__main__":
    raise SystemExit(main())
