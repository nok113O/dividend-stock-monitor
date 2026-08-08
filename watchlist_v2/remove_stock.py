"""ウォッチリストから銘柄を除外する(履歴は残す)。

codes.jsonからコードを削除し、stocks.jsonから該当エントリを削除する。
history_seed.json・edinet_codes.jsonのデータはそのまま保持し、
再追加時にゼロからデータ取得しなくて済むようにする。
除外の記録はremoved_codes.jsonに追記する(コード・銘柄名・除外日・理由のみ)。

使い方:
  python watchlist_v2/remove_stock.py 4021 --reason "割高すぎる判断"
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

CODES_FILE = Path(__file__).resolve().parent / "codes.json"
STOCKS_FILE = Path(__file__).resolve().parent / "stocks.json"
REMOVED_FILE = Path(__file__).resolve().parent / "removed_codes.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="ウォッチリストから銘柄を除外する(履歴は残す)")
    parser.add_argument("code", help="除外する証券コード")
    parser.add_argument("--reason", default="", help="除外理由")
    args = parser.parse_args()
    code = args.code

    codes = json.loads(CODES_FILE.read_text(encoding="utf-8"))
    if code not in codes:
        print(f"{code} はcodes.jsonに存在しません。")
        return
    codes = [c for c in codes if c != code]
    CODES_FILE.write_text(json.dumps(codes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    name = code
    if STOCKS_FILE.exists():
        payload = json.loads(STOCKS_FILE.read_text(encoding="utf-8"))
        stock = next((s for s in payload.get("stocks", []) if s["code"] == code), None)
        if stock:
            name = stock.get("name") or code
        payload["stocks"] = [s for s in payload.get("stocks", []) if s["code"] != code]
        STOCKS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    removed = json.loads(REMOVED_FILE.read_text(encoding="utf-8")) if REMOVED_FILE.exists() else []
    removed = [r for r in removed if r["code"] != code]
    removed.append({
        "code": code,
        "name": name,
        "removed_at": datetime.now().strftime("%Y-%m-%d"),
        "reason": args.reason,
    })
    REMOVED_FILE.write_text(json.dumps(removed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{code}({name}) をウォッチリストから除外しました。history_seed.jsonのデータは保持されています。")


if __name__ == "__main__":
    main()
