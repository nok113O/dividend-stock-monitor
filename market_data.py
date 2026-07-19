
from __future__ import annotations
from typing import Any
import yfinance as yf

class MarketDataError(RuntimeError):
    pass

def current_market_data(code: str) -> dict[str, Any]:
    ticker = yf.Ticker(f"{code}.T")
    price = None
    price_date = None

    try:
        hist = ticker.history(period="10d", auto_adjust=False)
        if hist is not None and not hist.empty:
            valid = hist["Close"].dropna()
            if not valid.empty:
                price = float(valid.iloc[-1])
                price_date = valid.index[-1].strftime("%Y-%m-%d")
    except Exception:
        pass

    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    if price is None:
        for key in ("currentPrice", "regularMarketPrice", "previousClose"):
            value = info.get(key)
            if value is not None:
                price = float(value)
                break

    return {
        "price": price,
        "price_date": price_date,
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "equity_ratio": None,
        "market_cap": info.get("marketCap"),
        "dividend_rate": info.get("dividendRate"),
        "dividend_yield": info.get("dividendYield"),
    }
