"""決算で分かった最新の会社予想配当を、watchlist.csv の「予想配当」に反映する。

- 数字は取得した会社予想そのまま。AIは計算しない(利回りは 予想配当÷株価 の単純計算)。
- 反映するのは「増配方向」「変化なし」だけ。減配方向・取得形式不明・古い決算は反映せず、人が確認する。
- 買い1〜3は変更しない(Excel側で再計算するまでそのまま)。
- 同じ決算を二重に反映しないよう、earnings_digest.json の各項目に applied を記録する。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from earnings_watch import norm_code

JST = timezone(timedelta(hours=9))


def eligible(rec):
    fl = set(rec.get("flags", []))
    if rec.get("applied") or rec.get("v") != 2:
        return False
    if fl & {"減配方向", "取得形式不明", "データ未反映", "配当予想なし"}:
        return False
    if (rec.get("disclosure_date") or "") < rec.get("announce_date", ""):
        return False
    return rec.get("div_forecast_new") is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    dp = os.path.join(a.out, "earnings_digest.json")
    if not os.path.exists(dp):
        print("apply: no digest")
        return 0
    digest = json.load(open(dp, encoding="utf-8"))
    df = pd.read_csv(a.csv, dtype=str, encoding="utf-8-sig")
    idx = {norm_code(c): i for i, c in df["コード"].items()}
    today = datetime.now(JST).strftime("%Y-%m-%d")
    changed = same = 0
    for k, rec in digest.items():
        if not eligible(rec):
            continue
        i = idx.get(rec["code"])
        if i is None:
            continue
        new = float(rec["div_forecast_new"])
        old = pd.to_numeric(df.at[i, "予想配当"], errors="coerce")
        if pd.isna(old) or abs(old - new) > 1e-9:
            df.at[i, "予想配当"] = repr(new) if new != int(new) else str(int(new))
            price = pd.to_numeric(df.at[i, "株価"], errors="coerce")
            if pd.notna(price) and price > 0 and "配当利回り%" in df.columns:
                df.at[i, "配当利回り%"] = repr(new / float(price) * 100.0)
            changed += 1
        else:
            same += 1
        rec["applied"] = today
    df.to_csv(a.csv, index=False, encoding="utf-8-sig")
    json.dump(digest, open(dp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    print(f"apply: changed={changed} same={same}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
