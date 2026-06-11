from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post a generated Markdown article to note as a draft via Playwright."
    )
    parser.add_argument("--markdown-path", help="Path to the note-ready Markdown file.")
    parser.add_argument(
        "--db",
        type=Path,
        help="Optional investment DB path used for markdown fallback loading and audit logging.",
    )
    parser.add_argument("--date", help="Target date (YYYY-MM-DD) when loading from DB.")
    parser.add_argument(
        "--digest-topic",
        default="disclosure-digest-note",
        help="daily_digest topic to read when loading from DB.",
    )
    parser.add_argument(
        "--note-config",
        required=True,
        help="Path to the local note automation config JSON.",
    )
    parser.add_argument(
        "--log-path",
        help="Optional JSON log output path.",
    )
    parser.add_argument(
        "--screenshot-path",
        help="Optional screenshot path after the draft save action.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_markdown_text(text: str, source_label: str) -> tuple[str, str]:
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")

    title = ""
    body_start = 0
    for index, line in enumerate(lines):
        if line.strip():
            title = line.strip()
            body_start = index + 1
            break

    if not title:
        raise ValueError(f"Markdown text is empty: {source_label}")

    body = "\n".join(lines[body_start:]).strip()
    if not body:
        raise ValueError(f"Markdown body is empty: {source_label}")

    return title, body


def parse_markdown(markdown_path: Path) -> tuple[str, str]:
    text = markdown_path.read_text(encoding="utf-8")
    return parse_markdown_text(text, str(markdown_path))


def load_markdown_text(markdown_path: Path) -> str:
    text = markdown_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    if not text:
        raise ValueError(f"Markdown file is empty: {markdown_path}")
    return text


def load_markdown_from_db(db_path: Path, target_date: str, topic: str) -> tuple[str, str, str]:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            str(r["name"])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('daily_digest','collection_artifacts')"
            ).fetchall()
        }
        if "daily_digest" in tables:
            row = conn.execute(
                "SELECT summary, path FROM daily_digest WHERE topic=? AND date=?",
                (topic, target_date),
            ).fetchone()
            if row and row["summary"]:
                return str(row["summary"]), f"daily_digest:{topic}", str(row["path"] or "")
        if "collection_artifacts" in tables:
            artifact = conn.execute(
                "SELECT payload_json FROM collection_artifacts WHERE artifact_key=? AND artifact_date=?",
                ("disclosure_digest", target_date),
            ).fetchone()
            if artifact and artifact["payload_json"]:
                payload = json.loads(str(artifact["payload_json"]))
                if isinstance(payload, dict):
                    note_markdown = str(payload.get("note_markdown") or "")
                    if note_markdown.strip():
                        return note_markdown, "collection_artifacts:disclosure_digest", ""
    finally:
        conn.close()
    raise SystemExit(f"note markdown not found in DB for {target_date}")


