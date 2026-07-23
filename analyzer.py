from __future__ import annotations

from typing import Any
import math
import pandas as pd

def num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
        if math.isnan(x):
            return None
        return x
    except (TypeError, ValueError):
        return None

def pct(value: Any) -> float | None:
    x = num(value)
    if x is None:
        return None
    return x * 100 if abs(x) <= 1 else x

def judge_le(value: float | None, limit: float) -> str:
    return "○" if value is not None and value <= limit else ("×" if value is not None else "要確認")

def judge_ge(value: float | None, limit: float) -> str:
    return "○" if value is not None and value >= limit else ("×" if value is not None else "要確認")

def latest_close(bars: list[dict]) -> tuple[float | None, str | None]:
    valid = [r for r in bars if num(r.get("C")) is not None]
    if not valid:
        return None, None
    row = sorted(valid, key=lambda r: r.get("Date", ""))[-1]
    return num(row.get("C")), row.get("Date")

def latest_summary(rows: list[dict]) -> dict:
    if not rows:
        return {}
    # 決算訂正等で古い会計期間がDiscNoの大きい値で再提出されることがあるため、
    # 対象期間(CurPerEn)を優先し、同一期間内の最新提出をDiscDate/DiscNoで選ぶ。
    latest = sorted(
        rows,
        key=lambda r: (r.get("CurPerEn", ""), r.get("DiscDate", ""), r.get("DiscNo", "")),
    )[-1]
    # 業績予想の修正等、貸借対照表項目(自己資本比率・純資産・総資産)を含まない開示が
    # 最新になっている場合、それらの項目だけ直近の実績開示から補う。
    balance_sheet_fields = ("EqAR", "Eq", "TA", "NP")
    if all(not str(latest.get(f, "")).strip() for f in balance_sheet_fields):
        with_financials = [
            r for r in rows if str(r.get("EqAR", "")).strip()
        ]
        if with_financials:
            fallback = sorted(
                with_financials,
                key=lambda r: (r.get("DiscDate", ""), r.get("DiscNo", "")),
            )[-1]
            latest = dict(latest)
            for f in balance_sheet_fields:
                if not str(latest.get(f, "")).strip():
                    latest[f] = fallback.get(f)
    return latest

def latest_fy_summaries(rows: list[dict]) -> list[dict]:
    fy = [r for r in rows if str(r.get("CurPerType", "")).upper() == "FY"]
    by_period: dict[str, dict] = {}
    for row in fy:
        period = row.get("CurFYEn") or row.get("CurPerEn")
        if not period:
            continue
        old = by_period.get(period)
        if old is None or (row.get("DiscDate", ""), row.get("DiscNo", "")) > (
            old.get("DiscDate", ""), old.get("DiscNo", "")
        ):
            by_period[period] = row
    return [by_period[k] for k in sorted(by_period)]

def select_forecast_dividend(row: dict) -> float | None:
    for key in ("NxFDivAnn", "FDivAnn", "DivAnn"):
        value = num(row.get(key))
        if value is not None:
            return value
    return None

def select_forecast_eps(row: dict) -> float | None:
    for key in ("NxFEPS", "FEPS", "EPS"):
        value = num(row.get(key))
        if value is not None:
            return value
    return None

def step1_metrics(price: float | None, latest: dict) -> dict[str, float | None]:
    bps = num(latest.get("BPS"))
    eps_forecast = select_forecast_eps(latest)
    dividend = select_forecast_dividend(latest)
    np_value = num(latest.get("NP"))
    equity = num(latest.get("Eq"))
    assets = num(latest.get("TA"))
    eq_ratio = pct(latest.get("EqAR"))
    shares = num(latest.get("ShOutFY"))
    treasury = num(latest.get("TrShFY"))

    market_cap = None
    if price is not None and shares is not None:
        market_cap = price * max(shares - (treasury or 0), 0)

    return {
        "PER": price / eps_forecast if price is not None and eps_forecast and eps_forecast > 0 else None,
        "PBR": price / bps if price is not None and bps and bps > 0 else None,
        "ROE": np_value / equity * 100 if np_value is not None and equity and equity > 0 else None,
        "ROA": np_value / assets * 100 if np_value is not None and assets and assets > 0 else None,
        "配当利回り": dividend / price * 100 if price and dividend is not None else None,
        "自己資本比率": eq_ratio,
        "時価総額（億円）": market_cap / 100_000_000 if market_cap is not None else None,
        "予想年間配当": dividend,
        "予想EPS": eps_forecast,
        "最新BPS": bps,
    }

