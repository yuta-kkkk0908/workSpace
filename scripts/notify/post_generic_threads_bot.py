#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MESSAGE = ROOT / "prompts" / "generic-topics-discord-message.txt"
DEFAULT_STATE = ROOT / "prompts" / "generic-threads-state.json"
DEFAULT_CHANNEL_ID = "1504310716998615161"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Append generic-topic digests into persistent Discord threads")
    p.add_argument("--message-path", default=str(DEFAULT_MESSAGE))
    p.add_argument("--state-path", default=str(DEFAULT_STATE))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def load_env() -> tuple[str, str]:
    token = (
        os.getenv("DISCORD_GENERIC_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_TASKS_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_SCENARIOS_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_BOT_TOKEN", "").strip()
    )
    channel_id = (
        os.getenv("DISCORD_GENERIC_CHANNEL_ID", "").strip()
        or os.getenv("DISCORD_GENERIC_TOPICS_CHANNEL_ID", "").strip()
        or DEFAULT_CHANNEL_ID
    )
    if not token:
        raise SystemExit("Discord bot token is empty")
    if not channel_id:
        raise SystemExit("Generic channel id is empty")
    return token, channel_id


def empty_state() -> dict:
    return {"index_message_id": "", "latest_date": "", "topics": {}}


def migrate_legacy_state(data: dict) -> dict:
    state = empty_state()
    if not isinstance(data, dict):
        return state
    if "topics" in data and isinstance(data.get("topics"), dict):
        state.update(data)
        state.setdefault("index_message_id", "")
        state.setdefault("latest_date", "")
        for topic_state in state["topics"].values():
            if isinstance(topic_state, dict):
                topic_state.setdefault("daily_posts", {})
        return state

    dates = data.get("dates", {})
    if not isinstance(dates, dict):
        return state

    for date_str in sorted(dates.keys()):
        date_state = dates.get(date_str, {})
        if not isinstance(date_state, dict):
            continue
        state["latest_date"] = max(state["latest_date"], date_str)
        for topic_name, topic_info in (date_state.get("topics", {}) or {}).items():
            if not isinstance(topic_info, dict):
                continue
            topic_state = state["topics"].setdefault(topic_name, {"daily_posts": {}})
            topic_state.setdefault("anchor_message_id", topic_info.get("anchor_message_id", ""))
            topic_state.setdefault("thread_id", topic_info.get("thread_id", ""))
            daily_posts = topic_state.setdefault("daily_posts", {})
            last_hash = topic_info.get("last_body_hash", "")
            if last_hash:
                daily_posts.setdefault(date_str, {"hash": last_hash, "message_ids": []})
    return state


def read_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_state()
    return migrate_legacy_state(data)


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discord_request(token: str, method: str, url: str, payload: dict | None = None) -> dict:
    body = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "aios-generic-threads-bot/1.0",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API {method} {url} failed: {e.code} {detail}") from e


def post_message(token: str, channel_id: str, content: str) -> dict:
    return discord_request(
        token,
        "POST",
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        {"content": content, "allowed_mentions": {"parse": []}},
    )


def patch_message(token: str, channel_id: str, message_id: str, content: str) -> dict:
    return discord_request(
        token,
        "PATCH",
        f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}",
        {"content": content, "allowed_mentions": {"parse": []}},
    )


def start_thread_from_message(token: str, channel_id: str, message_id: str, name: str) -> dict:
    return discord_request(
        token,
        "POST",
        f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/threads",
        {"name": name[:100], "auto_archive_duration": 1440},
    )