def ensure_note_post_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS note_draft_posts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          target_date TEXT,
          digest_topic TEXT,
          title TEXT,
          markdown_source TEXT NOT NULL,
          markdown_source_kind TEXT NOT NULL,
          note_config_path TEXT NOT NULL,
          mode TEXT,
          status TEXT NOT NULL,
          error TEXT,
          screenshot_path TEXT,
          payload_json TEXT NOT NULL,
          started_at TEXT NOT NULL,
          saved_at TEXT,
          finished_at TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    columns = {
        str(r[1])
        for r in conn.execute("PRAGMA table_info(note_draft_posts)").fetchall()
    }
    if "finished_at" not in columns:
        conn.execute("ALTER TABLE note_draft_posts ADD COLUMN finished_at TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_note_draft_posts_date_status
          ON note_draft_posts(target_date, status, created_at)
        """
    )


def insert_note_post_audit(db_path: Path | None, payload: dict[str, Any]) -> int | None:
    if db_path is None:
        return None
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        ensure_note_post_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO note_draft_posts(
              target_date,digest_topic,title,markdown_source,markdown_source_kind,
              note_config_path,mode,status,error,screenshot_path,payload_json,started_at,saved_at,finished_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.get("target_date"),
                payload.get("digest_topic"),
                payload.get("title"),
                payload["markdown_source"],
                payload["markdown_source_kind"],
                payload["note_config_path"],
                payload.get("mode"),
                payload["status"],
                payload.get("error"),
                payload.get("screenshot_path"),
                json.dumps(payload, ensure_ascii=False),
                payload["started_at"],
                payload.get("saved_at"),
                payload.get("finished_at"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def update_note_post_audit(db_path: Path | None, row_id: int | None, payload: dict[str, Any]) -> None:
    if db_path is None or row_id is None:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        ensure_note_post_schema(conn)
        conn.execute(
            """
            UPDATE note_draft_posts
            SET target_date=?,
                digest_topic=?,
                title=?,
                markdown_source=?,
                markdown_source_kind=?,
                note_config_path=?,
                mode=?,
                status=?,
                error=?,
                screenshot_path=?,
                payload_json=?,
                started_at=?,
                saved_at=?,
                finished_at=?
            WHERE id=?
            """,
            (
                payload.get("target_date"),
                payload.get("digest_topic"),
                payload.get("title"),
                payload["markdown_source"],
                payload["markdown_source_kind"],
                payload["note_config_path"],
                payload.get("mode"),
                payload["status"],
                payload.get("error"),
                payload.get("screenshot_path"),
                json.dumps(payload, ensure_ascii=False),
                payload["started_at"],
                payload.get("saved_at"),
                payload.get("finished_at"),
                row_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def save_note_post_audit(db_path: Path | None, payload: dict[str, Any]) -> int | None:
    return insert_note_post_audit(db_path, payload)


def format_inline_html(text: str) -> str:
    escaped = html.escape(text)
    url_pattern = re.compile(r"(https?://[^\s<]+)")
    return url_pattern.sub(
        lambda match: (
            f'<a href="{html.escape(match.group(1), quote=True)}">'
            f"{html.escape(match.group(1))}</a>"
        ),
        escaped,
    )


def markdown_to_note_html(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    parts: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        content = "<br>".join(format_inline_html(line) for line in paragraph_lines)
        parts.append(f"<p>{content}</p>")
        paragraph_lines.clear()

    def flush_list() -> None:
        if not list_items:
            return
        items = "".join(f"<li>{format_inline_html(item)}</li>" for item in list_items)
        parts.append(f"<ul>{items}</ul>")
        list_items.clear()

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h3>{format_inline_html(stripped[4:])}</h3>")
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h2>{format_inline_html(stripped[3:])}</h2>")
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h1>{format_inline_html(stripped[2:])}</h1>")
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            list_items.append(stripped[2:])
            continue
        flush_list()
        paragraph_lines.append(stripped)

    flush_paragraph()
    flush_list()
    return "".join(parts)


def dump_log(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def resolve_optional_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    if re.match(r"^/mnt/[a-zA-Z]/", raw_path):
        drive = raw_path[5].upper()
        suffix = raw_path[6:].replace("/", "\\").lstrip("\\")
        return Path(f"{drive}:\\{suffix}")
    return Path(raw_path).expanduser()


def note_login_required(page: Any) -> bool:
    try:
        url = str(page.url or "")
        if "note.com/login" in url:
            return True
        login_markers = [
            "text=ログイン",
            "text=メールアドレス または note ID",
            "input[placeholder*='mail@example.com']",
        ]
        return any(page.locator(selector).count() > 0 for selector in login_markers)
    except Exception:
        return False


def visible_locator(page: Any, selectors: list[str], label: str, pick: str = "first") -> Any:
    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()
        if count == 0:
            continue
        if pick == "last":
            candidate = locator.last
            if candidate.is_visible():
                return candidate
        else:
            candidate = locator.first
            if candidate.is_visible():
                return candidate
    joined = ", ".join(selectors)
    raise RuntimeError(f"Unable to find a visible {label} using selectors: {joined}")


def replace_editor_text(page: Any, locator: Any, text: str) -> None:
    locator.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    is_contenteditable = bool(
        locator.evaluate("(el) => Boolean(el && el.isContentEditable)")
    )
    if not is_contenteditable:
        locator.fill(text)
        return

    lines = text.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        if index > 0:
            page.keyboard.press("Enter")
        if line:
            page.keyboard.insert_text(line)


def replace_editor_markdown(page: Any, locator: Any, text: str) -> None:
    locator.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    is_contenteditable = bool(
        locator.evaluate("(el) => Boolean(el && el.isContentEditable)")
    )
    if not is_contenteditable:
        locator.fill(text)
        return

    html_content = markdown_to_note_html(text)
    locator.evaluate(
        """
        (el, html) => {
            el.innerHTML = html;
            const inputEvent = new InputEvent("input", {
                bubbles: true,
                cancelable: true,
                inputType: "insertFromPaste",
                data: null,
            });
            el.dispatchEvent(inputEvent);
            el.dispatchEvent(new Event("change", { bubbles: true }));
        }
        """,
        html_content,
    )


def run_post(
    markdown_path: Path | None,
    note_config_path: Path,
    log_path: Path | None,
    screenshot_path: Path | None,
    db_path: Path | None,
    target_date: str | None,
    digest_topic: str,
)-> None:
    audit_row_id: int | None = None
    payload: dict[str, Any] = {
        "status": "started",
        "markdown_source": str(markdown_path) if markdown_path is not None else f"db:{target_date}:{digest_topic}",
        "markdown_source_kind": "markdown_path" if markdown_path is not None else "db_lookup",
        "note_config_path": str(note_config_path),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "title": "",
        "target_date": target_date,
        "digest_topic": digest_topic,
        "error": None,
        "mode": None,
        "saved_at": None,
        "finished_at": None,
    }
    audit_row_id = insert_note_post_audit(db_path, payload)

    def finalize_audit() -> None:
        update_note_post_audit(db_path, audit_row_id, payload)

    context = None
    browser = None
    page = None
    try:
        config = load_json(note_config_path)
        if markdown_path is not None:
            title, body = parse_markdown(markdown_path)
            full_markdown = load_markdown_text(markdown_path)
            source_kind = "markdown_path"
            source_label = str(markdown_path)
        else:
            if db_path is None or not target_date:
                raise SystemExit("either --markdown-path or (--db and --date) is required")
            full_markdown, source_kind, source_label = load_markdown_from_db(db_path, target_date, digest_topic)
            title, body = parse_markdown_text(full_markdown, source_label)

        payload["markdown_source"] = source_label
        payload["markdown_source_kind"] = source_kind
        payload["title"] = title

        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            headless = bool(config.get("headless", True))
            storage_state_path = resolve_optional_path(config.get("storage_state_path"))
            chrome_user_data_dir = resolve_optional_path(config.get("chrome_user_data_dir"))
            chrome_profile_directory = config.get("chrome_profile_directory")
            chrome_channel = str(config.get("browser_channel") or "").strip()
            context = None
            browser = None
            page = None
            try:
                if chrome_user_data_dir is not None:
                    chrome_user_data_dir.mkdir(parents=True, exist_ok=True)
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(chrome_user_data_dir),
                        channel=chrome_channel or None,
                        headless=headless,
                        args=(
                            [f"--profile-directory={chrome_profile_directory}"]
                            if chrome_profile_directory
                            else None
                        ),
                    )
                    page = context.pages[0] if context.pages else context.new_page()
                    payload["chrome_user_data_dir"] = str(chrome_user_data_dir)
                    if chrome_channel:
                        payload["browser_channel"] = chrome_channel
                    if chrome_profile_directory:
                        payload["chrome_profile_directory"] = str(chrome_profile_directory)
                else:
                    browser = playwright.chromium.launch(headless=headless)
                    context_kwargs: dict[str, Any] = {}
                    if storage_state_path and storage_state_path.exists():
                        context_kwargs["storage_state"] = str(storage_state_path)
                    context = browser.new_context(**context_kwargs)
                    page = context.new_page()

                page.goto(str(config["editor_url"]), wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                if note_login_required(page):
                    raise RuntimeError(
                        "note login is required before draft posting. "
                        "If Google login shows 'This browser or app may not be secure', "
                        "use note email/note ID login instead via bootstrap_note_login.py."
                    )
                body_locator = visible_locator(
                    page=page,
                    selectors=list(config["body_selectors"]),
                    label="body field",
                    pick=str(config.get("body_selector_pick", "last")),
                )

                if bool(config.get("body_only_mode", False)):
                    replace_editor_markdown(page, body_locator, full_markdown)
                    payload["mode"] = "body_only"
                else:
                    title_locator = visible_locator(
                        page=page,
                        selectors=list(config["title_selectors"]),
                        label="title field",
                        pick=str(config.get("title_selector_pick", "first")),
                    )
                    replace_editor_text(page, title_locator, title)
                    replace_editor_markdown(page, body_locator, body)
                    payload["mode"] = "title_and_body"

                save_locator = visible_locator(
                    page=page,
                    selectors=list(config["save_selectors"]),
                    label="save control",
                    pick=str(config.get("save_selector_pick", "first")),
                )
                save_locator.click()

                wait_ms = int(config.get("post_save_wait_ms", 3000))
                if wait_ms > 0:
                    page.wait_for_timeout(wait_ms)

                if storage_state_path and chrome_user_data_dir is None:
                    context.storage_state(path=str(storage_state_path))

                if screenshot_path is not None:
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot_path), full_page=True)

                payload["status"] = "ok"
                payload["saved_at"] = datetime.now().isoformat(timespec="seconds")
                payload["finished_at"] = payload["saved_at"]
                if screenshot_path is not None:
                    payload["screenshot_path"] = str(screenshot_path)
            except Exception as exc:
                payload["status"] = "error"
                payload["error"] = str(exc)
                payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
                if screenshot_path is not None and page is not None:
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    payload["screenshot_path"] = str(screenshot_path)
                raise
            finally:
                if context is not None:
                    context.close()
                if browser is not None:
                    browser.close()
    except ImportError as exc:
        payload["status"] = "error"
        payload["error"] = (
            "Playwright is not installed. Run `python -m pip install playwright` and "
            "`playwright install chromium` before using note draft posting."
        )
        payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
        finalize_audit()
        raise RuntimeError(payload["error"]) from exc
    finally:
        finalize_audit()
        dump_log(log_path, payload)


def main() -> None:
    args = parse_args()
    run_post(
        markdown_path=Path(args.markdown_path) if args.markdown_path else None,
        note_config_path=Path(args.note_config),
        log_path=Path(args.log_path) if args.log_path else None,
        screenshot_path=Path(args.screenshot_path) if args.screenshot_path else None,
        db_path=Path(args.db) if args.db else None,
        target_date=args.date,
        digest_topic=str(args.digest_topic),
    )


if __name__ == "__main__":
    main()
