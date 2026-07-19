from __future__ import annotations
from datetime import datetime
import pandas as pd
import streamlit as st

from analyzer import analyze_step1, analyze_step2, calculate_step3, make_comment, overall_rating
from data_fetcher import fetch_all
from sector_master import classify
from storage import load_watchlist, save_watchlist, upsert, to_excel_bytes

st.set_page_config(page_title="高配当株監視ツール", page_icon="📈", layout="wide")

@st.cache_data(ttl=1800, show_spinner=False)
def cached_fetch(code: str):
    return fetch_all(code)

def fmt(value, digits=2, suffix=""):
    if value is None or pd.isna(value):
        return "取得不可"
    return f"{value:,.{digits}f}{suffix}"

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

    st.markdown("### Step1")
    s1_rows = []
    for name, row in step1["rows"].items():
        s1_rows.append({
            "項目": name,
            "実績": fmt(row["value"], 2, row["unit"]),
            "基準": row["criterion"],
            "判定": row["judge"],
        })
    st.dataframe(pd.DataFrame(s1_rows), hide_index=True, use_container_width=True)
    st.write(f"**Step1総合：{step1['overall']}**")

    st.markdown("### Step2")
    s2_rows = [
        {"項目": name, "確認結果": row["detail"], "判定": row["judge"]}
        for name, row in step2["rows"].items()
    ]
    st.dataframe(pd.DataFrame(s2_rows), hide_index=True, use_container_width=True)
    st.write(f"**Step2総合：{step2['overall']}**")

    st.markdown("### Step3")
    t1, t2, t3 = st.columns(3)
    t1.metric("過去10期EPS合計", fmt(step3["eps_sum"], 2, "円"))
    t2.metric("最新BPS", fmt(step3["latest_bps"], 2, "円"))
    t3.metric("目標株価", fmt(step3["target_price"], 2, "円"))
    st.caption("目標株価 ＝ 過去10期EPS合計 ＋ 最新BPS")

    st.markdown("### 所感")
    st.write(comment)

    if data.get("irbank_error"):
        st.warning("IR BANKの自動取得に失敗しました。前提データをサイトで確認してください。")

    st.markdown(
        f"[Yahoo!ファイナンスを開く]({data['yahoo_url']})　"
        f"[IR BANKを開く]({data['irbank_url']})"
    )

    return {
        "sector": sector, "cycle": cycle, "step1": step1, "step2": step2,
        "step3": step3, "comment": comment, "rating": rating,
    }

st.title("高配当株監視ツール")
st.caption("Yahoo!ファイナンスとIR BANKを基に、Step1～3を自動判定します。取得結果は必ず元サイトでも確認してください。")

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()
if "last_data" not in st.session_state:
    st.session_state.last_data = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None

tab1, tab2 = st.tabs(["銘柄分析・追加", "監視リスト"])

with tab1:
    code = st.text_input("銘柄コード（4桁）", max_chars=4, placeholder="例：8058")
    col_a, col_b = st.columns(2)
    analyze_clicked = col_a.button("分析する", type="primary", use_container_width=True)
    refresh_clicked = col_b.button("キャッシュを消して再取得", use_container_width=True)

    if refresh_clicked:
        cached_fetch.clear()
        st.success("取得キャッシュを消去しました。もう一度「分析する」を押してください。")

    if analyze_clicked:
        try:
            with st.spinner("Yahoo!ファイナンス・IR BANKから取得中…"):
                data = cached_fetch(code)
            st.session_state.last_data = data
        except Exception as exc:
            st.error(f"取得できませんでした：{exc}")

    if st.session_state.last_data:
        data = st.session_state.last_data
        result = display_result(data)
        st.session_state.last_result = result

        st.markdown("### 3段階の買いライン")
        with st.form("buy_lines"):
            b1, b2 = st.columns(2)
            y1 = b1.number_input("第1目標利回り（%）", min_value=0.0, step=0.01)
            p1 = b2.number_input("第1目標株価（円）", min_value=0.0, step=1.0)
            b3, b4 = st.columns(2)
            y2 = b3.number_input("第2目標利回り（%）", min_value=0.0, step=0.01)
            p2 = b4.number_input("第2目標株価（円）", min_value=0.0, step=1.0)
            b5, b6 = st.columns(2)
            y3 = b5.number_input("第3目標利回り（%）", min_value=0.0, step=0.01)
            p3 = b6.number_input("第3目標株価（円）", min_value=0.0, step=1.0)
            add = st.form_submit_button("監視リストへ追加・更新", type="primary")

        if add:
            r = st.session_state.last_result
            row = {
                "コード": data["code"],
                "銘柄名": data.get("name"),
                "業種": data.get("industry"),
                "セクター": r["sector"],
                "景気区分": r["cycle"],
                "現在株価": data.get("price"),
                "予想年間配当": data.get("forecast_dividend"),
                "現在利回り": data.get("dividend_yield"),
                "Step1": r["step1"]["overall"],
                "Step2": r["step2"]["overall"],
                "Step3目標株価": r["step3"]["target_price"],
                "総合判定": r["rating"],
                "第1目標利回り": y1 or None, "第1目標株価": p1 or None,
                "第2目標利回り": y2 or None, "第2目標株価": p2 or None,
                "第3目標利回り": y3 or None, "第3目標株価": p3 or None,
                "所感": r["comment"],
                "最終更新": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            st.session_state.watchlist = upsert(st.session_state.watchlist, row)
            save_watchlist(st.session_state.watchlist)
            st.success("監視リストへ追加・更新しました。")

with tab2:
    st.info(
        "Streamlit Community Cloudでは端末や再起動により保存が消える可能性があります。"
        "更新後はExcelをダウンロードして保管してください。"
    )
    edited = st.data_editor(
        st.session_state.watchlist,
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="watchlist_editor",
    )
    c1, c2 = st.columns(2)
    if c1.button("編集内容を保存", use_container_width=True):
        st.session_state.watchlist = edited
        save_watchlist(edited)
        st.success("保存しました。")
    excel = to_excel_bytes(edited)
    c2.download_button(
        "Excelをダウンロード",
        data=excel,
        file_name=f"高配当株監視リスト_{datetime.now():%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.divider()
st.caption(
    "注意：Yahoo!ファイナンス・IR BANKのページ仕様変更、反映時点、株式分割等により、"
    "取得不能または異常値になる場合があります。投資判断は各社IR資料を含めて確認してください。"
)
