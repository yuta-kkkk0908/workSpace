# Investment Python Scripts

## Purpose
投資系 Python の役割、入出力、実行順を整理する。

この一覧は売買助言ではなく、`investment-research` の材料整理、検証、タグ付けを安定して回すための運用メモ。

## Execution Lanes
### adaptive daily lane
毎日の `今日の情報` 後に軽く回す候補。

```bash
make investment-adaptive DATE=YYYY-MM-DD
```

内容:
- 既存 outcome があれば軽い再集計を行う
- long/short の入力が揃っていれば rule dashboard / history を更新する
- market-signals のタグ索引を更新する
- `tag-index.md` / `tag-index.json` を更新する
- AI が次回全文を読み直さずに、同種シグナルや未確認項目を見つけやすくする

### rule check lane
既存データからルール再現性を軽く確認する。

```bash
make investment-rule-check DATE=YYYY-MM-DD
```

内容:
- rough outcome からルール候補を集計する
- daily で使うには、必要に応じて long/short dashboard まで進める

### deep backtest lane
レートと時間に余裕があるときだけ実行する。

```bash
make investment-backtest-expand DATE=YYYY-MM-DD
make investment-backtest-expand DATE=YYYY-MM-DD SEED_LIST=rough_backtest_short_focus
make investment-backtest-expand DATE=YYYY-MM-DD SEED_LIST=rough_backtest_light CACHE_ONLY=1
```

内容:
- サンプル収集
- outcome 補完
- テクニカル/信用/市場/セクター文脈補完
- ロング/ショート再分類
- rule dashboard / rule history / tag-index 更新

### rough backtest を継続拡張する運用手順
`ticker + signalDate + signalType` の新規組を増やし続けるときの、実運用向けの最短手順。

1. まず母集団を拡張側で実行する（通常は `extended`）。

```bash
python scripts/investment/backtest/fill_market_outcomes.py --date YYYY-MM-DD --seed-config configs/investment-seeds-extended.json --seed-list rough_backtest_extended
```

2. `parsed / ok / failed` を確認する。
- `ok` が増えていれば前進。
- `--cache-only` で `failed` が固定する場合は、ネット取得あり（`--cache-only` なし）で再実行する。

3. 同一日付で再実行して補完する。
- このスクリプトは同じ出力ファイルを更新する前提。
- 再開専用フラグはないため、同コマンド再実行で進める。

4. `ok` が目標到達したら採用する。
- 例: `ok >= 300` を採用基準にする。
- `failed=0` まで追うかは運用判断（時間・ネット状況次第）。

5. `failed` 内訳を別ファイル化して次回に回す（任意）。
- 例: `inbox/{date}-rough-backtest-failed-23.md` に `ticker/signalDate/signalType/reason` を保存。
- これで次回の補完対象を明示できる。

6. DB に取り込む。

```bash
python scripts/data/ingest_investment_db.py --date YYYY-MM-DD
```

7. DB反映を確認する（推奨）。
- `data/investment.db` の `backtest_outcomes` を `date=YYYY-MM-DD` で件数確認。
- `source_path` が `topics/investment-research/inbox/{date}-rough-backtest-outcomes-batch-1.md` になっていることを確認。

注意:
- `fill_market_outcomes.py` 自体はDB書き込みしない（Markdown出力 + cache更新のみ）。
- DB件数の「純増」は `ok` 増分と一致しない。`ingest_investment_db.py` は upsert のため、既存キーは更新扱いになる。

#### 実行テンプレート（コピペ用）
```bash
# 0) 3年窓のseedリストを自動更新（推奨）
python scripts/investment/backtest/build_extended_seed_list.py --as-of YYYY-MM-DD --years 3

# 1) outcome 補完（ネット取得あり）
python scripts/investment/backtest/fill_market_outcomes.py --date YYYY-MM-DD --seed-config configs/investment-seeds-extended.json --seed-list rough_backtest_extended

# 2) cache-only で埋まるか確認（必要時）
python scripts/investment/backtest/fill_market_outcomes.py --date YYYY-MM-DD --seed-config configs/investment-seeds-extended.json --seed-list rough_backtest_extended --cache-only

# 3) DB取り込み
python scripts/data/ingest_investment_db.py --date YYYY-MM-DD
```

