AGENT.md と commands/need-organize.md を読んで、ニーズの二次トリアージを実行して。

対象:
- prompts/needs-ai-queue.md
- prompts/needs-ai-queue.json

やること:
1. 重複ニーズを統合し、同義のものは代表1件にまとめる
2. 各項目に labels / priority / action (watch/investigate/discard) を確定する
3. 根拠メモを1〜2行で付与する（なぜその判定か）
4. 重要度上位のものは product-idea-watch の次アクション候補として残す
5. triage結果を apply まで実行する

制約:
- 個人情報は保存しない
- 断定的な市場需要表現は避ける
- 転載は最小限（要約中心）

出力:
- 反映ファイル
- triaged件数
- watch/investigate/discard の件数
- 次回までの持ち越し事項
