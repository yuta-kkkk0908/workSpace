#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Detect whether signal message changed since last post")
    p.add_argument(
        "--message",
        default="prompts/market-signals-discord-message.txt",
        help="message text path",
    )
    p.add_argument(
        "--state",
        default="prompts/.last-signal-message.sha256.txt",
        help="hash state file path",
    )
    p.add_argument(
        "--update",
        action="store_true",
        help="update state hash when changed",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    msg_path = Path(args.message)
    state_path = Path(args.state)

    if not msg_path.exists():
        print(f"missing message file: {msg_path}")
        return 2

    message = msg_path.read_text(encoding="utf-8")
    if not message.strip():
        print("empty message")
        return 2

    current = hashlib.sha256(message.encode("utf-8")).hexdigest()
    last = state_path.read_text(encoding="utf-8").strip() if state_path.exists() else ""

    if current == last:
        print("unchanged")
        return 1

    print("changed")
    if args.update:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(current + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