#### failed が残るときの判断
- `--cache-only` で `failed` が固定する場合、キャッシュ不足が原因なので `--cache-only` なしで再実行する。
- ネット取得ありでも `failed` が固定する場合、当該銘柄の価格欠損・非営業日・シンボル不一致の可能性が高い。
- 運用上は `ok` が目標閾値（例: 300）を超えた時点で採用し、`failed` は別ファイルに分離して次回補完対象に回す。

#### DB反映の確認（SQLite）
```bash
python - <<'PY'
import sqlite3
conn = sqlite3.connect("data/investment.db")
cur = conn.cursor()
date = "YYYY-MM-DD"
print("date_count", cur.execute("select count(*) from backtest_outcomes where date=?", (date,)).fetchone()[0])
for row in cur.execute("select count(*), source_path from backtest_outcomes where date=? group by source_path order by count(*) desc", (date,)):
    print("source", row[0], row[1])
conn.close()
PY
```

#### `backtest_outcomes` の同一性仕様（重複防止）
- 対象テーブル: `data/investment.db` の `backtest_outcomes`
- 取り込みスクリプト: `scripts/data/ingest_investment_db.py` の `upsert_backtest`

同一レコード判定の前提:
- 必須項目は `sourceSignalId` / `signalDate` / `signalType` の3つ。
- いずれかが欠ける行は malformed とみなし、DBに取り込まない。

DB投入時の安定キー:
- `outcome_id` は入力Markdown側の値をそのまま信用せず、以下の決定的IDに正規化して投入する。
- `outcome_<sourceSignalId>_<signalDate>_<signalType>`
- `signalType` は英数字・`_`・`-` 以外を `_` に置換して正規化する。

運用上の意味:
- 再取り込み・再実行時も同一シグナルは同じ `outcome_id` に upsert される。
- `sourceSignalId` のみで取り込んでいた時期に起きた重複混入を再発させない。

既存重複のクレンジング方針:
- 重複判定キーは `source_signal_id + signal_date + signal_type`。
- 同キーで複数行ある場合は `updated_at` 最新を残し、同値時は `rowid` の大きい行を残す。

参考SQL（重複検出）:
```sql
SELECT source_signal_id, signal_date, signal_type, COUNT(*) AS c
FROM backtest_outcomes
WHERE COALESCE(source_signal_id,'')<>''
  AND COALESCE(signal_date,'')<>''
  AND COALESCE(signal_type,'')<>''
GROUP BY source_signal_id, signal_date, signal_type
HAVING COUNT(*) > 1
ORDER BY c DESC;
```

参考SQL（重複削除）:
```sql
DELETE FROM backtest_outcomes
WHERE rowid IN (
  SELECT rowid FROM (
    SELECT rowid,
           ROW_NUMBER() OVER (
             PARTITION BY source_signal_id, signal_date, signal_type
             ORDER BY COALESCE(updated_at, '') DESC, rowid DESC
           ) AS rn
    FROM backtest_outcomes
    WHERE COALESCE(source_signal_id,'')<>''
      AND COALESCE(signal_date,'')<>''
      AND COALESCE(signal_type,'')<>''
  ) t
  WHERE t.rn > 1
);
```

### seed list config
バックテストの母集団は `configs/investment-seeds.json` で管理する。

なぜ設定ファイルにするか:
- `fill_market_outcomes.py` と `analyze_market_outcomes.py` が同じ母集団を読むため、入力ズレを防げる
- サンプル追加/除外がコード変更ではなく設定変更になる
- 「今回の検証はどのログを含めたか」をJSONとしてレビューできる
- seed list を複数持てば、軽量版/拡張版/ショート強化版の比較がしやすい

```bash
python3 scripts/investment/backtest/fill_market_outcomes.py --date YYYY-MM-DD --seed-list rough_backtest_full
python3 scripts/investment/analysis/analyze_market_outcomes.py --date YYYY-MM-DD --seed-list rough_backtest_full
```

現在の seed list:
- `rough_backtest_light`: market-signals中心。軽量確認用
- `rough_backtest_short_focus`: short側の検証を厚めに見る
- `rough_backtest_full`: 現在の標準deep用
- `rough_backtest_v1`: 互換用エイリアス

