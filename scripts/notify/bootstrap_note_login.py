from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open note in a browser, let the user log in manually, and save Playwright storage state."
    )
    parser.add_argument(
        "--note-config",
        required=True,
        help="Path to the local note automation config JSON.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        help="How long to wait for the browser session to leave the login page.",
    )
    parser.add_argument(
        "--poll-ms",
        type=int,
        default=1000,
        help="Polling interval while waiting for login to complete.",
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


def login_completed(page: Any, login_url: str) -> bool:
    current = str(page.url or "")
    if not current:
        return False
    if "note.com/login" in current:
        return False
    if current.rstrip("/") == login_url.rstrip("/"):
        return False
    return "note.com" in current


def main() -> None:
    args = parse_args()
    config = load_json(Path(args.note_config))
    storage_state_path = resolve_optional_path(config.get("storage_state_path"))
    chrome_user_data_dir = resolve_optional_path(config.get("chrome_user_data_dir"))
    chrome_profile_directory = config.get("chrome_profile_directory")
    login_url = str(config.get("login_url") or config.get("editor_url") or "https://note.com/login")
    chrome_channel = str(config.get("browser_channel") or "").strip()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run `python -m pip install playwright` and "
            "`playwright install chromium` before bootstrapping note login."
        ) from exc

    with sync_playwright() as playwright:
        browser = None
        if chrome_user_data_dir is not None:
            chrome_user_data_dir.mkdir(parents=True, exist_ok=True)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(chrome_user_data_dir),
                channel=chrome_channel or None,
                headless=False,
                args=(
                    [f"--profile-directory={chrome_profile_directory}"]
                    if chrome_profile_directory
                    else None
                ),
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
        page.goto(login_url, wait_until="domcontentloaded")
        print("Log in to note in the opened browser, preferably with note email/note ID.")
        print("Google OAuth may be blocked in Playwright-controlled browsers as 'not secure'.")
        print(f"Waiting up to {args.timeout_seconds}s for login to complete...")
        timeout_ms = max(1, args.timeout_seconds) * 1000
        poll_ms = max(200, args.poll_ms)
        waited = 0
        while waited < timeout_ms:
            if login_completed(page, login_url):
                break
            page.wait_for_timeout(poll_ms)
            waited += poll_ms
        else:
            raise TimeoutError(
                "Timed out waiting for note login to complete. "
                "Keep the browser open and rerun if needed."
            )
        if storage_state_path is not None and chrome_user_data_dir is None:
            storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(storage_state_path))
        context.close()
        if browser is not None:
            browser.close()
        if chrome_user_data_dir is not None:
            print(f"Ready to reuse Chrome profile at {chrome_user_data_dir}")
        elif storage_state_path is not None:
            print(f"Saved storage state to {storage_state_path}")


if __name__ == "__main__":
    main()
