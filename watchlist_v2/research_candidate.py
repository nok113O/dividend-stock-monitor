"""新規候補銘柄の一次スクリーニングを行うツール。

EDINET DB(検索・財務時系列)とmarket_data(現在値)を使い、
Step1相当の定量条件・10期の配当推移・株式分割の有無を一括表示する。
history_seed.jsonにそのまま貼り付けられるJSONスニペットも出力する。

必要な環境変数:
  EDINETDB_API_KEY  EDINET DB のAPIキー

使い方:
  EDINETDB_API_KEY=... python watchlist_v2/research_candidate.py 8014
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from edinetdb_client import EdinetDbClient, EdinetDbError  # noqa: E402
from market_data import current_market_data  # noqa: E402
from sector_master import classify, step1_thresholds  # noqa: E402

CODES_FILE = Path(__file__).resolve().parent / "codes.json"


def resolve_company(client: EdinetDbClient, code: str) -> dict | None:
    target = f"{code}0"
    for company in client.search(code):
        if company.get("sec_code") == target:
            return company
    return None


def fmt(value, digits=2, unit="") -> str:
    if value is None:
        return "取得不可"
    return f"{value:,.{digits}f}{unit}"


def judge(ok: bool | None) -> str:
    if ok is None:
        return "？"
    return "○" if ok else "×"


def print_step1_table(sector: str, price, market: dict, equity_ratio_official) -> None:
    overrides = step1_thresholds(sector)
    per = market.get("trailing_pe")
    pbr = market.get("price_to_book")
    roe = market.get("roe")
    roe_pct = roe * 100 if roe is not None else None
    roa = market.get("roa")
    roa_pct = roa * 100 if roa is not None else None
    div_yield = market.get("dividend_yield")
    if div_yield is not None:
        div_yield_pct = div_yield * 100 if abs(div_yield) <= 1 else div_yield
    else:
        div_yield_pct = None
    equity_ratio_pct = equity_ratio_official * 100 if equity_ratio_official is not None else None
    market_cap_oku = market.get("market_cap") / 100_000_000 if market.get("market_cap") is not None else None

    roa_threshold = overrides.get("ROA", 3.0)
    equity_threshold = overrides.get("自己資本比率", 35.0)
    sector_note = f"(業種調整: 自己資本比率{equity_threshold}%以上・ROA{roa_threshold}%以上)" if overrides else ""

    rows = [
        ("PER", per, per is not None and per <= 12, "12倍以下"),
        ("PBR", pbr, pbr is not None and pbr <= 1.3, "1.3倍以下"),
        ("ROE", roe_pct, roe_pct is not None and roe_pct >= 7, "7%以上"),
        ("ROA", roa_pct, roa_pct is not None and roa_pct >= roa_threshold, f"{roa_threshold}%以上"),
        ("配当利回り", div_yield_pct, div_yield_pct is not None and div_yield_pct >= 3, "3%以上"),
        ("自己資本比率", equity_ratio_pct, equity_ratio_pct is not None and equity_ratio_pct >= equity_threshold, f"{equity_threshold}%以上"),
        ("時価総額(億円)", market_cap_oku, market_cap_oku is not None and market_cap_oku >= 100, "100億円以上"),
    ]
    print(f"\n[第1段階・定量条件 目安] {sector_note}")
    passed = 0
    for name, value, ok, criterion in rows:
        if ok:
            passed += 1
        print(f"  {name:12s} {fmt(value):>12s}  基準:{criterion:10s}  {judge(ok)}")
    print(f"  -> {passed}/7 条件クリア")


def print_history_and_note(rows: list[dict]) -> tuple[list[dict], bool]:
    print("\n[10期履歴(EDINET DB分割調整値)]")
    print(f"  {'決算期':10s} {'EPS':>10s} {'BPS':>10s} {'配当':>8s} {'split factor':>12s} {'basis':>18s}")
    factors = set()
    history = []
    for r in rows:
        factor = r.get("split_adjustment_factor")
        factors.add(factor)
        eps = r.get("adjusted_eps")
        bps = r.get("adjusted_bps")
        div = r.get("adjusted_dividend_per_share")
        basis = r.get("adjusted_dividend_basis")
        print(f"  {r['fiscal_year']}/03      {fmt(eps):>10s} {fmt(bps):>10s} {fmt(div):>8s} {fmt(factor):>12s} {str(basis):>18s}")
        history.append({
            "period": f"{r['fiscal_year']}-03-31",
            "eps": round(eps, 2) if eps is not None else None,
            "bps": round(bps, 2) if bps is not None else None,
            "dividend": round(div, 2) if div is not None else None,
        })
    split_flag = len(factors - {1.0, None}) > 0 or len(factors) > 1
    if split_flag:
        print("\n  ⚠ 株式分割の影響でsplit_adjustment_factorが変動しています。")
        print("     EDINET DBの自動調整は分割またぎ期でズレることがあるため、")
        print("     IRBANK等の実測値で配当推移を目視確認してから採用してください。")
    else:
        print("\n  分割調整なし(factor常に1.0)。EDINET DB値をそのまま信頼して良さそうです。")
    return history, split_flag


def main() -> None:
    if len(sys.argv) < 2:
        print("使い方: python watchlist_v2/research_candidate.py <証券コード> [<証券コード> ...]")
        sys.exit(1)

    api_key = os.environ.get("EDINETDB_API_KEY", "")
    client = EdinetDbClient(api_key)
    existing_codes = json.loads(CODES_FILE.read_text(encoding="utf-8"))

    for code in sys.argv[1:]:
        print("=" * 70)
        print(f"銘柄コード: {code}")
        if code in existing_codes:
            print("  ※ 既にウォッチリストに登録済みです。")

        company = resolve_company(client, code)
        if not company:
            print("  EDINET DBで該当企業が見つかりませんでした。")
            continue

        edinet_code = company["edinet_code"]
        name = company.get("name")
        industry = company.get("industry")
        sector, cycle = classify(industry)
        print(f"  企業名: {name} / 業種: {industry} -> 分類: {sector}({cycle})")

        try:
            financial_rows = client.financials(edinet_code, years=10)
            profile = client.company_profile(edinet_code)
        except EdinetDbError as exc:
            print(f"  EDINET DB取得エラー: {exc}")
            continue

        market = current_market_data(code)
        latest_row = financial_rows[-1] if financial_rows else {}
        print_step1_table(sector, market.get("price"), market, latest_row.get("equity_ratio_official"))

        payout = latest_row.get("payout_ratio")
        if payout is not None:
            print(f"\n  配当性向(最新期): {payout * 100:.1f}%")

        history, split_flag = print_history_and_note(financial_rows)

        latest_earnings = profile.get("latest_earnings") or {}
        forecast_dividend = latest_earnings.get("forecast_dividend_per_share")
        disclosure_date = latest_earnings.get("disclosure_date")
        print(f"\n[直近開示] {disclosure_date} 時点の予想配当: {fmt(forecast_dividend, 1, '円')}")

        print("\n[history_seed.json 貼り付け用スニペット]")
        note = "EDINET DBより自動取得。" + (
            "株式分割ありのため配当系列は独立ソースで要確認。"
            if split_flag else
            "株式分割なし、EDINET DB値をそのまま採用。"
        )
        snippet = {
            code: {
                "history": history,
                "current_dividend_forecast": forecast_dividend,
                "note": note,
            }
        }
        print(json.dumps(snippet, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
