"""分割買いラインの「要再審査」(減配検知による無効化)状態を解除し、
その時点の最新データで確定値を引き直す。

Step1・Step2の再審査自体はこのスクリプトでは行わない(チャットで別途
確認してから、ユーザーが解除を指示する運用)。解除日・理由(チャットで
伝えられた内容)を履歴に残す。

使い方:
  JQUANTS_API_KEY=... python watchlist_v2/clear_review.py 9304 --reason "決算を確認し問題ないと判断"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch import (  # noqa: E402
    OUTPUT_FILE, _check_order, _compose_buy3, _large_increase_fields, fetch_one, load_previous_stocks,
)
from jquants_client import JQuantsClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="「要再審査」状態を解除し、最新データで確定値を引き直す")
    parser.add_argument("code", help="証券コード")
    parser.add_argument("--reason", required=True, help="解除理由(チャットでユーザーが伝えた内容)")
    args = parser.parse_args()

    api_key = os.environ.get("JQUANTS_API_KEY", "")
    client = JQuantsClient(api_key, min_interval_seconds=1.5)
    previous = load_previous_stocks()
    prev_stock = previous.get(args.code)
    if not prev_stock:
        print(f"{args.code} はウォッチリストに存在しません。")
        sys.exit(1)

    locked = prev_stock.get("locked_targets") or {}
    if not locked.get("disabled"):
        print(f"{args.code} は現在「要再審査」状態ではありません(disabled=False)。解除の必要はありません。")
        sys.exit(1)

    result = fetch_one(client, args.code, None, None, prev_stock)

    ty = result["target_yield"]
    step3 = result["step3"]
    buy3, buy3_source = _compose_buy3(ty.get("buy3_price"), step3.get("target_price"))
    buy1, buy2 = ty.get("buy1_price"), ty.get("buy2_price")
    today_str = date.today().strftime("%Y-%m-%d")
    old_snapshot = {"buy1": locked.get("buy1"), "buy2": locked.get("buy2"), "buy3": locked.get("buy3")}
    large_increase_warning, large_increase_detail = _large_increase_fields(
        locked.get("forecast_dividend_basis"), result.get("forecast_dividend")
    )

    new_locked = {
        "buy1": buy1,
        "buy2": buy2,
        "buy3": buy3,
        "target1_pct": ty.get("target1_pct"),
        "target2_pct": ty.get("target2_pct"),
        "target3_pct": ty.get("target3_pct"),
        "buy3_source": buy3_source,
        "forecast_dividend_basis": result.get("forecast_dividend"),
        "price_at_lock": result.get("price"),
        "large_increase_warning": large_increase_warning,
        "large_increase_detail": large_increase_detail,
        "basis_date": today_str,
        "reason": f"手動解除(再審査完了): {args.reason}",
        "disabled": False,
        "disabled_reason": None,
        "order_warning": _check_order(buy1, buy2, buy3),
        "last_disc_no": locked.get("last_disc_no"),
        "history": (list(locked.get("history") or []) + [{
            "date": today_str,
            "trigger": "手動解除",
            "note": args.reason,
            "from": old_snapshot,
            "to": {"buy1": buy1, "buy2": buy2, "buy3": buy3},
        }])[-10:],
    }
    result["locked_targets"] = new_locked

    data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    for i, s in enumerate(data["stocks"]):
        if s["code"] == args.code:
            data["stocks"][i] = result
            break
    else:
        print(f"{args.code} がstocks.json内に見つかりませんでした。")
        sys.exit(1)
    data["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    OUTPUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{args.code} の再審査を解除し、確定値を引き直しました。")
    print(json.dumps(new_locked, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
