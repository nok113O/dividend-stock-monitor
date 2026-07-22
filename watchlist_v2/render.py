"""watchlist_v2/stocks.json から、公開用のウォッチリストHTML(Artifact用)を生成する。

数値の見せ方をClaudeが毎回手書きすると転記ミスの余地があるため、
stocks.jsonの値からHTMLへの変換は本スクリプトで機械的に行う。

使い方:
  python watchlist_v2/render.py
  -> watchlist_v2/rendered.html を書き出す
"""
from __future__ import annotations

import json
from pathlib import Path

STOCKS_FILE = Path(__file__).resolve().parent / "stocks.json"
OUTPUT_FILE = Path(__file__).resolve().parent / "rendered.html"

UNITS = {
    "PER": "倍",
    "PBR": "倍",
    "ROE": "%",
    "ROA": "%",
    "配当利回り": "%",
    "自己資本比率": "%",
    "時価総額": "億円",
}

STEP2_LABELS = [
    "EPS10期赤字なし",
    "今期EPSが9期前の2倍以上",
    "BPS10期連続増加",
    "10期で減配2回未満",
    "10期で無配なし",
]

CSS = """
  :root {
    --paper: #eef0f2;
    --paper-raised: #f8f9fa;
    --paper-sunken: #e7e9ec;
    --ink: #1b2430;
    --ink-dim: #5b6472;
    --rule: rgba(27, 36, 48, 0.12);
    --indigo: #2c3e6b;
    --indigo-soft: rgba(44, 62, 107, 0.09);
    --hanko: #a13d34;
    --hanko-soft: rgba(161, 61, 52, 0.1);
    --green: #3f7a56;
    --green-soft: rgba(63, 122, 86, 0.1);
  }
  :root[data-theme="dark"] {
    --paper: #12151c; --paper-raised: #191d26; --paper-sunken: #0e1015;
    --ink: #e8e6df; --ink-dim: #9aa2b1; --rule: rgba(232, 230, 223, 0.14);
    --indigo: #8ea0d6; --indigo-soft: rgba(142, 160, 214, 0.14);
    --hanko: #d97567; --hanko-soft: rgba(217, 117, 103, 0.14);
    --green: #7ec49a; --green-soft: rgba(126, 196, 154, 0.14);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --paper: #12151c; --paper-raised: #191d26; --paper-sunken: #0e1015;
      --ink: #e8e6df; --ink-dim: #9aa2b1; --rule: rgba(232, 230, 223, 0.14);
      --indigo: #8ea0d6; --indigo-soft: rgba(142, 160, 214, 0.14);
      --hanko: #d97567; --hanko-soft: rgba(217, 117, 103, 0.14);
      --green: #7ec49a; --green-soft: rgba(126, 196, 154, 0.14);
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--paper); color: var(--ink); }
  body {
    font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic Medium", "Yu Gothic", "Noto Sans JP", sans-serif;
    -webkit-font-smoothing: antialiased;
    padding: 28px 16px 64px;
  }
  .sheet { max-width: 480px; margin: 0 auto; }
  header.masthead {
    display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
    padding-bottom: 18px; margin-bottom: 20px; border-bottom: 1px solid var(--rule);
  }
  .masthead h1 {
    font-family: "Shippori Mincho", "Hiragino Mincho ProN", "Yu Mincho", serif;
    font-weight: 600; font-size: 1.5rem; letter-spacing: 0.02em; margin: 0 0 4px; text-wrap: balance;
  }
  .masthead p { margin: 0; font-size: 0.8rem; color: var(--ink-dim); }
  .seal {
    flex: none; width: 40px; height: 40px; border-radius: 50%;
    border: 1.5px solid var(--hanko); color: var(--hanko);
    display: flex; align-items: center; justify-content: center;
    font-family: "Shippori Mincho", "Hiragino Mincho ProN", serif;
    font-size: 1.1rem; font-weight: 700; transform: rotate(-4deg);
  }
  .cards { display: flex; flex-direction: column; gap: 14px; }
  .card { background: var(--paper-raised); border: 1px solid var(--rule); border-radius: 14px; padding: 18px 18px 16px; }
  .card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  .code {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 0.72rem;
    color: var(--indigo); background: var(--indigo-soft); padding: 2px 7px; border-radius: 5px; letter-spacing: 0.03em;
  }
  .name {
    font-family: "Shippori Mincho", "Hiragino Mincho ProN", "Yu Mincho", serif;
    font-size: 1.15rem; font-weight: 600; margin: 6px 0 0; text-wrap: balance;
  }
  .price-block { text-align: right; }
  .price {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums; font-size: 1.4rem; font-weight: 600; line-height: 1.1;
  }
  .delta {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums; font-size: 0.78rem; margin-top: 2px;
  }
  .delta.up { color: var(--green); }
  .delta.down { color: var(--hanko); }
  .delta.flat { color: var(--ink-dim); }
  .stat-grid {
    margin-top: 14px; display: grid; grid-template-columns: repeat(3, 1fr);
    border-top: 1px dashed var(--rule); padding-top: 12px;
  }
  .stat { text-align: center; padding: 0 4px; border-left: 1px dashed var(--rule); }
  .stat:first-child { border-left: none; }
  .stat .label { font-size: 0.68rem; color: var(--ink-dim); letter-spacing: 0.03em; }
  .stat .value {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums; font-size: 1rem; font-weight: 600; margin-top: 3px;
  }
  .yield-value { color: var(--indigo); }
  .step { margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--rule); }
  .step-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .step-name { font-size: 0.82rem; font-weight: 600; }
  .step-sub { font-size: 0.68rem; color: var(--ink-dim); margin-top: 1px; }
  .chip {
    flex: none; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.72rem; font-weight: 700; padding: 1px 9px; border-radius: 999px;
  }
  .chip.pass { color: var(--green); background: var(--green-soft); }
  .chip.fail { color: var(--hanko); background: var(--hanko-soft); }
  .chip.pending { color: var(--ink-dim); background: var(--paper-sunken); }
  .chip.lg { font-size: 0.8rem; padding: 3px 12px; }
  .check-list { margin-top: 10px; display: flex; flex-direction: column; gap: 7px; }
  .check-row { display: flex; align-items: center; gap: 8px; font-size: 0.8rem; }
  .check-label { flex: 1; min-width: 0; }
  .check-crit { display: block; font-size: 0.66rem; color: var(--ink-dim); }
  .check-value {
    flex: none; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums; font-size: 0.8rem; color: var(--ink-dim);
    min-width: 4.6em; text-align: right;
  }
  .data-gap {
    margin-top: 10px; font-size: 0.76rem; color: var(--ink-dim); line-height: 1.55;
    background: var(--paper-sunken); border-radius: 8px; padding: 8px 10px;
  }
  .data-gap strong { color: var(--ink); }
  .step3-box { margin-top: 10px; display: flex; align-items: baseline; justify-content: space-between; font-size: 0.8rem; }
  .step3-box .value {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums; color: var(--ink-dim);
  }
  .tabs { margin-top: 10px; border-top: 1px dashed var(--rule); padding-top: 10px; }
  .tab-radio { position: absolute; opacity: 0; pointer-events: none; }
  .tab-labels { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .tab-btn {
    text-align: center; font-size: 0.72rem; padding: 6px 4px; border-radius: 8px;
    background: var(--paper-sunken); color: var(--ink-dim); cursor: pointer;
    border: 1.5px solid transparent; transition: border-color 0.15s ease;
  }
  .tab-btn.reached { background: var(--green-soft); color: var(--green); font-weight: 600; }
  .tab-panel { display: none; text-align: center; padding-top: 12px; }
  .target-crit { display: block; font-size: 0.68rem; color: var(--ink-dim); }
  .target-yield {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums; font-size: 1.3rem; font-weight: 600;
    color: var(--indigo); margin-top: 4px;
  }
  .target-price {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums; font-size: 0.8rem; color: var(--ink-dim); margin-top: 2px;
  }
  .target-status {
    display: inline-block; margin-top: 6px; font-size: 0.68rem; font-weight: 600;
    padding: 1px 9px; border-radius: 999px; background: var(--paper-sunken); color: var(--ink-dim);
  }
  .target-status.reached { background: var(--green-soft); color: var(--green); }
  .card .tabs input.tab-radio:nth-of-type(1):checked ~ .tab-labels label:nth-of-type(1),
  .card .tabs input.tab-radio:nth-of-type(2):checked ~ .tab-labels label:nth-of-type(2),
  .card .tabs input.tab-radio:nth-of-type(3):checked ~ .tab-labels label:nth-of-type(3) {
    border-color: var(--indigo);
  }
  .card .tabs input.tab-radio:nth-of-type(1):checked ~ .panel-1,
  .card .tabs input.tab-radio:nth-of-type(2):checked ~ .panel-2,
  .card .tabs input.tab-radio:nth-of-type(3):checked ~ .panel-3 {
    display: block;
  }
  .comment { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--rule); font-size: 0.78rem; line-height: 1.6; }
  .comment .label { display: inline-block; font-size: 0.66rem; color: var(--ink-dim); letter-spacing: 0.03em; margin-bottom: 3px; }
  .asof { margin-top: 12px; font-size: 0.68rem; color: var(--ink-dim); font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
  footer {
    margin-top: 26px; padding-top: 16px; border-top: 1px solid var(--rule);
    font-size: 0.72rem; color: var(--ink-dim); line-height: 1.7;
  }
  footer strong { color: var(--ink); }
  @media (prefers-reduced-motion: no-preference) {
    .card { animation: rise 0.4s ease both; }
    .card:nth-child(2) { animation-delay: 0.05s; }
  }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
"""


