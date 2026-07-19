from __future__ import annotations
from datetime import datetime
import pandas as pd
import streamlit as st

from analyzer import analyze_step1, analyze_step2, calculate_step3, make_comment, overall_rating
from data_fetcher import fetch_all
from sector_master import classify
from storage import load_watchlist, load_uploaded, save_watchlist, upsert, to_excel_bytes

st.set_page_config(page_title="高配当株監視ツール Ver.2.0", page_icon="📈", layout="wide")

@st.cache_data(ttl=1800, show_spinner=False)
def cached_fetch(code: str):
    return fetch_all(code)

def fmt(value, digits=2, suffix=""):
    if value is None or pd.isna(value):
        return "取得不可"
    return f"{value:,.{digits}f}{suffix}"

def existing_lines(df: pd.DataFrame, code: str) -> dict:
    if df.empty:
        return {}
    hit = df[df["コード"].astype(str).str.zfill(4) == str(code).zfill(4)]
    return hit.iloc[0].to_dict() if not hit.empty else {}

def display_series(label: str, values: list[float]):
    st.write(f"**{label}（古い期 → 新しい期）**")
    if values:
        st.dataframe(
            pd.DataFrame({"期": list(range(1, len(values) + 1)), label: values}),
            hide_index=True, use_container_width=True
        )
    else:
        st.info("取得できませんでした。IR BANKリンクで確認してください。")

