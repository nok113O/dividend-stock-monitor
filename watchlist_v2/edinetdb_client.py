"""EDINET DB (https://edinetdb.jp) のREST APIクライアント。

J-Quants Freeプランは財務情報の反映が実際の開示から12週遅れるため、
決算短信ベースの予想配当・実績を先取りする目的でEDINET DBを併用する。
データ出典: EDINET DB (https://edinetdb.jp)
"""
from __future__ import annotations

from typing import Any
import requests

BASE_URL = "https://edinetdb.jp/v1"


class EdinetDbError(RuntimeError):
    pass


class EdinetDbClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise EdinetDbError("EDINET DB APIキーが設定されていません。")
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": api_key,
            "Accept": "application/json",
        })

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(f"{BASE_URL}{path}", params=params or {}, timeout=30)
        if response.status_code == 401:
            raise EdinetDbError("EDINET DB APIキーが無効です。")
        if response.status_code == 429:
            raise EdinetDbError("EDINET DBのレート上限に達しました。日を改めて再実行してください。")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text[:300].strip()
            raise EdinetDbError(
                f"EDINET DB取得エラー: HTTP {response.status_code} / {path} / {detail or '詳細なし'}"
            ) from exc
        return response.json()

    def search(self, query: str) -> list[dict[str, Any]]:
        payload = self._get("/search", {"q": query})
        return payload.get("data", [])

    def resolve_edinet_code(self, sec_code_4digit: str) -> str | None:
        """4桁の証券コードからEDINETコードを解決する(5桁=4桁+検査数字0で完全一致するもの)。"""
        target = f"{sec_code_4digit}0"
        for company in self.search(sec_code_4digit):
            if company.get("sec_code") == target:
                return company.get("edinet_code")
        return None

    def company_profile(self, edinet_code: str) -> dict[str, Any]:
        payload = self._get(f"/companies/{edinet_code}")
        return payload.get("data", {})

    def financials(self, edinet_code: str, years: int = 10) -> list[dict[str, Any]]:
        payload = self._get(f"/companies/{edinet_code}/financials", {"years": years})
        return payload.get("data", [])

    def calendar(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        payload = self._get("/calendar", {"from": date_from, "to": date_to})
        return payload.get("data", {}).get("calendar", [])

    def earnings(self, edinet_code: str, limit: int = 3) -> list[dict[str, Any]]:
        payload = self._get(f"/companies/{edinet_code}/earnings", {"limit": limit})
        return payload.get("data", {}).get("earnings", [])
