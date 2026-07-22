from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any
import requests

class MarketDataError(RuntimeError):
    pass

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_JST = timezone(timedelta(hours=9))

_session: requests.Session | None = None
_crumb: str | None = None

def _session_and_crumb(refresh: bool = False) -> tuple[requests.Session, str]:
    global _session, _crumb
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": _UA})
        _session.get("https://fc.yahoo.com", timeout=15)
    if _crumb is None or refresh:
        resp = _session.get(
            "https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=15
        )
        resp.raise_for_status()
        _crumb = resp.text.strip()
    return _session, _crumb

def _raw(block: dict, key: str) -> Any:
    value = block.get(key)
    return value.get("raw") if isinstance(value, dict) else value

def _empty_result() -> dict[str, Any]:
    return {
        "price": None,
        "price_date": None,
        "change": None,
        "change_pct": None,
        "trailing_pe": None,
        "price_to_book": None,
        "roe": None,
        "roa": None,
        "equity_ratio": None,
        "market_cap": None,
        "dividend_rate": None,
        "dividend_yield": None,
    }

def current_market_data(code: str) -> dict[str, Any]:
    """Yahoo! FinanceのquoteSummaryを直接呼び出して現在値を取得する。

    yfinanceパッケージ(curl_cffiでブラウザTLSを偽装する)はTLSを再終端する
    プロキシ環境下で接続が切れることがあるため、素のrequestsで
    cookie/crumb認証フローを踏んで同じエンドポイントを呼び出している。
    """
    result = _empty_result()
    symbol = f"{code}.T"

    for attempt in range(2):
        try:
            session, crumb = _session_and_crumb(refresh=(attempt == 1))
            resp = session.get(
                f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
                params={
                    "modules": "summaryDetail,defaultKeyStatistics,financialData,price",
                    "crumb": crumb,
                },
                timeout=15,
            )
            if resp.status_code == 401 and attempt == 0:
                continue
            resp.raise_for_status()
            payload = resp.json().get("quoteSummary", {}).get("result") or []
            if not payload:
                return result
            data = payload[0]
            summary = data.get("summaryDetail", {})
            stats = data.get("defaultKeyStatistics", {})
            financial = data.get("financialData", {})
            price_block = data.get("price", {})

            price = _raw(financial, "currentPrice") or _raw(price_block, "regularMarketPrice")
            market_time = _raw(price_block, "regularMarketTime")
            price_date = (
                datetime.fromtimestamp(market_time, tz=_JST).strftime("%Y-%m-%d %H:%M")
                if market_time
                else None
            )

            result.update({
                "price": float(price) if price is not None else None,
                "price_date": price_date,
                "change": _raw(price_block, "regularMarketChange"),
                "change_pct": _raw(price_block, "regularMarketChangePercent"),
                "trailing_pe": _raw(summary, "trailingPE"),
                "price_to_book": _raw(stats, "priceToBook"),
                "roe": _raw(financial, "returnOnEquity"),
                "roa": _raw(financial, "returnOnAssets"),
                "market_cap": _raw(summary, "marketCap"),
                "dividend_rate": _raw(summary, "dividendRate"),
                "dividend_yield": _raw(summary, "dividendYield"),
            })
            return result
        except requests.RequestException:
            if attempt == 1:
                return result
    return result