def esc(value) -> str:
    if value is None:
        return "―"
    return str(value)


def fmt_num(value, digits=2):
    if value is None:
        return None
    return f"{value:,.{digits}f}"


def chip(judge: str, size: str = "") -> str:
    cls = {"○": "pass", "×": "fail"}.get(judge, "pending")
    label = judge if judge in ("○", "×") else "要確認"
    size_cls = f" {size}" if size else ""
    return f'<span class="chip {cls}{size_cls}">{label}</span>'


def render_step1(step1: dict) -> str:
    rows = step1["rows"]
    order = ["PER", "PBR", "ROE", "ROA", "配当利回り", "自己資本比率", "時価総額"]
    passed = sum(1 for name in order if rows.get(name, {}).get("judge") == "○")
    parts = [
        '<div class="step">',
        '<div class="step-head"><div><div class="step-name">第1段階・定量条件</div>'
        f'<div class="step-sub">7条件中 {passed}つ合格</div></div>{chip(step1["overall"], "lg")}</div>',
        '<div class="check-list">',
    ]
    for name in order:
        row = rows.get(name, {})
        unit = UNITS[name]
        value = row.get("value")
        if value is None:
            value_text = "取得不可"
        elif name == "時価総額":
            value_text = f"{fmt_num(value, 0)}{unit}"
        else:
            value_text = f"{fmt_num(value, 2)}{unit}"
        parts.append(
            '<div class="check-row">'
            f'<div class="check-label">{name}<span class="check-crit">{row.get("criterion", "")}</span></div>'
            f'<div class="check-value">{value_text}</div>'
            f'{chip(row.get("judge", "要確認"))}'
            "</div>"
        )
    parts.append("</div></div>")
    return "".join(parts)


