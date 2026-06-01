#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLUGIN_CONFIG = ROOT / "configs" / "topic-ingest-plugins.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Unified runner for topic/needs DB ingestion (plugin-based)")
    p.add_argument("--date", help="target date YYYY-MM-DD (optional)")
    p.add_argument("--target", choices=["topics", "needs", "all"], default="all")
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--topics-db", default="data/topics.db")
    p.add_argument("--needs-db", default="data/needs.db")
    p.add_argument("--plugin-config", default=str(DEFAULT_PLUGIN_CONFIG))
    p.add_argument("--list-plugins", action="store_true", help="show available ingest plugins and exit")
    return p.parse_args()


def run(cmd: list[str]) -> int:
    print("[run]", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


def load_plugins(config_path: Path) -> list[dict]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        raise ValueError(f"invalid plugin config: {config_path}")
    out: list[dict] = []
    for p in plugins:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "") or "").strip()
        script = str(p.get("script", "") or "").strip()
        db_arg = str(p.get("dbArg", "--db") or "--db").strip()
        db_name = str(p.get("dbPathArgName", "") or "").strip()
        if not name or not script or not db_name:
            continue
        out.append({"name": name, "script": script, "dbArg": db_arg, "dbPathArgName": db_name})
    if not out:
        raise ValueError(f"no valid plugins in config: {config_path}")
    return out


def resolve_db_path(arg_name: str, topics_db: str, needs_db: str) -> str:
    if arg_name == "topics_db":
        return topics_db
    if arg_name == "needs_db":
        return needs_db
    raise ValueError(f"unknown dbPathArgName: {arg_name}")


def build_plugin_cmd(plugin: dict, py: str, date: str | None, topics_db: str, needs_db: str) -> list[str]:
    cmd = [
        py,
        str(plugin["script"]),
        str(plugin["dbArg"]),
        resolve_db_path(str(plugin["dbPathArgName"]), topics_db, needs_db),
    ]
    if date:
        cmd.extend(["--date", date])
    return cmd


def main() -> int:
    args = parse_args()
    py = args.python
    rc = 0
    config_path = Path(args.plugin_config)
    plugin_defs = load_plugins(config_path)
    plugin_names = [str(p["name"]) for p in plugin_defs]

    if args.list_plugins:
        for p in plugin_names:
            print(p)
        return 0

    selected: list[str]
    if args.target == "all":
        selected = plugin_names
    else:
        selected = [args.target]

    for plugin_name in selected:
        plugin = next((p for p in plugin_defs if p["name"] == plugin_name), None)
        if plugin is None:
            raise SystemExit(f"plugin not found: {plugin_name}")
        cmd = build_plugin_cmd(plugin, py, args.date, args.topics_db, args.needs_db)
        rc |= run(cmd)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
