# Command: rate-budget

## Purpose
weekly / 5h レート消費を抑えながら、この Repo の情報収集と分析を継続するための実行方針を決める。

## Trigger
- レート節約
- 低消費
- 省エネ運用
- rate budget
- rate constrained
- 消費量の見直し

## Default Policy
レート残量が厳しいときは、分析を止めるのではなく、重い処理を後回しにする。

優先順位:
1. daily の継続
2. 投資の期限到来 outcome
3. 重要変化の差分確認
4. 既存 dashboard / history の反映
5. deep 作業の候補化

## Budgets
### adaptive
推奨モード。
常時低消費に固定せず、軽量トリアージから必要なものだけ深掘りへ昇格する。

実行してよい:
- daily の差分確認
- 投資の core check
- 期限到来 outcome
- 最新 rule brief / rule history の参照
- tag-index による同種事例の軽量確認
- 深掘りキューの作成

避ける:
- 条件なしの deep 実行
- product idea の裏収集
- unknown 一括補完
- 週次/月次レポート
- 投資バックテスト拡張

深掘り昇格条件:
- active rule に該当する
- T+1 / T+5 / T+20 の期限到来がある
- 外部トリガーと個別銘柄の反応が食い違う
- short 側の重要候補が出る
- 決算、下方修正、減配、希薄化、TOB/M&A、不祥事などの強い材料が出る
- 出来高急増、大陽線/大陰線、寄り天/引け急変など短期検証価値が高い
- tag-index 上で同種事例が少ない、または既存パターンから外れている

### lean
毎日回すための低消費モード。

実行してよい:
- daily の差分確認
- 重要ニュース/重要開示の確認
- 投資の T+1 / T+5 / T+20 期限到来分
- 最新 `daily-rule-brief` / `rule-history` の参照
- ポケモンカードの抽選/新パック環境変化の N/C 確認
- 技術記事の少数紹介

避ける:
- `inbox/` 全量読み
- `sources.json` 全量読み
- product idea の裏収集
- 大量バックフィル
- unknown 一括補完
- 週次/月次レポート
- 投資バックテスト拡張
- 長い候補表の出力

### balanced
通常モード。

実行してよい:
- daily watch topic の一通りの確認
- product idea の軽量 background 収集
- market signal の軽量更新
- 既存 outcome / rule dashboard の確認

避ける:
- 明示依頼なしの大量バックフィル
- 明示依頼なしの deep レポート

### deep
レートと時間に余裕があるときの深掘りモード。

実行してよい:
- 投資バックテスト拡張
- unknown 一括補完
- ショート/ロング再分類
- rule history 再集計
- 週次/月次レポート
- ニーズ束の分析

## Daily Routing
ユーザーが「今日の情報」とだけ言った場合:

- レート状態が不明なら `adaptive`
- ユーザーが残量不足を伝えている場合は `lean`
- weekly rate が 50% 未満でリセットまで24時間以上ある場合は `lean`
- ユーザーが「ずっと低消費は嫌」「必要なときだけ深掘り」と言った場合は `adaptive`

`lean` の daily は次の形にする:

```text
AGENT.md と commands/daily.md を読んで、「今日の情報」を budget: lean でまとめて。
product-idea-watch の裏収集は skip。
大規模バックテスト、unknown一括補完、週次/月次レポート生成はしない。
```

## Investment Routing
投資分析は重くなりやすいので、低消費時は分離する。

`adaptive`:
- core check: 外部トリガー、重要開示、期限到来 outcome、rule brief
- gate decision: tag-index も参照して `deep_dive_now` / `deep_queue` / `no_change`
- limited deep: 当日重要かつ少数のものだけ深掘り

`lean`:
- 当日重要シグナル
- 期限到来 outcome
- 最新 rule brief の反映

`deep`:
- バックテスト拡張
- unknown 補完
- ルール再評価
- 200〜300件規模のサンプル拡張

## Output Policy
- 低消費時は、長い説明より「差分」「未確認」「次に回すもの」を優先する
- deep 作業は、実行せず `next_watch` に積む
- 同じ確認を毎回繰り返さず、既存ファイルへの参照を使う
