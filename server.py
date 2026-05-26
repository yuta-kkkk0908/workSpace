import json
import os
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

mcp = FastMCP("discord")
load_dotenv()


def _get_token() -> str:
    token = (
        os.getenv("DISCORD_TASKS_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_BOT_TOKEN", "").strip()
    )
    if not token:
        raise RuntimeError(
            "Discord bot token is not set (DISCORD_TASKS_BOT_TOKEN / DISCORD_BOT_TOKEN / DISCORD_TOKEN)"
        )
    return token


def _discord_get(path: str, params: dict[str, str] | None = None) -> list[dict]:
    token = _get_token()
    url = "https://discord.com/api/v10" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "AIOS-MCP-Discord/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Discord API error: status={exc.code} body={body}") from exc


@mcp.tool()
async def list_guilds(limit: int = 50) -> list[dict]:
    """List guilds (servers) the bot is in."""
    limit = max(1, min(int(limit), 200))
    raw = _discord_get("/users/@me/guilds", {"limit": str(limit)})
    out: list[dict] = []
    for g in raw:
        out.append(
            {
                "id": g.get("id"),
                "name": g.get("name"),
                "owner": g.get("owner", False),
            }
        )
    return out


@mcp.tool()
async def list_text_channels(guild_id: str) -> list[dict]:
    """List text channels in a guild (server)."""
    raw = _discord_get(f"/guilds/{int(guild_id)}/channels")
    out: list[dict] = []
    for ch in raw:
        ch_type = ch.get("type")
        # 0=text channel, 5=announcement channel
        if ch_type not in (0, 5):
            continue
        out.append(
            {
                "id": ch.get("id"),
                "name": ch.get("name"),
                "type": ch_type,
                "position": ch.get("position"),
            }
        )
    out.sort(key=lambda x: (x.get("position") or 0, x.get("name") or ""))
    return out


@mcp.tool()
async def find_channel_id(guild_id: str, channel_name: str) -> list[dict]:
    """Find channel IDs by (partial) channel name in a guild."""
    q = (channel_name or "").strip().lower()
    if not q:
        raise RuntimeError("channel_name is required")
    channels = await list_text_channels(guild_id)
    matches: list[dict] = []
    for ch in channels:
        name = (ch.get("name") or "").lower()
        if q in name:
            matches.append(ch)
    return matches


@mcp.tool()
async def latest_messages(channel_id: str, limit: int = 10) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    raw = _discord_get(f"/channels/{int(channel_id)}/messages", {"limit": str(limit)})
    msgs: list[dict] = []
    for msg in raw:
        author = msg.get("author") or {}
        msgs.append(
            {
                "id": msg.get("id"),
                "author": author.get("global_name") or author.get("username"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("timestamp"),
            }
        )
    return msgs


if __name__ == "__main__":
    mcp.run()
