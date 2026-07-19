from __future__ import annotations

import math
from typing import Any


def _valid(value: Any) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def judge_le(value: float | None, limit: float) -> str:
    return "○" if _valid(value) and value <= limit else ("×" if _valid(value) else "要確認")


def judge_ge(value: float | None, limit: float) -> str:
    return "○" if _valid(value) and value >= limit else ("×" if _valid(value) else "要確認")


def analyze_step1(data: dict[str, Any]) -> dict:
    market_cap_oku = float(data["market_cap"]) / 100_000_000 if _valid(data.get("market_cap")) else None
    rows = {
        "PER": {"value": data.get("per"), "unit": "倍", "criterion": "12倍以下", "judge": judge_le(data.get("per"), 12)},
        "PBR": {"value": data.get("pbr"), "unit": "倍", "criterion": "1.3倍以下", "judge": judge_le(data.get("pbr"), 1.3)},
        "ROE": {"value": data.get("roe"), "unit": "%", "criterion": "7%以上", "judge": judge_ge(data.get("roe"), 7)},
        "ROA": {"value": data.get("roa"), "unit": "%", "criterion": "3%以上", "judge": judge_ge(data.get("roa"), 3)},
        "配当利回り": {"value": data.get("dividend_yield"), "unit": "%", "criterion": "3%以上", "judge": judge_ge(data.get("dividend_yield"), 3)},
        "自己資本比率": {"value": data.get("equity_ratio"), "unit": "%", "criterion": "35%以上", "judge": judge_ge(data.get("equity_ratio"), 35)},
        "時価総額": {"value": market_cap_oku, "unit": "億円", "criterion": "100億円以上", "judge": judge_ge(market_cap_oku, 100)},
    }
    judges = [row["judge"] for row in rows.values()]
    overall = "○" if all(j == "○" for j in judges) else ("要確認" if "要確認" in judges else "×")
    return {"rows": rows, "overall": overall}


def analyze_step2(
    eps_rows: list[dict[str, Any]],
    bps_rows: list[dict[str, Any]],
    dividend_rows: list[dict[str, Any]],
) -> dict:
    eps10 = eps_rows[-10:] if len(eps_rows) >= 10 else []
    bps10 = bps_rows[-10:] if len(bps_rows) >= 10 else []
    dividends10 = dividend_rows[-10:] if len(dividend_rows) >= 10 else []

    result: dict[str, dict[str, Any]] = {}

    if eps10:
        values = [float(row["value"]) for row in eps10]
        result["EPS10期赤字なし"] = {
            "judge": "○" if all(value >= 0 for value in values) else "×",
            "detail": f"赤字 {sum(value < 0 for value in values)}期",
        }
        if values[0] > 0:
            ratio = values[-1] / values[0]
            result["今期EPSが9期前の2倍以上"] = {
                "judge": "○" if ratio >= 2 else "×",
                "detail": f"{ratio:.2f}倍",
            }
        else:
            result["今期EPSが9期前の2倍以上"] = {
                "judge": "要確認",
                "detail": "9期前EPSが0円以下",
            }
    else:
        result["EPS10期赤字なし"] = {"judge": "要確認", "detail": f"{len(eps_rows)}期分取得"}
        result["今期EPSが9期前の2倍以上"] = {"judge": "要確認", "detail": f"{len(eps_rows)}期分取得"}

    if bps10:
        values = [float(row["value"]) for row in bps10]
        failures = sum(values[i] <= values[i - 1] for i in range(1, len(values)))
        result["BPS10期連続増加"] = {
            "judge": "○" if failures == 0 else "×",
            "detail": f"減少・横ばい {failures}回",
        }
    else:
        result["BPS10期連続増加"] = {"judge": "要確認", "detail": f"{len(bps_rows)}期分取得"}

    if dividends10:
        values = [float(row["value"]) for row in dividends10]
        decreases = sum(values[i] < values[i - 1] for i in range(1, len(values)))
        zero_count = sum(value <= 0 for value in values)
        result["10期で減配2回未満"] = {
            "judge": "○" if decreases < 2 else "×",
            "detail": f"減配 {decreases}回",
        }
        result["10期で無配なし"] = {
            "judge": "○" if zero_count == 0 else "×",
            "detail": f"無配 {zero_count}期",
        }
    else:
        result["10期で減配2回未満"] = {"judge": "要確認", "detail": f"{len(dividend_rows)}期分取得"}
        result["10期で無配なし"] = {"judge": "要確認", "detail": f"{len(dividend_rows)}期分取得"}

    judges = [item["judge"] for item in result.values()]
    overall = "○" if all(j == "○" for j in judges) else ("要確認" if "要確認" in judges else "×")
    return {
        "rows": result,
        "overall": overall,
        "eps10": eps10,
        "bps10": bps10,
        "dividends10": dividends10,
    }


