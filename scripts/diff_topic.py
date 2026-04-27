#!/usr/bin/env python3
import argparse
import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return f.readlines()


def iter_files(left: Path, right: Path) -> list[Path]:
    paths: set[Path] = set()
    for base in [left, right]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.name != ".gitkeep":
                paths.add(path.relative_to(base))
    return sorted(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff two topic directories.")
    parser.add_argument("left", help="Left topic directory")
    parser.add_argument("right", help="Right topic directory")
    args = parser.parse_args()

    left = (ROOT / args.left).resolve()
    right = (ROOT / args.right).resolve()

    if not left.exists():
        print(f"Failed: left path does not exist: {left}")
        return 1
    if not right.exists():
        print(f"Failed: right path does not exist: {right}")
        return 1

    printed = False
    for rel in iter_files(left, right):
        left_file = left / rel
        right_file = right / rel
        diff = difflib.unified_diff(
            read_lines(left_file),
            read_lines(right_file),
            fromfile=str(left_file.relative_to(ROOT)),
            tofile=str(right_file.relative_to(ROOT)),
        )
        chunk = list(diff)
        if chunk:
            printed = True
            print("".join(chunk), end="")

    if not printed:
        print("No differences")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