def render_step2(step2: dict) -> str:
    periods = step2.get("periods_available", 0)
    if periods < 10:
        return (
            '<div class="step">'
            '<div class="step-head"><div><div class="step-name">第2段階・10期実績</div>'
            f'<div class="step-sub">J-Quants取得 {periods}/10期</div></div>{chip("要確認", "lg")}</div>'
            '<div class="data-gap"><strong>データ不足：</strong>'
            "J-Quants無料プランは直近の決算のみ保持しているため、"
            "残り分のEPS・BPS・1株配当を過去実績から補えば判定できます。"
            "</div></div>"
        )
    rows = step2["rows"]
    parts = [
        '<div class="step">',
        '<div class="step-head"><div><div class="step-name">第2段階・10期実績</div>'
        f'<div class="step-sub">J-Quants取得 {periods}/10期</div></div>{chip(step2["overall"], "lg")}</div>',
        '<div class="check-list">',
    ]
    for name in STEP2_LABELS:
        row = rows.get(name, {})
        parts.append(
            '<div class="check-row">'
            f'<div class="check-label">{name}</div>'
            f'<div class="check-value">{esc(row.get("detail"))}</div>'
            f'{chip(row.get("judge", "要確認"))}'
            "</div>"
        )
    parts.append("</div></div>")
    return "".join(parts)