def calculate_step3(eps_rows: list[dict[str, Any]], bps_rows: list[dict[str, Any]]) -> dict:
    if len(eps_rows) < 10 or not bps_rows:
        return {
            "eps_sum": None,
            "latest_bps": bps_rows[-1]["value"] if bps_rows else None,
            "target_price": None,
        }
    eps_sum = sum(float(row["value"]) for row in eps_rows[-10:])
    latest_bps = float(bps_rows[-1]["value"])
    return {
        "eps_sum": round(eps_sum, 2),
        "latest_bps": round(latest_bps, 2),
        "target_price": round(eps_sum + latest_bps, 2),
    }


def make_comment(step1: dict, step2: dict, cycle: str) -> str:
    notes: list[str] = []
    for name, row in step1["rows"].items():
        if row["judge"] == "×":
            if name in {"ROA", "自己資本比率"}:
                category = "業界特有の可能性"
                notes.append(f"{name}：{category}。同業他社との比較が必要。")
            elif name in {"PER", "PBR", "配当利回り"}:
                notes.append(f"{name}：株価・予想値で変動するため、更新時に再判定。")
            else:
                notes.append(f"{name}：構造的か一過性か、決算資料で確認。")
        elif row["judge"] == "要確認":
            notes.append(f"{name}：取得できず要確認。")

    for name, row in step2["rows"].items():
        if row["judge"] == "×":
            if "無配" in name or "減配" in name:
                notes.append(f"{name}：高配当株として重要な懸念。")
            elif "赤字" in name:
                note = "景気敏感株のため市況要因も考慮。" if cycle == "景気敏感" else ""
                notes.append(f"{name}：一過性損失か本業悪化か確認。{note}")
            elif "EPS" in name:
                notes.append(f"{name}：長期利益成長が基準未達。")
            elif "BPS" in name:
                notes.append(f"{name}：自社株買い・為替・損失等の原因確認が必要。")
        elif row["judge"] == "要確認":
            notes.append(f"{name}：10期データ不足のため要確認。")

    return " ".join(notes[:5]) if notes else "Step1・Step2の全項目で基準を満たしています。"


def overall_rating(step1: dict, step2: dict) -> str:
    if step1["overall"] == "○" and step2["overall"] == "○":
        return "監視継続"

    severe = [
        name
        for name, row in step2["rows"].items()
        if row["judge"] == "×" and ("無配" in name or "減配" in name or "赤字" in name)
    ]
    if severe:
        return "除外候補"
    return "条件付き監視"


def buy_zone(price: float | None, target_prices: list[float | None]) -> str:
    if price is None:
        return "要確認"
    valid = [value for value in target_prices if value not in (None, 0)]
    if not valid:
        return "買いライン未入力"

    p1, p2, p3 = (target_prices + [None, None, None])[:3]
    if p3 and price <= p3:
        return "第3買い到達"
    if p2 and price <= p2:
        return "第2買い到達"
    if p1 and price <= p1:
        return "第1買い到達"
    if p1 and price <= p1 * 1.03:
        return "第1買い接近"
    return "待機"