def analyze_step1(metrics: dict, sector: str | None = None) -> dict:
    from sector_master import step1_thresholds
    overrides = step1_thresholds(sector)
    roa_limit = overrides.get("ROA", 3)
    eq_ratio_limit = overrides.get("自己資本比率", 35)

    rows = {
        "PER": {"value": metrics.get("PER"), "criterion": "12倍以下", "judge": judge_le(metrics.get("PER"), 12)},
        "PBR": {"value": metrics.get("PBR"), "criterion": "1.3倍以下", "judge": judge_le(metrics.get("PBR"), 1.3)},
        "ROE": {"value": metrics.get("ROE"), "criterion": "7%以上", "judge": judge_ge(metrics.get("ROE"), 7)},
        "ROA": {"value": metrics.get("ROA"), "criterion": f"{roa_limit:g}%以上", "judge": judge_ge(metrics.get("ROA"), roa_limit)},
        "配当利回り": {"value": metrics.get("配当利回り"), "criterion": "3%以上", "judge": judge_ge(metrics.get("配当利回り"), 3)},
        "自己資本比率": {"value": metrics.get("自己資本比率"), "criterion": f"{eq_ratio_limit:g}%以上", "judge": judge_ge(metrics.get("自己資本比率"), eq_ratio_limit)},
        "時価総額": {"value": metrics.get("時価総額（億円）"), "criterion": "100億円以上", "judge": judge_ge(metrics.get("時価総額（億円）"), 100)},
    }
    judges = [r["judge"] for r in rows.values()]
    overall = "○" if all(j == "○" for j in judges) else ("要確認" if "要確認" in judges else "×")
    return {"rows": rows, "overall": overall, "sector_adjusted": bool(overrides)}

