"""決算発表の検知(数字は一切計算しない。日付の記録だけ)。

毎日の株価更新と同じワークフローから呼ぶ。
- EDINET DB の決算カレンダーから、監視銘柄の今後14日分の発表予定を取得
- 予定日が今日以前になったものを「pending(分析待ち)」に移す
- 状態は earnings_state.json に保存(data-repo 側)

必要: 環境変数 EDINET_DB_API_KEY(無料キー。1日100回の枠のうち1回だけ使う)
失敗しても株価更新は止めない(ワークフロー側で continue-on-error)。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

BASE = "https://edinetdb.jp/v1/calendar"
JST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; dividend-monitor/1.0)"
LOOKAHEAD_DAYS = 14


def norm_code(v):
    s = str(v).strip()
    if len(s) == 5 and s.endswith("0"):
        s = s[:4]
    return s


def fetch_calendar(api_key, d_from, d_to, get=requests.get):
    r = get(
        BASE,
        params={"from": d_from, "to": d_to, "limit": 2000, "status": "all"},
        headers={"X-API-Key": api_key, "User-Agent": UA},
        timeout=60,
    )
    r.raise_for_status()
    js = r.json()
    found = _find_list(js)
    if found is None:
        raise ValueError(f"unexpected response: {_shape(js)}")
    return found


def _find_list(x, depth=0):
    """応答のどこにあっても、辞書のリスト(カレンダー本体)を探す。"""
    if isinstance(x, list):
        return x if (not x or isinstance(x[0], dict)) else None
    if isinstance(x, dict) and depth < 3:
        for k in ("calendar", "data", "results", "items"):
            if k in x:
                r = _find_list(x[k], depth + 1)
                if r is not None:
                    return r
        for v in x.values():
            r = _find_list(v, depth + 1)
            if r is not None:
                return r
    return None


def _shape(x, depth=0):
    """エラー表示用。値は出さず、キーと型だけ。"""
    if isinstance(x, dict) and depth < 2:
        return {k: _shape(v, depth + 1) for k, v in list(x.items())[:6]}
    if isinstance(x, list):
        return f"list[{len(x)}]"
    return type(x).__name__


def entry_date(e):
    return e.get("announcementDate") or e.get("estimatedAnnouncementDate")


def entry_key(e):
    return f"{norm_code(e.get('secCode'))}|{e.get('fiscalYearEnd')}|{e.get('periodTypeEn')}"


def update_state(state, entries, codes, today):
    """state を更新し、今回新しく pending になった項目を返す。"""
    state.setdefault("upcoming", {})
    state.setdefault("pending", {})
    state.setdefault("done", [])
    for e in entries:
        code = norm_code(e.get("secCode"))
        d = entry_date(e)
        if code not in codes or not d:
            continue
        k = entry_key(e)
        if k in state["done"] or k in state["pending"]:
            continue
        state["upcoming"][k] = {
            "code": code,
            "name": e.get("companyName"),
            "period": e.get("periodTypeEn"),
            "fiscal_year_end": e.get("fiscalYearEnd"),
            "date": d,
            "date_status": e.get("dateStatus"),
        }
    new = []
    for k, v in list(state["upcoming"].items()):
        if v["date"] <= today:
            state["pending"][k] = {**v, "detected": today}
            del state["upcoming"][k]
            new.append(state["pending"][k])
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    key = os.environ.get("EDINET_DB_API_KEY", "").strip()
    if not key:
        print("earnings: skipped (no EDINET_DB_API_KEY)")
        return 0

    df = pd.read_csv(a.csv, dtype=str, encoding="utf-8-sig")
    codes = {norm_code(c) for c in df["コード"].dropna()}

    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    to = (now + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y-%m-%d")

    path = os.path.join(a.out, "earnings_state.json")
    state = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            state = json.load(f)

    entries = fetch_calendar(key, today, to)
    new = update_state(state, entries, codes, today)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"earnings: calendar={len(entries)} upcoming={len(state['upcoming'])} "
          f"pending={len(state['pending'])} new={len(new)}")

    bark = os.environ.get("BARK_KEY", "").strip()
    if bark and new:
        names = "、".join(f"{x['name']}({x['code']})" for x in new[:5])
        try:
            requests.post("https://api.day.app/push", timeout=20, json={
                "device_key": bark, "title": "決算発表を検知",
                "body": names + (" ほか" if len(new) > 5 else "")})
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
