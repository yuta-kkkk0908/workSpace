import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.notify import render_paper_stats_discord_message as mod


class RenderPaperStatsDiscordMessageTests(unittest.TestCase):
    def test_render_includes_rule_based_and_ai_review_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "topics" / "investment-research" / "inbox"
            out_dir = root / "prompts"
            inbox.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            db_path = root / "investment.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE paper_trades (
                  trade_id TEXT PRIMARY KEY,
                  mode TEXT NOT NULL,
                  entry_date TEXT NOT NULL,
                  ticker TEXT NOT NULL,
                  company TEXT NOT NULL DEFAULT '',
                  side TEXT NOT NULL,
                  lots INTEGER NOT NULL DEFAULT 1,
                  entry_style TEXT NOT NULL DEFAULT '',
                  planned_entry_price REAL,
                  status TEXT NOT NULL DEFAULT '',
                  signal_id TEXT,
                  source_path TEXT NOT NULL DEFAULT '',
                  updated_at TEXT NOT NULL,
                  price_path_json TEXT,
                  t1_return_pct REAL,
                  t5_return_pct REAL,
                  t20_return_pct REAL
                );
                CREATE TABLE collection_artifacts (
                  artifact_key TEXT NOT NULL,
                  artifact_date TEXT NOT NULL,
                  artifact_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(artifact_key, artifact_date)
                );
                """
            )
            conn.executemany(
                """
                INSERT INTO paper_trades(
                  trade_id, mode, entry_date, ticker, company, side, lots, entry_style,
                  planned_entry_price, status, signal_id, source_path, updated_at, price_path_json,
                  t1_return_pct, t5_return_pct, t20_return_pct
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        "t1",
                        "live",
                        "2026-06-04",
                        "1111",
                        "Test Live",
                        "long",
                        1,
                        "auto",
                        None,
                        "open",
                        "",
                        "",
                        "2026-06-04T00:00:00Z",
                        json.dumps(
                            {
                                "base_close": 100.0,
                                "bars": [{"close": 100.0}, {"close": 101.0}, {"close": 102.0}, {"close": 103.0}, {"close": 104.0}, {"close": 105.0}, {"close": 106.0}, {"close": 107.0}, {"close": 108.0}, {"close": 109.0}, {"close": 110.0}],
                            },
                            ensure_ascii=False,
                        ),
                        1.0,
                        2.0,
                        3.0,
                    ),
                    (
                        "t2",
                        "watch",
                        "2026-06-04",
                        "2222",
                        "Test Watch",
                        "long",
                        1,
                        "auto",
                        None,
                        "open",
                        "",
                        "",
                        "2026-06-04T00:00:00Z",
                        json.dumps(
                            {
                                "base_close": 100.0,
                                "bars": [{"close": 100.0}, {"close": 99.0}, {"close": 98.0}, {"close": 97.0}, {"close": 96.0}, {"close": 95.0}, {"close": 94.0}, {"close": 93.0}, {"close": 92.0}, {"close": 91.0}, {"close": 90.0}],
                            },
                            ensure_ascii=False,
                        ),
                        -1.0,
                        -2.0,
                        -3.0,
                    ),
                ],
            )
            conn.execute(
                "INSERT INTO collection_artifacts VALUES(?,?,?,?,?)",
                (
                    "weekly_tuning_review",
                    "2026-06-05",
                    "weekly_review",
                    json.dumps({"kpi": {"watch_ratio_pct": 33.3}}, ensure_ascii=False),
                    "2026-06-05T12:00:00Z",
                ),
            )
            conn.commit()
            conn.close()

            review_file = inbox / "2026-06-05-weekly-trade-watch-review.md"
            review_file.write_text(
                "\n".join(
                    [
                        "# Weekly Trade/Watch Review",
                        "",
                        "## Next Week Actions (Auto)",
                        "- trade実績が薄い。次週はロット固定で検証優先（拡大しない）。",
                        "- watch優位。昇格しきい値（min_samples/min_winrate）を段階緩和して候補を増やす。",
                        "- exit設計は現行維持。T+1/T+5/T+20の差分が明確化するまでデータ蓄積を継続する。",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            ai_review_file = inbox / "2026-06-05-weekly-tuning-ai-review.md"
            ai_review_file.write_text(
                "\n".join(
                    [
                        "1) 先週の要点",
                        "- AI要点A",
                        "- AI要点B",
                        "",
                        "2) ボトルネック",
                        "- AIボトルネックA",
                        "",
                        "3) 次週の実験タスク",
                        "- AIタスクA",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            argv = [
                "render_paper_stats_discord_message.py",
                "--date",
                "2026-06-05",
                "--db",
                str(db_path),
            ]
            with patch.object(mod, "INBOX", inbox), patch.object(mod, "OUT_DIR", out_dir), patch.object(sys, "argv", argv):
                rc = mod.main()

            self.assertEqual(rc, 0)
            text = (out_dir / "paper-stats-discord-message.txt").read_text(encoding="utf-8")
            self.assertIn("【次週アクション（ルールベース）】", text)
            self.assertIn("【AIレビュー】", text)
            self.assertIn("trade実績(live)", text)
            self.assertIn("T+3", text)
            self.assertIn("T+10", text)
            self.assertIn("用語: trade=実エントリー / become=有望シグナル / watch=監視", text)
            self.assertIn("trade実績が薄い", text)
            self.assertIn("AI要点A", text)
            self.assertIn("AIボトルネックA", text)


if __name__ == "__main__":
    unittest.main()
