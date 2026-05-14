#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "needs.db"
DEFAULT_MD = ROOT / "prompts" / "needs-ai-queue.md"
DEFAULT_JSON = ROOT / "prompts" / "needs-ai-queue.json"

TOKEN_RE = re.compile(r"[A-Za-z0-9ぁ-んァ-ヶ一-龠]+")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build AI triage queue from needs DB")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--out-md", default=str(DEFAULT_MD))
    p.add_argument("--out-json", default=str(DEFAULT_JSON))
    return p.parse_args()


def tokens(text: str) -> set[str]:
    toks = {t.lower() for t in TOKEN_RE.findall(text or "") if len(t) >= 2}
    stop = {"です", "する", "して", "ある", "いる", "こと", "ため", "よう", "with", "from", "need"}
    return {t for t in toks if t not in stop}


def overlap_score(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    uni = len(a | b)
    return inter / uni if uni else 0.0


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT i.need_id,i.date,i.title,i.category,i.pain,i.request,i.source_url,i.source_path,
                   COALESCE(s.status,'new') AS status, COALESCE(s.cluster_id,'') AS cluster_id
            FROM need_items i
            LEFT JOIN need_item_state s
              ON i.need_id=s.need_id AND i.date=s.date AND i.source_path=s.source_path
            WHERE COALESCE(s.status,'new') IN ('new','queued')
            ORDER BY i.date DESC, i.need_id
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
    finally:
        conn.close()

    items = []
    for r in rows:
        text = " ".join([r["title"] or "", r["pain"] or "", r["request"] or ""])
        items.append(
            {
                "need_id": r["need_id"],
                "date": r["date"],
                "title": r["title"] or "",
                "category": r["category"] or "",
                "pain": r["pain"] or "",
                "request": r["request"] or "",
                "source_url": r["source_url"] or "",
                "source_path": r["source_path"],
                "status": r["status"],
                "cluster_id": r["cluster_id"] or "",
                "_tokens": sorted(tokens(text)),
            }
        )

    # Similarity hints
    pairs = []
    for i in range(len(items)):
        ti = set(items[i]["_tokens"])
        for j in range(i + 1, len(items)):
            tj = set(items[j]["_tokens"])
            s = overlap_score(ti, tj)
            if s >= 0.22:
                pairs.append((s, items[i]["need_id"], items[j]["need_id"]))
    pairs.sort(reverse=True)

    cat_count = Counter(i["category"] or "uncategorized" for i in items)

    md_lines = [
        "# Needs AI Queue",
        "",
        "未整理ニーズのクラスタリングと優先度付けをしてください。",
        "",
        "## Instructions",
        "- 各 need に `cluster_id` を付与",
        "- `status` を `triaged` へ変更する前提で判定",
        "- 重要度を `priority` (1-5) で付与",
        "- 同内容重複は `review_note` に duplicate を記載",
        "",
        "## Category Counts",
    ]
    for k, v in cat_count.most_common():
        md_lines.append(f"- {k}: {v}")

    md_lines.append("")
    md_lines.append("## Similarity Hints")
    if not pairs:
        md_lines.append("- no high-overlap pairs")
    else:
        for s, a, b in pairs[:20]:
            md_lines.append(f"- {a} <-> {b}: score={s:.2f}")

    md_lines.append("")
    md_lines.append("## Queue Items")
    for it in items:
        md_lines.extend(
            [
                f"### {it['need_id']}: {it['title']}",
                f"- date: {it['date']}",
                f"- category: {it['category']}",
                f"- status: {it['status']}",
                f"- current_cluster: {it['cluster_id'] or '(none)'}",
                f"- pain: {it['pain']}",
                f"- request: {it['request']}",
                f"- source_url: {it['source_url']}",
                f"- source_path: {it['source_path']}",
                "",
            ]
        )

    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md_lines).rstrip() + "\n", encoding="utf-8")

    out_json = Path(args.out_json)
    payload = {"items": [{k: v for k, v in it.items() if not k.startswith("_")} for it in items], "similarity_hints": pairs[:50]}
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {out_md.relative_to(ROOT)}")
    print(f"wrote {out_json.relative_to(ROOT)}")
    print(f"queue_items={len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

