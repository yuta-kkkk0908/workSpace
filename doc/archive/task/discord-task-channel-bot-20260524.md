
## Discord Task Channel Bot 実装メモ（2026-05-24）

### 目的
- Discordのタスクチャンネル投稿をトリガーに、DB記録・コマンド実行・結果返信を行う。
- poll実行時のノイズ投稿をなくし、アクション時のみ返信する。

### 追加/変更ファイル
- `scripts/notify/sync_tasks_channel_bot.py`
- `scripts/ops/run_sync_tasks_channel.ps1`
- `scripts/data/init_investment_db.py`（`discord_task_events` 追加）

### 接続した機能
1. チャンネル監視
- 環境変数: `DISCORD_TASK_CHANNEL_ID`
- Botトークン優先: `DISCORD_TASKS_BOT_TOKEN`（fallbackあり）

2. DB保存
- テーブル: `discord_task_events`
- 保存内容: message_id / raw_content / command_name / args / status / result_json / processed_at

3. 実行可能コマンド（日本語短縮）
- `状態`
- `エラー詳細`
- `投資補完`
- `投資情報収集`
- `昼の投資情報`
- `夕の投資情報`
- `シナリオ`
- `母数強化`
- `週次30再収集`
- `週次365再収集`
- `月次ローテA|B|C`
- `outcomes補完 [YYYY-MM-DD]`

4. 応答方針
- 応答は「何をしたか」だけを短く返す。
- pollごとの自動投稿は無効化（アクションがあった投稿への返信のみ）。

### 補足
- `seed-list` は乱数seedではなく、outcomes補完対象ルール集合のプリセット名（例: `rough_backtest_full`）。
- 現状は既存の投資収集ルート実行に寄せた最小権限の運用。

## 汎用トピックスレッド運用メモ（2026-05-24）

### 方針
- `DISCORD_TASKS_BOT_TOKEN` を流用して、汎用トピック専用チャンネルへ Bot 投稿する。
- topicごとに固定アンカーを作り、スレッドは日付ごとに増やさず固定で使い続ける。
- 今後の `generic-topics` 日次内容は各固定スレッドへ蓄積する。

### 使用チャンネル/状態
- チャンネルID: `1508102418863493220`
- インデックス/アンカー/スレッド状態: `prompts/generic-threads-state.json`

### 実装ファイル
- `scripts/notify/post_generic_threads_bot.py`
- `scripts/notify/post_generic_threads_discord.ps1`
- `scripts/ops/run_night_and_post_generic.ps1`
- `scripts/notify/test_discord_bot_post.py`

### 投稿ルール
- チャンネル直下:
  - 固定インデックス投稿 1件
  - topic固定アンカー投稿
- スレッド内:
  - `### YYYY-MM-DD` 見出しで当日分を追記
  - 同日同内容は再投稿しない
  - 同日内容更新時は `(updated)` を付けて追記する

### 投稿経路メモ
- `Invoke-RestMethod` での Discord Bot POST は、読取可能チャンネルでも `40333 internal network error` になるケースを確認。
- 同一Botトークンでも `Python + urllib.request` 経路では投稿成功。
- Bot投稿の検証/運用は Python 実装を正とする。

### 2026-05-26 追記
- `汎用スレッド` での固定アンカー `PATCH` は、古いメッセージ編集回数制限に当たる。
- 実際のエラーは Discord `429` / `code=30046`:
  - `Maximum number of edits to messages older than 1 hour reached.`
- 対応:
  - `post_generic_threads_bot.py` は古いアンカー編集をやめた。
  - `post_generic_forum_bot.py` を追加し、forum運用へ移行可能にした。
  - forum ID: `1508808144753791006` (`汎用フォーラム`)
  - `.env` に `DISCORD_GENERIC_FORUM_CHANNEL_ID` を入れると、`AIOS-Night` は forum 投稿を優先する。

## シナリオスレッド運用メモ（2026-05-24）

### 方針
- `DISCORD_SCENARIO_CHANNEL_ID=1508104046030880899` を `シナリオスレッド` 用チャンネルとして使用する。
- 今後のシナリオ投稿はフラット投稿ではなく、1シナリオ=1スレッドで扱う。
- エントリー判定や exit 反映は、各スレッド内メッセージを同期して処理する。

### 実装
- 投稿: `scripts/notify/post_scenarios_bot.py`
- Windowsラッパー: `scripts/notify/post_scenario_discord.ps1`
- 返信同期: `scripts/notify/sync_scenario_replies_bot.py`
- 同期起動: `scripts/ops/run_sync_scenario_replies.ps1`

### DB
- `scenario_messages`
  - `channel_id`: 親チャンネル
  - `thread_id`: シナリオスレッドID
  - `anchor_message_id`: 親チャンネルのアンカー投稿ID
  - `message_id`: スレッド内の詳細メッセージID
- `scenario_reply_events`
  - thread 内の command 反映履歴を保持

### 運用メモ
- スレッド化で難しくなるのは「どのシナリオに対する返信か」の解決だけ。
- これは `thread_id` を保存して、同期時に thread 単位で対象シナリオを解決することで対応した。
- したがって `entry / exit / cancel / credit` の判定ロジック自体は大きく変わらない。
- `trade` シナリオは投稿時に `paper_trades.mode='paper'` へ自動登録する。
- 目的は「実エントリーしなくても、シナリオ昇格ルールの事後成績を必ず回収する」こと。
- `entry paper` / `entry 机上` は watch や個別検証を追加したいときの補助コマンドとして残す。
