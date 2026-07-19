from __future__ import annotations

import json
import re
import time
from io import StringIO
from dataclasses import dataclass
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup
import pandas as pd
import yfinance as yf


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

REQUEST_TIMEOUT = 30
REQUEST_INTERVAL_SECONDS = 0.8


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


def _clean_code(code: str) -> str:
    code = re.sub(r"\D", "", str(code))
    if len(code) != 4:
        raise ValueError("銘柄コードは4桁で入力してください。")
    return code


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def _get(session: requests.Session, url: str, accept_json: bool = False) -> requests.Response:
    headers = {"Accept": "application/json,text/plain,*/*"} if accept_json else None
    response = session.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def fetch_yahoo(code: str) -> dict[str, Any]:
    """Yahoo Finance由来の現在値をyfinance経由で取得する。"""
    symbol = f"{code}.T"
    ticker = yf.Ticker(symbol)
    errors: list[str] = []

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

    equity_ratio = None
    try:
        bs = ticker.quarterly_balance_sheet
        if not bs.empty and len(bs.columns):
            col = bs.columns[0]
            assets = _float(bs.loc["Total Assets", col]) if "Total Assets" in bs.index else None
            equity = None
            for key in ("Stockholders Equity", "Total Equity Gross Minority Interest"):
                if key in bs.index:
                    equity = _float(bs.loc[key, col])
                    if equity is not None:
                        break
            if assets and equity is not None:
                equity_ratio = equity / assets * 100
    except Exception as exc:
        errors.append(f"balance_sheet: {exc}")

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
        "equity_ratio": equity_ratio,
        "market_cap": _float(fast.get("market_cap")) or _float(info.get("marketCap")),
        "yahoo_url": f"https://finance.yahoo.co.jp/quote/{symbol}",
        "yahoo_status": "取得成功" if (price is not None or bool(info)) else "取得失敗",
        "yahoo_error": " / ".join(errors) if errors else None,
    }


def resolve_irbank_company(session: requests.Session, code: str) -> tuple[str, str]:
    response = _get(session, f"https://irbank.net/{code}")
    match = re.search(r"irbank\.net/(E\d+)", response.url)
    company_id = match.group(1) if match else code
    return company_id, response.url


def _parse_market_cap_yen(text: str) -> float | None:
    text = text.replace(",", "")
    cho = re.search(r"時価総額.*?(\d+(?:\.\d+)?)兆(?:円|)(\d+(?:\.\d+)?)?億?", text, re.S)
    if cho:
        trillion = float(cho.group(1))
        oku = float(cho.group(2) or 0)
        return trillion * 1_000_000_000_000 + oku * 100_000_000
    oku = re.search(r"時価総額.*?(\d+(?:\.\d+)?)億(?:円|)", text, re.S)
    if oku:
        return float(oku.group(1)) * 100_000_000
    return None


def _first_number_after(text: str, labels: Iterable[str], suffix: str) -> float | None:
    for label in labels:
        pattern = rf"{re.escape(label)}[^\d\-]{{0,80}}(-?\d+(?:\.\d+)?)\s*{re.escape(suffix)}"
        match = re.search(pattern, text, re.S)
        if match:
            return float(match.group(1))
    return None


def fetch_irbank_quote(session: requests.Session, code: str) -> dict[str, Any]:
    """
    IR BANK企業ページからStep1補完値を取得。
    yfinanceで欠けた場合の補完に使用する。
    """
    response = _get(session, f"https://irbank.net/{code}")
    soup = BeautifulSoup(response.text, "lxml")
    text = soup.get_text("\n", strip=True)
    return {
        "per": _first_number_after(text, ["PER（連）予", "PER 予", "PER（連）"], "倍"),
        "pbr": _first_number_after(text, ["PBR（連）", "PBR"], "倍"),
        "dividend_yield": _first_number_after(text, ["配当利回り 予", "配当 予"], "%"),
        "roe": _first_number_after(text, ["ROE（連）予", "ROE 予", "ROE（連）"], "%"),
        "roa": _first_number_after(text, ["ROA（連）予", "ROA 予", "ROA（連）"], "%"),
        "equity_ratio": _first_number_after(
            text, ["株主資本比率（連）", "自己資本比率", "株主資本比率"], "%"
        ),
        "market_cap": _parse_market_cap_yen(text),
        "irbank_quote_url": response.url,
    }


