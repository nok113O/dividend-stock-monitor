"""stocks.jsonから監視銘柄一覧のExcelファイルを書き出す。

watchlist_v2/fetch.py実行後のstocks.jsonを読み込み、一覧性の高いExcel
(.xlsx)を1シートで出力する。分割買いラインの確定値(買い1/2/3・到達状況・
要再審査・大幅増配注記)も含む。

使い方:
  python watchlist_v2/export_excel.py [出力先パス]
  (省略時は watchlist_v2/watchlist.xlsx に出力)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

STOCKS_FILE = Path(__file__).resolve().parent / "stocks.json"
DEFAULT_OUT = Path(__file__).resolve().parent / "watchlist.xlsx"

COLUMNS = [
    "コード", "銘柄名", "業種", "セクター", "総合判定",
    "Step1", "Step2",
    "現在株価", "株価日", "予想配当", "配当利回り(%)",
    "PER", "PBR", "ROE(%)", "ROA(%)", "自己資本比率(%)", "時価総額(億円)",
    "確定買い1", "確定買い2", "確定買い3", "買い3採用根拠", "到達状況",
    "要再審査", "要再審査理由", "大幅増配注記", "確定値基準日", "確定理由",
    "優先度スコア", "期待IRR(%)", "所感", "最終更新",
]


def locked_buy_status(price, locked: dict | None) -> str:
    if price is None or not locked or locked.get("disabled"):
        return "要確認" if not locked else "監視(要再審査中)"
    b1, b2, b3 = locked.get("buy1"), locked.get("buy2"), locked.get("buy3")
    if b3 is not None and price <= b3:
        return "第3買い（本格購入）"
    if b2 is not None and price <= b2:
        return "第2買い（追加買い）"
    if b1 is not None and price <= b1:
        return "第1買い（打診買い）"
    return "監視"


def build_rows(stocks: list[dict]) -> list[dict]:
    rows = []
    for s in stocks:
        step1_rows = s.get("step1", {}).get("rows", {})
        locked = s.get("locked_targets") or {}
        priority = s.get("priority_score", {}) or {}
        rows.append({
            "コード": s.get("code"),
            "銘柄名": s.get("name"),
            "業種": s.get("industry"),
            "セクター": s.get("sector"),
            "総合判定": s.get("rating"),
            "Step1": s.get("step1", {}).get("overall"),
            "Step2": s.get("step2", {}).get("overall"),
            "現在株価": s.get("price"),
            "株価日": s.get("price_date"),
            "予想配当": s.get("forecast_dividend"),
            "配当利回り(%)": s.get("dividend_yield_pct"),
            "PER": step1_rows.get("PER", {}).get("value"),
            "PBR": step1_rows.get("PBR", {}).get("value"),
            "ROE(%)": step1_rows.get("ROE", {}).get("value"),
            "ROA(%)": step1_rows.get("ROA", {}).get("value"),
            "自己資本比率(%)": step1_rows.get("自己資本比率", {}).get("value"),
            "時価総額(億円)": step1_rows.get("時価総額", {}).get("value"),
            "確定買い1": locked.get("buy1"),
            "確定買い2": locked.get("buy2"),
            "確定買い3": locked.get("buy3"),
            "買い3採用根拠": locked.get("buy3_source"),
            "到達状況": locked_buy_status(s.get("price"), locked),
            "要再審査": "○" if locked.get("disabled") else "",
            "要再審査理由": locked.get("disabled_reason"),
            "大幅増配注記": locked.get("large_increase_detail") if locked.get("large_increase_warning") else "",
            "確定値基準日": locked.get("basis_date"),
            "確定理由": locked.get("reason"),
            "優先度スコア": priority.get("total_score"),
            "期待IRR(%)": (s.get("expected_irr") or {}).get("expected_irr_pct"),
            "所感": s.get("comment"),
            "最終更新": s.get("updated_at"),
        })
    return rows


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    data = json.loads(STOCKS_FILE.read_text(encoding="utf-8"))
    rows = build_rows(data.get("stocks", []))
    df = pd.DataFrame(rows, columns=COLUMNS)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="監視銘柄一覧", index=False)
        ws = writer.sheets["監視銘柄一覧"]
        ws.freeze_panes = "C2"
        for col_cells in ws.columns:
            length = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 8), 40)

    print(f"出力完了: {len(rows)}銘柄 -> {out_path}")


if __name__ == "__main__":
    main()
