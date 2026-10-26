"""ウォッチリスト(v2)のデータを取得・計算し、watchlist_v2/stocks.json に書き出す。

app.py と同じロジック(analyzer.py / jquants_client.py / market_data.py / sector_master.py)を
再利用し、Excel/Streamlitに依存しないスタンドアロン実行用のスクリプトにしたもの。

実行に必要な環境変数:
  JQUANTS_API_KEY   J-Quants V2 の x-api-key
  EDINETDB_API_KEY  EDINET DB のAPIキー(任意。無ければEDINET DB連携はスキップされる)

対象銘柄コードは watchlist_v2/codes.json (JSON配列) で指定する。
EDINETコードのマッピングは watchlist_v2/edinet_codes.json (build_edinet_codes.pyで作成)。

使い方:
  python watchlist_v2/fetch.py            # codes.json全銘柄を再取得
  python watchlist_v2/fetch.py 8014 1939  # 指定銘柄のみ再取得(他は前回値を保持)

EDINET DBは無料プラン(100回/日)のため、同じ日に2回目以降fetch.pyを実行しても
カレンダー・決算短信の問い合わせは自動的にスキップされる(株価・J-Quants分は毎回更新される)。
その日のうちにどうしてもEDINET DB分も再実行したい場合は --force-edinet を付ける。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from analyzer import (  # noqa: E402
    analyze_step1, analyze_step2, calculate_equity_ratio_trend, calculate_expected_irr,
    calculate_forecast_tendency, calculate_priority_score, calculate_step3,
    calculate_valuation_range, latest_fy_summaries, latest_summary, make_comment,
    merge_new_fy, normalize_history, num, overall_rating, step1_metrics,
)
from edinetdb_client import EdinetDbClient, EdinetDbError  # noqa: E402
from jquants_client import JQuantsClient, JQuantsError  # noqa: E402
from market_data import current_market_data  # noqa: E402
from sector_master import classify  # noqa: E402
from target_yield_engine import calculate_targets, purchase_price  # noqa: E402
from target_yield_engine import status as purchase_status  # noqa: E402
from workbook_io import empty_history  # noqa: E402

CODES_FILE = Path(__file__).resolve().parent / "codes.json"
OUTPUT_FILE = Path(__file__).resolve().parent / "stocks.json"
SEED_FILE = Path(__file__).resolve().parent / "history_seed.json"
EDINET_CODES_FILE = Path(__file__).resolve().parent / "edinet_codes.json"
EDINET_LAST_RUN_FILE = Path(__file__).resolve().parent / ".edinet_last_run"
EDINET_CALENDAR_LOOKBACK_DAYS = 7


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


def apply_ordinary_dividend_overrides(history: pd.DataFrame, seed: dict) -> None:
    """記念・特別配当を含む期について、普通配当（記念・特別分を除いた額）をhistory_seed.jsonの
    `ordinary_dividend_overrides`から適用する(in-place)。未補正の期は普通配当＝総配当のまま
    (analyzer.normalize_historyがフォールバックする)。

    history_seed.jsonでの指定例:
      "ordinary_dividend_overrides": [
        {"period": "2024-03-31", "ordinary_dividend": 65.0, "note": "記念あり(2024・創業50周年)"}
      ]
    """
    overrides = seed.get("ordinary_dividend_overrides") or []
    if not overrides or history.empty:
        return
    if "普通配当" not in history.columns:
        history["普通配当"] = None
    if "記念配当注記" not in history.columns:
        history["記念配当注記"] = None
    period_key = pd.to_datetime(history["決算期"], errors="coerce").dt.strftime("%Y-%m-%d")
    for row in overrides:
        period = row.get("period")
        value = row.get("ordinary_dividend")
        if not period or value is None:
            continue
        mask = period_key == period
        if mask.any():
            history.loc[mask, "普通配当"] = float(value)
            history.loc[mask, "記念配当注記"] = row.get("note")


def load_edinet_codes() -> dict[str, str]:
    if not EDINET_CODES_FILE.exists():
        return {}
    return json.loads(EDINET_CODES_FILE.read_text(encoding="utf-8"))


def fetch_recent_edinet_earnings(
    codes: list[str], force: bool = False
) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """直近の決算短信カレンダーを見て、開示があったウォッチリスト銘柄だけ最新開示と
    有報5期分の時系列(期末PER・自己資本比率等)を取得する。

    データ出典: EDINET DB (https://edinetdb.jp)
    無料プラン(100回/日)を守るため、カレンダー参照1回+該当銘柄分のみリクエストする。
    さらに、同じ日にfetch.pyを複数回実行しても日次上限を圧迫しないよう、
    その日すでにEDINET DBへ問い合わせ済みなら2回目以降はスキップする(force=Trueで無視可能)。

    期末PER・自己資本比率5期推移(valuation_range/equity_ratio_trend)は、このEDINET
    取得が走った(=決算発表があった)銘柄だけ再計算し、それ以外は前回値を保持する
    (fetch_one呼び出し側で前回値を引き継ぐ)。
    """
    api_key = os.environ.get("EDINETDB_API_KEY", "")
    if not api_key:
        return {}, {}
    edinet_codes = load_edinet_codes()
    if not edinet_codes:
        return {}, {}

    today_str = date.today().strftime("%Y-%m-%d")
    if not force and EDINET_LAST_RUN_FILE.exists():
        last_run = EDINET_LAST_RUN_FILE.read_text(encoding="utf-8").strip()
        if last_run == today_str:
            print(
                f"EDINET DB: 本日({today_str})は実行済みのためスキップします"
                "(--force-edinet で強制実行可)。"
            )
            return {}, {}

    client = EdinetDbClient(api_key)
    today = date.today()
    date_from = (today - timedelta(days=EDINET_CALENDAR_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")
    # カレンダーへの問い合わせを試みた時点で「本日実行済み」と記録する(エラー時も含む＝再試行の連打を防ぐ)。
    EDINET_LAST_RUN_FILE.write_text(today_str, encoding="utf-8")
    try:
        calendar_entries = client.calendar(date_from, date_to)
    except EdinetDbError as exc:
        print(f"EDINET DBカレンダー取得エラー(スキップ): {exc}")
        return {}, {}

    edinet_to_code = {v: k for k, v in edinet_codes.items()}
    our_codes = set(codes)
    hit_codes = {
        edinet_to_code[entry.get("edinetCode")]
        for entry in calendar_entries
        if entry.get("edinetCode") in edinet_to_code and edinet_to_code[entry.get("edinetCode")] in our_codes
    }

    earnings_results: dict[str, dict] = {}
    financials_results: dict[str, list[dict]] = {}
    for code in sorted(hit_codes):
        edinet_code = edinet_codes[code]
        try:
            earnings = client.earnings(edinet_code, limit=1)
        except EdinetDbError as exc:
            print(f"  {code}: EDINET DB決算短信取得エラー(スキップ): {exc}")
            continue
        if earnings:
            earnings_results[code] = earnings[0]
        try:
            financials_results[code] = client.financials(edinet_code, years=5)
        except EdinetDbError as exc:
            print(f"  {code}: EDINET DB有報時系列取得エラー(スキップ): {exc}")
    if hit_codes:
        print(f"EDINET DB: 直近{EDINET_CALENDAR_LOOKBACK_DAYS}日で開示があった対象銘柄 {sorted(hit_codes)}")
    return earnings_results, financials_results


def fetch_one(
    client: JQuantsClient,
    code: str,
    edinet_latest: dict | None = None,
    edinet_financials: list[dict] | None = None,
    prev_stock: dict | None = None,
) -> dict:
    master = client.master(code)
    market = current_market_data(code)
    summaries = client.financial_summary(code)

    price = market.get("price")
    price_date = market.get("price_date")
    latest = latest_summary(summaries)
    fy_summaries = latest_fy_summaries(summaries)
    fy_latest = fy_summaries[-1] if fy_summaries else None
    metrics = step1_metrics(price, latest, fy_latest)

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

    edinet_disclosure_date = None
    if edinet_latest and override_dividend is None:
        edinet_forecast = edinet_latest.get("forecast_dividend_per_share")
        if edinet_forecast is not None:
            metrics["予想年間配当"] = float(edinet_forecast)
            if price:
                metrics["配当利回り"] = metrics["予想年間配当"] / price * 100
            raw_disclosure_date = edinet_latest.get("disclosure_date")
            if raw_disclosure_date:
                try:
                    edinet_disclosure_date = datetime.strptime(
                        raw_disclosure_date, "%a, %d %b %Y %H:%M:%S %Z"
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    edinet_disclosure_date = raw_disclosure_date

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    history = merge_new_fy(seed_history_df(code, seed), code, summaries, now)
    apply_ordinary_dividend_overrides(history, seed)

    forecast_tendency = calculate_forecast_tendency(fy_summaries)
    valuation_range = None
    equity_ratio_trend = None
    if edinet_financials is not None:
        valuation_range = calculate_valuation_range(
            edinet_financials, metrics.get("予想EPS"), metrics.get("予想年間配当")
        )
        equity_ratio_trend = calculate_equity_ratio_trend(edinet_financials)

    sector, cycle = classify(master.get("S33Nm"))
    step1 = analyze_step1(metrics, sector)
    step2 = analyze_step2(history, code)
    step3 = calculate_step3(history, code)
    priority = calculate_priority_score(metrics, step2.get("history"), seed.get("dividend_policy"))
    expected_irr = calculate_expected_irr(metrics, step2.get("history"))
    comment = make_comment(step1, step2)
    rating = overall_rating(step1, step2)

    fiscal_year_end_month = None
    if not history.empty:
        latest_period = history.sort_values("決算期")["決算期"].iloc[-1]
        if pd.notna(latest_period):
            fiscal_year_end_month = int(latest_period.month)

    eps_hist = pd.to_numeric(history["EPS"], errors="coerce").dropna().tolist()
    div_hist = pd.to_numeric(history["1株配当"], errors="coerce").dropna().tolist()
    forecast_dividend = metrics.get("予想年間配当")
    try:
        targets = calculate_targets(code, master.get("S33Nm"), eps_hist, div_hist)
        buy1 = purchase_price(forecast_dividend, targets.target1)
        buy2 = purchase_price(forecast_dividend, targets.target2)
        buy3 = purchase_price(forecast_dividend, targets.target3)
        target_yield = {
            "cycle_class": targets.cycle_class,
            "reason": targets.reason,
            "target1_pct": targets.target1,
            "target2_pct": targets.target2,
            "target3_pct": targets.target3,
            "buy1_price": buy1,
            "buy2_price": buy2,
            "buy3_price": buy3,
            "buy_status": purchase_status(price, buy1, buy2, buy3),
            "sample_daily": targets.sample_daily,
            "sample_annual": targets.sample_annual,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        target_yield = {
            "cycle_class": None, "reason": None,
            "target1_pct": None, "target2_pct": None, "target3_pct": None,
            "buy1_price": None, "buy2_price": None, "buy3_price": None,
            "buy_status": "要確認", "sample_daily": 0, "sample_annual": 0,
            "error": str(exc),
        }

    ordinary_div_series = normalize_history(history, code)["普通配当"].dropna()
    last_ordinary_dividend = float(ordinary_div_series.iloc[-1]) if not ordinary_div_series.empty else None

    locked_targets = update_locked_targets(
        prev_stock or {}, code, master.get("S33Nm"), summaries, eps_hist, div_hist,
        forecast_dividend, step3, target_yield, date.today().strftime("%Y-%m-%d"),
        override_dividend is not None, last_ordinary_dividend,
    )

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
        "fiscal_year_end_month": fiscal_year_end_month,
        "price": clean(price),
        "price_date": price_date,
        "price_change": clean(market.get("change")),
        "price_change_pct": clean(market.get("change_pct")),
        "step1": {
            "overall": step1["overall"],
            "sector_adjusted": step1["sector_adjusted"],
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
            "special_dividend_notes": step2.get("special_dividend_notes", []),
        },
        "step3": {
            "eps_sum": clean(step3["eps_sum"]),
            "latest_bps": clean(step3["latest_bps"]),
            "target_price": clean(step3["target_price"]),
        },
        "forecast_dividend": clean(metrics.get("予想年間配当")),
        "dividend_yield_pct": clean(metrics.get("配当利回り")),
        "dividend_override_note": override_note,
        "target_yield": target_yield,
        "rating": rating,
        "comment": comment,
        "priority_score": {
            "growth_score": priority["growth_score"],
            "income_score": priority["income_score"],
            "total_score": priority["total_score"],
            "payout_ratio_pct": clean(metrics.get("配当性向")),
            "dividend_cagr_pct": priority["dividend_cagr_pct"],
            "dividend_years_to_double": priority["dividend_years_to_double"],
            "growth_detail": priority["growth_detail"],
            "income_detail": priority["income_detail"],
            "dividend_quality_badges": priority["dividend_quality_badges"],
        },
        "expected_irr": expected_irr,
        "forecast_tendency": forecast_tendency,
        "valuation_range": valuation_range,
        "equity_ratio_trend": equity_ratio_trend,
        "locked_targets": locked_targets,
        "updated_at": now,
        "_edinet_disclosure_date": edinet_disclosure_date,
    }


def load_previous_stocks() -> dict[str, dict]:
    if not OUTPUT_FILE.exists():
        return {}
    try:
        payload = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {s["code"]: s for s in payload.get("stocks", [])}


# 分割買いラインの引き直しトリガー種別。同日に複数開示があった場合の優先順位にも使う。
TRIGGER_PRIORITY = {"決算短信": 3, "配当予想の修正": 2, "業績予想の修正": 1, "その他": 0}

# "1QFinancialStatements_Consolidated_JP" のように {期}{連結/単体}{会計基準(JP/IFRS/USGAAP)}の
# 組み合わせで何通りもの値がある(IFRS・米国会計基準の銘柄も監視対象に含まれるため)。
# 個別に列挙せず正規表現で判定する。
FINANCIAL_STATEMENT_DOC_TYPE_RE = re.compile(
    r"^(?:1Q|2Q|3Q|FY)FinancialStatements_(?:Consolidated|NonConsolidated)_(?:JP|IFRS|USGAAP)$"
)


def classify_doc_type(doc_type: str | None) -> str:
    if doc_type and FINANCIAL_STATEMENT_DOC_TYPE_RE.match(doc_type):
        return "決算短信"
    if doc_type == "DividendForecastRevision":
        return "配当予想の修正"
    if doc_type == "EarnForecastRevision":
        return "業績予想の修正"
    return "その他"


def group_new_disclosures(summaries: list[dict], last_disc_no) -> list[dict]:
    """前回ロック以降の新規開示を開示日ごとにグループ化し、各日の最優先トリガーを返す(日付昇順)。

    同日に複数開示があれば、決算短信＞配当予想の修正＞業績予想の修正＞その他の優先順位で1件選ぶ
    (「同じ日に複数の開示が出た場合は1回の引き直しにまとめる」仕様に対応)。
    """
    try:
        last_no = int(last_disc_no) if last_disc_no not in (None, "") else -1
    except (TypeError, ValueError):
        last_no = -1

    new_rows = []
    for r in summaries:
        try:
            disc_no = int(r.get("DiscNo") or 0)
        except (TypeError, ValueError):
            continue
        if disc_no > last_no:
            new_rows.append(r)
    if not new_rows:
        return []

    groups: dict[str, list[dict]] = {}
    for r in new_rows:
        groups.setdefault(r.get("DiscDate", ""), []).append(r)

    result = []
    for disc_date in sorted(groups.keys()):
        rows = sorted(
            groups[disc_date],
            key=lambda r: -TRIGGER_PRIORITY.get(classify_doc_type(r.get("DocType")), 0),
        )
        chosen = rows[0]
        result.append({
            "disc_date": disc_date,
            "trigger": classify_doc_type(chosen.get("DocType")),
            "row": chosen,
        })
    return result


def detect_earn_revision_direction(row: dict, summaries: list[dict]) -> str:
    """業績予想の修正開示について、同一対象期間の直前の予想と比べ上方/下方を判定する。"""
    target_period = row.get("CurFYEn") or row.get("CurPerEn")
    new_np = num(row.get("FNP"))
    if new_np is None:
        new_np = num(row.get("FNCNP"))
    if new_np is None or not target_period:
        return "不明"
    this_no = int(row.get("DiscNo") or 0)
    candidates = [
        r for r in summaries
        if (r.get("CurFYEn") or r.get("CurPerEn")) == target_period
        and int(r.get("DiscNo") or 0) < this_no
    ]
    if not candidates:
        return "不明"
    prior = max(candidates, key=lambda r: int(r.get("DiscNo") or 0))
    prior_np = num(prior.get("FNP"))
    if prior_np is None:
        prior_np = num(prior.get("FNCNP"))
    if prior_np is None:
        return "不明"
    if new_np > prior_np:
        return "上方修正"
    if new_np < prior_np:
        return "下方修正"
    return "変更なし"


def _compose_buy3(buy3_yield, step3_price):
    """買い3は「目標利回り③の買付株価」と「第3段階・目標株価」のうち低い方を採用する。"""
    if buy3_yield is None and step3_price is None:
        return None, None
    if buy3_yield is None:
        return step3_price, "目標株価"
    if step3_price is None:
        return buy3_yield, "利回り③"
    if step3_price <= buy3_yield:
        return step3_price, "目標株価"
    return buy3_yield, "利回り③"


def _check_order(buy1, buy2, buy3) -> bool:
    """買い1≥買い2≥買い3になっているか検証する。崩れていればTrue(警告)を返す。"""
    if buy1 is not None and buy2 is not None and buy1 < buy2:
        return True
    if buy2 is not None and buy3 is not None and buy2 < buy3:
        return True
    return False


def _cut_baseline(row: dict, locked: dict, last_ordinary_dividend) -> tuple[float | None, str]:
    """トリガー発生時点で減配判定に使う「直前の予想配当」基準値を決める。

    本決算(FY)の決算短信は予想の対象年度が翌期に切り替わるため、直前の予想値ではなく
    当期の年間配当実績(普通配当ベース)と比較する。それ以外(1Q/2Q/3Q決算短信・配当予想の
    修正)は、直前の確定値を計算した時点の予想配当(forecast_dividend_basis)と比較する。
    """
    cur_per_type = (row.get("CurPerType") or "").upper() if row else ""
    is_fy_result = cur_per_type == "FY" and classify_doc_type(row.get("DocType")) == "決算短信"
    if is_fy_result and last_ordinary_dividend is not None:
        return last_ordinary_dividend, "当期実績(普通配当ベース)"
    return locked.get("forecast_dividend_basis"), "直前の確定値時点の予想配当"


def _finalize_lock(old_locked: dict, new_locked: dict, trigger: str, disc_date: str) -> dict:
    new_locked["order_warning"] = _check_order(
        new_locked.get("buy1"), new_locked.get("buy2"), new_locked.get("buy3")
    )
    entry = {
        "date": disc_date,
        "trigger": trigger,
        "from": {"buy1": old_locked.get("buy1"), "buy2": old_locked.get("buy2"), "buy3": old_locked.get("buy3")},
        "to": {"buy1": new_locked.get("buy1"), "buy2": new_locked.get("buy2"), "buy3": new_locked.get("buy3")},
    }
    new_locked["history"] = (list(old_locked.get("history") or []) + [entry])[-10:]
    return new_locked


def update_locked_targets(
    prev_stock: dict,
    code: str,
    industry: str | None,
    summaries: list[dict],
    eps_hist: list[float],
    div_hist: list[float],
    forecast_dividend,
    step3: dict,
    target_yield: dict,
    today_str: str,
    dividend_override_active: bool,
    last_ordinary_dividend,
) -> dict | None:
    """分割買いラインの確定値を、前回ロック以降の新規開示に応じて引き直す。

    減配の判定は開示の種類(DocType)ではなく、予想配当(普通配当ベース)の数字そのものを
    比較して行う。決算短信・配当予想の修正のどちらでも、新しい予想配当が直前の確定値
    時点の予想配当を下回っていれば減配として扱う(同日に決算短信が優先されるケースや、
    本決算の中だけで翌期予想が下がるケースも取りこぼさないため)。本決算(FY)で予想の
    対象年度が翌期に切り替わる場合は、直前の予想値ではなく当期の年間配当実績(普通配当
    ベース)と比較する。

    トリガー種別ごとの扱い(減配でない場合):
      決算短信(1Q/2Q/3Q/FY): ①②③の％・買付株価・第3段階目標株価すべて引き直す
      配当予想の修正(増配等): ％は据え置き、新しい予想配当(普通配当ベース)で買付株価だけ再計算
      業績予想の修正        : 買いラインの計算に予想EPSを使っていないため記録のみ(ライン不変)
      その他(訂正等)        : 記録のみ
    """
    existing = prev_stock.get("locked_targets")
    if not existing:
        buy3, buy3_source = _compose_buy3(target_yield.get("buy3_price"), step3.get("target_price"))
        buy1, buy2 = target_yield.get("buy1_price"), target_yield.get("buy2_price")
        if buy1 is None and buy2 is None and buy3 is None:
            return None
        last_disc_no = max((int(r.get("DiscNo") or 0) for r in summaries), default=None)
        return {
            "buy1": buy1,
            "buy2": buy2,
            "buy3": buy3,
            "target1_pct": target_yield.get("target1_pct"),
            "target2_pct": target_yield.get("target2_pct"),
            "target3_pct": target_yield.get("target3_pct"),
            "buy3_source": buy3_source,
            "forecast_dividend_basis": forecast_dividend,
            "basis_date": today_str,
            "reason": "初期設定",
            "disabled": False,
            "disabled_reason": None,
            "order_warning": _check_order(buy1, buy2, buy3),
            "last_disc_no": last_disc_no,
            "history": [],
        }

    locked = dict(existing)
    # Step1・Step2導入時点で登録済みの確定値には％・予想配当基準値が保存されていないため、
    # 現在の参考値で一度だけ補完する(新規開示によって引き直されたわけではないのでセマン
    # ティクスの変化はない)。
    if locked.get("target1_pct") is None:
        locked["target1_pct"] = target_yield.get("target1_pct")
        locked["target2_pct"] = target_yield.get("target2_pct")
        locked["target3_pct"] = target_yield.get("target3_pct")
    if locked.get("forecast_dividend_basis") is None:
        locked["forecast_dividend_basis"] = prev_stock.get("forecast_dividend")

    groups = group_new_disclosures(summaries, locked.get("last_disc_no"))
    override_note = "(普通配当ベース・手動補正あり)" if dividend_override_active else ""

    for group in groups:
        trigger, disc_date, row = group["trigger"], group["disc_date"], group["row"]

        # 予想配当が取得できていない日は、買付株価をnullで上書きして既存の確定値を
        # 壊してしまわないよう、全ライン引き直し・配当予想修正の処理自体をスキップする
        # (Yahoo!ファイナンス等の一時的な欠損を確定値に取り込まないための安全策)。
        if trigger in ("決算短信", "配当予想の修正") and forecast_dividend is None:
            new_locked = dict(locked)
            new_locked["history"] = (list(locked.get("history") or []) + [{
                "date": disc_date, "trigger": trigger,
                "note": "予想配当が取得できなかったため、この開示の引き直しはスキップ(確定値は現状維持)",
            }])[-10:]
            locked = new_locked
            continue

        if trigger in ("決算短信", "配当予想の修正"):
            # 減配判定は開示の種類ではなく予想配当(普通配当ベース)の数字そのもので行う。
            # 決算短信と配当予想の修正が同日に重なって決算短信が優先された場合や、
            # 決算短信の中だけで翌期予想が下がる場合も、ここで一律に検知する。
            baseline, baseline_label = _cut_baseline(row, locked, last_ordinary_dividend)
            is_cut = baseline is not None and forecast_dividend is not None and forecast_dividend < baseline
            if is_cut:
                new_locked = dict(locked)
                new_locked["disabled_reason"] = (
                    f"減配を検知({baseline_label} {baseline}円→予想{forecast_dividend}円、"
                    f"{disc_date}開示・{trigger}){override_note}によりStep1・Step2から再審査が必要"
                )
                new_locked["disabled"] = True
                new_locked["reason"] = new_locked["disabled_reason"]
                new_locked["basis_date"] = disc_date
                new_locked["forecast_dividend_basis"] = forecast_dividend
                locked = _finalize_lock(locked, new_locked, trigger, disc_date)
                continue

        if trigger == "決算短信":
            try:
                targets = calculate_targets(code, industry, eps_hist, div_hist)
                buy1 = purchase_price(forecast_dividend, targets.target1)
                buy2 = purchase_price(forecast_dividend, targets.target2)
                buy3_yield = purchase_price(forecast_dividend, targets.target3)
            except Exception:  # noqa: BLE001
                continue
            buy3, buy3_source = _compose_buy3(buy3_yield, step3.get("target_price"))
            new_locked = dict(locked)
            new_locked.update({
                "buy1": buy1, "buy2": buy2, "buy3": buy3,
                "target1_pct": targets.target1, "target2_pct": targets.target2, "target3_pct": targets.target3,
                "buy3_source": buy3_source,
                "forecast_dividend_basis": forecast_dividend,
                "basis_date": disc_date,
                "reason": "決算短信取り込みによる引き直し",
                # disabled/disabled_reasonはここでは触らない(=既存の状態を維持する)。
                # 減配を検知して無効化された確定値は、別の開示がdisabledでないからといって
                # 自動で再有効化してはならず、Step1・Step2の再審査後に手動で解除する想定。
            })
            locked = _finalize_lock(locked, new_locked, trigger, disc_date)

        elif trigger == "配当予想の修正":
            t1, t2, t3 = locked.get("target1_pct"), locked.get("target2_pct"), locked.get("target3_pct")
            buy1 = purchase_price(forecast_dividend, t1)
            buy2 = purchase_price(forecast_dividend, t2)
            buy3_yield = purchase_price(forecast_dividend, t3)
            buy3, buy3_source = _compose_buy3(buy3_yield, step3.get("target_price"))
            new_locked = dict(locked)
            new_locked.update({
                "buy1": buy1, "buy2": buy2, "buy3": buy3,
                "buy3_source": buy3_source,
                "forecast_dividend_basis": forecast_dividend,
                "basis_date": disc_date,
                "reason": f"配当予想の修正(予想配当{forecast_dividend}円){override_note}による買付株価の再計算",
                # disabled/disabled_reasonはここでは触らない(決算短信と同様、既存の状態を維持)。
            })
            locked = _finalize_lock(locked, new_locked, trigger, disc_date)

        elif trigger == "業績予想の修正":
            direction = detect_earn_revision_direction(row, summaries)
            new_locked = dict(locked)
            new_locked["history"] = (list(locked.get("history") or []) + [{
                "date": disc_date, "trigger": trigger, "direction": direction,
                "note": "買いラインの計算には予想EPSを使用していないためライン据え置き",
            }])[-10:]
            locked = new_locked

        else:
            new_locked = dict(locked)
            new_locked["history"] = (list(locked.get("history") or []) + [{
                "date": disc_date, "trigger": trigger, "note": "未対応の開示区分のため記録のみ",
            }])[-10:]
            locked = new_locked

    locked["last_disc_no"] = max(
        (int(r.get("DiscNo") or 0) for r in summaries), default=locked.get("last_disc_no")
    )
    return locked


def diff_forecast_changes(
    code: str, new_forecast, previous: dict[str, dict], disclosure_date: str | None = None
) -> list[dict]:
    """前回取得時と予想配当が変わっていれば改定履歴に追記する(直近5件保持)。

    disclosure_dateが分かる場合(EDINET DB経由)はそれを変更日として使い、
    分からない場合は実行日を変更日とする。
    """
    prev_stock = previous.get(code) or {}
    prev_forecast = prev_stock.get("forecast_dividend")
    changes = list(prev_stock.get("forecast_dividend_changes") or [])
    if new_forecast is not None and prev_forecast is not None and new_forecast != prev_forecast:
        changes.append({
            "date": disclosure_date or datetime.now().strftime("%Y-%m-%d"),
            "from": prev_forecast,
            "to": new_forecast,
        })
        changes = changes[-5:]
    return changes


def main() -> None:
    api_key = os.environ.get("JQUANTS_API_KEY", "")
    all_codes = json.loads(CODES_FILE.read_text(encoding="utf-8"))

    requested = sys.argv[1:]
    force_edinet = "--force-edinet" in requested
    requested = [c for c in requested if c != "--force-edinet"]
    if requested:
        unknown = [c for c in requested if c not in all_codes]
        if unknown:
            print(f"codes.jsonに存在しないコードです: {unknown}")
            sys.exit(1)
        target_codes = requested
    else:
        target_codes = all_codes

    client = JQuantsClient(api_key, min_interval_seconds=1.5)
    previous = load_previous_stocks()
    edinet_latest_by_code, edinet_financials_by_code = fetch_recent_edinet_earnings(
        target_codes, force=force_edinet
    )

    fresh: dict[str, dict] = {}
    errors = []
    for i, code in enumerate(target_codes):
        if i > 0:
            time.sleep(2)
        try:
            prev_stock = previous.get(code) or {}
            result = fetch_one(
                client, code, edinet_latest_by_code.get(code), edinet_financials_by_code.get(code),
                prev_stock,
            )
            disclosure_date = result.pop("_edinet_disclosure_date", None)
            result["forecast_dividend_changes"] = diff_forecast_changes(
                code, result.get("forecast_dividend"), previous, disclosure_date
            )
            # 期末PERレンジ・自己資本比率推移は、今回EDINETの有報時系列を再取得できた
            # 銘柄だけ新しい値が入る。再取得していない銘柄は前回値を引き継ぐ。
            if code not in edinet_financials_by_code:
                result["valuation_range"] = prev_stock.get("valuation_range")
                result["equity_ratio_trend"] = prev_stock.get("equity_ratio_trend")
            fresh[code] = result
        except JQuantsError as exc:
            errors.append({"code": code, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            errors.append({"code": code, "error": f"{type(exc).__name__}: {exc}"})

    # codes.jsonの並び順(=追加順)を保った状態で、更新分は新しい値、それ以外は前回値を使う。
    results = [fresh[code] if code in fresh else previous[code] for code in all_codes if code in fresh or code in previous]

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stocks": results,
        "errors": errors,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"取得完了: {len(results)}件（うち今回更新 {len(fresh)}件） / エラー {len(errors)}件 -> {OUTPUT_FILE}")
    if errors:
        for e in errors:
            kept = "（前回値を保持）" if e["code"] in previous else "（データなし）"
            print(f"  - {e['code']}: {e['error']} {kept}")


if __name__ == "__main__":
    main()
