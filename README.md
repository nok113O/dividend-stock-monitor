# 高配当株監視ツール Ver.2.0

## Ver.2.0の主な改善

- Step1の実績値・基準・○×を一覧表示
- Step2の過去10期EPS・BPS・1株配当を表示
- Step3「過去10期EPS合計＋最新BPS」を自動計算
- Yahoo!ファイナンス系／IR BANKの取得状態を表示
- ×項目だけ簡潔な所感を生成
- 監視リストにStep1の各指標も保存
- 3段階の目標利回り・目標株価を更新時も維持
- Excelバックアップのアップロード復元に対応
- 現在のGitHub配置に合わせ、ルートのwatchlist.csvも使用可能

## Ver.1.0からの更新

GitHubの既存リポジトリで、次のファイルをVer.2.0のものへ置き換えます。

- app.py
- analyzer.py
- data_fetcher.py
- storage.py
- requirements.txt
- README.md

`sector_master.py`は同梱版で上書きして構いません。
現在の監視データを残したい場合、`watchlist.csv`は上書きしないでください。

GitHubへコミットすると、Streamlit Community Cloudへ通常は自動反映されます。
反映しない場合はアプリの `Manage app` から再起動してください。

## 注意

- yfinanceはYahoo Finance由来のデータを利用します。
- IR BANKは公開ページの構造を読み取るため、ページ変更で取得不能になる場合があります。
- Streamlit Community Cloudのローカル保存は永続性が保証されません。
- 監視リスト更新後はExcelをダウンロードしてください。
