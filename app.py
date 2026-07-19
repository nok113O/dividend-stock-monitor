from __future__ import annotations

from datetime import datetime
import time

import pandas as pd
import streamlit as st

from analyzer import (
    analyze_step1,
    analyze_step2,
    buy_zone,
    calculate_step3,
    make_comment,
    overall_rating,
)
from data_fetcher import fetch_all
from sector_master import classify
from storage import (
    delete_code,
    load_uploaded,
    load_watchlist,
    save_watchlist,
    to_excel_bytes,
    upsert,
)


st.set_page_config(
    page_title="高配当株監視ツール Ver.3.1",
    page_icon="📈",
    layout="wide",
)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_fetch(code: str):
    return fetch_all(code)


def fmt(value, digits=2, suffix=""):
    if value is None or pd.isna(value):
        return "取得不可"
    return f"{value:,.{digits}f}{suffix}"


def rows_table(rows: list[dict], label: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["年度", label])
    return pd.DataFrame(rows).rename(columns={"year": "年度", "value": label})


def existing_record(df: pd.DataFrame, code: str) -> dict:
    if df.empty:
        return {}
    hit = df[df["コード"].astype(str).str.zfill(4) == str(code).zfill(4)]
    return hit.iloc[0].to_dict() if not hit.empty else {}


def analyze_data(data: dict) -> dict:
    sector, cycle = classify(data.get("industry"))
    step1 = analyze_step1(data)
    step2 = analyze_step2(
        data.get("eps_rows", []),
        data.get("bps_rows", []),
        data.get("dividend_rows", []),
    )
    step3 = calculate_step3(
        data.get("eps_rows", []),
        data.get("bps_rows", []),
    )
    comment = make_comment(step1, step2, cycle)
    rating = overall_rating(step1, step2)
    return {
        "sector": sector,
        "cycle": cycle,
        "step1": step1,
        "step2": step2,
        "step3": step3,
        "comment": comment,
        "rating": rating,
    }


