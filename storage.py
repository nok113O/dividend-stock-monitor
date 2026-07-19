from __future__ import annotations

from io import BytesIO
from pathlib import Path
import pandas as pd


BASE_DIR = Path(__file__).parent
ROOT_WATCHLIST = BASE_DIR / "watchlist.csv"
WATCHLIST_PATH = ROOT_WATCHLIST

COLUMNS = [
    "コード", "銘柄名", "業種", "セクター", "景気区分",
    "現在株価", "予想年間配当", "現在利回り", "買い場判定",
    "PER", "PBR", "ROE", "ROA", "自己資本比率", "時価総額（億円）",
    "Step1", "Step2", "過去10期EPS合計", "最新BPS", "Step3目標株価",
    "総合判定",
    "第1目標利回り", "第1目標株価",
    "第2目標利回り", "第2目標株価",
    "第3目標利回り", "第3目標株価",
    "所感", "Yahoo取得状態", "IR BANK取得状態", "最終更新",
]


def empty_watchlist() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None:
        return empty_watchlist()
    df = df.copy()
    if "コード" in df.columns:
        df["コード"] = (
            df["コード"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
        )
    for column in COLUMNS:
        if column not in df.columns:
            df[column] = None
    return df[COLUMNS]


def load_watchlist() -> pd.DataFrame:
    if WATCHLIST_PATH.exists():
        try:
            return normalize(pd.read_csv(WATCHLIST_PATH, dtype={"コード": str}))
        except Exception:
            pass
    return empty_watchlist()


def save_watchlist(df: pd.DataFrame) -> None:
    normalize(df).to_csv(WATCHLIST_PATH, index=False, encoding="utf-8-sig")


def load_uploaded(file) -> pd.DataFrame:
    name = (getattr(file, "name", "") or "").lower()
    if name.endswith(".xlsx"):
        return normalize(pd.read_excel(file, sheet_name="監視銘柄一覧", dtype={"コード": str}))
    return normalize(pd.read_csv(file, dtype={"コード": str}))


def upsert(df: pd.DataFrame, row: dict) -> pd.DataFrame:
    df = normalize(df)
    code = str(row["コード"]).zfill(4)
    row["コード"] = code
    existing = (
        df["コード"].astype(str).str.zfill(4) == code
        if not df.empty
        else pd.Series([], dtype=bool)
    )

    manual_columns = [
        "第1目標利回り", "第1目標株価",
        "第2目標利回り", "第2目標株価",
        "第3目標利回り", "第3目標株価",
    ]
    if existing.any():
        old = df.loc[existing].iloc[0]
        for column in manual_columns:
            if row.get(column) in (None, "", 0, 0.0):
                row[column] = old.get(column)
        df = df.loc[~existing].copy()

    new_row = {column: row.get(column) for column in COLUMNS}
    output = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    return normalize(output).sort_values("コード").reset_index(drop=True)


def delete_code(df: pd.DataFrame, code: str) -> pd.DataFrame:
    code = str(code).zfill(4)
    return normalize(df[df["コード"].astype(str).str.zfill(4) != code].copy())


def to_excel_bytes(df: pd.DataFrame, detail_data: dict | None = None) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        normalize(df).to_excel(writer, sheet_name="監視銘柄一覧", index=False)
        if detail_data:
            for code, data in detail_data.items():
                for label, title in (
                    ("eps", "EPS"),
                    ("bps", "BPS"),
                    ("dividends", "一株配当"),
                ):
                    rows = data.get(label, [])
                    if rows:
                        pd.DataFrame(rows).rename(
                            columns={"year": "年度", "value": title}
                        ).to_excel(
                            writer,
                            sheet_name=f"{code}_{label}"[:31],
                            index=False,
                        )
    return output.getvalue()
