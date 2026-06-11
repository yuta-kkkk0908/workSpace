from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any


EXCLUDE_DIRS = {
    "Cache",
    "Cache_Data",
    "Code Cache",
    "Crashpad",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "GPUCache",
    "GraphiteDawnCache",
    "GrShaderCache",
    "ShaderCache",
    "Safe Browsing",
    "Service Worker",
    "Session Storage",
    "shared_proto_db",
}

EXCLUDE_FILES = {
    "LOCK",
    "LOCKFILE",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync a normal Chrome profile into a dedicated automation profile for note posting."
    )
    parser.add_argument(
        "--note-config",
        required=True,
        help="Path to the local note automation config JSON.",
    )
    parser.add_argument(
        "--source-user-data-dir",
        help="Chrome User Data root to copy from. Defaults to the normal Chrome User Data directory.",
    )
    parser.add_argument(
        "--source-profile-directory",
        default="Default",
        help="Profile directory inside the source User Data root.",
    )
    parser.add_argument(
        "--target-profile-directory",
        help="Profile directory inside the target automation User Data root. Defaults to config value or Default.",
    )
    parser.add_argument(
        "--clean-target",
        action="store_true",
        help="Remove the target profile directory before syncing.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_optional_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    if re.match(r"^/mnt/[a-zA-Z]/", raw_path):
        drive = raw_path[5].upper()
        suffix = raw_path[6:].replace("/", "\\").lstrip("\\")
        return Path(f"{drive}:\\{suffix}")
    return Path(raw_path).expanduser()


def should_skip_dir(path: Path) -> bool:
    return path.name in EXCLUDE_DIRS


def should_skip_file(path: Path) -> bool:
    if path.name in EXCLUDE_FILES:
        return True
    lower = path.name.lower()
    return lower.endswith("-journal") or lower.startswith("singleton")


def copy_tree(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if should_skip_dir(item):
                continue
            target.mkdir(parents=True, exist_ok=True)
            copy_tree(item, target)
            continue
        if should_skip_file(item):
            continue
        try:
            shutil.copy2(item, target)
        except OSError:
            # Skip transient/locked files and continue with the stable subset.
            continue


def main() -> int:
    args = parse_args()
    config = load_json(Path(args.note_config))
    target_user_data_dir = resolve_optional_path(config.get("chrome_user_data_dir"))
    if target_user_data_dir is None:
        raise SystemExit("chrome_user_data_dir is required in note config")

    source_user_data_dir = resolve_optional_path(args.source_user_data_dir)
    if source_user_data_dir is None:
        source_user_data_dir = Path("/mnt/c/Users/yuta_/AppData/Local/Google/Chrome/User Data")

    source_profile_directory = str(args.source_profile_directory or "Default")
    target_profile_directory = str(
        args.target_profile_directory or config.get("chrome_profile_directory") or "Default"
    )

    source_profile_dir = source_user_data_dir / source_profile_directory
    target_profile_dir = target_user_data_dir / target_profile_directory

    if source_user_data_dir.resolve() == target_user_data_dir.resolve():
        raise SystemExit("source and target user data directories must differ")
    if not source_profile_dir.exists():
        raise SystemExit(f"source profile not found: {source_profile_dir}")

    target_user_data_dir.mkdir(parents=True, exist_ok=True)
    if args.clean_target and target_profile_dir.exists():
        shutil.rmtree(target_profile_dir)
    target_profile_dir.mkdir(parents=True, exist_ok=True)

    local_state = source_user_data_dir / "Local State"
    if local_state.exists():
        shutil.copy2(local_state, target_user_data_dir / "Local State")

    copy_tree(source_profile_dir, target_profile_dir)
    print(f"synced: {source_profile_dir} -> {target_profile_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
