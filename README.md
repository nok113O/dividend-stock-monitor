# 高配当株監視ツール Ver.3.2

Ver.3.1でもIR BANKの過去10期が0件になる問題に対する修正版です。

## 修正内容

- `pandas.read_html`への依存を廃止
- `/valuation`本文から年度・EPS・BPSを正規表現で直接抽出
- `/dividend`本文を年度ブロックごとに解析
- 配当は「実績 > 修正 > 予想」の順で採用
- データ取得状態にHTTP状態と直接一致件数を表示

## 更新するファイル

- `data_fetcher.py`
- `app.py`
- `README.md`

## 正常時の表示例

- `EPS:17期／BPS:16期／配当:17期／最少16期`
- `valuation HTTP=200, 直接一致=17／dividend HTTP=200, 直接一致=17`

HTTPが403や429の場合は、IR BANKがStreamlit Cloudからの接続を制限しています。
その場合はコード解析では解決できず、別のデータ取得方式へ変更する必要があります。