def _year_token(line: str) -> str | None:
    match = re.search(r"(20\d{2}/\d{2}|20\d{2}年\d{1,2}月|20\d{2}/\d{1,2})", line)
    return match.group(1) if match else None


def _yen_value(line: str) -> float | None:
    cleaned = (
        line.replace(",", "")
        .replace("−", "-")
        .replace("▲", "-")
        .replace("△", "-")
        .replace("*", "")
    )
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*円", cleaned)
    return float(match.group(1)) if match else None


def parse_irbank_series_from_text(text: str, heading_names: list[str]) -> list[dict[str, Any]]:
    """
    IR BANKの決算まとめページ本文を、見出し単位で解析する。
    h2構造が変わっても、プレーンテキストの「見出し→年度→円」の並びを利用して復旧する。
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    start = None
    for i, line in enumerate(lines):
        normalized = re.sub(r"#\d+", "", line).strip()
        if normalized in heading_names:
            start = i + 1
            break
    if start is None:
        return []

    rows: list[dict[str, Any]] = []
    pending_year: str | None = None

    for line in lines[start:]:
        normalized = re.sub(r"#\d+", "", line).strip()

        # 次のセクション見出し
        if normalized.startswith("## ") or normalized.startswith("# "):
            break
        # HTML get_textでは#は付かないので、既知の見出し風行も停止条件にする
        if (
            normalized in {
                "ROE（自己資本利益率）", "ROA（総資産利益率）", "営業利益",
                "経常利益", "売上高", "配当金の支払額", "純資産配当率",
                "自社株買い", "総還元額", "総還元性向", "キャッシュ・フローの推移"
            }
            and normalized not in heading_names
        ):
            break

        year = _year_token(normalized)
        value = _yen_value(normalized)

        if year:
            pending_year = year
            # 同一行に値がある表形式にも対応
            tail = normalized[normalized.find(year) + len(year):]
            same_line_value = _yen_value(tail)
            if same_line_value is not None:
                rows.append({"year": pending_year, "value": same_line_value})
                pending_year = None
            continue

        if pending_year is not None and value is not None:
            rows.append({"year": pending_year, "value": value})
            pending_year = None

    # 同じ年度が重複した場合は後勝ち
    dedup: dict[str, float] = {}
    for row in rows:
        dedup[row["year"]] = row["value"]
    return [{"year": year, "value": value} for year, value in dedup.items()]


def parse_irbank_series_from_html(html: str) -> dict[str, list[dict[str, Any]]]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)
    return {
        "eps": parse_irbank_series_from_text(text, ["EPS"]),
        "bps": parse_irbank_series_from_text(text, ["BPS"]),
        "dividends": parse_irbank_series_from_text(text, ["一株配当", "1株配当"]),
    }


def _flatten_json(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    flattened: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_path = f"{path}.{key}" if path else str(key)
            flattened.extend(_flatten_json(value, next_path))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            flattened.extend(_flatten_json(value, f"{path}[{index}]"))
    else:
        flattened.append((path, obj))
    return flattened


def _extract_rows_from_json(payload: Any, aliases: list[str]) -> list[dict[str, Any]]:
    """
    IR BANK JSONの構造差を吸収する汎用抽出。
    年度キーと対象項目名が含まれる値を探索する。
    """
    aliases_lower = [alias.lower() for alias in aliases]
    rows: dict[str, float] = {}

    def walk(obj: Any, inherited_year: str | None = None, inherited_key: str = "") -> None:
        if isinstance(obj, dict):
            year = inherited_year
            for key, value in obj.items():
                if isinstance(value, str):
                    found = _year_token(value)
                    if found:
                        year = found
                found_key_year = _year_token(str(key))
                if found_key_year:
                    year = found_key_year

            for key, value in obj.items():
                key_text = str(key).lower()
                target = any(alias in key_text for alias in aliases_lower)
                if target:
                    numeric = None
                    if isinstance(value, (int, float)):
                        numeric = float(value)
                    elif isinstance(value, str):
                        numeric = _yen_value(value)
                        if numeric is None:
                            try:
                                numeric = float(value.replace(",", "").replace("*", ""))
                            except Exception:
                                pass
                    elif isinstance(value, dict):
                        for candidate in ("value", "amount", "val", "current"):
                            if candidate in value:
                                try:
                                    numeric = float(str(value[candidate]).replace(",", "").replace("*", ""))
                                    break
                                except Exception:
                                    continue
                    if year and numeric is not None:
                        rows[year] = numeric
                walk(value, year, key_text)

        elif isinstance(obj, list):
            for item in obj:
                walk(item, inherited_year, inherited_key)

    walk(payload)
    return [{"year": year, "value": value} for year, value in rows.items()]


def fetch_irbank_json(session: requests.Session, code: str) -> dict[str, list[dict[str, Any]]]:
    urls = {
        "all": f"https://f.irbank.net/files/{code}/fy-data-all.json",
        "pl": f"https://f.irbank.net/files/{code}/fy-profit-and-loss.json",
        "dividend": f"https://f.irbank.net/files/{code}/fy-stock-dividend.json",
        "balance": f"https://f.irbank.net/files/{code}/fy-balance-sheet.json",
    }
    payloads: dict[str, Any] = {}
    for key, url in urls.items():
        try:
            time.sleep(REQUEST_INTERVAL_SECONDS)
            response = _get(session, url, accept_json=True)
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type.lower() and not response.text.lstrip().startswith(("{", "[")):
                continue
            payloads[key] = response.json()
        except Exception:
            continue

    eps = []
    bps = []
    dividends = []

    for payload in payloads.values():
        if not eps:
            eps = _extract_rows_from_json(payload, ["eps", "earningspershare", "一株利益"])
        if not bps:
            bps = _extract_rows_from_json(payload, ["bps", "bookvaluepershare", "一株純資産"])
        if not dividends:
            dividends = _extract_rows_from_json(
                payload, ["dividendpershare", "annualdividendpershare", "一株配当", "配当"]
            )
    return {"eps": eps, "bps": bps, "dividends": dividends}


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple[int, int]:
        match = re.search(r"(20\d{2})[/年](\d{1,2})", str(row.get("year", "")))
        if not match:
            return (0, 0)
        return int(match.group(1)), int(match.group(2))
    return sorted(rows, key=key)


def _merge_rows(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, float] = {}
    for row in fallback:
        merged[str(row["year"])] = float(row["value"])
    for row in primary:
        merged[str(row["year"])] = float(row["value"])
    return _sort_rows([{"year": year, "value": value} for year, value in merged.items()])



def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(part) for part in col if str(part) != "nan").strip()
            for col in df.columns
        ]
    else:
        df.columns = [str(col).strip() for col in df.columns]
    return df


def _clean_numeric(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).replace(",", "").replace("円", "").replace("*", "").strip()
    raw = raw.replace("−", "-").replace("▲", "-").replace("△", "-")
    if raw in {"", "-", "—", "nan", "None"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    return float(match.group(0)) if match else None


def _normalize_year(value: Any) -> str | None:
    raw = str(value).strip()
    match = re.search(r"(20\d{2})[年/](\d{1,2})", raw)
    if not match:
        return None
    return f"{match.group(1)}/{int(match.group(2)):02d}"


def fetch_valuation_history(
    session: requests.Session,
    company_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """
    IR BANK /valuation の本文から「年度 EPS BPS」の3項目を直接抽出する。
    pandas.read_htmlやHTMLの列構造には依存しない。
    """
    url = f"https://irbank.net/{company_id}/valuation"
    response = _get(session, url)
    soup = BeautifulSoup(response.text, "lxml")
    plain = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    # 例: 2024/12 345.31 円 4026.22 円
    pattern = re.compile(
        r"(20\d{2}/\d{1,2})\s*"
        r"(-?\d+(?:\.\d+)?)\s*円\s*"
        r"(-?\d+(?:\.\d+)?)\s*円"
    )

    eps_rows: list[dict[str, Any]] = []
    bps_rows: list[dict[str, Any]] = []
    for year, eps, bps in pattern.findall(plain):
        normalized_year = _normalize_year(year)
        if normalized_year:
            eps_rows.append({"year": normalized_year, "value": float(eps)})
            bps_rows.append({"year": normalized_year, "value": float(bps)})

    # テーブル末尾の予想EPSはBPSが「-」のため別に拾う。
    forecast_pattern = re.compile(
        r"(20\d{2}/\d{1,2})\s*"
        r"(-?\d+(?:\.\d+)?)\s*円\s*-\s*(?=EPS|##|開示資料|$)"
    )
    for year, eps in forecast_pattern.findall(plain):
        normalized_year = _normalize_year(year)
        if normalized_year and not any(row["year"] == normalized_year for row in eps_rows):
            eps_rows.append({"year": normalized_year, "value": float(eps)})

    return {
        "eps": _sort_rows(eps_rows),
        "bps": _sort_rows(bps_rows),
        "url": url,
        "http_status": response.status_code,
        "matched_rows": len(eps_rows),
    }


def _last_number_before_percent(row_text: str) -> float | None:
    """
    配当表の1行から「分割調整配当」を取得。
    IR BANKでは利回り（%）の直前に分割調整後の年間配当が置かれる。
    """
    cleaned = row_text.replace(",", "").replace("#", " ")
    percent_match = re.search(r"\d+(?:\.\d+)?\s*%", cleaned)
    before_percent = cleaned[:percent_match.start()] if percent_match else cleaned
    numbers = re.findall(r"-?\d+(?:\.\d+)?", before_percent)
    return float(numbers[-1]) if numbers else None


def fetch_dividend_history(
    session: requests.Session,
    company_id: str,
) -> dict[str, Any]:
    """
    IR BANK /dividend の本文を年度ブロック単位で解析する。
    実績 > 修正 > 予想の順で採用し、利回り直前の分割調整配当を使う。
    """
    url = f"https://irbank.net/{company_id}/dividend"
    response = _get(session, url)
    soup = BeautifulSoup(response.text, "lxml")
    plain = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    table_start = plain.find("配当金の状況")
    table_end = plain.find("配当利回り", table_start + 1)
    table_text = plain[table_start:table_end] if table_start >= 0 and table_end > table_start else plain

    year_matches = list(re.finditer(r"(20\d{2})年", table_text))
    candidates: dict[str, tuple[int, float]] = {}
    priority = {"実績": 3, "修正": 2, "予想": 1}

    for index, match in enumerate(year_matches):
        year = match.group(1)
        block_end = year_matches[index + 1].start() if index + 1 < len(year_matches) else len(table_text)
        block = table_text[match.end():block_end]

        month_match = re.search(r"(\d{1,2})月", block)
        if not month_match:
            continue
        month = int(month_match.group(1))
        fiscal_year = f"{year}/{month:02d}"

        row_matches = list(re.finditer(r"(実績|修正|予想)", block))
        for row_index, row_match in enumerate(row_matches):
            kind = row_match.group(1)
            row_end = row_matches[row_index + 1].start() if row_index + 1 < len(row_matches) else len(block)
            row_text = block[row_match.end():row_end]
            value = _last_number_before_percent(row_text)
            if value is None:
                continue
            rank = priority[kind]
            if fiscal_year not in candidates or rank > candidates[fiscal_year][0]:
                candidates[fiscal_year] = (rank, value)

    rows = [
        {"year": year, "value": rank_value[1]}
        for year, rank_value in candidates.items()
    ]
    return {
        "dividends": _sort_rows(rows),
        "url": url,
        "http_status": response.status_code,
        "matched_rows": len(rows),
    }
def fetch_irbank_history(session: requests.Session, code: str, company_id: str) -> dict[str, Any]:
    valuation_error = dividend_error = None
    valuation = {"eps": [], "bps": [], "url": f"https://irbank.net/{company_id}/valuation"}
    dividend = {"dividends": [], "url": f"https://irbank.net/{company_id}/dividend"}
    try:
        valuation = fetch_valuation_history(session, company_id)
    except Exception as exc:
        valuation_error = str(exc)
    try:
        time.sleep(REQUEST_INTERVAL_SECONDS)
        dividend = fetch_dividend_history(session, company_id)
    except Exception as exc:
        dividend_error = str(exc)
    json_data = {"eps": [], "bps": [], "dividends": []}
    try:
        json_data = fetch_irbank_json(session, code)
    except Exception:
        pass
    results_url = f"https://irbank.net/{company_id}/results"
    html_data = {"eps": [], "bps": [], "dividends": []}
    try:
        response = _get(session, results_url)
        html_data = parse_irbank_series_from_html(response.text)
    except Exception:
        pass
    eps_rows = _merge_rows(valuation.get("eps", []), _merge_rows(json_data.get("eps", []), html_data.get("eps", [])))
    bps_rows = _merge_rows(valuation.get("bps", []), _merge_rows(json_data.get("bps", []), html_data.get("bps", [])))
    dividend_rows = _merge_rows(dividend.get("dividends", []), _merge_rows(json_data.get("dividends", []), html_data.get("dividends", [])))
    minimum = min(len(eps_rows), len(bps_rows), len(dividend_rows))
    errors = [x for x in (valuation_error, dividend_error) if x]
    return {
        "eps_rows": eps_rows,
        "bps_rows": bps_rows,
        "dividend_rows": dividend_rows,
        "eps": [r["value"] for r in eps_rows],
        "bps": [r["value"] for r in bps_rows],
        "dividends": [r["value"] for r in dividend_rows],
        "results_url": results_url,
        "valuation_url": valuation.get("url"),
        "dividend_url": dividend.get("url"),
        "irbank_status": (
            f"EPS:{len(eps_rows)}期／BPS:{len(bps_rows)}期／"
            f"配当:{len(dividend_rows)}期／最少{minimum}期"
        ),
        "irbank_debug": (
            f"valuation HTTP={valuation.get('http_status', '-')}, "
            f"直接一致={valuation.get('matched_rows', 0)}／"
            f"dividend HTTP={dividend.get('http_status', '-')}, "
            f"直接一致={dividend.get('matched_rows', 0)}"
        ),
        "irbank_error": " / ".join(errors) if errors else None,
    }

def fetch_all(code: str) -> dict[str, Any]:
    code = _clean_code(code)
    session = _session()

    yahoo = fetch_yahoo(code)

    company_id = code
    company_url = f"https://irbank.net/{code}"
    irbank_error = None
    try:
        company_id, company_url = resolve_irbank_company(session, code)
    except Exception as exc:
        irbank_error = f"企業ページ: {exc}"

    quote = {}
    try:
        quote = fetch_irbank_quote(session, code)
    except Exception as exc:
        irbank_error = f"{irbank_error or ''} 指標: {exc}".strip()

    history = {
        "eps_rows": [], "bps_rows": [], "dividend_rows": [],
        "eps": [], "bps": [], "dividends": [],
        "results_url": f"https://irbank.net/{company_id}/results",
        "irbank_status": "取得失敗", "irbank_error": None,
    }
    try:
        history = fetch_irbank_history(session, code, company_id)
    except Exception as exc:
        history["irbank_error"] = str(exc)

    # IR BANKを補完元として利用。Yahoo値がある場合はYahooを優先。
    for key in ("per", "pbr", "roe", "roa", "equity_ratio", "market_cap", "dividend_yield"):
        if yahoo.get(key) is None and quote.get(key) is not None:
            yahoo[key] = quote[key]

    return {
        **yahoo,
        **history,
        "irbank_url": company_url,
        "irbank_results_url": history.get("results_url"),
        "irbank_error": history.get("irbank_error") or irbank_error,
    }