def render_step3(step3: dict) -> str:
    target = step3.get("target_price")
    if target is None:
        value_text = "10期データ確定後に算出"
    else:
        value_text = (
            f"{fmt_num(step3['eps_sum'], 2)}円 + {fmt_num(step3['latest_bps'], 2)}円 "
            f"= {fmt_num(target, 0)}円"
        )
    return (
        '<div class="step"><div class="step-head"><div class="step-name">第3段階・目標株価</div></div>'
        '<div class="step3-box"><span>過去10期EPS合計 ＋ 最新BPS</span>'
        f'<span class="value">{value_text}</span></div></div>'
    )


def render_target_yield(code: str, current_price, ty: dict) -> str:
    if ty.get("error") or ty.get("target1_pct") is None:
        return (
            '<div class="step">'
            '<div class="step-head"><div class="step-name">目標配当利回り（正規分布モデル）</div>'
            f'{chip("要確認", "lg")}</div>'
            f'<div class="data-gap"><strong>算定不可：</strong>{esc(ty.get("error")) or "データ不足"}</div>'
            "</div>"
        )
    status = ty.get("buy_status", "要確認")
    status_cls = "pass" if "買い" in status and status != "監視" else "pending"
    tiers = [
        ("①第1買い", "85%/75%", ty["target1_pct"], ty["buy1_price"]),
        ("②第2買い", "92.5%/85%", ty["target2_pct"], ty["buy2_price"]),
        ("③第3買い", "97.5%/95%", ty["target3_pct"], ty["buy3_price"]),
    ]
    reached = [
        current_price is not None and buy_price is not None and current_price <= buy_price
        for _, _, _, buy_price in tiers
    ]
    # デフォルトで開くタブ：到達している中で最も深い段階（未到達なら①）
    default_open = 1
    for i, r in enumerate(reached, start=1):
        if r:
            default_open = i

    group = f"ty-{code}"
    radios = "".join(
        f'<input type="radio" class="tab-radio" name="{group}" id="{group}-{i}"'
        f'{" checked" if i == default_open else ""}>'
        for i in range(1, 4)
    )
    tab_labels = "".join(
        f'<label for="{group}-{i}" class="tab-btn{" reached" if reached[i-1] else ""}">{tiers[i-1][0]}</label>'
        for i in range(1, 4)
    )
    def render_panel(i: int, label: str, crit: str, pct, buy_price) -> str:
        is_reached = reached[i - 1]
        price_text = fmt_num(buy_price, 0) if buy_price is not None else "―"
        status_text = "到達済み" if is_reached else "未到達"
        status_cls2 = "reached" if is_reached else ""
        return (
            f'<div class="tab-panel panel-{i}">'
            f'<div class="target-crit">正規分布 {crit}</div>'
            f'<div class="target-yield">{fmt_num(pct, 2)}%</div>'
            f"<div class=\"target-price\">買付株価 {price_text}円</div>"
            f'<div class="target-status {status_cls2}">{status_text}</div>'
            "</div>"
        )

    panels = "".join(
        render_panel(i, label, crit, pct, buy_price)
        for i, (label, crit, pct, buy_price) in enumerate(tiers, start=1)
    )
    return (
        '<div class="step">'
        '<div class="step-head"><div>'
        '<div class="step-name">目標配当利回り（正規分布モデル）</div>'
        f'<div class="step-sub">{esc(ty.get("cycle_class"))}／{esc(ty.get("reason"))}</div>'
        f'</div><span class="chip {status_cls} lg">{status}</span></div>'
        f'<div class="tabs">{radios}<div class="tab-labels">{tab_labels}</div>{panels}</div>'
        f'<div class="step-sub" style="margin-top:8px;">サンプル：日次{ty.get("sample_daily", 0)}件／年次{ty.get("sample_annual", 0)}件（3年TTM＋10年年次）</div>'
        "</div>"
    )


