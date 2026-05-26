# unchanged対策タスク（2026-05-22）

## 背景
- `unchanged` は送信成功でも運用上は異常。
- 主因を `DATA_THIN`（母数不足）と `RULE_THIN`（ルール通過不足）に分解して対策する方針で合意。

## 合意した方針
1. unchanged を品質異常として扱う（連続検知/閾値超えで失敗コード）
2. 通知は0件でも最低限の判断材料を出す（N/Cのみで終わらせない）
3. 連続unchanged時は収集強化モードに自動切替
4. ルール通過不足は watch専用の緩和段で救う

## 実装済み
- `scripts/notify/post_discord_message.ps1`
  - `UnchangedStreakFile`, `UnchangedFailThreshold` 追加
  - `QUALITY_WARN/QUALITY_ERROR` ログ出力
  - 理由ラベル `DATA_THIN / RULE_THIN`
- `scripts/notify/post_signal_discord.ps1`
- `scripts/notify/post_generic_discord.ps1`
- `scripts/notify/post_paper_stats_discord.ps1`
  - streakファイル + 閾値(3)を設定
- `scripts/notify/render_market_signals_discord_message.py`
  - signals 0件でも終了しない
  - entry_candidates上位補完
  - 補完も無い場合は「信用取引不可除外」上位を参考表示
- `scripts/run_ops_scheduler.py`
  - signal unchanged streak>=2でKabutan収集を自動ブースト
- `scripts/investment/signals/generate_entry_candidates.py`
  - ランク正規化 (`A-`, `B+` などを A/B/C として扱う)
  - technicalシグナルが候補抽出から落ちる欠陥を修正

## 変更の解釈
- `exit 2` は「送信障害」ではなく「品質上の連続異常」を意味する。
- `A-`,`B+` を `A/B` と同等扱いにするのは、ルール緩和段（watch優先）での救済目的。

## 次タスク
1. `RULE_THIN` 詳細ログ（どの条件で落ちたか）をJSONで残す
2. watch緩和シグナル（MA反発/BB追従/3本陽線）の採用率を日次集計
3. watch->trade昇格評価に、緩和シグナル由来フラグを接続
