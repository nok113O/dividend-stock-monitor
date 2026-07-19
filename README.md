# 高配当株監視ツール Ver.3.0

## 主な機能

- 銘柄コードからYahoo!ファイナンス系とIR BANKのデータを取得
- Step1の7項目を個別に○×判定
- Step2のEPS・BPS・一株配当の過去10期を判定
- Step3「過去10期EPS合計＋最新BPS」を計算
- セクター、景気敏感／ディフェンシブ分類
- ×項目の簡潔な所感
- 3段階の目標利回り・目標株価
- 買い場判定
- 監視リストへの追加・編集・削除
- 全銘柄一括更新
- Excelバックアップと復元

## IR BANK取得の改善

Ver.3.0では次の順に取得します。

1. IR BANK公式配布JSON
2. IR BANK決算まとめHTML
3. Yahoo Finance由来データでStep1を補完

IR BANK公式は、通期データのCSV・JSONを公開しています。
アクセス過多は禁止されているため、全銘柄更新では待機時間を設けています。

## Ver.2.0からの更新対象

以下をGitHubへ上書きしてください。

- app.py
- analyzer.py
- data_fetcher.py
- storage.py
- sector_master.py
- requirements.txt
- README.md

`watchlist.csv`は既存データを残すため上書きしないでください。

## 更新後の確認

1. GitHubへコミット
2. Streamlitアプリを再読み込み
3. 画面上部に「Ver.3.0」と表示されることを確認
4. 1605で分析
5. IR BANK取得状態に「JSON」「HTML」または最少期数が表示されることを確認

## 注意

- 自動取得結果は会社IRでも照合してください。
- IR BANKの通期配布データは即時更新ではありません。
- Streamlit Community Cloudのローカル保存は永続性が保証されません。
- 監視リスト更新後はExcelをダウンロードしてください。