`CACHE_ONLY=1` または `--cache-only` を使うと、Yahoo / JPX / 株探などのネット取得を避け、既存キャッシュや既存出力だけで進める。
ネット取得ができない環境では、未取得項目は `unknown` / `unknown_cache_only` として残す。

品質とseed差分を見る:

```bash
make investment-quality DATE=YYYY-MM-DD
make investment-seed-compare DATE=YYYY-MM-DD LEFT_SEED=rough_backtest_light RIGHT_SEED=rough_backtest_full
```

- `quality-report`: 欠損、unknown、cache-onlyの影響を確認する
- `seed-list-comparison`: light/full/short_focusでルール候補がどれだけ変わるか確認する

### generated output policy
現時点では既存参照を壊さないため、生成物は従来どおり `topics/investment-research/inbox/` に出力する。

ただし運用上は次のように読む:
- 人間が読む一次ログ: daily / market-signals / manually written backfill
- 機械生成物: `rough-backtest-*`、`*-context-*`、`rule-check-*`、`short-*`、`tag-index.*`
- 今後移動するなら、まず `sources.json` と各スクリプトの出力先を一括で `generated/` 対応にしてから行う

## Script Groups
### 1. Framework / Topic Utilities
| script | role |
| --- | --- |
| `validate_topics.py` | topic / tasks / sources のスキーマと参照ファイルを検証する |
| `new_topic.py` | template から topic を作成する |
| `export_sample_topic.py` | 実 topic から公開サンプルを出力する |
| `diff_topic.py` | topic と sample-topic の差分を確認する |
| `check_daily_missing.py` | daily の実行漏れを検知し、補完プロンプトを生成する |
| `check_daily_missing_toast.ps1` | Windows Toast 通知とクリップボード補助 |

### 2. Collect
| script | input | output | notes |
| --- | --- | --- | --- |
| `collect_kabutan_surprise_signals.py` | 株探サプライズ系ページ | `inbox/{date}-six-month-rough-backtest-batch-5-kabutan-surprise.md` | deep 用。ネット取得あり |
| `collect_kabutan_short_signals.py` | 株探の悪材料/下落候補 | `inbox/{date}-six-month-rough-backtest-batch-6-short-negative.md` | deep 用。ネット取得あり |

### 3. Fill / Enrich
| script | input | output | notes |
| --- | --- | --- | --- |
| `fill_market_outcomes.py` | backtest / market-signals | `{date}-rough-backtest-outcomes-*` + Yahoo chart cache | T+1/T+5/T+20の基礎。`--date` / `--output` / `--aggregation-output` / positional inputs 対応。ネット取得あり |
| `fill_sector_context.py` | outcome rows | `{date}-sector-context-data.json` | セクター分類補完。`--date` / `--output` 対応 |
| `extract_margin_context.py` | manual margin fill | `{date}-margin-context-data.json` | 信用文脈抽出。`--date` / `--input` / `--output` 対応。指定日の入力がなければ旧priority fillへfallback |
| `fill_technical_context.py` | Yahoo chart cache + outcome rows | `{date}-technical-context-*` | MA/RSI/MACD/ローソク足など。`--date` / `--output-*` 対応。必要時ネット取得あり |
| `fill_borrow_context.py` | JPX貸借一覧 + rows | `{date}-borrow-context-*` | JPX現時点の貸借区分。`--date` / `--output-*` 対応。ネット取得あり |
| `fill_market_context.py` | market proxy data | `{date}-market-context-data.json` | 外部市場文脈。`--date` / `--output` 対応。取得失敗時も unknown で継続 |
| `fill_sector_market_context.py` | sector proxy data | `{date}-sector-market-context-data.json` | セクター相対強弱。`--date` / `--output` 対応 |

