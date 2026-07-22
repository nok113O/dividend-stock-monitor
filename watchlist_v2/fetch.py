"""ウォッチリスト(v2)のデータを取得・計算し、watchlist_v2/stocks.json に書き出す。

app.py と同じロジック(analyzer.py / jquants_client.py / market_data.py / sector_master.py)を
再利用し、Excel/Streamlitに依存しないスタンドアロン実行用のスクリプトにしたもの。

実行に必要な環境変数:
  JQUANTS_API_KEY  J-Quants V2 の x-api-key

対象銘柄コードは watchlist_v2/codes.json (JSON配列) で指定する。

使い方:
  python watchlist_v2/fetch.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from analyzer import (  # noqa: E402
    analyze_step1, analyze_step2, calculate_step3,
    latest_summary, make_comment, merge_new_fy,
    overall_rating, step1_metrics,
)
from jquants_client import JQuantsClient, JQuantsError  # noqa: E402
from market_data import current_market_data  # noqa: E402
from sector_master import classify  # noqa: E402
from workbook_io import empty_history  # noqa: E402

CODES_FILE = Path(__file__).resolve().parent / "codes.json"
OUTPUT_FILE = Path(__file__).resolve().parent / "stocks.json"
SEED_FILE = Path(__file__).resolve().parent / "history_seed.json"


def load_seed(code: str) -> dict:
    if not SEED_FILE.exists():
        return {}
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return data.get(code, {})


def seed_history_df(code: str, seed: dict) -> pd.DataFrame:
    """J-Quants Freeが保持していない古い決算期を補うための手入力データを読み込む。"""
    rows = seed.get("history", [])
    if not rows:
        return empty_history()
    return pd.DataFrame([
        {
            "コード": str(code).zfill(4),
            "決算期": row["period"],
            "EPS": row["eps"],
            "BPS": row["bps"],
            "1株配当": row["dividend"],
            "データ元": "手入力",
            "更新日": "seed",
        }
        for row in rows
    ])


def fetch_one(client: JQuantsClient, code: str) -> dict:
    master = client.master(code)
    market = current_market_data(code)
    summaries = client.financial_summary(code)

    price = market.get("price")
    price_date = market.get("price_date")
    latest = latest_summary(summaries)
    metrics = step1_metrics(price, latest)

    if metrics.get("PER") is None:
        metrics["PER"] = market.get("trailing_pe")
    if metrics.get("PBR") is None:
        metrics["PBR"] = market.get("price_to_book")
    if metrics.get("ROE") is None and market.get("roe") is not None:
        metrics["ROE"] = float(market["roe"]) * 100
    if metrics.get("ROA") is None and market.get("roa") is not None:
        metrics["ROA"] = float(market["roa"]) * 100
    if metrics.get("時価総額（億円）") is None and market.get("market_cap") is not None:
        metrics["時価総額（億円）"] = float(market["market_cap"]) / 100_000_000
    if metrics.get("予想年間配当") is None and market.get("dividend_rate") is not None:
        metrics["予想年間配当"] = float(market["dividend_rate"])
    if metrics.get("配当利回り") is None:
        if metrics.get("予想年間配当") is not None and price:
            metrics["配当利回り"] = metrics["予想年間配当"] / price * 100
        elif market.get("dividend_yield") is not None:
            y = float(market["dividend_yield"])
            metrics["配当利回り"] = y * 100 if abs(y) <= 1 else y

    seed = load_seed(code)
    override_note = None
    override_dividend = seed.get("current_dividend_forecast")
    if override_dividend is not None:
        override_note = seed.get("note")
        metrics["予想年間配当"] = float(override_dividend)
        if price:
            metrics["配当利回り"] = metrics["予想年間配当"] / price * 100

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    history = merge_new_fy(seed_history_df(code, seed), code, summaries, now)

    step1 = analyze_step1(metrics)
    step2 = analyze_step2(history, code)
    step3 = calculate_step3(history, code)
    sector, cycle = classify(master.get("S33Nm"))
    comment = make_comment(step1, step2)
    rating = overall_rating(step1, step2)

    def clean(value):
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        return value

    return {
        "code": code,
        "name": master.get("CoName"),
        "industry": master.get("S33Nm"),
        "sector": sector,
        "cycle": cycle,
        "price": clean(price),
        "price_date": price_date,
        "price_change": clean(market.get("change")),
        "price_change_pct": clean(market.get("change_pct")),
        "step1": {
            "overall": step1["overall"],
            "rows": {
                name: {"value": clean(row["value"]), "criterion": row["criterion"], "judge": row["judge"]}
                for name, row in step1["rows"].items()
            },
        },
        "step2": {
            "overall": step2["overall"],
            "rows": {
                name: {"judge": row["judge"], "detail": row["detail"]}
                for name, row in step2["rows"].items()
            },
            "periods_available": int(len(step2["history"])),
        },
        "step3": {
            "eps_sum": clean(step3["eps_sum"]),
            "latest_bps": clean(step3["latest_bps"]),
            "target_price": clean(step3["target_price"]),
        },
        "forecast_dividend": clean(metrics.get("予想年間配当")),
        "dividend_yield_pct": clean(metrics.get("配当利回り")),
        "dividend_override_note": override_note,
        "rating": rating,
        "comment": comment,
        "updated_at": now,
    }


def main() -> None:
    api_key = os.environ.get("JQUANTS_API_KEY", "")
    codes = json.loads(CODES_FILE.read_text(encoding="utf-8"))
    client = JQuantsClient(api_key, min_interval_seconds=1.2)

    results = []
    errors = []
    for i, code in enumerate(codes):
        if i > 0:
            time.sleep(2)
        try:
            results.append(fetch_one(client, code))
        except JQuantsError as exc:
            errors.append({"code": code, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            errors.append({"code": code, "error": f"{type(exc).__name__}: {exc}"})

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stocks": results,
        "errors": errors,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"取得完了: {len(results)}件 / エラー {len(errors)}件 -> {OUTPUT_FILE}")
    if errors:
        for e in errors:
            print(f"  - {e['code']}: {e['error']}")


if __name__ == "__main__":
    main()