def render_card(stock: dict) -> str:
    price = stock.get("price")
    price_text = fmt_num(price, 1) if price is not None else "取得不可"
    change = stock.get("price_change")
    change_pct = stock.get("price_change_pct")
    if change is None or change_pct is None:
        delta_html = '<div class="delta flat">前日比 データなし</div>'
    else:
        cls = "up" if change > 0 else ("down" if change < 0 else "flat")
        sign = "+" if change >= 0 else ""
        delta_html = (
            f'<div class="delta {cls}">前日比 {sign}{fmt_num(change, 1)}'
            f"（{sign}{change_pct * 100:.2f}%）</div>"
        )

    forecast_dividend = stock.get("forecast_dividend")
    dividend_yield = stock.get("dividend_yield_pct")
    override_note = stock.get("dividend_override_note")
    override_html = (
        f'<div class="data-gap"><strong>予想配当を手動補正：</strong>{override_note}</div>'
        if override_note
        else ""
    )

    return (
        '<div class="card">'
        '<div class="card-top"><div>'
        f'<span class="code">{stock["code"]}</span>'
        f'<div class="name">{stock["name"]}</div></div>'
        '<div class="price-block">'
        f'<div class="price">{price_text}<span style="font-size:0.75rem;font-weight:500;"> 円</span></div>'
        f"{delta_html}</div></div>"
        '<div class="stat-grid">'
        f'<div class="stat"><div class="label">予想配当</div><div class="value">'
        f'{fmt_num(forecast_dividend, 1) if forecast_dividend is not None else "取得不可"}円</div></div>'
        f'<div class="stat"><div class="label">配当利回り</div><div class="value yield-value">'
        f'{fmt_num(dividend_yield, 2) if dividend_yield is not None else "取得不可"}%</div></div>'
        f'<div class="stat"><div class="label">総合判定</div><div class="value">{stock["rating"]}</div></div>'
        "</div>"
        f"{override_html}"
        f'{render_step1(stock["step1"])}'
        f'{render_step2(stock["step2"])}'
        f'{render_step3(stock["step3"])}'
        f'{render_target_yield(stock["code"], price, stock.get("target_yield", {}))}'
        f'<div class="comment"><span class="label">所感</span><br>{stock["comment"]}</div>'
        f'<div class="asof">株価取得：{esc(stock.get("price_date"))} JST／財務：J-Quants API</div>'
        "</div>"
    )


def render(payload: dict) -> str:
    cards = "".join(render_card(s) for s in payload["stocks"])
    errors_note = ""
    if payload.get("errors"):
        codes = "、".join(e["code"] for e in payload["errors"])
        errors_note = f"<br>取得失敗：{codes}（前回値を保持）"
    return f"""<title>高配当株ウォッチリスト</title>
<style>{CSS}</style>
<div class="sheet">
  <header class="masthead">
    <div>
      <h1>高配当株ウォッチリスト</h1>
      <p>第1〜第3段階の判定つき ／ J-Quants + Yahoo!ファイナンス</p>
    </div>
    <div class="seal">高</div>
  </header>
  <div class="cards">{cards}</div>
  <footer>
    <strong>最終更新：{payload["generated_at"]}</strong><br>
    株価はYahoo!ファイナンス、財務データはJ-Quants APIから取得しています。第2・第3段階は10期分のデータが揃い次第、自動で判定されます。<br>
    平日16:00 JST（東証終了後）に自動更新されます。売買判断は各証券会社の最新情報でご確認ください。{errors_note}
  </footer>
</div>
"""


def main() -> None:
    payload = json.loads(STOCKS_FILE.read_text(encoding="utf-8"))
    html = render(payload)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"生成完了: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
