#!/usr/bin/env python3
import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

TOPICS_DIR = ROOT / "topics"
SAMPLE_TOPICS_DIR = ROOT / "sample-topics"
TEMPLATES_DIR = ROOT / "templates" / "topic"
SCHEMAS_DIR = ROOT / "schemas"
INVESTMENT_SEEDS_CONFIG = ROOT / "configs" / "investment-seeds.json"
DEFAULT_DB_DATE = date.today().isoformat()

DB_SPECS = {
    "topics": {
        "path": ROOT / "data" / "topics.db",
        "tables": {"ingest_log", "topic_daily_digest", "topic_links"},
    },
    "needs": {
        "path": ROOT / "data" / "needs.db",
        "tables": {"ingest_log", "need_items", "need_item_state"},
    },
    "investment": {
        "path": resolve_investment_db(),
        "tables": {"raw_events", "signals", "entry_candidates", "backtest_outcomes", "opening_scenarios", "execution_plan"},
    },
    "ops": {
        "path": ROOT / "data" / "ops.db",
        "tables": {"task_log_events", "discord_log_events", "discord_task_events", "agent_memory_events"},
    },
}

KIND_TO_DB = {
    "daily-watch": "topics",
    "need-watch": "needs",
    "research": "investment",
    "ops": "ops",
}

SCHEMA_MAP = {
    "topic-manifest.json": SCHEMAS_DIR / "topic-manifest.schema.json",
    "tasks.json": SCHEMAS_DIR / "tasks.schema.json",
    "sources.json": SCHEMAS_DIR / "sources.schema.json",
}

CANONICAL_FILES = [
    "topic-manifest.json",
    "index.md",
    "summary.md",
    "decisions.md",
    "tasks.json",
    "sources.json",
]

REQUIRED_DIRS = [
    "inbox",
    "archive",
]

SENSITIVE_PATTERNS = [
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"confidential", re.IGNORECASE),
    re.compile(r"gmail\\.com|yahoo\\.co\\.jp|outlook\\.com", re.IGNORECASE),
]


