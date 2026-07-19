from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import math

def _ok_number(value: Any) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))

def judge_le(value: float | None, limit: float) -> str:
    return "○" if _ok_number(value) and value <= limit else ("×" if _ok_number(value) else "要確認")

def judge_ge(value: float | None, limit: float) -> str:
    return "○" if _ok_number(value) and value >= limit else ("×" if _ok_number(value) else "要確認")

def analyze_step1(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    market_cap_oku = None
    if _ok_number(data.get("market_cap")):
        market_cap_oku = float(data["market_cap"]) / 100_000_000

    rows = {
        "PER": {"value": data.get("per"), "unit": "倍", "criterion": "12倍以下",
                "judge": judge_le(data.get("per"), 12)},
        "PBR": {"value": data.get("pbr"), "unit": "倍", "criterion": "1.3倍以下",
                "judge": judge_le(data.get("pbr"), 1.3)},
        "ROE": {"value": data.get("roe"), "unit": "%", "criterion": "7%以上",
                "judge": judge_ge(data.get("roe"), 7)},
        "ROA": {"value": data.get("roa"), "unit": "%", "criterion": "3%以上",
                "judge": judge_ge(data.get("roa"), 3)},
        "配当利回り": {"value": data.get("dividend_yield"), "unit": "%", "criterion": "3%以上",
                "judge": judge_ge(data.get("dividend_yield"), 3)},
        "自己資本比率": {"value": data.get("equity_ratio"), "unit": "%", "criterion": "35%以上",
                "judge": judge_ge(data.get("equity_ratio"), 35)},
        "時価総額": {"value": market_cap_oku, "unit": "億円", "criterion": "100億円以上",
                "judge": judge_ge(market_cap_oku, 100)},
    }
    judges = [r["judge"] for r in rows.values()]
    overall = "○" if all(j == "○" for j in judges) else ("要確認" if "要確認" in judges else "×")
    return {"rows": rows, "overall": overall}

def analyze_step2(eps: list[float], bps: list[float], dividends: list[float]) -> dict[str, dict[str, Any]]:
    # リストは古い期→新しい期の順
    result: dict[str, dict[str, Any]] = {}

    if len(eps) >= 10:
        e = eps[-10:]
        result["EPS10期赤字なし"] = {
            "judge": "○" if all(x >= 0 for x in e) else "×",
            "detail": f"最低EPS {min(e):,.2f}円"
        }
        if e[0] > 0:
            ratio = e[-1] / e[0]
            result["今期EPSが9期前の2倍以上"] = {
                "judge": "○" if ratio >= 2 else "×",
                "detail": f"{ratio:.2f}倍"
            }
        else:
            result["今期EPSが9期前の2倍以上"] = {
                "judge": "要確認",
                "detail": "9期前EPSが0円以下のため単純比較不可"
            }
    else:
        result["EPS10期赤字なし"] = {"judge": "要確認", "detail": f"{len(eps)}期分のみ取得"}
        result["今期EPSが9期前の2倍以上"] = {"judge": "要確認", "detail": f"{len(eps)}期分のみ取得"}

    if len(bps) >= 10:
        b = bps[-10:]
        increases = [b[i] > b[i-1] for i in range(1, len(b))]
        failed = sum(not x for x in increases)
        result["BPS10期連続増加"] = {
            "judge": "○" if all(increases) else "×",
            "detail": f"減少・横ばい {failed}回"
        }
    else:
        result["BPS10期連続増加"] = {"judge": "要確認", "detail": f"{len(bps)}期分のみ取得"}

    if len(dividends) >= 10:
        d = dividends[-10:]
        decreases = sum(d[i] < d[i-1] for i in range(1, len(d)))
        zero_count = sum(x <= 0 for x in d)
        result["10期で減配2回未満"] = {
            "judge": "○" if decreases < 2 else "×",
            "detail": f"減配 {decreases}回"
        }
        result["10期で無配なし"] = {
            "judge": "○" if zero_count == 0 else "×",
            "detail": f"無配 {zero_count}期"
        }
    else:
        result["10期で減配2回未満"] = {"judge": "要確認", "detail": f"{len(dividends)}期分のみ取得"}
        result["10期で無配なし"] = {"judge": "要確認", "detail": f"{len(dividends)}期分のみ取得"}

    judges = [x["judge"] for x in result.values()]
    overall = "○" if all(j == "○" for j in judges) else ("要確認" if "要確認" in judges else "×")
    return {"rows": result, "overall": overall}

def calculate_step3(eps: list[float], bps: list[float]) -> dict[str, float | None]:
    if len(eps) < 10 or not bps:
        return {"eps_sum": None, "latest_bps": bps[-1] if bps else None, "target_price": None}
    eps_sum = sum(eps[-10:])
    latest_bps = bps[-1]
    return {
        "eps_sum": round(eps_sum, 2),
        "latest_bps": round(latest_bps, 2),
        "target_price": round(eps_sum + latest_bps, 2),
    }

def make_comment(step1: dict, step2: dict) -> str:
    notes = []
    industry_sensitive = {"ROA", "自己資本比率"}
    for name, row in step1["rows"].items():
        if row["judge"] == "×":
            if name in industry_sensitive:
                notes.append(f"{name}は基準未達。業界特性の影響もあるため同業比較が必要。")
            elif name in {"PER", "PBR", "配当利回り"}:
                notes.append(f"{name}は基準未達。株価または会社予想の変化で動くため更新時に再確認。")
            else:
                notes.append(f"{name}は基準未達。構造的か一過性か決算資料で確認。")
        elif row["judge"] == "要確認":
            notes.append(f"{name}は自動取得できず要確認。")

    for name, row in step2["rows"].items():
        if row["judge"] == "×":
            if "減配" in name or "無配" in name:
                notes.append(f"{name}は基準未達。高配当株として重要な懸念。")
            elif "EPS" in name:
                notes.append(f"{name}は基準未達。一過性損失か収益力低下かを確認。")
            elif "BPS" in name:
                notes.append(f"{name}は基準未達。自社株買い・為替・損失など原因確認が必要。")
        elif row["judge"] == "要確認":
            notes.append(f"{name}は10期データ不足または取得失敗のため要確認。")

    return " ".join(notes[:4]) if notes else "全項目で基準を満たしています。"

def overall_rating(step1: dict, step2: dict) -> str:
    if step2["overall"] == "○" and step1["overall"] == "○":
        return "監視継続"
    severe = [
        k for k, v in step2["rows"].items()
        if v["judge"] == "×" and ("無配" in k or "減配" in k or "赤字" in k)
    ]
    if severe:
        return "除外候補"
    return "条件付き監視"
