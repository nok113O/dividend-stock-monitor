from __future__ import annotations
from pathlib import Path
from io import BytesIO
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
WATCHLIST_PATH = DATA_DIR / "watchlist.csv"

COLUMNS = [
    "コード", "銘柄名", "業種", "セクター", "景気区分",
    "現在株価", "予想年間配当", "現在利回り",
    "Step1", "Step2", "Step3目標株価", "総合判定",
    "第1目標利回り", "第1目標株価",
    "第2目標利回り", "第2目標株価",
    "第3目標利回り", "第3目標株価",
    "所感", "最終更新"
]

def load_watchlist() -> pd.DataFrame:
    if WATCHLIST_PATH.exists():
        try:
            df = pd.read_csv(WATCHLIST_PATH, dtype={"コード": str})
        except Exception:
            df = pd.DataFrame(columns=COLUMNS)
    else:
        df = pd.DataFrame(columns=COLUMNS)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[COLUMNS]

def save_watchlist(df: pd.DataFrame) -> None:
    df.to_csv(WATCHLIST_PATH, index=False, encoding="utf-8-sig")

def upsert(df: pd.DataFrame, row: dict) -> pd.DataFrame:
    code = str(row["コード"]).zfill(4)
    row["コード"] = code
    existing = df["コード"].astype(str).str.zfill(4) == code if not df.empty else pd.Series([], dtype=bool)

    # 手動入力の買いラインは更新時も維持
    manual_cols = [
        "第1目標利回り", "第1目標株価",
        "第2目標利回り", "第2目標株価",
        "第3目標利回り", "第3目標株価",
    ]
    if existing.any():
        old = df.loc[existing].iloc[0]
        for col in manual_cols:
            if row.get(col) in (None, ""):
                row[col] = old.get(col)
        df = df.loc[~existing].copy()

    new_row = {col: row.get(col) for col in COLUMNS}
    return pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

def to_excel_bytes(df: pd.DataFrame, details: dict | None = None) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="監視銘柄一覧", index=False)
        if details:
            for key, values in details.items():
                if isinstance(values, list):
                    pd.DataFrame({"値": values}).to_excel(
                        writer, sheet_name=key[:31], index=False
                    )
    return output.getvalue()
