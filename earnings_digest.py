"""分析待ち(earnings_state.json の pending)の銘柄について、最新の決算短信から
数字だけを機械的に取り出し、watchlist.csv の予想配当と比べて earnings_digest.json に書く。

- 数字は取得値と単純な比率だけ。AIは計算しない。
- 1回の実行で最大 --max 銘柄(APIの1日100回枠を守るため)。残りは翌日以降に自動で続く。
- ログには件数だけを出す(公開リポジトリのため、銘柄名は出さない)。
"""
import argparse
import json
import os
import re
import sys
import time

import pandas as pd
import requests

from earnings_watch import UA, _find_list, _shape, norm_code

BASE = "https://edinetdb.jp/v1/companies/{code}/earnings"


def fetch_latest(api_key, edinet_code, get=requests.get):
    r = get(BASE.format(code=edinet_code), params={"limit": 2},
            headers={"X-API-Key": api_key, "User-Agent": UA}, timeout=60)
    r.raise_for_status()
    rows = _find_list(r.json())
    if not rows:
        raise ValueError(f"no rows: {_shape(r.json())}")
    return sorted(rows, key=lambda x: g(x, "disclosureDate") or "", reverse=True)[0]


def g(row, camel, default=None):
    """camelCase でも snake_case でも拾える取得関数(APIの表記ゆれ対策)。"""
    if camel in row and row[camel] is not None:
        return row[camel]
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", camel).lower()
    return row.get(snake, default)


def _num(v):
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


def build_record(entry, row, csv_div):
    div_new = _num(g(row, "effectiveForecastDividendPerShare"))
    if div_new is None:
        div_new = _num(g(row, "forecastDividendPerShare"))
    flags = []
    disc = g(row, "disclosureDate")
    if not disc:
        flags.append("取得形式不明")
    elif disc < entry["date"]:
        flags.append("データ未反映")
    chg = None
    if div_new is None and disc:
        flags.append("配当予想なし")
    elif div_new is not None and csv_div:
        chg = round((div_new / csv_div - 1) * 100, 1)
        if chg <= -0.05:
            flags.append("減配方向")
        elif chg >= 0.05:
            flags.append("増配方向")
        else:
            flags.append("配当予想変化なし")
    return {
        "code": entry["code"], "name": entry["name"], "period": entry["period"],
        "fiscal_year_end": entry["fiscal_year_end"], "announce_date": entry["date"],
        "disclosure_date": disc, "quarter": g(row, "quarter"),
        "div_forecast_new": div_new, "div_csv": csv_div, "div_change_pct": chg,
        "net_income": g(row, "netIncome"), "net_income_yoy": g(row, "netIncomeChange"),
        "op_income_yoy": g(row, "operatingIncomeChange"),
        "forecast_net_income": g(row, "effectiveForecastNetIncome") or g(row, "forecastNetIncome"),
        "forecast_net_income_change": g(row, "effectiveForecastNetIncomeChange")
        or g(row, "forecastNetIncomeChange"),
        "equity_ratio": g(row, "equityRatio"), "pdf": g(row, "pdfUrl"), "flags": flags,
        "row_keys": sorted(row)[:40] if not disc else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=45)
    a = ap.parse_args()
    key = os.environ.get("EDINET_DB_API_KEY", "").strip()
    if not key:
        print("digest: skipped (no key)")
        return 0
    sp = os.path.join(a.out, "earnings_state.json")
    if not os.path.exists(sp):
        print("digest: no state")
        return 0
    state = json.load(open(sp, encoding="utf-8"))
    dp = os.path.join(a.out, "earnings_digest.json")
    digest = json.load(open(dp, encoding="utf-8")) if os.path.exists(dp) else {}
    df = pd.read_csv(a.csv, dtype=str, encoding="utf-8-sig")
    div_map = {norm_code(r["コード"]): _num(r.get("予想配当")) for _, r in df.iterrows()}

    todo = [(k, v) for k, v in state.get("pending", {}).items()
            if k not in digest or {"データ未反映", "取得形式不明"} & set(digest[k].get("flags", []))]
    ok = fail = skip = 0
    for k, v in todo[: a.max]:
        if not v.get("edinet_code"):
            skip += 1
            continue
        try:
            row = fetch_latest(key, v["edinet_code"])
            digest[k] = build_record(v, row, div_map.get(v["code"]))
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            code = getattr(getattr(e, "response", None), "status_code", None)
            print(f"digest: error {type(e).__name__} status={code}")
            if code == 429:  # 1日の上限。これ以上呼ばずに止める(翌日の実行で続きをやる)
                print("digest: rate limit reached, stopping")
                break
        time.sleep(0.3)
    json.dump(digest, open(dp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    left = max(0, len(todo) - a.max)
    print(f"digest: ok={ok} fail={fail} no_code={skip} remaining={left} total={len(digest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
