from __future__ import annotations
import re
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
    symbol = f"{code}.T"
    ticker = yf.Ticker(symbol)
    errors = []

    try:
        fast = dict(ticker.fast_info)
    except Exception as exc:
        fast = {}
        errors.append(f"fast_info: {exc}")

    try:
        info = ticker.info or {}
    except Exception as exc:
        info = {}
        errors.append(f"info: {exc}")

    price = (
        _float(fast.get("last_price"))
        or _float(info.get("currentPrice"))
        or _float(info.get("regularMarketPrice"))
        or _float(info.get("previousClose"))
    )
    dividend_rate = _float(info.get("dividendRate"))
    dividend_yield = _float(info.get("dividendYield"), percent=True)
    if dividend_yield is None and price and dividend_rate is not None:
        dividend_yield = dividend_rate / price * 100

    name = info.get("longName") or info.get("shortName") or code
    industry = info.get("industry") or info.get("sector") or ""

    # 自己資本比率：totalStockholderEquity / totalAssets を取得できる場合のみ計算
    equity_ratio = None
    try:
        bs = ticker.quarterly_balance_sheet
        if not bs.empty and len(bs.columns):
            col = bs.columns[0]
            assets = None
            equity = None
            for key in ("Total Assets",):
                if key in bs.index:
                    assets = _float(bs.loc[key, col])
            for key in ("Stockholders Equity", "Total Equity Gross Minority Interest"):
                if key in bs.index:
                    equity = _float(bs.loc[key, col])
                    if equity is not None:
                        break
            if assets and equity is not None:
                equity_ratio = equity / assets * 100
    except Exception as exc:
        errors.append(f"balance_sheet: {exc}")

    ok = bool(price or info)
    return {
        "code": code,
        "symbol": symbol,
        "name": name,
        "industry": industry,
        "price": price,
        "forecast_dividend": dividend_rate,
        "dividend_yield": dividend_yield,
        "per": _float(info.get("forwardPE")) or _float(info.get("trailingPE")),
        "pbr": _float(info.get("priceToBook")),
        "roe": _float(info.get("returnOnEquity"), percent=True),
        "roa": _float(info.get("returnOnAssets"), percent=True),
        "equity_ratio": equity_ratio,
        "market_cap": _float(fast.get("market_cap")) or _float(info.get("marketCap")),
        "yahoo_url": f"https://finance.yahoo.co.jp/quote/{symbol}",
        "yahoo_status": "取得成功" if ok else "取得失敗",
        "yahoo_error": " / ".join(errors) if errors else None,
    }

def _get(url: str) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    response.raise_for_status()
    return response

def resolve_irbank_company(code: str) -> tuple[str, str]:
    response = _get(f"https://irbank.net/{code}")
    match = re.search(r"irbank\.net/(E\d+)", response.url)
    company_id = match.group(1) if match else code
    return company_id, response.url

def _number(text: str) -> float | None:
    text = text.replace(",", "").replace("−", "-").replace("▲", "-").replace("△", "-")
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*円", text)
    return float(m.group(1)) if m else None

def _extract_series(text: str, heading_candidates: list[str]) -> list[float]:
    """
    IR BANKの決算まとめ本文から年次系列を取得。
    年度表記と円表記が近接する構造を利用し、古い期→新しい期で返す。
    """
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    headings = {
        "EPS", "BPS", "1株配当", "配当", "配当性向", "ROE", "ROA",
        "売上高", "営業利益", "経常利益", "純利益", "自己資本比率",
        "営業CF", "投資CF", "財務CF"
    }
    start = None
    selected = None
    for i, line in enumerate(lines):
        if line in heading_candidates:
            start = i + 1
            selected = line
            break
    if start is None:
        return []

    values = []
    i = start
    while i < len(lines):
        line = lines[i]
        if line in headings and line != selected:
            break
        if re.search(r"20\d{2}/\d{2}", line) or re.search(r"20\d{2}年\d{1,2}月", line):
            window = " ".join(lines[i:min(i + 5, len(lines))])
            value = _number(window)
            if value is not None:
                values.append(value)
        i += 1

    # 連続重複だけ除去
    clean = []
    for value in values:
        if not clean or value != clean[-1]:
            clean.append(value)
    return clean

def _find_latest_percent(text: str, labels: list[str]) -> float | None:
    for label in labels:
        # ラベル後の比較的近い位置にある最後の%値を優先
        pos = text.find(label)
        if pos >= 0:
            chunk = text[pos:pos + 5000]
            vals = re.findall(r"(-?\d+(?:\.\d+)?)\s*%", chunk)
            if vals:
                return float(vals[-1])
    return None

def fetch_irbank(code: str) -> dict[str, Any]:
    company_id, company_url = resolve_irbank_company(code)
    results_url = f"https://irbank.net/{company_id}/results"
    response = _get(results_url)
    soup = BeautifulSoup(response.text, "lxml")
    text = soup.get_text("\n", strip=True)

    eps = _extract_series(text, ["EPS"])
    bps = _extract_series(text, ["BPS"])
    dividends = _extract_series(text, ["1株配当", "配当"])
    equity_ratio = _find_latest_percent(text, ["自己資本比率", "株主資本比率"])
    roa = _find_latest_percent(text, ["ROA"])

    enough = len(eps) >= 10 and len(bps) >= 10 and len(dividends) >= 10
    return {
        "company_id": company_id,
        "company_url": company_url,
        "results_url": results_url,
        "eps": eps,
        "bps": bps,
        "dividends": dividends,
        "equity_ratio": equity_ratio,
        "roa": roa,
        "irbank_status": "取得成功（10期以上）" if enough else "一部取得",
        "irbank_error": None,
    }

def fetch_all(code: str) -> dict[str, Any]:
    code = re.sub(r"\D", "", code)
    if len(code) != 4:
        raise ValueError("銘柄コードは4桁で入力してください。")

    yahoo = fetch_yahoo(code)
    try:
        irbank = fetch_irbank(code)
    except Exception as exc:
        irbank = {
            "eps": [], "bps": [], "dividends": [],
            "equity_ratio": None, "roa": None,
            "company_url": f"https://irbank.net/{code}",
            "results_url": f"https://irbank.net/{code}",
            "irbank_status": "取得失敗",
            "irbank_error": str(exc),
        }

    # Step1のROA・自己資本比率はIR BANKを優先し、無い場合だけYahoo側を利用
    if irbank.get("equity_ratio") is not None:
        yahoo["equity_ratio"] = irbank["equity_ratio"]
    if irbank.get("roa") is not None:
        yahoo["roa"] = irbank["roa"]

    return {
        **yahoo,
        "eps": irbank.get("eps", []),
        "bps": irbank.get("bps", []),
        "dividends": irbank.get("dividends", []),
        "irbank_url": irbank.get("company_url"),
        "irbank_results_url": irbank.get("results_url"),
        "irbank_status": irbank.get("irbank_status"),
        "irbank_error": irbank.get("irbank_error"),
    }
