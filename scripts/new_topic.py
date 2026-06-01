#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS_DIR = ROOT / "topics"
TEMPLATE_DIR = ROOT / "templates" / "topic"


def slugify(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


def titleize_slug(slug: str) -> str:
    return slug.replace("-", " ")


def build_summary(example_mode: str) -> str:
    if example_mode == "research":
        return """# Summary

## Current State
- 調査用 topic を初期化済み
- まだ整理済みの結論はない

## Key Points
- 未整理情報は `inbox/` に集約する
- 判断は `decisions.md` に理由付きで残す

## Open Questions
- 何を比較対象にするか
- どの評価軸を優先するか
"""

    return """# Summary

## Current State
- 未整理

## Key Points
- まだ要約はありません

## Open Questions
- 未設定
"""


def build_decisions(example_mode: str) -> str:
    if example_mode == "research":
        return """# Decisions

## Decision Log
- まだ決定はありません
"""

    return """# Decisions

## Decision Log
- まだ決定はありません
"""


def build_tasks(example_mode: str, task_prefix: str, topic_slug: str, kind: str) -> str:
    data = []
    if kind in {"daily-watch", "need-watch"}:
        data.append(
            {
                "id": f"{task_prefix}_ingest_001",
                "title": "DB ingest runner で当日分を取り込む",
                "status": "todo",
                "priority": "high",
                "relatedFiles": ["topic-manifest.json", "inbox/"],
                "notes": "実行例: make topic-db-ingest DATE=YYYY-MM-DD",
            }
        )
    if kind == "daily-watch":
        data.append(
            {
                "id": f"{task_prefix}_daily_001",
                "title": "daily-watch の初回収集と digest 確認",
                "status": "todo",
                "priority": "high",
                "relatedFiles": ["summary.md", "decisions.md"],
                "notes": f"check: topic_daily_digest topic={topic_slug}",
            }
        )
    if kind == "need-watch":
        data.append(
            {
                "id": f"{task_prefix}_need_001",
                "title": "need-item の抽出項目を確認する",
                "status": "todo",
                "priority": "high",
                "relatedFiles": ["summary.md", "decisions.md"],
                "notes": "need_items / need_item_state への投入を確認",
            }
        )
    if example_mode == "research":
        data.append(
            {
                "id": f"{task_prefix}_001",
                "title": "調査対象と比較観点を定義する",
                "status": "todo",
                "priority": "high",
                "relatedFiles": ["summary.md", "decisions.md"],
                "notes": "topic の目的に沿って最初の評価軸を揃える",
            }
        )

    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def build_index(topic_title: str, purpose: str, kind: str) -> str:
    return f"""# Topic: {topic_title}

## Purpose
{purpose}

## Kind
{kind}

## Canonical Files
- `topic-manifest.json`
- `summary.md`
- `decisions.md`
- `tasks.json`
- `sources.json`

## Rules
- 新規情報は `inbox/` に保存する
- 要約は `summary.md` を更新する
- 判断は `decisions.md` に記録する
- 次アクションは `tasks.json` に記録する
- 古いデータは `archive/` に移す

## Output Policy
- 現状確認は `summary.md` を優先
- 判断履歴は `decisions.md` を優先
- 次アクションは `tasks.json` を優先
- 根拠は `sources.json` と `inbox/` を参照

## DB Ingest Hook
- 共通 ingest 実行: `make topic-db-ingest DATE=YYYY-MM-DD`
- 個別実行:
  - topic digest: `make topics-db-ingest DATE=YYYY-MM-DD`
  - needs digest: `make needs-db-ingest DATE=YYYY-MM-DD`
"""


def build_manifest(topic_slug: str, topic_title: str, purpose: str, kind: str) -> str:
    data = {
        "slug": topic_slug,
        "title": topic_title,
        "kind": kind,
        "visibility": "local",
        "storage": "workspace",
        "status": "active",
        "publishable": False,
        "description": purpose,
        "sourcePolicy": "mixed",
        "updatedAt": "2026-04-27",
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a new topic from templates/topic.")
    parser.add_argument("topic", help="Topic name or slug")
    parser.add_argument(
        "--slug",
        help="Explicit topic slug. If omitted, it is derived from the topic argument.",
    )
    parser.add_argument(
        "--title",
        help="Display title to write into index.md. If omitted, topic or slug is used.",
    )
    parser.add_argument(
        "--purpose",
        default="この topic で扱う対象を記載する。",
        help="Purpose text to write into index.md",
    )
    parser.add_argument(
        "--from-example",
        choices=["blank", "research"],
        default="blank",
        help="Optional starter shape for the topic contents.",
    )
    parser.add_argument(
        "--kind",
        choices=["research", "daily-watch", "need-watch", "demo", "ops", "reference"],
        help="topic-manifest kind. If omitted, inferred from --from-example.",
    )
    parser.add_argument(
        "--open-task-id-prefix",
        default="task",
        help="Prefix for starter task IDs when using a non-blank example.",
    )
    args = parser.parse_args()

    kind = args.kind or ("research" if args.from_example == "research" else "reference")
    topic_slug = slugify(args.slug or args.topic)
    if not topic_slug:
        print("Failed: topic slug is empty after normalization", file=sys.stderr)
        return 1

    topic_title = args.title or args.topic.strip() or titleize_slug(topic_slug)
    target_dir = TOPICS_DIR / topic_slug
    if target_dir.exists():
        print(f"Failed: topic already exists: {target_dir.relative_to(ROOT)}", file=sys.stderr)
        return 1

    shutil.copytree(TEMPLATE_DIR, target_dir)
    (target_dir / "topic-manifest.json").write_text(
        build_manifest(topic_slug, topic_title, args.purpose, kind),
        encoding="utf-8",
    )
    (target_dir / "index.md").write_text(build_index(topic_title, args.purpose, kind), encoding="utf-8")
    (target_dir / "summary.md").write_text(build_summary(args.from_example), encoding="utf-8")
    (target_dir / "decisions.md").write_text(build_decisions(args.from_example), encoding="utf-8")
    (target_dir / "tasks.json").write_text(
        build_tasks(args.from_example, args.open_task_id_prefix, topic_slug, kind),
        encoding="utf-8",
    )

    print(f"Created: {target_dir.relative_to(ROOT)}")
    print(f"- title: {topic_title}")
    print(f"- slug: {topic_slug}")
    print(f"- kind: {kind}")
    print(f"- from-example: {args.from_example}")
    print("- topic-manifest.json")
    print("- index.md")
    print("- summary.md")
    print("- decisions.md")
    print("- tasks.json")
    print("- sources.json")
    print("- inbox/")
    print("- archive/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
