# TRADING_RULES.md

# 現在のトレードルール（暫定）

## 位置づけ

- これは「裁量を減らすための実行ルール」。
- 売買助言ではなく、監視・検証・見送り判断の基準として使う。
- ルールの強弱は、`topics/investment-research/signal-rules.md` と outcome 蓄積で見直す。

## 基本思想

- 感情でエントリーしない
- シナリオ先行（Entry/Exit/無効条件を先に書く）
- 大負け回避を優先
- 一貫性を優先し、単発の成功体験でルールを壊さない

## 既存ルール（継続）

### 上位足

- 1分、5分、10分足を確認
- 10分足方向を優先

### MA系

- 5MA位置を重視
- 1分足の 5MA / 25MA で超短期方向判断
- MA反発を狙う

### エントリー前の必須確認

- MA反発
- 上位足方向一致
- 出来高
- 材料
- 地合い

### 禁止事項

- 焦りエントリー
- 感覚のみの飛び乗り
- 根拠不足エントリー

### エグジット

- 反対ヒゲ
- 次足で反対足
- MA割れ
- シナリオ崩壊
- 地合い悪化

## DB運用と接続するルール

- `longSignalRank` / `shortSignalRank` は監視優先度として使用
- `shortReadiness` は用途分離して扱う
  - `high/medium`: 空売り監視候補
  - `avoid_short_rebound_risk`: 戻り売り待ち
  - `low_liquidity_avoid`: 買い回避/見送り
- `N/C` は「未確認」ではなく「確認済み変化なし」

## aggressiveness の扱い

- `scenarioTier` は運用ティア。`trade / paper_trade_only / watch` のどれで投稿・実行するかを決める。
- `aggressiveness` は信号の攻め度合い。`signal_type` 単位の過去成績から、サイズ・TP/SL幅・保有日数の強弱を決める。
- 目安
  - `aggressive`: `sample>=20` かつ `T+5 winRate>=58%` かつ `T+5 dir avg return>=0.60%` かつ `T+20 dir avg return>=0.30%`
  - `balanced`: `sample>=10` かつ `T+5 winRate>=54%` かつ `T+5 dir avg return>=0.25%`
  - `conservative`: `sample>=5` かつ `T+5 winRate>=50%` かつ `T+5 dir avg return>=0.00%`
  - `avoid`: `sample<5` または `T+5 winRate<47%` または `T+5 dir avg return<-0.25%`
- 使い分け
  - `scenarioTier` は「出すかどうか」
  - `aggressiveness` は「出すならどれだけ攻めるか」
  - したがって `watch` でも `balanced` 以上の研究対象はありうるし、`trade` でも `conservative` で始めることはある
- 実際にどこへ効くか

| ラベル | 意味 | 効く場所 | 主な影響 |
|---|---|---|---|
| `trade` | 実運用に出す候補 | `scripts/notify/post_scenarios_bot.py` / `opening_scenarios` / `paper_trades.mode='paper'` | Discord 投稿、紙トレ履歴登録、後続の成績追跡 |
| `paper_trade_only` | まず紙トレで様子を見る候補 | `scripts/notify/post_scenarios_bot.py` / `opening_scenarios` / `paper_trades.mode='watch'` | 投稿はするが実運用に上げず、紙トレ観測として残す |
| `watch` | 監視継続候補 | `scripts/notify/post_scenarios_bot.py` / `opening_scenarios` / `paper_trades.mode='watch'` | 監視投稿、エントリー候補の補助表示、観測のみ |
| `paper` | いまの紙トレ運用モード | `paper_trades` の登録・集計 | `trade` ティアの自動紙トレ記録に使う |
| `paper_history` | 紙トレ履歴の分析ラベル | `scripts/investment/backtest/*` / `scripts/notify/render_paper_stats_discord_message.py` | `paper_trades` の勝率・平均リターン・保有期間比較に使う |

- 補足
  - `paper` は運用用、`paper_history` は分析用
  - `backtest` は旧呼称で、今は内部互換のためだけに残している

## ルール改定ループ

1. 日次でシグナル収集（朝/昼/夕）
2. T+1/T+5/T+20 outcome を蓄積
3. 週次で勝敗・再現性を確認
4. 昇格/降格候補を `signal-rules.md` へ反映

## 昇格・降格の目安（暫定）

- 昇格候補:
  - `mode=watch` の T+5 で `samples >= 3` かつ `winRate >= 55%` かつ `avgRet >= 0.2%`
  - 直近週次レビューで `trade-watch` のギャップを確認し、逆行が強い場合は昇格保留
  - 昇格直後はロット固定で検証（いきなりサイズ拡大しない）
- 降格候補:
  - 出現は多いのに再現性が低い
  - 追い風下で機能せず、例外が多い

## シナリオ投稿運用（Discord）

- 1銘柄1投稿で通知する（返信で entry/exit を扱う）
- 返信で `見送り` を送ると、見送り理由候補を返し、内容は `scenario_reply_events` に記録する
- 同一 `ticker + direction + tier` の短時間連投は抑止（`dedupe-hours`）
- `trade` が不足するときのみ `watch` を補助表示し、検証母数を増やす
- 返信フォーマット異常時はエラーACKを返し、誤登録を防止する
- 未エントリのシナリオスレッドは週次整理で削除する
- `watch` 投稿は `Ladder` で優先度を表示する（`strict > balanced > early > none`）
- `none` は失格ではなく「現時点で昇格条件未達」の意味で、継続観測対象

## 次に強化する項目

- ExitAnalyzer（出口ボトルネック観測）
- 地合いスコア
- 材料強度スコア
- ボラ/ギャップ判定
- RSI/MACD/ボリンジャー重みづけ
- 見送り条件の自動抽出

## 朝シナリオ出力（目標）

- 監視銘柄
- Entry条件
- 損切り
- 利確候補
- 無効条件
- 注意点

目的は「場中の感情介入を減らす」こと。