### 4. Analyze
| script | input | output | notes |
| --- | --- | --- | --- |
| `analyze_market_outcomes.py` | rough outcome + context data | `{date}-rough-backtest-stratified-analysis.md` | 基礎集計の中核。`--date` と主要context入力差し替えに対応 |
| `analyze_cross_factors.py` | `analyze_market_outcomes` rows | `{date}-cross-factor-read.md` | 複合条件の読み。`--date` と主要context入力差し替えに対応 |
| `prioritize_unknowns.py` | outcome / stratified / margin | `{date}-unknown-priority-queue.md` | unknown 補完優先度。`--date` / `--outcome` / `--margin-data` / `--output` 対応 |
| `rule_check_market_outcomes.py` | analyzed outcome rows | `{date}-rule-check-*` | ルール候補集計。`--date` / `--outcome` / 主要context入力差し替えに対応 |
| `analyze_long_rule_reproducibility.py` | `{date}-rule-check-data.json` | `{date}-long-rule-reproducibility.*` | long側の再現性分類 |

### 5. Short Classification / Review
| script | input | output | notes |
| --- | --- | --- | --- |
| `classify_short_use_cases.py` | analyzed rows | `{date}-short-use-case-*` | short / avoid / event 用途を分ける。`--date` 対応 |
| `classify_short_readiness.py` | short use cases + borrow/technical | `{date}-short-readiness-*` | 実監視準備度。`--date` / `--short-use` / `--borrow` / `--output-*` 対応 |
| `analyze_short_high_readiness.py` | short readiness | `{date}-short-high-readiness-review*` | high/mediumの詳細。`--date` / `--input` / `--output-*` 対応 |
| `generate_short_watch_report.py` | short readiness | `{date}-short-watch-report.md` | daily 表示用 |
| `analyze_short_chart_windows.py` | short readiness + chart cache | `{date}-short-chart-window-*` | 追随/戻りリスク確認 |
| `analyze_short_chart_window_stats.py` | chart-window data | `{date}-short-chart-window-stats.*` | short パターン集計 |
| `analyze_short_rebound_risk.py` | short readiness + chart cache | `{date}-short-rebound-risk-*` | rebound risk 除外ルール |
| `classify_short_conviction.py` | short review data | `{date}-short-conviction-*` | shortの確信度/仮説分類 |

### 6. Rule / Index
| script | input | output | notes |
| --- | --- | --- | --- |
| `generate_rule_dashboard.py` | long reproducibility + short conviction | `{date}-rule-dashboard.*`, `{date}-daily-rule-brief.md` | daily 表示用の統合ルール |
| `update_rule_history.py` | `{date}-rule-dashboard.json` | `rule-history.*` | 累積履歴 |
| `build_investment_tag_index.py` | `inbox/*market-signals.md` | `tag-index.*` | 軽量検索・adaptive gate 用 |
| `list_investment_generated.py` | investment inbox | `{date}-generated-inventory.*` | 生成物をfilenameベースで棚卸し。移動はしない |
| `analyze_investment_quality.py` | generated files | `{date}-quality-report.*` | unknown/cache-only/欠損の品質棚卸し |
| `compare_investment_seed_lists.py` | rule-check by seed list | `{date}-seed-list-comparison.*` | seed listごとのルール差分比較 |

## Known Debt
- 主要な outcome / context / analyze / short 表示系は `--date` 対応済み。
- `fill_market_outcomes.py` の既定入力リストと `analyze_market_outcomes.py` の source index 用 seed list は `configs/investment-seeds.json` へ分離済み。
- ただし seed list の中身は過去バックフィルログを読むため固定ファイルを含む。
- JPX貸借取得やYahoo取得はネット失敗時に unknown で継続する箇所があるため、daily表示では `unknown_fetch_failed` を未確認として扱う。
- short分類/表示系は、`--date` と必要な `--input` / `--output` 指定に概ね対応済み。
- `scripts/` 直下に投資系と汎用系が混在している。
- ネット取得あり/なしがスクリプト名だけでは分かりにくい。
- `sources.json` への登録はまだ手動/半手動が多い。
- output path の命名は揃ってきたが、収集元の既定リストは過去検証用ログに依存している。

## Next Refactor Plan
1. 投資系を `scripts/investment/` に移すか、wrapper を作る
2. `generated-inventory` を見ながら、生成物の移動対象を決める
3. `sources.json` 登録を自動化する
4. seed list ごとの勝敗差分を比較する
5. cache-only で unknown になった項目を次回deepで補完する
