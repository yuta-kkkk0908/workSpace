#!/usr/bin/env python3
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class CmdResult:
    cmd: list[str]
    returncode: int


def run_cmd(cmd: list[str], dry_run: bool = False) -> CmdResult:
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"[pipeline] {printable}")
    if dry_run:
        return CmdResult(cmd=cmd, returncode=0)
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {printable} (exit={proc.returncode})")
    return CmdResult(cmd=cmd, returncode=proc.returncode)
