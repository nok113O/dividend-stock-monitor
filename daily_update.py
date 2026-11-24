"""毎日の株価更新と購入ライン検知(最小版)。対象は実運用の「ウォッチリスト」形式のCSV。

- 更新するのは「株価・前日比%・配当利回り%・買付状況・株価日」だけ。
- 予想配当・買い1〜3(購入ライン)・総合判定などは一切再計算しない(保存済みの値を使う)。
- 買付状況は既存の target_yield_engine.status() をそのまま使う。
- 接近判定(買い1の+3%以内)は analyzer.buy_zone() と同じ閾値。
- ログに銘柄名や株価を出さない(public リポジトリのActionsログは公開されるため)。
- 初回は --baseline を付ける(既存の買付状況との差で大量の通知が出るのを防ぐ)。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from target_yield_engine import status as purchase_status

APPROACH_RATIO = 1.03  # analyzer.buy_zone と同じ
RANK = {"監視": 0, "要確認": 0, "第1買い（打診買い）": 1, "第2買い（追加買い）": 2, "第3買い（本格購入）": 3}

C_CODE, C_NAME = "コード", "銘柄名"
C_PRICE, C_CHG, C_DIV, C_YIELD = "株価", "前日比%", "予想配当", "配当利回り%"
C_B1, C_B2, C_B3, C_STATUS, C_PDATE = "買い1", "買い2", "買い3", "買付状況", "株価日"


def _num(v):
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


def fetch_prices(codes: list[str]) -> dict[str, tuple[float, str]]:
    """Yahoo!Finance から一括取得(auto_adjust=False。market_data.py と同じ終値定義)。"""
    import yfinance as yf

    tickers = [f"{c}.T" for c in codes]
    df = yf.download(tickers, period="10d", auto_adjust=False, progress=False,
                     group_by="ticker", threads=True)
    out: dict[str, tuple[float, str]] = {}
    for c in codes:
        try:
            s = (df["Close"] if len(codes) == 1 else df[f"{c}.T"]["Close"]).dropna()
            if len(s):
                out[c] = (float(s.iloc[-1]), s.index[-1].strftime("%Y-%m-%d"))
        except Exception:
            continue
    return out


def detect(old_price, new_price, old_status, new_status, p1):
    """到達(ランク上昇)と接近(買い1の+3%以内に新規突入)を返す。"""
    events = []
    if RANK.get(new_status, 0) > RANK.get(old_status, 0):
        events.append("到達")
    if p1 and new_price is not None and new_price > p1 and new_price <= p1 * APPROACH_RATIO:
        was_near = old_price is not None and old_price <= p1 * APPROACH_RATIO
        if not was_near:
            events.append("接近")
    return events


def notify_bark(key: str, title: str, body: str) -> None:
    requests.post("https://api.day.app/push",
                  json={"device_key": key, "title": title, "body": body}, timeout=20)


def run(csv_path: Path, out_dir: Path, prices=None, baseline: bool = False) -> list[dict]:
    df = pd.read_csv(csv_path, dtype={C_CODE: str}, encoding="utf-8-sig")
    df[C_CODE] = df[C_CODE].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    if C_PDATE not in df.columns:
        df[C_PDATE] = None
    codes = df[C_CODE].dropna().tolist()
    prices = prices if prices is not None else fetch_prices(codes)

    alerts, missing = [], 0
    for i, row in df.iterrows():
        code = row[C_CODE]
        if code not in prices:
            missing += 1
            continue
        price, pdate = prices[code]
        p1, p2, p3 = (_num(row.get(c)) for c in (C_B1, C_B2, C_B3))
        div = _num(row.get(C_DIV))
        old_price, old_status = _num(row.get(C_PRICE)), str(row.get(C_STATUS) or "")
        new_status = purchase_status(price, p1, p2, p3)

        same_day = str(row.get(C_PDATE) or "") == pdate  # 同日の再実行では前日比を上書きしない
        if old_price and not same_day:
            df.at[i, C_CHG] = price / old_price - 1
        df.at[i, C_PRICE] = price
        df.at[i, C_PDATE] = pdate
        if div is not None and price:
            df.at[i, C_YIELD] = div / price * 100
        df.at[i, C_STATUS] = new_status
        if not baseline and not same_day:
            for ev in detect(old_price, price, old_status, new_status, p1):
                alerts.append({"code": code, "name": row.get(C_NAME), "event": ev,
                               "status": new_status, "price": price, "buy1": p1})

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    (out_dir / "alerts_latest.json").write_text(
        json.dumps({"generated_at": now, "baseline": baseline, "alerts": alerts},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    # ログは件数のみ(銘柄・株価は出さない)
    print(f"updated={len(codes) - missing} missing={missing} alerts={len(alerts)} baseline={baseline}")
    return alerts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline", action="store_true", help="初回用: 通知・検知を出さずに基準を揃える")
    a = ap.parse_args()
    alerts = run(Path(a.csv), Path(a.out), baseline=a.baseline)
    key = os.environ.get("BARK_KEY")
    if key and alerts:
        body = " / ".join(f"{x['code']} {x['name']} {x['event']}" for x in alerts[:10])
        notify_bark(key, f"購入ライン {len(alerts)}件", body)


if __name__ == "__main__":
    main()
