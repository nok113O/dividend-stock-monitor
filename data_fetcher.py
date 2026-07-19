from __future__ import annotations
import re
import time
from typing import Any
import requests
from bs4 import BeautifulSoup
import yfinance as yf

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}

def _float(value: Any, percent: bool = False) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
        if percent and abs(x) <= 1:
            x *= 100
        return x
    except (TypeError, ValueError):
        return None

def fetch_yahoo(code: str) -> dict[str, Any]:
    """yfinance経由でYahoo Finance由来の現在情報を取得。"""
    symbol = f"{code}.T"
    ticker = yf.Ticker(symbol)

    # fast_infoは価格取得が比較的軽い。infoは財務指標用。
    fast = {}
    info = {}
    try:
        fast = dict(ticker.fast_info)
    except Exception:
        fast = {}
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    price = (
        _float(fast.get("last_price"))
        or _float(info.get("currentPrice"))
        or _float(info.get("regularMarketPrice"))
    )
    dividend_rate = _float(info.get("dividendRate"))
    dividend_yield = _float(info.get("dividendYield"), percent=True)

    # dividendYieldが欠ける場合は予想配当÷株価
    if dividend_yield is None and price and dividend_rate is not None:
        dividend_yield = dividend_rate / price * 100

    return {
        "code": code,
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or code,
        "industry": info.get("industry") or info.get("sector") or "",
        "price": price,
        "forecast_dividend": dividend_rate,
        "dividend_yield": dividend_yield,
        "per": _float(info.get("forwardPE")) or _float(info.get("trailingPE")),
        "pbr": _float(info.get("priceToBook")),
        "roe": _float(info.get("returnOnEquity"), percent=True),
        "roa": _float(info.get("returnOnAssets"), percent=True),
        "equity_ratio": None,  # IR BANKで補完
        "market_cap": _float(fast.get("market_cap")) or _float(info.get("marketCap")),
        "yahoo_url": f"https://finance.yahoo.co.jp/quote/{symbol}",
    }

def _get(url: str) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    response.raise_for_status()
    return response

def resolve_irbank_company(code: str) -> tuple[str, str]:
    """
    https://irbank.net/8058 にアクセスし、リダイレクト後のEDINET企業IDを取得。
    戻り値: (企業IDまたはコード, 最終URL)
    """
    response = _get(f"https://irbank.net/{code}")
    match = re.search(r"irbank\.net/(E\d+)", response.url)
    company_id = match.group(1) if match else code
    return company_id, response.url

def _parse_number(text: str) -> float | None:
    text = text.replace(",", "").replace("−", "-").replace("▲", "-")
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*円", text)
    if not m:
        m = re.search(r"(-?\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None

def _extract_series_from_text(text: str, heading: str) -> list[float]:
    """
    IR BANK結果ページのテキストから、指定見出し直後の年次値を抽出。
    次の主要見出しまでを対象にする。ページ変更時は要修正。
    """
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    start = normalized.find(f"\n{heading}\n")
    if start < 0 and normalized.startswith(f"{heading}\n"):
        start = 0
    if start < 0:
        return []

    section = normalized[start + len(heading) + 1:]
    stop_headings = [
        "売上高", "営業利益", "経常利益", "純利益", "包括利益",
        "ROE", "ROA", "BPS", "EPS", "配当", "配当性向",
        "自己資本比率", "営業CF", "投資CF", "財務CF"
    ]
    stops = []
    for h in stop_headings:
        if h == heading:
            continue
        pos = section.find(f"\n{h}\n")
        if 0 <= pos < 12000:
            stops.append(pos)
    if stops:
        section = section[:min(stops)]

    lines = section.splitlines()
    values: list[float] = []
    # 年度行の直後数行にある「xx円」を拾う
    for i, line in enumerate(lines):
        if re.search(r"20\d{2}/\d{2}", line) or re.search(r"20\d{2}年\d{1,2}月", line):
            window = " ".join(lines[i:i+4])
            value = _parse_number(window)
            if value is not None:
                values.append(value)

    # 重複を軽く除去（順序維持）
    cleaned = []
    for v in values:
        if not cleaned or v != cleaned[-1]:
            cleaned.append(v)
    return cleaned

def _find_percent(text: str, labels: list[str]) -> float | None:
    for label in labels:
        patterns = [
            rf"{re.escape(label)}[^\d\-]{{0,40}}(-?\d+(?:\.\d+)?)\s*%",
            rf"{re.escape(label)}.*?\n.*?(-?\d+(?:\.\d+)?)\s*%",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.S)
            if m:
                return float(m.group(1))
    return None

def fetch_irbank(code: str) -> dict[str, Any]:
    company_id, company_url = resolve_irbank_company(code)
    results_url = f"https://irbank.net/{company_id}/results"
    response = _get(results_url)
    soup = BeautifulSoup(response.text, "lxml")
    text = soup.get_text("\n", strip=True)

    eps = _extract_series_from_text(text, "EPS")
    bps = _extract_series_from_text(text, "BPS")

    # 配当見出しは企業により「1株配当」「配当」等の差がある
    dividends = _extract_series_from_text(text, "1株配当")
    if not dividends:
        dividends = _extract_series_from_text(text, "配当")

    equity_ratio = _find_percent(text, ["自己資本比率", "株主資本比率"])
    roa = _find_percent(text, ["ROA"])

    return {
        "company_id": company_id,
        "company_url": company_url,
        "results_url": results_url,
        "eps": eps,
        "bps": bps,
        "dividends": dividends,
        "equity_ratio": equity_ratio,
        "roa": roa,
    }

def fetch_all(code: str) -> dict[str, Any]:
    code = re.sub(r"\D", "", code)
    if len(code) != 4:
        raise ValueError("銘柄コードは4桁で入力してください。")

    yahoo = fetch_yahoo(code)
    irbank_error = None
    try:
        irbank = fetch_irbank(code)
    except Exception as exc:
        irbank = {
            "eps": [], "bps": [], "dividends": [],
            "equity_ratio": None, "roa": None,
            "company_url": f"https://irbank.net/{code}",
            "results_url": f"https://irbank.net/{code}",
        }
        irbank_error = str(exc)

    if yahoo.get("equity_ratio") is None:
        yahoo["equity_ratio"] = irbank.get("equity_ratio")
    if yahoo.get("roa") is None:
        yahoo["roa"] = irbank.get("roa")

    return {
        **yahoo,
        "eps": irbank.get("eps", []),
        "bps": irbank.get("bps", []),
        "dividends": irbank.get("dividends", []),
        "irbank_url": irbank.get("company_url"),
        "irbank_results_url": irbank.get("results_url"),
        "irbank_error": irbank_error,
    }
