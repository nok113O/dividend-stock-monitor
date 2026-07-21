# 高配当株ウォッチリスト（Ver.2 / ゼロベース）

既存の `app.py`（J-Quants連携のExcel運用ツール）とは独立した、シンプルなウォッチリストです。
銘柄を手動で指定し、Web検索で取得した株価・配当情報を `stocks.json` に保持し、
スマホで見やすいArtifactページとして公開しています。

- 公開ページ: https://claude.ai/code/artifact/d3ec115c-ba5a-4dd4-a568-8e62b2022116
- データ: `stocks.json`
- 更新方法: Claude Codeセッションのスケジュール実行（Routine）が日次でWeb検索により
  株価・配当予想を再取得し、`stocks.json` の更新とArtifactページの再公開を行います。

## 現在の対象銘柄

- 8306 三菱UFJフィナンシャル・グループ
- 9433 KDDI

銘柄の追加・削除はチャットで依頼してください。
