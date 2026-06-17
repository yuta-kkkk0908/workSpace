# 2026-06-11 Note / Needs / Disclosure 実行タスク

## 目的
- `codex exec` を使ったニーズ収集を中核に置く
- ニーズ収集結果を要約し、note 下書きまでつなげる
- 適時開示の要約記事下書きに、`investment.db` の過去データ比較とシグナルを組み込む
- 下書き生成と投稿結果を DB 正本で追跡できるようにする

## 前提方針
- 収集の生データはファイルではなく DB 正本へ寄せる
- note 下書きは一時ファイルではなく、DB からレンダリングした成果物として扱う
- 自動公開はしない。まずは draft save までをゴールにする
- 外部収集の機械部分は既存 Python スクリプト、解釈・統合・文章化は `codex exec` を担当させる
- 既存の `workModel` にある note / disclosure 実装資産は移植元として利用する

## 実装全体像
1. ニーズ候補を収集する
2. ニーズ候補を triage して cluster 化する
3. 記事化候補を作る
4. note 下書き用 Markdown を生成する
5. note へ draft save する
6. 適時開示の要約記事を同じ流れで生成する
7. 実行履歴・監査・比較根拠を DB に残す

## タスク一覧

### task_001
- title: note / disclosure の保存先 DB 設計を決める
- priority: high
- status: todo
- relatedFiles:
  - `scripts/data/init_ops_db.py`
  - `scripts/data/init_investment_db.py`
  - `doc/ops/OPERATION_CURRENT.md`
  - `doc/investment-db-unified-schema.md`
- description:
  - note 下書き本体、生成結果、投稿ログ、比較根拠、失敗ログの保存先を決める
  - `ops.db` と `investment.db` の役割分担を明確化する
  - `payload_json` 系で受ける可変項目と、固定列に昇格する項目を決める

### task_002
- title: `codex exec` で動かすニーズ収集ジョブを用意する
- priority: high
- status: todo
- relatedFiles:
  - `commands/need-watch.md`
  - `commands/need-organize.md`
  - `prompts/needs-triage.prompt.md`
  - `tmp/prompts/needs-ai-queue.md`
  - `scripts/build_needs_ai_queue.py`
  - `scripts/apply_needs_triage.py`
- description:
  - 既存の needs 収集・整理フローを `codex exec` から起動できる形にする
  - 収集対象、読ませる契約、出力契約を固定する
  - 重複統合、優先度付け、`watch / investigate / discard` の確定までを一連化する

### task_003
- title: needs から note 下書き seed を生成する
- priority: high
- status: todo
- relatedFiles:
  - `commands/need-organize.md`
  - `commands/need-watch.md`
  - `topics/product-idea-watch/summary.md`
  - `topics/product-idea-watch/tasks.json`
- description:
  - `article_seeds` を note 投稿向けの見出し構成に変換する
  - 現象、原因候補、比較対象、検証観点を含む下書きテンプレートを作る
  - 断定的な市場需要表現を避け、観測ベースの記事にする

### task_004
- title: note draft 投稿スクリプトを repo に移植する
- priority: high
- status: todo
- relatedFiles:
  - `/mnt/c/Users/yuta_/OneDrive/ドキュメント/workModel/scripts/post_note_draft.py`
  - `/mnt/c/Users/yuta_/OneDrive/ドキュメント/workModel/scripts/bootstrap_note_login.py`
  - `/mnt/c/Users/yuta_/OneDrive/ドキュメント/workModel/configs/note.local.example.json`
  - `scripts/notify/`
- description:
  - `workModel` の note draft 投稿処理をこの repo に持ってくる
  - Playwright で draft save まで実行できるようにする
  - `configs/note.local.json` のローカル運用を整える

