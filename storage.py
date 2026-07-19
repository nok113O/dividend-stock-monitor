from __future__ import annotations
from pathlib import Path
from io import BytesIO
import pandas as pd

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Current repository has watchlist.csv at root. Prefer it so updates preserve the same file.
ROOT_WATCHLIST = BASE_DIR / "watchlist.csv"
DATA_WATCHLIST = DATA_DIR / "watchlist.csv"
WATCHLIST_PATH = ROOT_WATCHLIST if ROOT_WATCHLIST.exists() else DATA_WATCHLIST

COLUMNS = [
    "コード", "銘柄名", "業種", "セクター", "景気区分",
    "現在株価", "予想年間配当", "現在利回り",
    "PER", "PBR", "ROE", "ROA", "自己資本比率", "時価総額（億円）",
    "Step1", "Step2", "過去10期EPS合計", "最新BPS", "Step3目標株価",
    "総合判定",
    "第1目標利回り", "第1目標株価",
    "第2目標利回り", "第2目標株価",
    "第3目標利回り", "第3目標株価",
    "所感", "Yahoo取得状態", "IR BANK取得状態", "最終更新"
]

def empty_watchlist() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return empty_watchlist()
    df = df.copy()
    if "コード" in df.columns:
        df["コード"] = df["コード"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[COLUMNS]

def load_watchlist() -> pd.DataFrame:
    if WATCHLIST_PATH.exists():
        try:
            return normalize(pd.read_csv(WATCHLIST_PATH, dtype={"コード": str}))
        except Exception:
            return empty_watchlist()
    return empty_watchlist()

def load_uploaded(file) -> pd.DataFrame:
    name = (getattr(file, "name", "") or "").lower()
    if name.endswith(".xlsx"):
        df = pd.read_excel(file, sheet_name="監視銘柄一覧", dtype={"コード": str})
    else:
        df = pd.read_csv(file, dtype={"コード": str})
    return normalize(df)

def save_watchlist(df: pd.DataFrame) -> None:
    normalize(df).to_csv(WATCHLIST_PATH, index=False, encoding="utf-8-sig")

def upsert(df: pd.DataFrame, row: dict) -> pd.DataFrame:
    df = normalize(df)
    code = str(row["コード"]).zfill(4)
    row["コード"] = code
    existing = df["コード"].astype(str).str.zfill(4) == code if not df.empty else pd.Series([], dtype=bool)

    manual_cols = [
        "第1目標利回り", "第1目標株価",
        "第2目標利回り", "第2目標株価",
        "第3目標利回り", "第3目標株価",
    ]
    if existing.any():
        old = df.loc[existing].iloc[0]
        for col in manual_cols:
            if row.get(col) in (None, "", 0, 0.0):
                row[col] = old.get(col)
        df = df.loc[~existing].copy()

    new_row = {col: row.get(col) for col in COLUMNS}
    out = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    return normalize(out).sort_values("コード").reset_index(drop=True)

def to_excel_bytes(df: pd.DataFrame, detail_data: dict | None = None) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        normalize(df).to_excel(writer, sheet_name="監視銘柄一覧", index=False)
        if detail_data:
            for code, data in detail_data.items():
                for label in ("eps", "bps", "dividends"):
                    values = data.get(label, [])
                    if values:
                        sheet = f"{code}_{label}"[:31]
                        pd.DataFrame({"古い期→新しい期": values}).to_excel(
                            writer, sheet_name=sheet, index=False
                        )
    return output.getvalue()
