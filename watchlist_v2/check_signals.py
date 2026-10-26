"""日次更新で報告すべき分割買いラインの変化を検出する。

直前にコミットされていたstocks.json(= 前回の日次更新時点)と、今回生成した
stocks.jsonを比較し、以下の3種類の「新たに起きたこと」だけを報告する
(状態が変わらないものは対象外。例えば既に買い3に到達済みのまま・既に
無効化されたままの銘柄は報告しない)。

  1. 新たに買いラインへ到達した銘柄(到達レベルが上がった)
  2. 新たに無効化(減配検知)された銘柄
  3. 新たに現在株価が買い3を10%以上下回った銘柄(買い増し停止・要点検)

使い方:
  python watchlist_v2/check_signals.py [--before-ref HEAD]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

STOCKS_FILE = Path(__file__).resolve().parent / "stocks.json"

LEVEL_LABELS = {1: "1回目(買い1)", 2: "2回目(買い2)", 3: "3回目(買い3)"}


def locked_level(price, locked: dict | None) -> int:
    if price is None or not locked or locked.get("disabled"):
        return 0
    b1, b2, b3 = locked.get("buy1"), locked.get("buy2"), locked.get("buy3")
    if b3 is not None and price <= b3:
        return 3
    if b2 is not None and price <= b2:
        return 2
    if b1 is not None and price <= b1:
        return 1
    return 0


def deep_breach(price, locked: dict | None) -> bool:
    if not locked or locked.get("disabled"):
        return False
    buy3 = locked.get("buy3")
    if price is None or buy3 is None or buy3 <= 0:
        return False
    return price < buy3 * 0.9


def load_stocks(raw: str) -> dict[str, dict]:
    data = json.loads(raw)
    return {s["code"]: s for s in data.get("stocks", [])}


def main() -> None:
    parser = argparse.ArgumentParser(description="日次更新で報告すべき分割買いラインの変化を検出する")
    parser.add_argument(
        "--before-ref", default="HEAD",
        help="比較対象とする直前のgit参照(デフォルト: HEAD。今回の変更をコミットする前に実行する想定)",
    )
    args = parser.parse_args()

    try:
        before_raw = subprocess.run(
            ["git", "show", f"{args.before_ref}:watchlist_v2/stocks.json"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        print(f"直前のstocks.jsonが取得できませんでした: {exc.stderr}")
        return

    before = load_stocks(before_raw)
    after = load_stocks(STOCKS_FILE.read_text(encoding="utf-8"))

    newly_reached, newly_disabled, newly_breached = [], [], []
    for code, stock in after.items():
        prev_stock = before.get(code)
        if not prev_stock:
            continue
        locked = stock.get("locked_targets") or {}
        prev_locked = prev_stock.get("locked_targets") or {}
        price = stock.get("price")
        prev_price = prev_stock.get("price")

        level_after = locked_level(price, locked)
        level_before = locked_level(prev_price, prev_locked)
        if level_after > level_before:
            newly_reached.append({
                "code": code, "name": stock.get("name"),
                "level_label": LEVEL_LABELS.get(level_after, str(level_after)),
                "price": price, "basis_date": locked.get("basis_date"),
            })

        if locked.get("disabled") and not prev_locked.get("disabled"):
            newly_disabled.append({
                "code": code, "name": stock.get("name"),
                "reason": locked.get("disabled_reason"),
            })

        if deep_breach(price, locked) and not deep_breach(prev_price, prev_locked):
            newly_breached.append({
                "code": code, "name": stock.get("name"),
                "price": price, "buy3": locked.get("buy3"),
            })

    if not (newly_reached or newly_disabled or newly_breached):
        print("報告すべき変化はありません。")
        return

    if newly_reached:
        print(f"新たに買いラインへ到達した銘柄: {len(newly_reached)}件")
        for item in newly_reached:
            print(
                f"  {item['code']} {item['name']}: {item['level_label']}に到達"
                f"(株価{item['price']}円／確定値の基準日{item['basis_date']})"
            )
    if newly_disabled:
        print(f"新たに無効化(減配検知)された銘柄: {len(newly_disabled)}件")
        for item in newly_disabled:
            print(f"  {item['code']} {item['name']}: {item['reason']}")
    if newly_breached:
        print(f"新たに買い3を10%以上下回った銘柄(買い増し停止・要点検): {len(newly_breached)}件")
        for item in newly_breached:
            print(f"  {item['code']} {item['name']}: 株価{item['price']}円（買い3={item['buy3']}円）")


if __name__ == "__main__":
    main()