### task_005
- title: disclosure 下書き生成を repo 側に実装する
- priority: high
- status: todo
- relatedFiles:
  - `/mnt/c/Users/yuta_/OneDrive/ドキュメント/workModel/scripts/generate_disclosure_digest.py`
  - `/mnt/c/Users/yuta_/OneDrive/ドキュメント/workModel/scripts/run_morning_disclosure_digest.py`
  - `scripts/investment/collect/collect_tdnet_disclosures.py`
  - `scripts/notify/render_market_signals_discord_message.py`
  - `scripts/notify/render_opening_scenarios_discord_message.py`
- description:
  - TDnet 開示の要約下書きを repo に追加する
  - `investment.db` の過去データ、`collection_artifacts`、`signals`、`entry_candidates` を参照して比較文を作る
  - ニュース後追い記事で優位になるよう、単純要約ではなくシグナル付き文面にする

### task_006
- title: note 下書き生成の監査ログを DB に残す
- priority: high
- status: todo
- relatedFiles:
  - `scripts/data/init_ops_db.py`
  - `scripts/investment/analysis/execute_improvement_work_items.py`
  - `doc/ops/OPERATION_CURRENT.md`
- description:
  - いつ、何を入力にして、どの下書きを作ったかを保存する
  - 失敗時も含めて、比較に使った根拠と投稿結果を追跡可能にする
  - 実行ログ、生成ログ、投稿結果ログを分けて保持する

### task_007
- title: `workModel` から移植した note / disclosure 資産を repo に統合する
- priority: medium
- status: todo
- relatedFiles:
  - `/mnt/c/Users/yuta_/OneDrive/ドキュメント/workModel/docs/automation.md`
  - `/mnt/c/Users/yuta_/OneDrive/ドキュメント/workModel/docs/daily-disclosure-digest.md`
  - `/mnt/c/Users/yuta_/OneDrive/ドキュメント/workModel/templates/article_outline.md`
- description:
  - 既存の実装資産をそのまま使わず、repo のディレクトリ構成に合わせて整理する
  - note 固有の設定、スケジューラ起動、アウトプットディレクトリを調整する
  - 収集・要約・投稿の責務をこの repo の運用規約に合わせる

### task_008
- title: README と運用文書に note / disclosure フローを追加する
- priority: medium
- status: todo
- relatedFiles:
  - `README.md`
  - `doc/OPERATION_CURRENT.md`
  - `doc/script-role-catalog.md`
  - `doc/scheduler-job-catalog.md`
- description:
  - `codex exec` を使う位置づけを明記する
  - needs 収集と note 下書きの関係を説明する
  - disclosure 下書き生成と DB 比較の関係を説明する

### task_009
- title: note / disclosure 系のテストを追加する
- priority: medium
- status: todo
- relatedFiles:
  - `tests/`
  - `scripts/notify/post_note_draft.py`
  - `scripts/investment/collect/generate_disclosure_digest.py`
- description:
  - Markdown から note title/body を分割できることを確認する
  - disclosure 下書きに過去比較やシグナルが入ることを確認する
  - config 読み込みとログ出力の壊れを検知する

## 推奨実行順
1. task_001
2. task_002
3. task_003
4. task_005
5. task_004
6. task_006
7. task_007
8. task_008
9. task_009

## 直近の着手順
- まず `task_001` で DB の受け皿を決める
- 次に `task_002` と `task_003` で needs 側の `codex exec` フローを作る
- その後に `task_005` と `task_004` で disclosure と note 投稿を繋ぐ
- 最後に `task_006` 以降で監査・文書・テストを固める

## 補足
- note の下書き保存は自動公開と分ける
- ユーザー投稿の本番化は、下書き品質と監査が安定してから検討する
- `workModel` は雛形の参照元として使うが、正本はこの repo に置く

## proposal 投入済み
- `task_004`: note draft 投稿スクリプトを repo に移植する
- `task_005`: disclosure 下書き生成を repo 側に実装する
- `task_006`: note 下書き生成の監査ログを DB に残す
- `task_009`: note / disclosure 系のテストを追加する
