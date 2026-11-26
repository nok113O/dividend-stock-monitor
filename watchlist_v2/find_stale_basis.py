"""locked_targets.basis_date(直近に取り込んだ決算短信の開示日)が一定期間
より古い銘柄を抽出する。

J-Quants無料プランは新規開示の反映に最大12週間ほど遅延することがあり、
Notion側の更新を補助シグナルとして使う日次チェック(check_notion_disclosures.py)
だけでは、ユーザーのNotion更新自体が遅れているケースを取りこぼす
(2026-11-26に旭化成・みずほFG・理研ビタミンで実際に発生)。

四半期ごとの開示サイクル(おおよそ91日)を踏まえ、basis_dateからの経過日数が
しきい値(デフォルト75日)を超えた銘柄だけを抽出することで、「そろそろ次の
開示が出ているはず」な銘柄に絞り込む。この少数リストについてのみEDINET DBの
get_earningsで直接最新の予想配当を確認すれば、Notion更新に依存せず
J-Quants未反映の配当予想修正を検知できる。

使い方:
  python watchlist_v2/find_stale_basis.py [しきい値日数（デフォルト84=12週間）]

出力は経過日数の降順。EDINET DBで確認する際のedinet_codeも併記する。
しきい値超えが多い場合、呼び出し側(Claude自身)は経過日数の多い方から
1日あたり決まった件数(日次ルーティンでは15件)だけEDINET DBで確認し、
数日かけてバックログを消化する運用とする。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

STOCKS_FILE = Path(__file__).resolve().parent / "stocks.json"
EDINET_CODES_FILE = Path(__file__).resolve().parent / "edinet_codes.json"


def main() -> None:
    threshold_days = int(sys.argv[1]) if len(sys.argv) > 1 else 84

    data = json.loads(STOCKS_FILE.read_text(encoding="utf-8"))
    edinet_codes: dict[str, str] = json.loads(EDINET_CODES_FILE.read_text(encoding="utf-8"))
    today = date.today()

    stale = []
    for s in data["stocks"]:
        locked = s.get("locked_targets") or {}
        basis_date = locked.get("basis_date")
        if not basis_date:
            continue
        bd = date.fromisoformat(basis_date)
        days = (today - bd).days
        if days >= threshold_days:
            stale.append({
                "code": s["code"],
                "name": s["name"],
                "basis_date": basis_date,
                "days": days,
                "forecast_dividend_basis": locked.get("forecast_dividend_basis"),
                "edinet_code": edinet_codes.get(s["code"]),
            })

    stale.sort(key=lambda x: x["days"], reverse=True)

    print(f"基準日から{threshold_days}日以上経過した銘柄: {len(stale)}件")
    for x in stale:
        weeks = x["days"] / 7
        print(
            f"  {x['code']} {x['name']}: 基準日{x['basis_date']}"
            f"（{x['days']}日/{weeks:.1f}週経過） 現在の予想配当基準={x['forecast_dividend_basis']}"
            f" edinet_code={x['edinet_code']}"
        )


if __name__ == "__main__":
    main()
