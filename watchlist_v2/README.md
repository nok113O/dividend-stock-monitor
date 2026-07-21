# 高配当株ウォッチリスト（Ver.2 / ゼロベース）

既存の `app.py`（J-Quants連携のExcel運用ツール）とは独立した、シンプルなウォッチリストです。
銘柄を手動で指定し、`fetch.py` が既存の `analyzer.py` / `jquants_client.py` / `market_data.py` /
`sector_master.py` を再利用して、第1段階（7条件の定量判定）・第2段階（10期実績チェック）・
第3段階（目標株価＝過去10期EPS合計＋最新BPS）まで自動計算し、`stocks.json` に保存します。
スマホで見やすいArtifactページとして公開しています。

- 公開ページ: https://claude.ai/code/artifact/d3ec115c-ba5a-4dd4-a568-8e62b2022116
- 対象銘柄: `codes.json`（銘柄コードの配列）
- 取得・計算結果: `stocks.json`（`fetch.py` の実行で上書きされる）
- 取得スクリプト: `fetch.py`

## セットアップ

1. J-Quants（無料プランで可）に登録し、APIキー（x-api-key）を取得する。
2. このセッションが動くClaude Codeの環境（Environment）設定で、
   ネットワークアクセスを **Custom** にし、以下のドメインを許可する。
   ```
   api.jquants.com
   query1.finance.yahoo.com
   query2.finance.yahoo.com
   fc.yahoo.com
   ```
   （現在株価はFreeプランのJ-Quantsでは直近約12週間分が取得できないため、
   `market_data.py` 経由でYahoo! Financeから補完しています）
3. 同じ環境の環境変数に `JQUANTS_API_KEY=（取得したキー）` を追加する。
4. `python watchlist_v2/fetch.py` を実行すると `stocks.json` が更新される。

## 運用

- 平日16:00 JST（東証終了後）に、スケジュール実行（Routine）が `fetch.py` を実行し、
  `stocks.json` を更新→Artifactページを再公開→リポジトリへコミット・プッシュします。
- 上記のセットアップ（APIキー・ネットワーク許可）が完了するまでは、この自動更新は失敗します。

## 現在の対象銘柄

- 8306 三菱UFJフィナンシャル・グループ
- 9433 KDDI

銘柄の追加・削除はチャットで依頼してください。