def split_blocks(text: str, limit: int = 1800) -> list[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    buf = ""
    for line in lines:
        cand = f"{buf}\n{line}".strip("\n") if buf else line
        if len(cand) <= limit:
            buf = cand
            continue
        if buf:
            chunks.append(buf)
        if len(line) <= limit:
            buf = line
            continue
        for i in range(0, len(line), limit):
            chunks.append(line[i : i + limit])
        buf = ""
    if buf:
        chunks.append(buf)
    return chunks or [text[:limit]]


def parse_digest(text: str) -> tuple[str, str, str, list[dict[str, str]]]:
    src = (text or "").strip()
    if not src:
        raise ValueError("message is empty")
    lines = src.splitlines()
    title = lines[0].strip()
    m = re.match(r"^汎用トピック日次\s+(\d{4}-\d{2}-\d{2})$", title)
    if not m:
        raise ValueError(f"unexpected title line: {title}")
    date_str = m.group(1)
    summary_lines: list[str] = []
    topics: list[dict[str, str]] = []
    current_name = ""
    current_lines: list[str] = []
    in_topics = False
    for line in lines[1:]:
        if re.match(r"^\[[^\]]+\]$", line.strip()):
            if current_name:
                topics.append({"name": current_name, "body": "\n".join(current_lines).strip()})
            current_name = line.strip()[1:-1]
            current_lines = [line.strip()]
            in_topics = True
            continue
        if in_topics:
            current_lines.append(line)
        else:
            summary_lines.append(line)
    if current_name:
        topics.append({"name": current_name, "body": "\n".join(current_lines).strip()})
    summary = "\n".join([x for x in summary_lines if x.strip()]).strip()
    return date_str, title, summary, topics


def build_index_content(latest_date: str, topics: list[dict[str, str]]) -> str:
    lines = ["汎用トピックスレッド"]
    if latest_date:
        lines.append(f"- 最新反映日: {latest_date}")
    lines.append("- 運用: 各トピックは固定スレッドへ日次追記")
    lines.append("")
    lines.append("トピック一覧:")
    for topic in topics:
        lines.append(f"- {topic['name']}")
    return "\n".join(lines).strip()


def build_anchor_content(topic_name: str, latest_date: str, body: str) -> str:
    preview = ""
    for line in body.splitlines():
        s = line.strip()
        if re.match(r"^\d+\)", s):
            preview = s
            break
    lines = [f"[{topic_name}]"]
    lines.append("日次更新はこのスレッドへ蓄積")
    if latest_date:
        lines.append(f"最新反映: {latest_date}")
    if preview:
        lines.append(f"直近トピック: {preview}")
    return "\n".join(lines)


def build_thread_payload(date_str: str, topic_name: str, body: str, updated: bool) -> str:
    header = f"### {date_str}"
    if updated:
        header += " (updated)"
    return f"{header}\n[{topic_name}]\n{body}".strip()


def main() -> int:
    args = parse_args()
    load_dotenv()
    token, channel_id = load_env()
    message_path = Path(args.message_path)
    state_path = Path(args.state_path)
    text = message_path.read_text(encoding="utf-8")
    date_str, _title, summary, topics = parse_digest(text)
    state = read_state(state_path)
    state["latest_date"] = max(str(state.get("latest_date", "") or ""), date_str)

    index_content = build_index_content(state["latest_date"], topics)
    if args.dry_run:
        print(index_content)
        for topic in topics:
            print("")
            print(build_anchor_content(topic["name"], state["latest_date"], topic["body"]))
        print(f"topics={len(topics)}")
        return 0

    index_message_id = str(state.get("index_message_id", "") or "")
    if not index_message_id:
        resp = post_message(token, channel_id, index_content)
        state["index_message_id"] = str(resp["id"])

    for topic in topics:
        topic_name = topic["name"]
        body = topic["body"].strip()
        topic_hash = sha256_text(body)
        topic_state = state["topics"].setdefault(topic_name, {"daily_posts": {}})
        topic_state.setdefault("daily_posts", {})

        anchor_content = build_anchor_content(topic_name, state["latest_date"], body)
        anchor_message_id = str(topic_state.get("anchor_message_id", "") or "")
        thread_id = str(topic_state.get("thread_id", "") or "")

        if not anchor_message_id:
            resp = post_message(token, channel_id, anchor_content)
            anchor_message_id = str(resp["id"])
            topic_state["anchor_message_id"] = anchor_message_id

        if not thread_id:
            thread = start_thread_from_message(token, channel_id, anchor_message_id, topic_name)
            thread_id = str(thread["id"])
            topic_state["thread_id"] = thread_id

        daily_posts = topic_state["daily_posts"]
        prior = daily_posts.get(date_str)
        if prior and prior.get("hash") == topic_hash:
            continue

        payload = build_thread_payload(date_str, topic_name, body, updated=bool(prior))
        posted_ids: list[str] = []
        for chunk in split_blocks(payload, 1800):
            resp = post_message(token, thread_id, chunk)
            posted_ids.append(str(resp.get("id", "")))
        daily_posts[date_str] = {"hash": topic_hash, "message_ids": posted_ids}

    write_state(state_path, state)
    print(f"posted generic topic updates into persistent threads for {date_str} topics={len(topics)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
