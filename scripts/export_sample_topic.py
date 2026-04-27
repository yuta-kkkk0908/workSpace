#!/usr/bin/env python3
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS_DIR = ROOT / "topics"
SAMPLE_TOPICS_DIR = ROOT / "sample-topics"


def rewrite_manifest(target_dir: Path, sample_slug: str) -> None:
    manifest_path = target_dir / "topic-manifest.json"
    if not manifest_path.exists():
        return

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    manifest["slug"] = sample_slug
    manifest["visibility"] = "sample"
    manifest["storage"] = "sample"
    manifest["publishable"] = True

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a local topic into sample-topics for public-safe examples."
    )
    parser.add_argument("topic_slug", help="Slug under topics/")
    parser.add_argument(
        "--sample-slug",
        help="Slug under sample-topics/. Defaults to <topic-slug>-demo.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite destination sample if it already exists.",
    )
    args = parser.parse_args()

    source_dir = TOPICS_DIR / args.topic_slug
    if not source_dir.exists():
        print(f"Failed: source topic does not exist: {source_dir.relative_to(ROOT)}", file=sys.stderr)
        return 1

    sample_slug = args.sample_slug or f"{args.topic_slug}-demo"
    target_dir = SAMPLE_TOPICS_DIR / sample_slug

    if target_dir.exists():
        if not args.force:
            print(f"Failed: sample already exists: {target_dir.relative_to(ROOT)}", file=sys.stderr)
            return 1
        shutil.rmtree(target_dir)

    shutil.copytree(source_dir, target_dir)
    rewrite_manifest(target_dir, sample_slug)

    print(f"Exported: {source_dir.relative_to(ROOT)} -> {target_dir.relative_to(ROOT)}")
    print("Reminder: review the sample for private data before publishing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
