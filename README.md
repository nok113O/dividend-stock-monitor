# 高配当株監視ツール Ver.1.0

銘柄コードを入力すると、Yahoo!ファイナンス由来の現在情報とIR BANKの長期情報を取得し、
Step1～3を判定するStreamlitアプリです。

## できること

- 銘柄コード（4桁）の入力
- 基本情報、セクター、景気敏感／ディフェンシブ分類
- Step1の各項目を○×判定
- Step2の過去10期推移を○×判定
- Step3目標株価の計算
- ×項目の簡易所感
- 3段階の目標利回り・目標株価の手入力
- 監視リストへの追加・更新
- Excelダウンロード

## GitHubへアップロードするファイル

ZIPを解凍し、フォルダの「中身」をすべてGitHubへアップロードしてください。

- app.py
- analyzer.py
- data_fetcher.py
- sector_master.py
- storage.py
- requirements.txt
- README.md
- data/watchlist.csv

GitHubの空のリポジトリ画面で
`uploading an existing file` → ファイル選択 → `Commit changes`
の順に操作します。

## Streamlit Community Cloud

1. Streamlit Community CloudへGitHubでログイン
2. `Create app` または `New app`
3. Repository：作成したGitHubリポジトリ
4. Branch：`main`
5. Main file path：`app.py`
6. `Deploy`

## 重要な注意

### 1. データ取得
Yahoo!ファイナンスの現在情報は `yfinance` を利用します。
IR BANKは公開ページを読み取ります。サイトの仕様変更で取得できなくなる場合があります。

### 2. 10期データ
取得できた年次データのうち、新しい方から10期を使用します。
予想値が含まれる場合があります。画面のリンクから元サイトで照合してください。

### 3. 保存
Streamlit Community Cloudのローカルファイル保存は永続性が保証されません。
監視リスト更新後は必ずExcelをダウンロードしてください。
永続保存は次版でGoogle SheetsまたはSupabase連携を追加できます。

### 4. 投資判断
本ツールは判定補助です。会社IR、決算短信、有価証券報告書も確認してください。

## ローカル実行（任意）

```bash
pip install -r requirements.txt
streamlit run app.py
```
