from __future__ import annotations

from io import BytesIO
import pandas as pd

WATCHLIST_COLUMNS = [
    "コード", "銘柄名", "業種", "セクター", "景気区分", "景気敏感判定理由",
    "現在株価", "株価日", "予想年間配当", "現在利回り",
    "PER", "PBR", "ROE", "ROA", "自己資本比率", "時価総額（億円）",
    "Step1", "Step2", "過去10期EPS合計", "最新BPS", "Step3目標株価",
    "総合判定", "買い場判定",
    "第1目標利回り", "第1目標株価",
    "第2目標利回り", "第2目標株価",
    "第3目標利回り", "第3目標株価",
    "所感", "最終更新",
]

HISTORY_COLUMNS = ["コード", "決算期", "EPS", "BPS", "1株配当", "データ元", "更新日"]

def empty_watchlist() -> pd.DataFrame:
    return pd.DataFrame(columns=WATCHLIST_COLUMNS)

def empty_history() -> pd.DataFrame:
    return pd.DataFrame(columns=HISTORY_COLUMNS)

def normalize_watchlist(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return empty_watchlist()
    df = df.copy()
    for col in WATCHLIST_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["コード"] = df["コード"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    return df[WATCHLIST_COLUMNS]

def normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return empty_history()
    df = df.copy()
    for col in HISTORY_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["コード"] = df["コード"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    return df[HISTORY_COLUMNS]

def read_workbook(uploaded_file) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        watchlist = pd.read_excel(uploaded_file, sheet_name="監視銘柄一覧", dtype={"コード": str})
        uploaded_file.seek(0)
        history = pd.read_excel(uploaded_file, sheet_name="10期履歴", dtype={"コード": str})
    except Exception as exc:
        raise ValueError("指定のテンプレート形式ではありません。監視銘柄一覧と10期履歴が必要です。") from exc
    return normalize_watchlist(watchlist), normalize_history(history)

def to_excel_bytes(watchlist: pd.DataFrame, history: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        normalize_watchlist(watchlist).to_excel(writer, sheet_name="監視銘柄一覧", index=False)
        normalize_history(history).to_excel(writer, sheet_name="10期履歴", index=False)

        guide = pd.DataFrame([
            ["運用方法", "初回は過去10期を10期履歴へ登録。以後はJ-Quants Freeで新しいFY決算を追加します。"],
            ["更新", "アプリで銘柄更新後、必ずExcelをダウンロードして次回アップロードしてください。"],
            ["APIキー", "Streamlit SecretsのJQUANTS_API_KEYを使用します。ExcelやGitHubには保存しません。"],
            ["Step3", "目標株価＝過去10期EPS合計＋最新BPS"],
        ], columns=["項目", "内容"])
        guide.to_excel(writer, sheet_name="使い方", index=False)
    return output.getvalue()
