"""Notion「投資銘柄一覧」DBの最終更新日を使って、前回チェック時点から
決算直後の更新があった(かもしれない)銘柄を検出する。

比較対象は locked_targets.basis_date ではなく「前回このスクリプトを実行した
時点のNotion最終更新日」(.notion_last_checked.json に保存)。basis_date と
比較すると、ユーザーの別プロジェクト側でのリサーチ時期(2026年8月の一斉構築時
など、決算と無関係な編集)まで全部拾ってしまい大量の誤検知になるため。
「前回チェック以降に更新されたか」だけを見ることで、決算直後の更新だけに
近い形で絞り込む。

Notion MCPはこのスクリプト単体からは呼べないため、呼び出し側(Claude自身)が
notion-query-data-sourcesで「証券コード→最終更新日」の対応をJSONファイルに
書き出し、そのパスを引数で渡す運用とする。

使い方:
  python watchlist_v2/check_notion_disclosures.py <notion_last_updated.jsonのパス>

初回実行時(状態ファイルが無い場合)は、全銘柄を「初回ベースライン登録」として
扱い、フラグは立てずに状態ファイルだけ作成する。2回目以降の実行から、前回との
差分を検出する。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

STOCKS_FILE = Path(__file__).resolve().parent / "stocks.json"
STATE_FILE = Path(__file__).resolve().parent / ".notion_last_checked.json"


def main() -> None:
    if len(sys.argv) != 2:
        print("使い方: python watchlist_v2/check_notion_disclosures.py <notion_last_updated.jsonのパス>")
        sys.exit(1)

    notion_path = Path(sys.argv[1])
    notion_dates: dict[str, str] = json.loads(notion_path.read_text(encoding="utf-8"))
    data = json.loads(STOCKS_FILE.read_text(encoding="utf-8"))
    stocks = {s["code"]: s for s in data["stocks"]}

    is_first_run = not STATE_FILE.exists()
    prev_state: dict[str, str] = json.loads(STATE_FILE.read_text(encoding="utf-8")) if not is_first_run else {}

    flagged = []
    for code, notion_date in notion_dates.items():
        prev_date = prev_state.get(code)
        if not is_first_run and (prev_date is None or notion_date > prev_date):
            stock = stocks.get(code)
            locked = (stock or {}).get("locked_targets") or {}
            flagged.append({
                "code": code,
                "name": (stock or {}).get("name") or "(監視銘柄外)",
                "notion_last_updated": notion_date,
                "prev_checked": prev_date,
                "basis_date": locked.get("basis_date"),
            })

    STATE_FILE.write_text(json.dumps(notion_dates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    watchlist_codes = set(stocks.keys())
    not_in_notion = sorted(watchlist_codes - set(notion_dates.keys()))

    if is_first_run:
        print(f"初回実行：ベースラインとして{len(notion_dates)}件を記録しました。次回実行から差分を検出します。")
        return

    print(f"Notion DB件数: {len(notion_dates)} / 監視銘柄数: {len(stocks)}")
    print(f"前回チェック以降に更新された銘柄: {len(flagged)}")
    for f in sorted(flagged, key=lambda x: x["notion_last_updated"], reverse=True):
        prev = f["prev_checked"] or "(新規)"
        print(
            f"  {f['code']} {f['name']}: Notion最終更新 {f['notion_last_updated']}"
            f"（前回チェック時 {prev}）／確定値基準日 {f['basis_date']}"
        )
    print(f"監視銘柄だがNotionにない(突合対象外): {len(not_in_notion)} -> {not_in_notion}")


if __name__ == "__main__":
    main()
