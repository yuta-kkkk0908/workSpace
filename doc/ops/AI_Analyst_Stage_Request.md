# AI分析官ステージ追加 実装依頼

## 前提

このリポジトリは DB-first 運用である。

- 判定・通知の正本は DB
- ファイルは監査ログまたはフォールバック用途
- 原則: DB保存成功 → 必要なら通知用テキスト生成
- DB失敗時のみファイル経路へ退避

主要DB:

- `data/investment.db`
  - `signals`
  - `entry_candidates`
  - `opening_scenarios`
  - `paper_trades`
  - `daily_digest`
  - `collection_artifacts`

既存AI設定:

- `configs/ai_model_routing.json`
- `configs/ai_job_settings.json`

既存ジョブ:

- `AIOS-Inv-Morning`
- `AIOS-Inv-Noon`
- `AIOS-Inv-Evening`
- `AIOS-Inv-Scenario-0810`
- `AIOS-Inv-AI-2100`

既存AIステージは `allow_fail=True` を原則とする。

## 目的

機械的に抽出された `entry_candidates` / `opening_scenarios` に対して、AIが投資分析官として以下を整理するステージを追加したい。

AIに売買判断や発注判断はさせない。

AIの役割は以下に限定する。

- 強気シナリオ
- 弱気シナリオ
- 材料の解釈
- 地合い・セクター影響
- 見送り理由
- 追加確認ポイント
- リスク警告
- 人間が判断するための論点整理

## 重要な制約

- AIに新規事実を生成させない
- AIには DB から取得した情報のみを使わせる
- 不明な点は「不明」と出力させる
- 勝率や期待値はAIに推測させない
- 勝率・件数・集計値は機械集計結果がある場合のみ使う
- 実注文、ロット、信用余力判断、ナンピン判断は対象外
- AI失敗時に既存ジョブを停止させない

## 追加したい構成

### 1. 新規スクリプト

`scripts/investment/analysis/generate_ai_analyst_report.py`

役割:

1. `investment.db` から当日の候補を取得
2. `entry_candidates` / `opening_scenarios` / `signals` / `paper_trades` を必要に応じて参照
3. AI分析官用プロンプトを生成
4. AI API を呼び出す
5. 結果を DB に保存する

### 2. ジョブ追加

候補:

- `AIOS-Inv-Analyst-0815`

目的:

- 寄り前シナリオ生成後にAI分析官レポートを作成

### 3. Discord通知

既存の DB-first 通知方針に従う。

### 4. 設定追加

- `configs/ai_model_routing.json`
- `configs/ai_job_settings.json`

## AIプロンプト要件

あなたは投資助言者ではなく、情報整理担当の分析官です。
売買推奨、発注指示、ロット判断は行いません。
渡された情報のみを根拠に、強気シナリオ、弱気シナリオ、リスク、見送り条件、追加確認ポイントを整理してください。
根拠がない情報は推測せず、「不明」としてください。
勝率や期待値は、入力に明示された集計値がある場合のみ記載してください。

## 実装時の確認事項

- DB-first 契約を崩さないこと
- AI出力は必ずDBへ保存すること
- AI失敗時は既存処理を継続すること
- `allow_fail=True` にすること
- ドキュメント更新を行うこと

## 最終ゴール

機械的なシグナル抽出は現行ロジックで維持し、その後段にAI分析官を追加する。

AIは売買判断をしない。

AIは候補銘柄について、投資判断前の論点整理・リスク整理・シナリオ生成を担当する。

これにより、人間が最終判断する前の調査時間を短縮し、シナリオの質と振り返り可能性を高める。