def relpath(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        return f.read()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate topic structure/schema and optional DB-first consistency checks")
    p.add_argument("--check-db-first", action="store_true", help="Also validate DB existence/tables and manifest kind to DB mapping.")
    p.add_argument("--db-date", default=DEFAULT_DB_DATE, help="Target date for daily-watch existence check (YYYY-MM-DD).")
    return p.parse_args()


def validate_json_schema(target: Path, schema_path: Path) -> tuple[object | None, list[str]]:
    errors: list[str] = []
    try:
        data = load_json(target)
    except json.JSONDecodeError as exc:
        return None, [f"{relpath(target)}: invalid JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})"]

    schema = load_json(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in err.path)
        suffix = f" at {location}" if location else ""
        errors.append(f"{relpath(target)}: schema violation{suffix}: {err.message}")
    return data, errors


def collect_targets() -> list[tuple[Path, Path]]:
    targets: list[tuple[Path, Path]] = []

    for base_dir in [TOPICS_DIR, SAMPLE_TOPICS_DIR]:
        if not base_dir.exists():
            continue
        for topic_dir in sorted(p for p in base_dir.iterdir() if p.is_dir()):
            for filename, schema_path in SCHEMA_MAP.items():
                targets.append((topic_dir / filename, schema_path))

    for filename, schema_path in SCHEMA_MAP.items():
        targets.append((TEMPLATES_DIR / filename, schema_path))

    return targets


def validate_topic_structure(topic_dir: Path) -> list[str]:
    errors: list[str] = []

    for filename in CANONICAL_FILES:
        target = topic_dir / filename
        if not target.exists():
            errors.append(f"{relpath(target)}: missing canonical file")

    for dirname in REQUIRED_DIRS:
        target = topic_dir / dirname
        if not target.exists():
            errors.append(f"{relpath(target)}: missing required directory")
        elif not target.is_dir():
            errors.append(f"{relpath(target)}: expected directory")

    return errors


def validate_tasks_semantics(target: Path, tasks: object) -> list[str]:
    if not isinstance(tasks, list):
        return []

    errors: list[str] = []
    seen_ids: set[str] = set()
    for item in tasks:
        if not isinstance(item, dict):
            continue
        task_id = item.get("id")
        if task_id in seen_ids:
            errors.append(f"{relpath(target)}: duplicate task id: {task_id}")
        else:
            seen_ids.add(task_id)
    return errors


def validate_sources_semantics(topic_dir: Path, target: Path, sources: object) -> list[str]:
    if not isinstance(sources, list):
        return []

    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for item in sources:
        if not isinstance(item, dict):
            continue

        source_id = item.get("id")
        if source_id in seen_ids:
            errors.append(f"{relpath(target)}: duplicate source id: {source_id}")
        else:
            seen_ids.add(source_id)

        source_path = item.get("path")
        if source_path in seen_paths:
            errors.append(f"{relpath(target)}: duplicate source path: {source_path}")
        else:
            seen_paths.add(source_path)

        if isinstance(source_path, str) and source_path:
            resolved = topic_dir / source_path
            if not resolved.exists():
                errors.append(f"{relpath(target)}: referenced path does not exist: {source_path}")

    return errors


def validate_manifest_semantics(topic_dir: Path, target: Path, manifest: object) -> list[str]:
    if not isinstance(manifest, dict):
        return []

    errors: list[str] = []
    expected_slug = topic_dir.name
    if manifest.get("slug") != expected_slug:
        errors.append(f"{relpath(target)}: slug must match directory name '{expected_slug}'")

    if topic_dir.parent == SAMPLE_TOPICS_DIR:
        if manifest.get("storage") != "sample":
            errors.append(f"{relpath(target)}: sample topic storage must be 'sample'")
        if manifest.get("visibility") not in {"sample", "public"}:
            errors.append(f"{relpath(target)}: sample topic visibility must be 'sample' or 'public'")
    elif topic_dir.parent == TOPICS_DIR:
        if manifest.get("storage") != "workspace":
            errors.append(f"{relpath(target)}: local topic storage must be 'workspace'")
        if manifest.get("visibility") != "local":
            errors.append(f"{relpath(target)}: local topic visibility must be 'local'")

    return errors


def validate_sample_topic_safety(sample_dir: Path) -> list[str]:
    errors: list[str] = []
    for path in sample_dir.rglob("*"):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        text = load_text(path)
        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(text):
                errors.append(
                    f"{relpath(path)}: potential sensitive content matched pattern '{pattern.pattern}'"
                )
    return errors


def validate_investment_seed_config() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    validated: list[str] = []
    if not INVESTMENT_SEEDS_CONFIG.exists():
        return errors, validated

    try:
        data = load_json(INVESTMENT_SEEDS_CONFIG)
    except json.JSONDecodeError as exc:
        return [f"{relpath(INVESTMENT_SEEDS_CONFIG)}: invalid JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})"], validated

    if not isinstance(data, dict):
        return [f"{relpath(INVESTMENT_SEEDS_CONFIG)}: expected object"], validated

    default_seed_list = data.get("defaultSeedList")
    seed_lists = data.get("seedLists")
    if not isinstance(default_seed_list, str) or not default_seed_list:
        errors.append(f"{relpath(INVESTMENT_SEEDS_CONFIG)}: defaultSeedList must be a non-empty string")
    if not isinstance(seed_lists, dict) or not seed_lists:
        errors.append(f"{relpath(INVESTMENT_SEEDS_CONFIG)}: seedLists must be a non-empty object")
        return errors, validated
    if isinstance(default_seed_list, str) and default_seed_list not in seed_lists:
        errors.append(f"{relpath(INVESTMENT_SEEDS_CONFIG)}: defaultSeedList does not exist in seedLists: {default_seed_list}")

    for list_name, paths in seed_lists.items():
        if not isinstance(paths, list) or not paths:
            errors.append(f"{relpath(INVESTMENT_SEEDS_CONFIG)}: seedLists.{list_name} must be a non-empty array")
            continue
        seen_paths: set[str] = set()
        for idx, item in enumerate(paths):
            if not isinstance(item, str) or not item:
                errors.append(f"{relpath(INVESTMENT_SEEDS_CONFIG)}: seedLists.{list_name}[{idx}] must be a non-empty string")
                continue
            if Path(item).is_absolute() or ".." in Path(item).parts:
                errors.append(f"{relpath(INVESTMENT_SEEDS_CONFIG)}: seedLists.{list_name}[{idx}] must be a safe repo-relative path: {item}")
                continue
            if item in seen_paths:
                errors.append(f"{relpath(INVESTMENT_SEEDS_CONFIG)}: duplicate seed path in {list_name}: {item}")
            seen_paths.add(item)
            resolved = ROOT / item
            if not resolved.exists():
                errors.append(f"{relpath(INVESTMENT_SEEDS_CONFIG)}: referenced seed file does not exist: {item}")

    if not errors:
        validated.append(relpath(INVESTMENT_SEEDS_CONFIG))
    return errors, validated


def list_db_tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return {str(r[0]) for r in rows}


def collect_topic_manifests() -> list[tuple[Path, dict]]:
    manifests: list[tuple[Path, dict]] = []
    for base_dir in [TOPICS_DIR, SAMPLE_TOPICS_DIR]:
        if not base_dir.exists():
            continue
        for topic_dir in sorted(p for p in base_dir.iterdir() if p.is_dir()):
            manifest_path = topic_dir / "topic-manifest.json"
            if not manifest_path.exists():
                continue
            try:
                data = load_json(manifest_path)
            except Exception:
                continue
            if isinstance(data, dict):
                manifests.append((manifest_path, data))
    return manifests


def validate_db_first(db_date: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    validated: list[str] = []

    for key, spec in DB_SPECS.items():
        db_path = spec["path"]
        if not db_path.exists():
            errors.append(f"{relpath(db_path)}: missing DB file ({key})")
            continue
        try:
            tables = list_db_tables(db_path)
        except Exception as exc:
            errors.append(f"{relpath(db_path)}: unable to inspect tables ({type(exc).__name__}: {exc})")
            continue
        missing = sorted(spec["tables"] - tables)
        if missing:
            errors.append(f"{relpath(db_path)}: missing required tables ({key}): {', '.join(missing)}")
            continue
        validated.append(relpath(db_path))

    manifests = collect_topic_manifests()
    daily_watch_slugs: list[str] = []
    for manifest_path, manifest in manifests:
        kind = str(manifest.get("kind", "") or "").strip()
        slug = str(manifest.get("slug", "") or "").strip()
        if not slug:
            continue
        expected_db_key = KIND_TO_DB.get(kind)
        if expected_db_key is None:
            # demo/reference are intentionally outside DB-first mapping.
            continue
        expected_db_path = DB_SPECS[expected_db_key]["path"]
        if not expected_db_path.exists():
            errors.append(
                f"{relpath(manifest_path)}: kind '{kind}' expects {relpath(expected_db_path)} but DB file is missing"
            )
            continue
        validated.append(f"{relpath(manifest_path)}: kind={kind} -> {relpath(expected_db_path)}")
        # Daily existence checks are for runtime topics only (exclude sample-topics).
        if kind == "daily-watch" and manifest_path.parent.parent == TOPICS_DIR and slug != "investment-research":
            daily_watch_slugs.append(slug)

    topics_db_path = DB_SPECS["topics"]["path"]
    if daily_watch_slugs and topics_db_path.exists():
        try:
            conn = sqlite3.connect(topics_db_path)
            try:
                for slug in sorted(set(daily_watch_slugs)):
                    count = conn.execute(
                        "SELECT COUNT(*) FROM topic_daily_digest WHERE topic=? AND date=?",
                        (slug, db_date),
                    ).fetchone()[0]
                    if int(count or 0) <= 0:
                        errors.append(
                            f"{relpath(topics_db_path)}: topic_daily_digest missing for daily-watch topic='{slug}' date={db_date}"
                        )
            finally:
                conn.close()
        except Exception as exc:
            errors.append(f"{relpath(topics_db_path)}: daily-watch DB check failed ({type(exc).__name__}: {exc})")

    return errors, validated


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    validated: list[str] = []

    for base_dir in [TOPICS_DIR, SAMPLE_TOPICS_DIR]:
        if not base_dir.exists():
            continue
        for topic_dir in sorted(p for p in base_dir.iterdir() if p.is_dir()):
            errors.extend(validate_topic_structure(topic_dir))
            if base_dir == SAMPLE_TOPICS_DIR:
                errors.extend(validate_sample_topic_safety(topic_dir))

    for target, schema_path in collect_targets():
        if not target.exists():
            errors.append(f"{relpath(target)}: missing file")
            continue

        data, schema_errors = validate_json_schema(target, schema_path)
        errors.extend(schema_errors)
        if schema_errors:
            continue

        if target.name == "topic-manifest.json":
            errors.extend(validate_manifest_semantics(target.parent, target, data))
        elif target.name == "tasks.json":
            errors.extend(validate_tasks_semantics(target, data))
        elif target.name == "sources.json":
            topic_dir = target.parent if target.parent != TEMPLATES_DIR else TEMPLATES_DIR
            errors.extend(validate_sources_semantics(topic_dir, target, data))

        validated.append(relpath(target))

    seed_errors, seed_validated = validate_investment_seed_config()
    errors.extend(seed_errors)
    validated.extend(seed_validated)

    if args.check_db_first:
        db_errors, db_validated = validate_db_first(args.db_date)
        errors.extend(db_errors)
        validated.extend(db_validated)

    if errors:
        print("Validation failed")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Validation passed")
    for path in validated:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
