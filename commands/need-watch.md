# Command: need-watch

## Purpose
ネット上の不満、要望、未充足ニーズを巡回収集し、開発アイディアの材料として `product-idea-watch` に蓄積する。

## Trigger
- ニーズ収集
- 不満収集
- 開発アイディア収集
- product idea watch
- need watch

## Required Inputs
- `date`
  - 指定がなければ現在日付を使う

## Optional Inputs
- `rotation_sources`
- `max_sources`
  - 既定は 10 か所程度
- `max_items`
  - 固定上限ではないが、重複や低品質なものは除外する
- `focus`
  - developer-tools
  - consumer-apps
  - productivity
  - ai-tools
  - ecommerce
  - all

## Default Topic
- `topics/product-idea-watch`

## Rotation Source Candidates
巡回対象は固定せず、候補プールから毎回 10 か所程度をローテーションする。

## Rotation Balance
初期運用では次の比率を目安にする。

- Global: 60%
- Japanese: 40%
- Consumer: 65%
- Developer: 35%

日本語圏は 4 割程度を目安にするが、日本語技術者だけに寄せず、一般ユーザーの小さな不満を優先して拾う。

## Need Categories
一般ユーザーの声は、明示的な機能要望ではなく不満として出ることが多い。
収集時は次のカテゴリに分類する。

- 面倒
- 不安
- 忘れる
- 分からない
- 続かない
- 家族・共有
- 比較できない
- タイミング

## Cluster Policy
同じような不満や要望が繰り返し出る場合は、新規性の低い重複として捨てず、既存 cluster に紐づけて保存する。

収集時は各 need に次の項目を付ける。

- `cluster`: 既存または新規の短いID。例: `ai-tool-trust`
- `duplicateOf`: ほぼ同じ need が既にある場合、その need ID。なければ空欄
- `recurrence`: `new` / `repeated` / `strong`
- `evidenceCount`: 同じ cluster の概算件数
- `novelty`: `high` / `medium` / `low`
- `analysisCandidate`: `yes` / `no`

判断基準:

- 新しい観点がある場合は `novelty: high` として新規 need にする
- 既存 cluster と同じ痛みなら `recurrence: repeated` とし、cluster の evidence を増やす
- 5件以上の独立した観測がある cluster は `recurrence: strong` とし、分析候補にする
- 似ているが対象ユーザー、支払い意思、失敗コスト、既存代替が違う場合は、同じ cluster に入れつつ別 need として残す

初期 cluster 候補:

- `ai-tool-trust`: AI生成アプリ/AIツールの信頼性、安全性、レビュー疲れ
- `saas-sprawl-cost`: SaaS/アプリが増えすぎることによる費用、ログイン、通知、管理疲れ
- `opportunity-notification`: 抽選、予約、再販、締切、在庫、通知の取り逃し
- `feedback-roadmap-triage`: 顧客要望、フィードバック、ロードマップ、優先順位付け
- `scope-change-management`: スコープクリープ、変更依頼、請求、合意ログ
- `lightweight-web-complexity`: 過剰なWeb技術、古い標準/軽量実装への回帰
- `need-analysis-pipeline`: 集めた不満/要望の重複分析、記事種/プロダクト種への変換

## Source Pool

- Reddit
- Hacker News
- Product Hunt comments
- GitHub Issues
- App Store reviews
- Google Play reviews
- Chrome Web Store reviews
- Zenn / Qiita comments
- はてなブックマーク comments
- Stack Overflow / teratail
- YouTube comments
- Public community forums

追加候補:
- Reddit r/Entrepreneur
- Reddit r/SaaS
- Reddit r/Productivity
- Reddit r/webdev
- Reddit r/personalfinance
- Reddit r/Frugal
- Reddit r/parenting
- App Store reviews
- Google Play reviews
- VS Code Marketplace reviews
- G2 reviews
- Capterra reviews
- Indie Hackers
- Lobsters
- Figma Community comments
- Notion marketplace comments
- Amazon reviews
- 楽天レビュー
- 価格.com口コミ
- Yahoo!知恵袋
- 教えて!goo
- note
- Zenn
- Qiita
- はてなブックマーク
- teratail
- 日本語X検索

## Rotation Examples
### Round A: Global Consumer
- App Store reviews
- Google Play reviews
- Reddit r/Productivity
- Reddit r/personalfinance
- Reddit r/Frugal
- Product Hunt comments
- Chrome Web Store reviews
- YouTube app review comments
- Reddit r/parenting
- G2 reviews

### Round B: Japanese Consumer
- App Store 日本語レビュー
- Google Play 日本語レビュー
- Amazon reviews
- 楽天レビュー
- 価格.com口コミ
- Yahoo!知恵袋
- 教えて!goo
- note
- はてなブックマーク
- 日本語X検索

### Round C: Developer / SaaS
- GitHub Issues
- Hacker News
- Reddit r/webdev
- Reddit r/SaaS
- Stack Overflow
- VS Code Marketplace reviews
- Product Hunt comments
- Indie Hackers
- Zenn
- Qiita

### Round D: Mixed
- Reddit r/Entrepreneur
- Chrome Web Store reviews
- App Store reviews
- Product Hunt comments
- GitHub Issues
- Amazon reviews
- 価格.com口コミ
- Yahoo!知恵袋
- はてなブックマーク
- teratail

## Read Scope
- `AGENT.md`
- `commands/need-watch.md`
- `topics/product-idea-watch/topic-manifest.json`
- `topics/product-idea-watch/index.md`
- `topics/product-idea-watch/summary.md`
- `topics/product-idea-watch/decisions.md`
- `topics/product-idea-watch/tasks.json`
- `topics/product-idea-watch/sources.json`
- 必要に応じて `topics/product-idea-watch/inbox/*`

## Write Scope
- `topics/product-idea-watch/inbox/*`
- `topics/product-idea-watch/sources.json`
- 必要に応じて `topics/product-idea-watch/summary.md`
- 必要に応じて `topics/product-idea-watch/tasks.json`

## Execution Mode
- `proposal`
- `apply`

## Constraints
- 投稿本文を長く転載しない
- 個人名、アカウント名、連絡先などの個人情報は保存しない
- 個別投稿を断定的な市場需要として扱わない
- 同じ不満の重複は捨てず、cluster に紐づけて evidence として扱う
- 収集した声は `不満`, `要望`, `既存代替`, `作れそう度`, `検証方法` の観点で整理する
- daily digest には通常出さず、分析できる程度に蓄積したときだけ通知する

## Output Contract
### proposal
- `date`
- `sources_to_check`
- `candidate_needs`
- `dedupe_notes`
- `cluster_updates`
- `next_actions`

### apply
- `created_files`
- `updated_files`
- `collected_need_count`
- `cluster_updates`
- `source_entry`
- `threshold_status`

## Threshold Policy
次のいずれかを満たしたら、daily digest で「ニーズが分析できる程度に蓄積された」と通知する。

- 未分析の needs が 30 件以上
- 同じカテゴリの needs が 10 件以上
- 同じ不満パターンが 5 件以上

## Failure Handling
以下のいずれかで失敗を返す。

- `topic_not_found`
- `missing_canonical_file`
- `insufficient_sources`
- `network_unavailable`
- `malformed_json`

失敗時は以下を返す。

- `error_code`
- `message`
- `suggested_action`

## Success Criteria
- 開発アイディアにつながる不満・要望が追跡可能に蓄積される
- 低品質な声や重複が整理される
- 分析タイミングだけ daily に通知できる
