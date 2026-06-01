# タスク分解: 収集設計 / DB統合集約 / スクリプト改修（2026-05-20）

漏れ防止のため、実装を3本柱で分離して管理する。

## A. 収集設計（Source/Coverage設計）

- [x] A-1: 収集ソース定義表を作成（目的・鮮度・優先度・上限・再試行）
- [x] A-2: 未取得優先キュー（coverage planner）を設計
- [x] A-3: 新規率ベースの早期停止条件を実装
- [x] A-4: ソース混在時の正本採用規則（TDnet優先）をコード化
- [x] A-5: 信用可否不明=保留ルールを収集→シグナル→シナリオで統一

## B. テーブル統合集約（DB整流化）

- [x] B-1: 現行テーブル棚卸し（用途/主キー/参照元/参照先）
- [x] B-2: 統合先スキーマ案を作成（raw / facts / dimensions）
- [x] B-3: 一意キー規約を統一（重複排除の正規ルール）
- [x] B-4: 互換VIEWを追加（既存スクリプトを段階移行）
- [x] B-5: Raw 14日クリーンアップジョブを実装
- [x] B-6: 定性観測の受け皿 `observations`（JSON許容）を追加

## C. スクリプト改修（DB-first）

- [x] C-1: 収集スクリプト共通で `source_kind/source_url/fetched_at` 保存を統一（TDnet系から着手）
- [x] C-2: ingest系の upsert 衝突処理を統一（停止しない設計）
- [x] C-3: シグナル生成の入力をDB正本に寄せる（ファイル依存を削減）
- [x] C-4: シナリオ生成の入力をDB正本に寄せる（信用可否ルール反映）
- [x] C-5: アラート文面をKPI中心に統一（coverage/staleness/new_rows/error）
- [x] C-6: observations投入スクリプトを追加（手動メモ/半自動観測のDB取り込み）

## D. 運用化（自動実行）

- [x] D-1: `AIOS-Data-Harvest` を本番運用手順に固定
- [ ] D-2: 未ログイン時実行（実行ユーザー/権限/ログオンモード）を確定
  - blocker: `schtasks /Create ... /RU SYSTEM` が `Access is denied`（管理者権限不足）
- [x] D-3: 日次運用チェック項目を文書化（成功判定・失敗時対応）

## E. JPX日報ライン追加（過去補完専用）

- [x] E-1: JPX日報ページ（https://www.jpx.co.jp/markets/statistics-equities/daily/03.html）の取得対象定義
- [x] E-2: `collect_jpx_daily_stats.py` を追加（礼儀的レート制御・リトライ・日次上限）
- [x] E-3: HTML/CSV優先、PDFはバックフィル専用ラインとして分離
- [x] E-4: PDF抽出結果を `raw_events` に保存し、数値検証（合計一致/桁チェック）を実装
- [x] E-5: 日足正規化投入（`facts_price_daily` upsert: `date+ticker` 一意）
- [x] E-6: `collection_progress` に `source=jpx_daily` の進捗管理を追加（未収集レンジのみ実行）
- [x] E-7: `run_harvest_backfill.py` にJPXラインを組み込み（少量分割・途中コミット）
- [x] E-8: 監視KPIに `JPX取得率` を追加（coverage系メトリクス）

## F. 日足バックフィル戦略（分析有効本数）

- [x] F-1: 全銘柄で `200本` を先行確保するバックフィル戦略を実装
- [x] F-2: `200本` 到達後に `500本` まで段階拡張するキューを実装
- [x] F-3: 銘柄単位で `bars_collected` / `target_bars` を進捗記録
- [x] F-4: 1実行あたりの処理上限（銘柄数/日付レンジ/リクエスト数）を設定
- [x] F-5: 失敗銘柄は次回リトライ、成功分は即コミット（停止耐性）
- [x] F-6: 保管方針を固定（DB正本 + 月次Parquetエクスポート）

## 受け入れ条件（Done）

- [ ] 1. 手動指示なしで日次収集が継続実行される
- [ ] 2. DB正本でシグナル/シナリオ/アラートが一貫する
- [x] 3. 重複でジョブ停止しない
- [x] 4. Raw保持14日が自動適用される
- [x] 5. coverage/new_rows/error の推移が日次で確認できる
- [x] 6. JPXラインで進捗再開可能（途中停止後も未収集レンジから再開）
- [x] 7. 全銘柄の最低 `200本` 日足が確認できる
  - 判定注記: `price_coverage_summary_200` に基づく対象母集団（eligible）で達成率 98% 以上を合格とする
- [x] 8. `500本` 拡張対象の進捗率を日次で確認できる
