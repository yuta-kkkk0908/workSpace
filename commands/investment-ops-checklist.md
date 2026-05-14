# Command: investment-ops-checklist

## Purpose
投資運用を朝/夜の2回で安定実行するためのチェックリスト。

## Morning (before market)
- 外部要因確認: 米指数、米金利、ドル円、原油、要人発言
- 監視母集団の当日優先候補を抽出
- long/shortエントリー候補の仮説方向を確認

## Night (after market)
- `today-market-signals.md` を更新
- `make investment-entry-candidates DATE=YYYY-MM-DD`
- `make investment-signal-missing DATE=YYYY-MM-DD`
- T+1/T+5/T+20 期限到来のoutcome更新

## Notes
- 売買助言ではなく、監視候補の整理と検証ログ更新を目的とする。
