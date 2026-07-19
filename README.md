# 高配当株監視ツール Ver.4.0

## 採用方式

- 初回の過去10期：Excelに確定保存
- 以後の新しい決算：J-Quants API V2 Freeで追加
- 常に銘柄ごとの最新10期を維持
- IR BANKへの自動アクセスは完全削除

## API

- 上場銘柄一覧: `/v2/equities/master`
- 株価四本値: `/v2/equities/bars/daily`
- 財務情報: `/v2/fins/summary`
- 認証: `x-api-key`

Streamlit Secrets:
```toml
JQUANTS_API_KEY = "..."
```

## GitHubへ上書きするファイル

- app.py
- analyzer.py
- jquants_client.py
- workbook_io.py
- sector_master.py
- requirements.txt
- README.md

旧`data_fetcher.py`と`storage.py`は使用しません。残っていても動作には影響しません。

## 運用

1. 初期テンプレートExcelの「10期履歴」に過去10期を登録
2. アプリへExcelをアップロード
3. 銘柄コードを分析・更新
4. 監視リストへ保存
5. 更新済みExcelをダウンロード
6. 次回はそのExcelをアップロード

Excelが正本です。
