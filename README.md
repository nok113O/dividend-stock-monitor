# 高配当株監視ツール Ver.5.0

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


## Ver.5.0変更点

Freeプランでは直近約12週間の株価を取得できないため、現在株価はYahoo! Financeから取得します。
J-Quantsは上場銘柄情報と財務サマリーの更新に使用します。


## Ver.5.0 目標利回り自動算定エンジン

銘柄を初めて監視リストへ登録する際にだけ、Yahoo Financeの以下のデータから
3段階の目標利回りを算定します。

- 過去3年の日次TTM配当利回り
- 過去10年の年次配当利回り
- 業種、EPS変動、赤字年度、配当変動、減配履歴

景気敏感株:
- 第1 85パーセンタイル
- 第2 92.5パーセンタイル
- 第3 97.5パーセンタイル

非景気敏感株:
- 第1 75パーセンタイル
- 第2 85パーセンタイル
- 第3 95パーセンタイル

保存後の通常更新では目標利回りを再計算せず、最新の会社予想年間配当から
3段階の買付株価と現在ステータスだけを再計算します。