def display_analysis(data: dict, result: dict) -> None:
    st.subheader(f"{data['code']}　{data.get('name') or ''}")
    st.caption(
        f"業種：{data.get('industry') or '取得不可'} ｜ "
        f"セクター：{result['sector']} ｜ 景気区分：{result['cycle']}"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("現在株価", fmt(data.get("price"), 0, "円"))
    c2.metric("予想年間配当", fmt(data.get("forecast_dividend"), 2, "円"))
    c3.metric("現在利回り", fmt(data.get("dividend_yield"), 2, "%"))
    c4.metric("総合判定", result["rating"])

    with st.expander("データ取得状態", expanded=True):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "データ元": "Yahoo!ファイナンス系",
                        "状態": data.get("yahoo_status", "不明"),
                        "用途": "株価・予想配当・主要指標",
                    },
                    {
                        "データ元": "IR BANK",
                        "状態": data.get("irbank_status", "不明"),
                        "用途": "過去EPS・BPS・一株配当、指標補完",
                    },
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        if data.get("irbank_error"):
            st.caption(f"IR BANK取得メモ：{data['irbank_error']}")

    st.markdown("### Step1：定量スクリーニング")
    step1_rows = []
    for name, row in result["step1"]["rows"].items():
        step1_rows.append(
            {
                "項目": name,
                "実績": fmt(row["value"], 2, row["unit"]),
                "基準": row["criterion"],
                "判定": row["judge"],
            }
        )
    st.dataframe(pd.DataFrame(step1_rows), hide_index=True, use_container_width=True)
    st.write(f"**Step1総合：{result['step1']['overall']}**")

    st.markdown("### Step2：過去10期推移")
    step2_rows = [
        {"項目": name, "確認結果": row["detail"], "判定": row["judge"]}
        for name, row in result["step2"]["rows"].items()
    ]
    st.dataframe(pd.DataFrame(step2_rows), hide_index=True, use_container_width=True)
    st.write(f"**Step2総合：{result['step2']['overall']}**")

    with st.expander("過去10期の実数を見る", expanded=False):
        st.write("**EPS（古い期 → 新しい期）**")
        st.dataframe(
            rows_table(result["step2"]["eps10"], "EPS"),
            hide_index=True,
            use_container_width=True,
        )
        st.write("**BPS（古い期 → 新しい期）**")
        st.dataframe(
            rows_table(result["step2"]["bps10"], "BPS"),
            hide_index=True,
            use_container_width=True,
        )
        st.write("**一株配当（古い期 → 新しい期）**")
        st.dataframe(
            rows_table(result["step2"]["dividends10"], "一株配当"),
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("### Step3：目標株価")
    t1, t2, t3 = st.columns(3)
    t1.metric("過去10期EPS合計", fmt(result["step3"]["eps_sum"], 2, "円"))
    t2.metric("最新BPS", fmt(result["step3"]["latest_bps"], 2, "円"))
    t3.metric("目標株価", fmt(result["step3"]["target_price"], 2, "円"))
    st.caption("目標株価 ＝ 過去10期EPS合計 ＋ 最新BPS")

    st.markdown("### ×項目の所感")
    st.write(result["comment"])

    st.markdown(
        f"[Yahoo!ファイナンスを開く]({data['yahoo_url']})　"
        f"[IR BANKを開く]({data['irbank_url']})"
    )


def build_watchlist_row(data: dict, result: dict, lines: dict) -> dict:
    targets = [
        lines.get("第1目標株価"),
        lines.get("第2目標株価"),
        lines.get("第3目標株価"),
    ]
    step1_rows = result["step1"]["rows"]
    return {
        "コード": data["code"],
        "銘柄名": data.get("name"),
        "業種": data.get("industry"),
        "セクター": result["sector"],
        "景気区分": result["cycle"],
        "現在株価": data.get("price"),
        "予想年間配当": data.get("forecast_dividend"),
        "現在利回り": data.get("dividend_yield"),
        "買い場判定": buy_zone(data.get("price"), targets),
        "PER": data.get("per"),
        "PBR": data.get("pbr"),
        "ROE": data.get("roe"),
        "ROA": data.get("roa"),
        "自己資本比率": data.get("equity_ratio"),
        "時価総額（億円）": step1_rows["時価総額"]["value"],
        "Step1": result["step1"]["overall"],
        "Step2": result["step2"]["overall"],
        "過去10期EPS合計": result["step3"]["eps_sum"],
        "最新BPS": result["step3"]["latest_bps"],
        "Step3目標株価": result["step3"]["target_price"],
        "総合判定": result["rating"],
        **lines,
        "所感": result["comment"],
        "Yahoo取得状態": data.get("yahoo_status"),
        "IR BANK取得状態": data.get("irbank_status"),
        "最終更新": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


st.title("高配当株監視ツール Ver.3.1")
st.caption(
    "銘柄コード入力、Step1～3判定、3段階買いライン、監視リスト更新までを一画面で行います。"
)

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()
if "last_data" not in st.session_state:
    st.session_state.last_data = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "details" not in st.session_state:
    st.session_state.details = {}

tab_analyze, tab_watch, tab_update = st.tabs(
    ["銘柄分析・追加", "監視リスト", "全銘柄更新"]
)

with tab_analyze:
    code = st.text_input("銘柄コード（4桁）", max_chars=4, placeholder="例：1605")
    a1, a2 = st.columns(2)
    analyze_clicked = a1.button("分析する", type="primary", use_container_width=True)
    refresh_clicked = a2.button("キャッシュを消して再取得", use_container_width=True)

    if refresh_clicked:
        cached_fetch.clear()
        st.success("キャッシュを消去しました。")

    if analyze_clicked:
        try:
            with st.spinner("Yahoo!ファイナンス・IR BANKから取得中…"):
                st.session_state.last_data = cached_fetch(code)
                st.session_state.last_result = analyze_data(st.session_state.last_data)
        except Exception as exc:
            st.error(f"取得できませんでした：{exc}")

    if st.session_state.last_data and st.session_state.last_result:
        data = st.session_state.last_data
        result = st.session_state.last_result
        display_analysis(data, result)

        st.session_state.details[data["code"]] = {
            "eps": data.get("eps_rows", []),
            "bps": data.get("bps_rows", []),
            "dividends": data.get("dividend_rows", []),
        }

        old = existing_record(st.session_state.watchlist, data["code"])
        st.markdown("### 3段階の買いライン")
        st.caption("目標利回り・目標株価は自動変更せず、入力値を維持します。")

        with st.form(f"buy_lines_{data['code']}"):
            b1, b2 = st.columns(2)
            y1 = b1.number_input(
                "第1目標利回り（%）",
                min_value=0.0,
                step=0.01,
                value=float(old.get("第1目標利回り") or 0),
            )
            p1 = b2.number_input(
                "第1目標株価（円）",
                min_value=0.0,
                step=1.0,
                value=float(old.get("第1目標株価") or 0),
            )
            b3, b4 = st.columns(2)
            y2 = b3.number_input(
                "第2目標利回り（%）",
                min_value=0.0,
                step=0.01,
                value=float(old.get("第2目標利回り") or 0),
            )
            p2 = b4.number_input(
                "第2目標株価（円）",
                min_value=0.0,
                step=1.0,
                value=float(old.get("第2目標株価") or 0),
            )
            b5, b6 = st.columns(2)
            y3 = b5.number_input(
                "第3目標利回り（%）",
                min_value=0.0,
                step=0.01,
                value=float(old.get("第3目標利回り") or 0),
            )
            p3 = b6.number_input(
                "第3目標株価（円）",
                min_value=0.0,
                step=1.0,
                value=float(old.get("第3目標株価") or 0),
            )
            save_clicked = st.form_submit_button(
                "監視リストへ追加・更新",
                type="primary",
            )

        targets = [p1 or None, p2 or None, p3 or None]
        st.metric("現在の買い場判定", buy_zone(data.get("price"), targets))

        if save_clicked:
            lines = {
                "第1目標利回り": y1 or None,
                "第1目標株価": p1 or None,
                "第2目標利回り": y2 or None,
                "第2目標株価": p2 or None,
                "第3目標利回り": y3 or None,
                "第3目標株価": p3 or None,
            }
            row = build_watchlist_row(data, result, lines)
            st.session_state.watchlist = upsert(st.session_state.watchlist, row)
            save_watchlist(st.session_state.watchlist)
            st.success("監視リストへ追加・更新しました。")

with tab_watch:
    st.warning(
        "Streamlit Community Cloudのローカル保存は永続性が保証されません。"
        "更新後はExcelをダウンロードしてください。"
    )

    uploaded = st.file_uploader(
        "以前の監視リストを復元（ExcelまたはCSV）",
        type=["xlsx", "csv"],
    )
    if uploaded is not None and st.button("アップロードした監視リストを読み込む"):
        try:
            st.session_state.watchlist = load_uploaded(uploaded)
            save_watchlist(st.session_state.watchlist)
            st.success("監視リストを読み込みました。")
        except Exception as exc:
            st.error(f"読み込めませんでした：{exc}")

    edited = st.data_editor(
        st.session_state.watchlist,
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="watchlist_editor_v3",
    )

    w1, w2 = st.columns(2)
    if w1.button("編集内容を保存", use_container_width=True):
        st.session_state.watchlist = edited
        save_watchlist(edited)
        st.success("保存しました。")

    excel = to_excel_bytes(edited, st.session_state.details)
    w2.download_button(
        "Excelをダウンロード",
        data=excel,
        file_name=f"高配当株監視リスト_{datetime.now():%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    with st.expander("銘柄を監視リストから削除"):
        delete_target = st.selectbox(
            "削除する銘柄",
            options=edited["コード"].tolist() if not edited.empty else [],
        )
        if delete_target and st.button("選択銘柄を削除"):
            st.session_state.watchlist = delete_code(edited, delete_target)
            save_watchlist(st.session_state.watchlist)
            st.success(f"{delete_target}を削除しました。")
            st.rerun()

with tab_update:
    st.write("登録済み銘柄の株価・指標・Step判定を順番に再取得します。")
    st.caption("IR BANKへの過剰アクセスを避けるため、銘柄間に待機時間を設けています。")

    if st.button("全銘柄を更新", type="primary", use_container_width=True):
        if st.session_state.watchlist.empty:
            st.info("監視リストに銘柄がありません。")
        else:
            cached_fetch.clear()
            progress = st.progress(0)
            messages = st.empty()
            updated = st.session_state.watchlist.copy()
            total = len(updated)
            errors = []

            for index, record in updated.reset_index(drop=True).iterrows():
                code_value = str(record["コード"]).zfill(4)
                messages.write(f"{code_value}を更新中…（{index + 1}/{total}）")
                try:
                    data = fetch_all(code_value)
                    result = analyze_data(data)
                    lines = {
                        "第1目標利回り": record.get("第1目標利回り"),
                        "第1目標株価": record.get("第1目標株価"),
                        "第2目標利回り": record.get("第2目標利回り"),
                        "第2目標株価": record.get("第2目標株価"),
                        "第3目標利回り": record.get("第3目標利回り"),
                        "第3目標株価": record.get("第3目標株価"),
                    }
                    updated = upsert(updated, build_watchlist_row(data, result, lines))
                    st.session_state.details[code_value] = {
                        "eps": data.get("eps_rows", []),
                        "bps": data.get("bps_rows", []),
                        "dividends": data.get("dividend_rows", []),
                    }
                except Exception as exc:
                    errors.append(f"{code_value}: {exc}")

                progress.progress((index + 1) / total)
                time.sleep(1.0)

            st.session_state.watchlist = updated
            save_watchlist(updated)
            messages.write("全銘柄更新が完了しました。")
            if errors:
                st.warning("一部取得失敗：" + " / ".join(errors))
            else:
                st.success("全銘柄を更新しました。")

st.divider()
st.caption(
    "IR BANKの公開データは即時更新ではなく、アクセス過多は禁止されています。"
    "取得値は元サイト・会社IRでも照合してください。"
)
