# Topic DB Design (Draft)

## Goal
topicごとの収集データをDB化し、全ファイル読込を避ける。
「必要な行だけ」LLMへ渡してレートを節約する。

## Current DB
- path: `data/investment.db`
- tables:
  - `daily_digest`
  - `signals`
  - `entry_candidates`
  - `backtest_outcomes`
  - `ingest_log`

- path: `data/topics.db` (non-investment generic)
- tables:
  - `topic_daily_digest`
  - `topic_links`
  - `ingest_log`

- path: `data/needs.db` (product idea / need-watch専用)
- tables:
  - `need_items`
  - `need_item_state`
  - `need_clusters`
  - `ingest_log`

## Design Principle
- 収集ログは `inbox` に残す（原本）
- 分析用は DB に正規化（検索・集計）
- Codex要約には DB抽出結果を使う

## Planned DB Expansion by Topic
### ai-news-watch
- table: `ai_news_items`
- fields: date, source, title, url, impact_tag, verified

### tech-stack-reads
- table: `tech_articles`
- fields: date, source, title, url, domain_tag, why_read

### pokemon-card-watch
- table: `pokemon_watch`
- fields: date, source, pack, event_type, status, url

### product-idea-watch
- table: `needs_items`
- fields: date, source, need_type, pain_summary, frequency_hint, url

## Ingestion Rule
- date単位でupsert
- source pathを必ず保持
- missing/unknownを明示値で保持
- 元ファイルとDBの両方を残す

## Query First Policy
Codexに渡す前に次を先に実行する:
- 当日データ件数
- 上位候補
- 未確認項目
- 期限到来outcome

## Future
- 共通 `topic_ingest_runner.py` を作成
- topic別 parser を plugin 的に分離
- 週次/月次集計ビューを追加
