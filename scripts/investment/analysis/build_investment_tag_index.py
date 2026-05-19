#!/usr/bin/env python3
"""Build a lightweight tag index for investment-research notes."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOPIC = ROOT / "topics/investment-research"
INBOX = TOPIC / "inbox"
OUT_JSON = TOPIC / "tag-index.json"
OUT_MD = TOPIC / "tag-index.md"
JST = timezone(timedelta(hours=9))


FIELD_RE = re.compile(r"^- ([^:：]+)[:：]\s*(.*)$")
HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def norm(value: str | None) -> str:
    return (value or "").strip()


def split_signal_types(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[/,、\s]+", value)
    return [p.strip("` ") for p in parts if p.strip("` ")]


def signal_tag(signal: str) -> str:
    s = signal.lower()
    mapping = {
        "earnings_positive": "sig:earnings_positive",
        "earnings_negative": "sig:earnings_negative",
        "dividend_revision": "sig:dividend_revision",
        "buyback": "sig:buyback",
        "capital_policy": "sig:capital_policy",
        "midterm_plan": "sig:capital_policy",
        "shareholder_return_policy": "sig:capital_policy",
        "ma_tob": "sig:ma_tob",
        "large_order": "sig:large_order",
        "monthly_kpi": "sig:monthly_kpi",
        "risk_event": "sig:risk_event",
        "dilution": "sig:dilution",
        "external_trigger": "sig:external_trigger",
        "technical": "sig:technical",
    }
    return mapping.get(s, f"sig:{s}" if s else "sig:other")


def rank_tag(prefix: str, value: str) -> str | None:
    v = value.strip().upper()
    if v in {"A", "B", "C"}:
        return f"rank:{prefix}_{v.lower()}"
    return None


def direction_tags(fields: dict[str, str]) -> list[str]:
    tags: set[str] = set()
    expected = fields.get("expectedDirection", "").lower()
    trade_use = fields.get("tradeUse", "").lower()
    candidate = fields.get("candidateUse", "").lower()
    long_rank = fields.get("longSignalRank", "").upper()
    short_rank = fields.get("shortSignalRank", "").upper()

    if "up" in expected or long_rank in {"A", "B"}:
        tags.add("dir:long")
    if "down" in expected or short_rank in {"A", "B"} or "short" in trade_use or "short" in candidate:
        tags.add("dir:short")
    if "avoid" in expected or "avoid" in trade_use or "exit" in trade_use or "avoid" in candidate:
        tags.add("dir:avoid")
    if "neutral" in expected:
        tags.add("dir:neutral")
    if "watch" in expected or "watch" in trade_use or "watch" in candidate:
        tags.add("dir:watch")
    if not tags:
        tags.add("dir:unknown")
    return sorted(tags)


def market_tags(text: str, fields: dict[str, str]) -> list[str]:
    combined = " ".join([text.lower(), " ".join(v.lower() for v in fields.values())])
    if any(x in combined for x in ["tailwind", "追い風", "risk_on", "リスクオン"]):
        return ["mkt:tailwind"]
    if any(x in combined for x in ["headwind", "逆風", "risk_off", "リスクオフ"]):
        return ["mkt:headwind"]
    if "mixed" in combined:
        return ["mkt:mixed"]
    if "neutral" in combined:
        return ["mkt:neutral"]
    return ["mkt:unknown"]


def quality_tags(text: str, fields: dict[str, str]) -> list[str]:
    tags: set[str] = set()
    combined = " ".join([text, " ".join(fields.values())]).lower()
    if any(x in combined for x in ["未確認", "unknown", "未取得", "確認待ち"]):
        tags.add("q:unverified")
    else:
        tags.add("q:confirmed")
    if "secondary_only" in combined or "二次情報" in combined:
        tags.add("q:secondary_only")
    if "t+1" in combined or "t+5" in combined or "t+20" in combined:
        tags.add("q:needs_outcome")
    if "technical" in combined or "テクニカル" in combined or "ma25" in combined or "出来高" in combined:
        tags.add("q:needs_technical")
    if "margin" in combined or "信用" in combined or "貸借" in combined:
        tags.add("q:needs_margin")
    return sorted(tags)


def rule_tags(text: str, fields: dict[str, str]) -> list[str]:
    combined = " ".join([text, " ".join(fields.values())]).lower()
    tags: set[str] = set()
    if "active_rule" in combined:
        tags.add("rule:active")
    if "watch_rule" in combined or "rulehits" in combined or "rulehits" in {k.lower() for k in fields}:
        tags.add("rule:watch")
    if "hypothesis" in combined or "hypothesisonly" in combined:
        tags.add("rule:hypothesis")
    if "exception" in combined or "例外" in combined:
        tags.add("rule:exception")
    if not tags:
        tags.add("rule:none")
    return sorted(tags)


def priority_tags(text: str, fields: dict[str, str]) -> list[str]:
    combined = " ".join([text, " ".join(fields.values())]).lower()
    tags: set[str] = set()
    if "deep_dive_now" in combined:
        tags.add("prio:deep_dive_now")
    if "deep_queue" in combined:
        tags.add("prio:deep_queue")
    if "no_change" in combined or "n/c" in combined:
        tags.add("prio:no_change")
    if any(x in combined for x in ["watchreason", "watch", "監視", "確認観点"]):
        tags.add("prio:watch")
    if not tags:
        tags.add("prio:unknown")
    return sorted(tags)


def horizon_tags(text: str, fields: dict[str, str]) -> list[str]:
    combined = " ".join([text, " ".join(fields.values())]).lower()
    tags = []
    for h in ["T+0", "T+1", "T+5", "T+20"]:
        if h.lower() in combined:
            tags.append(f"h:{h.replace('+', '')}")
    if "intraday" in combined or "場中" in combined:
        tags.append("h:intraday")
    if "swing" in combined or "スイング" in combined:
        tags.append("h:swing")
    return sorted(set(tags)) or ["h:unknown"]


def date_from_path(path: Path) -> str:
    match = DATE_RE.search(path.name)
    return match.group(1) if match else "unknown"


def parse_market_signal_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    items: list[dict] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if not current_title or not current_lines:
            current_title = None
            current_lines = []
            return
        body = "\n".join(current_lines)
        fields: dict[str, str] = {}
        for line in current_lines:
            match = FIELD_RE.match(line)
            if match:
                fields[match.group(1).strip()] = match.group(2).strip()
        item = build_item(path, current_title, body, fields)
        items.append(item)
        current_title = None
        current_lines = []

    for line in lines:
        heading = HEADING_RE.match(line)
        if heading:
            title = heading.group(1)
            if title.lower().startswith("item_") or title in {"Signals"}:
                current_lines.append(line)
                continue
            flush()
            current_title = title
            current_lines = []
        elif current_title:
            current_lines.append(line)
    flush()
    return items


def build_item(path: Path, title: str, body: str, fields: dict[str, str]) -> dict:
    tags: set[str] = {"src:market_signal"}
    for signal in split_signal_types(fields.get("signalType", "")):
        tags.add(signal_tag(signal))
    if not any(t.startswith("sig:") for t in tags):
        material = fields.get("材料", "") or fields.get("signalSummary", "")
        material_lower = material.lower()
        material_map = {
            "最高益": "earnings_positive",
            "増益": "earnings_positive",
            "増配": "dividend_revision",
            "減配": "earnings_negative",
            "下方修正": "earnings_negative",
            "自社株買い": "buyback",
            "消却": "capital_policy",
            "株式分割": "capital_policy",
            "希薄化": "dilution",
            "売出": "dilution",
            "TOB": "ma_tob",
        }
        for needle, mapped in material_map.items():
            if needle.lower() in material_lower or needle in material:
                tags.add(signal_tag(mapped))
        for key in ["earnings_positive", "dividend_revision", "capital_policy", "buyback"]:
            if key in material_lower:
                tags.add(signal_tag(key))
        if not any(t.startswith("sig:") for t in tags):
            tags.add("sig:other")
    tags.update(direction_tags(fields))
    for prefix, field in [("long", "longSignalRank"), ("short", "shortSignalRank")]:
        tag = rank_tag(prefix, fields.get(field, ""))
        if tag:
            tags.add(tag)
    if not any(t.startswith("rank:") for t in tags):
        tags.add("rank:unknown")
    tags.update(rule_tags(body, fields))
    tags.update(market_tags(body, fields))
    tags.update(quality_tags(body, fields))
    tags.update(priority_tags(body, fields))
    tags.update(horizon_tags(body, fields))

    ticker = fields.get("ticker", "")
    if not ticker:
        m = re.match(r"^(\d{4})\s+(.+)$", title)
        if m:
            ticker = m.group(1)
    company = fields.get("company", "")
    if not company:
        m = re.match(r"^\d{4}\s+(.+)$", title)
        if m:
            company = m.group(1)

    return {
        "id": f"{date_from_path(path)}::{path.stem}::{slugify(title)}",
        "date": date_from_path(path),
        "path": str(path.relative_to(TOPIC)),
        "title": title,
        "ticker": ticker,
        "company": company,
        "signalType": fields.get("signalType", ""),
        "longSignalRank": fields.get("longSignalRank", ""),
        "shortSignalRank": fields.get("shortSignalRank", ""),
        "expectedDirection": fields.get("expectedDirection", ""),
        "tags": sorted(tags),
        "sourceUrl": fields.get("url", "") or fields.get("出典", ""),
    }


def slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z一-龥ぁ-んァ-ンー]+", "-", value).strip("-")
    return slug[:80] or "item"


def build_index(limit_days: int | None = None) -> dict:
    files = sorted(INBOX.glob("*market-signals.md"))
    if limit_days:
        files = files[-limit_days:]
    items: list[dict] = []
    for path in files:
        items.extend(parse_market_signal_file(path))
    tag_counts = Counter(tag for item in items for tag in item["tags"])
    by_tag: dict[str, list[str]] = defaultdict(list)
    for item in items:
        for tag in item["tags"]:
            by_tag[tag].append(item["id"])
    return {
        "generatedAt": datetime.now(JST).isoformat(timespec="seconds"),
        "topic": "investment-research",
        "itemCount": len(items),
        "tagCounts": dict(sorted(tag_counts.items())),
        "items": items,
        "byTag": {k: v for k, v in sorted(by_tag.items())},
    }


def write_markdown(index: dict) -> None:
    top_tags = sorted(index["tagCounts"].items(), key=lambda x: (-x[1], x[0]))[:30]
    lines = [
        "# Investment Tag Index",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- generatedAt: {index['generatedAt']}",
        f"- itemCount: {index['itemCount']}",
        "- caution: 売買助言ではなく、検索・集計用の軽量タグ索引。",
        "",
        "## Top Tags",
    ]
    lines.extend(f"- `{tag}`: {count}" for tag, count in top_tags)
    lines.extend(["", "## Recent Items"])
    for item in index["items"][-30:]:
        title = item["title"]
        tags = ", ".join(f"`{tag}`" for tag in item["tags"][:12])
        lines.append(f"- {item['date']} {title}: {tags}")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-days", type=int, default=None)
    args = parser.parse_args()

    index = build_index(limit_days=args.limit_days)
    OUT_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(index)
    print(f"wrote {OUT_JSON.relative_to(ROOT)} items={index['itemCount']}")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
