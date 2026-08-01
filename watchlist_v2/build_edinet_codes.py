"""codes.json の証券コードをEDINETコードに解決し、edinet_codes.json にキャッシュする。

無料プラン(100回/日)のレート制限を考慮し、未解決のコードだけを処理する。
レート上限に達したら安全に中断し、翌日以降の再実行で続きから処理される。

使い方:
  EDINETDB_API_KEY=... python watchlist_v2/build_edinet_codes.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from edinetdb_client import EdinetDbClient, EdinetDbError

CODES_FILE = Path(__file__).resolve().parent / "codes.json"
MAP_FILE = Path(__file__).resolve().parent / "edinet_codes.json"


def load_map() -> dict[str, str]:
    if MAP_FILE.exists():
        return json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {}


def main() -> None:
    api_key = os.environ.get("EDINETDB_API_KEY", "")
    client = EdinetDbClient(api_key)
    codes = json.loads(CODES_FILE.read_text(encoding="utf-8"))
    mapping = load_map()

    pending = [c for c in codes if c not in mapping]
    print(f"未解決 {len(pending)}件 / 全{len(codes)}件")

    resolved = 0
    failed = []
    for code in pending:
        try:
            edinet_code = client.resolve_edinet_code(code)
        except EdinetDbError as exc:
            print(f"中断: {exc}")
            break
        if edinet_code:
            mapping[code] = edinet_code
            resolved += 1
        else:
            failed.append(code)
        MAP_FILE.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(0.3)

    print(f"解決: {resolved}件 / 未解決のまま: {len(failed)}件 / マッピング総数: {len(mapping)}/{len(codes)}")
    if failed:
        print("未解決コード:", ", ".join(failed))


if __name__ == "__main__":
    main()