def normalize_history(history: pd.DataFrame, code: str) -> pd.DataFrame:
    cols = ["コード", "決算期", "EPS", "BPS", "1株配当", "データ元", "更新日"]
    if history is None or history.empty:
        return pd.DataFrame(columns=cols)
    df = history.copy()
    for col in cols:
        if col not in df.columns:
            df[col] = None
    df["コード"] = df["コード"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    df = df[df["コード"] == str(code).zfill(4)].copy()
    df["決算期"] = pd.to_datetime(df["決算期"], errors="coerce")
    for col in ("EPS", "BPS", "1株配当"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["決算期"]).sort_values("決算期")

def merge_new_fy(history: pd.DataFrame, code: str, summaries: list[dict], updated_at: str) -> pd.DataFrame:
    all_history = history.copy()
    if all_history.empty:
        all_history = pd.DataFrame(columns=["コード", "決算期", "EPS", "BPS", "1株配当", "データ元", "更新日"])

    new_rows = []
    for row in latest_fy_summaries(summaries):
        period = row.get("CurFYEn") or row.get("CurPerEn")
        eps = num(row.get("EPS"))
        bps = num(row.get("BPS"))
        dividend = num(row.get("DivAnn"))
        if not period or (eps is None and bps is None and dividend is None):
            continue
        new_rows.append({
            "コード": str(code).zfill(4),
            "決算期": period,
            "EPS": eps,
            "BPS": bps,
            "1株配当": dividend,
            "データ元": "J-Quants",
            "更新日": updated_at,
        })

    if new_rows:
        all_history = pd.concat([all_history, pd.DataFrame(new_rows)], ignore_index=True)

    all_history["コード"] = all_history["コード"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    all_history["決算期"] = pd.to_datetime(all_history["決算期"], errors="coerce")
    all_history = all_history.dropna(subset=["決算期"])
    all_history = (
        all_history.sort_values(["コード", "決算期", "更新日"])
        .drop_duplicates(["コード", "決算期"], keep="last")
    )

    # 各銘柄の最新10期だけ維持
    all_history = (
        all_history.sort_values(["コード", "決算期"])
        .groupby("コード", group_keys=False)
        .tail(10)
        .reset_index(drop=True)
    )
    return all_history

def analyze_step2(history: pd.DataFrame, code: str) -> dict:
    df = normalize_history(history, code).tail(10)
    result = {}

    if len(df) < 10:
        for name in (
            "EPS10期赤字なし",
            "今期EPSが9期前の2倍以上",
            "BPS10期連続増加",
            "10期で減配2回未満",
            "10期で無配なし",
        ):
            result[name] = {"judge": "要確認", "detail": f"{len(df)}期分"}
        return {"rows": result, "overall": "要確認", "history": df}

    eps = df["EPS"].tolist()
    bps = df["BPS"].tolist()
    divs = df["1株配当"].tolist()

    result["EPS10期赤字なし"] = {
        "judge": "○" if all(pd.notna(x) and x >= 0 for x in eps) else "×",
        "detail": f"赤字 {sum(pd.notna(x) and x < 0 for x in eps)}期",
    }
    if pd.notna(eps[0]) and eps[0] > 0 and pd.notna(eps[-1]):
        ratio = eps[-1] / eps[0]
        result["今期EPSが9期前の2倍以上"] = {
            "judge": "○" if ratio >= 2 else "×",
            "detail": f"{ratio:.2f}倍",
        }
    else:
        result["今期EPSが9期前の2倍以上"] = {"judge": "要確認", "detail": "比較不可"}

    bps_failures = sum(
        pd.isna(bps[i]) or pd.isna(bps[i-1]) or bps[i] <= bps[i-1]
        for i in range(1, 10)
    )
    result["BPS10期連続増加"] = {
        "judge": "○" if bps_failures == 0 else "×",
        "detail": f"減少・欠損 {bps_failures}回",
    }

    decreases = sum(
        pd.notna(divs[i]) and pd.notna(divs[i-1]) and divs[i] < divs[i-1]
        for i in range(1, 10)
    )
    zero_count = sum(pd.isna(x) or x <= 0 for x in divs)
    result["10期で減配2回未満"] = {
        "judge": "○" if decreases < 2 else "×",
        "detail": f"減配 {decreases}回",
    }
    result["10期で無配なし"] = {
        "judge": "○" if zero_count == 0 else "×",
        "detail": f"無配・欠損 {zero_count}期",
    }

    judges = [r["judge"] for r in result.values()]
    overall = "○" if all(j == "○" for j in judges) else ("要確認" if "要確認" in judges else "×")
    return {"rows": result, "overall": overall, "history": df}

def calculate_step3(history: pd.DataFrame, code: str) -> dict:
    df = normalize_history(history, code).tail(10)
    if len(df) < 10 or df["EPS"].isna().any() or pd.isna(df.iloc[-1]["BPS"]):
        return {"eps_sum": None, "latest_bps": None, "target_price": None}
    eps_sum = float(df["EPS"].sum())
    latest_bps = float(df.iloc[-1]["BPS"])
    return {
        "eps_sum": round(eps_sum, 2),
        "latest_bps": round(latest_bps, 2),
        "target_price": round(eps_sum + latest_bps, 2),
    }

def make_comment(step1: dict, step2: dict) -> str:
    notes = []
    for name, row in step1["rows"].items():
        if row["judge"] == "×":
            notes.append(f"{name}は基準未達。")
        elif row["judge"] == "要確認":
            notes.append(f"{name}は取得できず要確認。")
    for name, row in step2["rows"].items():
        if row["judge"] == "×":
            if "減配" in name or "無配" in name:
                notes.append(f"{name}は高配当株として重要な懸念。")
            elif "EPS" in name:
                notes.append(f"{name}は一過性か構造的か確認。")
            elif "BPS" in name:
                notes.append(f"{name}は自社株買い等の影響も確認。")
        elif row["judge"] == "要確認":
            notes.append(f"{name}は初期10期データの補完が必要。")
    return " ".join(notes[:5]) if notes else "全項目で基準を満たしています。"

def overall_rating(step1: dict, step2: dict) -> str:
    if step1["overall"] == "○" and step2["overall"] == "○":
        return "監視継続"
    severe = [
        name for name, row in step2["rows"].items()
        if row["judge"] == "×" and ("無配" in name or "減配" in name or "赤字" in name)
    ]
    return "除外候補" if severe else "条件付き監視"

def buy_zone(price: float | None, targets: list[float | None]) -> str:
    if price is None:
        return "要確認"
    p1, p2, p3 = (targets + [None, None, None])[:3]
    if p3 and price <= p3:
        return "第3買い到達"
    if p2 and price <= p2:
        return "第2買い到達"
    if p1 and price <= p1:
        return "第1買い到達"
    if p1 and price <= p1 * 1.03:
        return "第1買い接近"
    return "待機" if p1 else "買いライン未入力"
