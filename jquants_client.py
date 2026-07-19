from __future__ import annotations

from datetime import date, timedelta
import time
from typing import Any
import requests

BASE_URL = "https://api.jquants.com/v2"

class JQuantsError(RuntimeError):
    pass

class JQuantsClient:
    def __init__(self, api_key: str, min_interval_seconds: float = 1.0):
        if not api_key:
            raise JQuantsError("J-Quants APIキーが設定されていません。")
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "Accept": "application/json",
            "User-Agent": "DividendStockMonitor/4.0",
        })
        self.min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)

    def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        all_rows: list[dict[str, Any]] = []
        pagination_key = None

        while True:
            query = dict(params)
            if pagination_key:
                query["pagination_key"] = pagination_key

            self._wait()
            response = self.session.get(
                f"{BASE_URL}{path}",
                params=query,
                timeout=30,
            )
            self._last_request_at = time.monotonic()

            if response.status_code == 401:
                raise JQuantsError("APIキーが無効、またはSecretsへの登録が反映されていません。")
            if response.status_code == 403:
                raise JQuantsError("契約プランでは利用できないデータ、または取得期間です。")
            if response.status_code == 429:
                raise JQuantsError("レート上限に達しました。1分ほど待って再実行してください。")
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise JQuantsError(f"J-Quants取得エラー: HTTP {response.status_code}") from exc

            payload = response.json()
            rows = payload.get("data", [])
            if isinstance(rows, list):
                all_rows.extend(rows)

            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                break

        return all_rows

    def master(self, code: str) -> dict[str, Any]:
        rows = self._get("/equities/master", {"code": code})
        if not rows:
            raise JQuantsError(f"{code}の銘柄情報を取得できませんでした。")
        return rows[-1]

    def daily_bars(self, code: str, lookback_days: int = 45) -> list[dict[str, Any]]:
        end = date.today()
        start = end - timedelta(days=lookback_days)
        return self._get(
            "/equities/bars/daily",
            {"code": code, "from": start.isoformat(), "to": end.isoformat()},
        )

    def financial_summary(self, code: str) -> list[dict[str, Any]]:
        return self._get("/fins/summary", {"code": code})
