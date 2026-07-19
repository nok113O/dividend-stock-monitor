from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
import numpy as np
import pandas as pd
import yfinance as yf

@dataclass
class YieldTargets:
    cycle_class: str
    reason: str
    target1: float
    target2: float
    target3: float
    sample_daily: int
    sample_annual: int

CYCLICAL_INDUSTRIES = {
    "鉱業", "石油・石炭製品", "鉄鋼", "非鉄金属", "海運業", "空運業",
    "機械", "電気機器", "輸送用機器", "化学", "ガラス・土石製品",
    "建設業", "卸売業", "銀行業", "証券、商品先物取引業", "保険業",
    "その他金融業", "不動産業", "陸運業", "倉庫・運輸関連業",
}

DEFENSIVE_INDUSTRIES = {
    "食料品", "医薬品", "電気・ガス業", "情報・通信業", "小売業",
    "水産・農林業",
}

def _safe_float(value: Any) -> float | None:
    try:
        x = float(value)
        return None if pd.isna(x) else x
    except Exception:
        return None

def _normalize_dividends(dividends: pd.Series) -> pd.Series:
    if dividends is None or len(dividends) == 0:
        return pd.Series(dtype=float)
    s = dividends.copy()
    idx = pd.to_datetime(s.index)
    try:
        idx = idx.tz_localize(None)
    except TypeError:
        try:
            idx = idx.tz_convert(None)
        except Exception:
            pass
    s.index = idx
    return pd.to_numeric(s, errors="coerce").dropna().sort_index()

def _normalize_close(history: pd.DataFrame) -> pd.Series:
    if history is None or history.empty or "Close" not in history.columns:
        return pd.Series(dtype=float)
    s = pd.to_numeric(history["Close"], errors="coerce").dropna().copy()
    idx = pd.to_datetime(s.index)
    try:
        idx = idx.tz_localize(None)
    except TypeError:
        try:
            idx = idx.tz_convert(None)
        except Exception:
            pass
    s.index = idx
    return s.sort_index()

def build_daily_yields(close: pd.Series, dividends: pd.Series, years: int = 3) -> pd.Series:
    if close.empty or dividends.empty:
        return pd.Series(dtype=float)

    end = close.index.max()
    start = end - pd.DateOffset(years=years)
    close3 = close[close.index >= start]
    if close3.empty:
        return pd.Series(dtype=float)

    values = []
    for dt, px in close3.items():
        if px is None or px <= 0:
            continue
        ttm_start = dt - pd.Timedelta(days=365)
        ttm_div = dividends[(dividends.index > ttm_start) & (dividends.index <= dt)].sum()
        if ttm_div > 0:
            values.append(float(ttm_div / px * 100))
    return pd.Series(values, dtype=float)

def build_annual_yields(close: pd.Series, dividends: pd.Series, years: int = 10) -> pd.Series:
    if close.empty or dividends.empty:
        return pd.Series(dtype=float)

    end_year = int(close.index.max().year)
    start_year = end_year - years + 1
    rows = []
    for year in range(start_year, end_year + 1):
        yearly_close = close[close.index.year == year]
        if yearly_close.empty:
            continue
        year_end_close = float(yearly_close.iloc[-1])
        annual_div = float(dividends[dividends.index.year == year].sum())
        if year_end_close > 0 and annual_div > 0:
            rows.append(annual_div / year_end_close * 100)
    return pd.Series(rows, dtype=float)

def judge_cycle(
    industry: str | None,
    eps_history: list[float] | None,
    dividend_history: list[float] | None,
) -> tuple[str, str]:
    industry = (industry or "").strip()
    eps = pd.Series(eps_history or [], dtype=float).dropna()
    divs = pd.Series(dividend_history or [], dtype=float).dropna()

    reasons = []
    cyclical_score = 0
    defensive_score = 0

    if industry in CYCLICAL_INDUSTRIES:
        cyclical_score += 3
        reasons.append(f"業種：{industry}")
    elif industry in DEFENSIVE_INDUSTRIES:
        defensive_score += 3
        reasons.append(f"業種：{industry}")
    elif industry:
        reasons.append(f"業種：{industry}")

    if len(eps) >= 5:
        mean_abs = abs(float(eps.mean()))
        cv = float(eps.std(ddof=0) / mean_abs) if mean_abs > 0 else 9.99
        loss_years = int((eps < 0).sum())
        if cv >= 0.8:
            cyclical_score += 2
            reasons.append("利益変動大")
        elif cv <= 0.35:
            defensive_score += 1
            reasons.append("利益比較的安定")
        if loss_years > 0:
            cyclical_score += 2
            reasons.append(f"赤字{loss_years}期")

    if len(divs) >= 5:
        changes = divs.diff().dropna()
        cuts = int((changes < 0).sum())
        growth_ratio = float((changes >= 0).mean()) if len(changes) else 0
        div_cv = float(divs.std(ddof=0) / abs(divs.mean())) if abs(divs.mean()) > 0 else 0
        if cuts >= 2 or div_cv >= 0.45:
            cyclical_score += 2
            reasons.append("配当変動大")
        elif cuts == 0 and growth_ratio >= 0.8:
            defensive_score += 2
            reasons.append("減配なし・増配基調")
        elif cuts == 1:
            reasons.append("減配1回")

    cycle_class = "景気敏感株" if cyclical_score >= defensive_score else "非景気敏感株"
    return cycle_class, "・".join(reasons) if reasons else "業種・利益・配当履歴から判定"

def calculate_targets(
    code: str,
    industry: str | None,
    eps_history: list[float] | None = None,
    dividend_history: list[float] | None = None,
) -> YieldTargets:
    ticker = yf.Ticker(f"{code}.T")
    history = ticker.history(period="10y", auto_adjust=False, actions=False)
    close = _normalize_close(history)
    dividends = _normalize_dividends(ticker.dividends)

    daily = build_daily_yields(close, dividends, years=3)
    annual = build_annual_yields(close, dividends, years=10)
    combined = pd.concat([daily, annual], ignore_index=True).dropna()

    if len(combined) < 20:
        raise RuntimeError(
            f"利回りデータが不足しています（日次{len(daily)}件・年次{len(annual)}件）。"
        )

    cycle_class, reason = judge_cycle(industry, eps_history, dividend_history)
    percentiles = (85.0, 92.5, 97.5) if cycle_class == "景気敏感株" else (75.0, 85.0, 95.0)
    q1, q2, q3 = [float(np.percentile(combined.to_numpy(), p)) for p in percentiles]

    return YieldTargets(
        cycle_class=cycle_class,
        reason=reason,
        target1=round(q1, 2),
        target2=round(q2, 2),
        target3=round(q3, 2),
        sample_daily=int(len(daily)),
        sample_annual=int(len(annual)),
    )

def purchase_price(forecast_dividend: float | None, target_yield_pct: float | None) -> float | None:
    if forecast_dividend is None or target_yield_pct is None or target_yield_pct <= 0:
        return None
    return round(float(forecast_dividend) / (float(target_yield_pct) / 100.0))

def status(
    current_price: float | None,
    buy1: float | None,
    buy2: float | None,
    buy3: float | None,
) -> str:
    if current_price is None:
        return "要確認"
    if buy3 is not None and current_price <= buy3:
        return "第3買い（本格購入）"
    if buy2 is not None and current_price <= buy2:
        return "第2買い（追加買い）"
    if buy1 is not None and current_price <= buy1:
        return "第1買い（打診買い）"
    return "監視"
