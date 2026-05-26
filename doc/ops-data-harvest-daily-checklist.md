# 日次運用チェックリスト: Data Harvest

対象ジョブ: `AIOS-Data-Harvest`

## 1. 成功判定

- ジョブ終了コードが `0`
- `run_harvest_backfill.py` の `[summary] failed_days=0`
- `coverage` ログに当日行がある
- `cleanup_raw_events` が実行されている

## 2. KPI確認（当日）

- `jpx_coverage_pct > 0`
- `new_rate >= 0.02`（暫定）
- `bars_coverage_pct` が前日比で非減少
- `error_rate`（失敗コマンド数/実行コマンド数）が 20% 未満

## 3. 失敗時対応

- `collect_jpx_daily_stats.py` 失敗:
  - ネットワーク到達性確認
  - 失敗継続時は `collection_progress(source='jpx_daily')` の `error_message` を確認
- `collect_kabutan_*` 失敗:
  - `--max-pages` を半減して再実行
  - `--sleep` を増やして再実行
- `backfill_price_daily.py` 失敗:
  - `collection_progress(source='price_backfill_yahoo')` の `status='error'` を抽出
  - `--max-tickers` を縮小して再実行

## 4. 再実行コマンド（最小）

```powershell
python scripts/investment/collect/run_harvest_backfill.py --end-date <YYYY-MM-DD> --days 1 --price-max-tickers 10 --price-target-bars 200
```

## 5. 週次確認

- `raw_events` 14日保持が守られているか
- `collection_progress` の `error` が滞留していないか
- `facts_price_daily` の銘柄別本数分布（200本未満/500本未満）を確認

