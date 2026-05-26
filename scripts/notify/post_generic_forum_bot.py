#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MESSAGE = ROOT / "prompts" / "generic-topics-discord-message.txt"
DEFAULT_STATE = ROOT / "prompts" / "generic-forum-state.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Append generic-topic digests into persistent Discord forum posts")
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
        os.getenv("DISCORD_GENERIC_FORUM_CHANNEL_ID", "").strip()
        or os.getenv("DISCORD_GENERIC_CHANNEL_ID", "").strip()
    )
    if not token:
        raise SystemExit("Discord bot token is empty")
    if not channel_id:
        raise SystemExit("Generic forum channel id is empty")
    return token, channel_id


def empty_state() -> dict:
    return {"latest_date": "", "topics": {}}


def read_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_state()
    if not isinstance(data, dict):
        return empty_state()
    state = empty_state()
    state.update(data)
    state.setdefault("topics", {})
    return state


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discord_request(token: str, method: str, url: str, payload: dict | None = None) -> dict:
    body = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "aios-generic-forum-bot/1.0",
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


def patch_channel(token: str, channel_id: str, payload: dict) -> dict:
    return discord_request(
        token,
        "PATCH",
        f"https://discord.com/api/v10/channels/{channel_id}",
        payload,
    )


def create_forum_thread(token: str, forum_channel_id: str, topic_name: str, starter_content: str) -> dict:
    return discord_request(
        token,
        "POST",
        f"https://discord.com/api/v10/channels/{forum_channel_id}/threads",
        {
            "name": topic_name[:100],
            "auto_archive_duration": 1440,
            "message": {
                "content": starter_content,
                "allowed_mentions": {"parse": []},
            },
        },
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


def load_threads_parser():
    spec = importlib.util.spec_from_file_location("post_generic_threads_bot", ROOT / "scripts" / "notify" / "post_generic_threads_bot.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def build_starter_content(topic_name: str) -> str:
    return f"[{topic_name}]\n汎用トピックの蓄積スレッド"


def build_thread_payload(date_str: str, topic_name: str, body: str, updated: bool) -> str:
    header = f"### {date_str}"
    if updated:
        header += " (updated)"
    return f"{header}\n[{topic_name}]\n{body}".strip()


def main() -> int:
    args = parse_args()
    load_dotenv()
    token, forum_channel_id = load_env()
    parser_mod = load_threads_parser()
    text = Path(args.message_path).read_text(encoding="utf-8")
    date_str, _title, _summary, topics = parser_mod.parse_digest(text)
    state_path = Path(args.state_path)
    state = read_state(state_path)
    state["latest_date"] = max(str(state.get("latest_date", "") or ""), date_str)

    if args.dry_run:
        print(f"forum_channel_id={forum_channel_id}")
        print(f"date={date_str} topics={len(topics)}")
        for topic in topics:
            print(topic["name"])
        return 0

    for topic in topics:
        topic_name = topic["name"]
        body = topic["body"].strip()
        topic_hash = sha256_text(body)
        topic_state = state["topics"].setdefault(topic_name, {"daily_posts": {}})
        topic_state.setdefault("daily_posts", {})
        thread_id = str(topic_state.get("thread_id", "") or "")

        if not thread_id:
            thread = create_forum_thread(token, forum_channel_id, topic_name, build_starter_content(topic_name))
            thread_id = str(thread["id"])
            topic_state["thread_id"] = thread_id

        prior = topic_state["daily_posts"].get(date_str)
        if prior and prior.get("hash") == topic_hash:
            continue

        # Unarchive before posting when the forum post was auto-archived.
        try:
            patch_channel(token, thread_id, {"archived": False, "locked": False})
        except Exception:
            pass

        payload = build_thread_payload(date_str, topic_name, body, updated=bool(prior))
        posted_ids: list[str] = []
        for chunk in split_blocks(payload, 1800):
            resp = post_message(token, thread_id, chunk)
            posted_ids.append(str(resp.get("id", "")))
        topic_state["daily_posts"][date_str] = {"hash": topic_hash, "message_ids": posted_ids}

    write_state(state_path, state)
    print(f"posted generic topic updates into persistent forum posts for {date_str} topics={len(topics)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