def display_result(data: dict):
    sector, cycle = classify(data.get("industry"))
    step1 = analyze_step1(data)
    step2 = analyze_step2(data.get("eps", []), data.get("bps", []), data.get("dividends", []))
    step3 = calculate_step3(data.get("eps", []), data.get("bps", []))
    comment = make_comment(step1, step2)
    rating = overall_rating(step1, step2)

    st.subheader(f"{data['code']}　{data.get('name') or ''}")
    st.caption(
        f"業種：{data.get('industry') or '取得不可'} ｜ "
        f"セクター：{sector} ｜ 景気区分：{cycle}"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("現在株価", fmt(data.get("price"), 0, "円"))
    c2.metric("予想年間配当", fmt(data.get("forecast_dividend"), 2, "円"))
    c3.metric("現在利回り", fmt(data.get("dividend_yield"), 2, "%"))
    c4.metric("総合判定", rating)

    with st.expander("データ取得状態", expanded=True):
        status_df = pd.DataFrame([
            {"データ元": "Yahoo!ファイナンス系", "状態": data.get("yahoo_status", "不明"),
             "用途": "株価・予想配当・PER・PBR・ROE・時価総額"},
            {"データ元": "IR BANK", "状態": data.get("irbank_status", "不明"),
             "用途": "過去EPS・BPS・配当・ROA・自己資本比率"},
        ])
        st.dataframe(status_df, hide_index=True, use_container_width=True)
        if data.get("yahoo_error"):
            st.caption(f"Yahoo取得メモ：{data['yahoo_error']}")
        if data.get("irbank_error"):
            st.caption(f"IR BANK取得メモ：{data['irbank_error']}")

    st.markdown("### Step1：定量スクリーニング")
    s1_rows = [{
        "項目": name,
        "実績": fmt(row["value"], 2, row["unit"]),
        "基準": row["criterion"],
        "判定": row["judge"],
    } for name, row in step1["rows"].items()]
    st.dataframe(pd.DataFrame(s1_rows), hide_index=True, use_container_width=True)
    st.write(f"**Step1総合：{step1['overall']}**")

    st.markdown("### Step2：過去10期推移")
    s2_rows = [{"項目": name, "確認結果": row["detail"], "判定": row["judge"]}
               for name, row in step2["rows"].items()]
    st.dataframe(pd.DataFrame(s2_rows), hide_index=True, use_container_width=True)
    st.write(f"**Step2総合：{step2['overall']}**")

    with st.expander("過去10期の実数を見る"):
        display_series("EPS", step2["eps10"])
        display_series("BPS", step2["bps10"])
        display_series("1株配当", step2["dividends10"])

    st.markdown("### Step3：目標株価")
    t1, t2, t3 = st.columns(3)
    t1.metric("過去10期EPS合計", fmt(step3["eps_sum"], 2, "円"))
    t2.metric("最新BPS", fmt(step3["latest_bps"], 2, "円"))
    t3.metric("目標株価", fmt(step3["target_price"], 2, "円"))
    st.caption("目標株価 ＝ 過去10期EPS合計 ＋ 最新BPS")

    st.markdown("### ×項目の所感")
    st.write(comment)
    st.write(f"**総合判定：{rating}**")

    st.markdown(
        f"[Yahoo!ファイナンスを開く]({data['yahoo_url']})　"
        f"[IR BANKを開く]({data['irbank_url']})"
    )
    return {
        "sector": sector, "cycle": cycle, "step1": step1, "step2": step2,
        "step3": step3, "comment": comment, "rating": rating,
    }

st.title("高配当株監視ツール Ver.2.0")
st.caption("銘柄コードだけで基本情報・Step1～3・所感を表示し、監視リストへ保存します。")

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()
if "last_data" not in st.session_state:
    st.session_state.last_data = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "details" not in st.session_state:
    st.session_state.details = {}

tab1, tab2 = st.tabs(["銘柄分析・追加", "監視リスト"])

with tab1:
    code = st.text_input("銘柄コード（4桁）", max_chars=4, placeholder="例：1605")
    c1, c2 = st.columns(2)
    analyze_clicked = c1.button("分析する", type="primary", use_container_width=True)
    refresh_clicked = c2.button("キャッシュを消して再取得", use_container_width=True)

    if refresh_clicked:
        cached_fetch.clear()
        st.success("キャッシュを消去しました。「分析する」を押してください。")

    if analyze_clicked:
        try:
            with st.spinner("Yahoo!ファイナンス・IR BANKから取得中…"):
                st.session_state.last_data = cached_fetch(code)
        except Exception as exc:
            st.error(f"取得できませんでした：{exc}")

    if st.session_state.last_data:
        data = st.session_state.last_data
        result = display_result(data)
        st.session_state.last_result = result
        st.session_state.details[data["code"]] = {
            "eps": result["step2"]["eps10"],
            "bps": result["step2"]["bps10"],
            "dividends": result["step2"]["dividends10"],
        }

        old = existing_lines(st.session_state.watchlist, data["code"])
        st.markdown("### 3段階の買いライン")
        st.caption("ここは自動変更せず、入力した値を銘柄ごとに保存します。")
        with st.form(f"buy_lines_{data['code']}"):
            b1, b2 = st.columns(2)
            y1 = b1.number_input("第1目標利回り（%）", min_value=0.0, step=0.01,
                                 value=float(old.get("第1目標利回り") or 0))
            p1 = b2.number_input("第1目標株価（円）", min_value=0.0, step=1.0,
                                 value=float(old.get("第1目標株価") or 0))
            b3, b4 = st.columns(2)
            y2 = b3.number_input("第2目標利回り（%）", min_value=0.0, step=0.01,
                                 value=float(old.get("第2目標利回り") or 0))
            p2 = b4.number_input("第2目標株価（円）", min_value=0.0, step=1.0,
                                 value=float(old.get("第2目標株価") or 0))
            b5, b6 = st.columns(2)
            y3 = b5.number_input("第3目標利回り（%）", min_value=0.0, step=0.01,
                                 value=float(old.get("第3目標利回り") or 0))
            p3 = b6.number_input("第3目標株価（円）", min_value=0.0, step=1.0,
                                 value=float(old.get("第3目標株価") or 0))
            add = st.form_submit_button("監視リストへ追加・更新", type="primary")

        if add:
            r = st.session_state.last_result
            s1 = r["step1"]["rows"]
            market_cap_oku = s1["時価総額"]["value"]
            row = {
                "コード": data["code"], "銘柄名": data.get("name"), "業種": data.get("industry"),
                "セクター": r["sector"], "景気区分": r["cycle"],
                "現在株価": data.get("price"), "予想年間配当": data.get("forecast_dividend"),
                "現在利回り": data.get("dividend_yield"),
                "PER": data.get("per"), "PBR": data.get("pbr"), "ROE": data.get("roe"),
                "ROA": data.get("roa"), "自己資本比率": data.get("equity_ratio"),
                "時価総額（億円）": market_cap_oku,
                "Step1": r["step1"]["overall"], "Step2": r["step2"]["overall"],
                "過去10期EPS合計": r["step3"]["eps_sum"], "最新BPS": r["step3"]["latest_bps"],
                "Step3目標株価": r["step3"]["target_price"], "総合判定": r["rating"],
                "第1目標利回り": y1 or None, "第1目標株価": p1 or None,
                "第2目標利回り": y2 or None, "第2目標株価": p2 or None,
                "第3目標利回り": y3 or None, "第3目標株価": p3 or None,
                "所感": r["comment"],
                "Yahoo取得状態": data.get("yahoo_status"),
                "IR BANK取得状態": data.get("irbank_status"),
                "最終更新": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            st.session_state.watchlist = upsert(st.session_state.watchlist, row)
            save_watchlist(st.session_state.watchlist)
            st.success("監視リストへ追加・更新しました。")

with tab2:
    st.warning(
        "Streamlit Community Cloudのローカル保存は永続性が保証されません。"
        "更新後はExcelをダウンロードしてください。次回、Excelをアップロードして復元できます。"
    )

    uploaded = st.file_uploader("以前の監視リストを復元（ExcelまたはCSV）", type=["xlsx", "csv"])
    if uploaded is not None and st.button("アップロードした監視リストを読み込む"):
        try:
            st.session_state.watchlist = load_uploaded(uploaded)
            save_watchlist(st.session_state.watchlist)
            st.success("監視リストを読み込みました。")
        except Exception as exc:
            st.error(f"読み込めませんでした：{exc}")

    edited = st.data_editor(
        st.session_state.watchlist, hide_index=True, use_container_width=True,
        num_rows="dynamic", key="watchlist_editor_v2",
    )
    x1, x2 = st.columns(2)
    if x1.button("編集内容を保存", use_container_width=True):
        st.session_state.watchlist = edited
        save_watchlist(edited)
        st.success("保存しました。")
    excel = to_excel_bytes(edited, st.session_state.details)
    x2.download_button(
        "Excelをダウンロード",
        data=excel,
        file_name=f"高配当株監視リスト_{datetime.now():%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.divider()
st.caption(
    "自動取得値はサイトの反映時点・ページ仕様・株式分割等により異常値になる場合があります。"
    "判定前に画面内の元サイトリンクでも確認してください。"
)
