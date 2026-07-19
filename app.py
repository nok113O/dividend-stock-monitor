from __future__ import annotations

from datetime import datetime
import time
import pandas as pd
import streamlit as st

from analyzer import (
    analyze_step1, analyze_step2, buy_zone, calculate_step3,
    latest_summary, make_comment, merge_new_fy,
    overall_rating, step1_metrics,
)
from jquants_client import JQuantsClient, JQuantsError
from market_data import current_market_data
from target_yield_engine import calculate_targets, purchase_price, status as purchase_status
from sector_master import classify
from workbook_io import (
    empty_history, empty_watchlist, normalize_watchlist,
    read_workbook, to_excel_bytes,
)

st.set_page_config(page_title="高配当株監視ツール Ver.5.0", page_icon="📈", layout="wide")
st.title("高配当株監視ツール Ver.5.0")
st.caption("銘柄追加時に目標利回りを一度だけ自動算定し、通常更新では予想配当・株価・買付株価だけを更新します。")

def api_key() -> str:
    try:
        return str(st.secrets["JQUANTS_API_KEY"])
    except Exception:
        return ""

def fmt(value, digits=2, suffix=""):
    if value is None or pd.isna(value):
        return "取得不可"
    return f"{value:,.{digits}f}{suffix}"

def get_old(code: str) -> dict:
    df = st.session_state.watchlist
    if df.empty:
        return {}
    hit = df[df["コード"].astype(str).str.zfill(4) == code]
    return hit.iloc[0].to_dict() if not hit.empty else {}


def history_arrays(code: str) -> tuple[list[float], list[float]]:
    df = st.session_state.history.copy()
    if df.empty:
        return [], []
    df["コード"] = df["コード"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    hit = df[df["コード"] == code].copy()
    hit["決算期"] = pd.to_datetime(hit["決算期"], errors="coerce")
    hit = hit.sort_values("決算期").tail(10)
    eps = pd.to_numeric(hit["EPS"], errors="coerce").dropna().tolist()
    divs = pd.to_numeric(hit["1株配当"], errors="coerce").dropna().tolist()
    return eps, divs

def update_one(code: str) -> tuple[dict, dict]:
    client = JQuantsClient(api_key(), min_interval_seconds=1.2)
    master = client.master(code)
    # Freeプランは直近約12週間の株価を取得できないため、現在株価はYahoo! Financeを使用
    market = current_market_data(code)
    summaries = client.financial_summary(code)

    price = market.get("price")
    price_date = market.get("price_date")
    latest = latest_summary(summaries)
    metrics = step1_metrics(price, latest)

    # J-Quants財務で欠ける現在指標をYahoo! Financeで補完
    if metrics.get("PER") is None:
        metrics["PER"] = market.get("trailing_pe")
    if metrics.get("PBR") is None:
        metrics["PBR"] = market.get("price_to_book")
    if metrics.get("ROE") is None and market.get("roe") is not None:
        metrics["ROE"] = float(market["roe"]) * 100
    if metrics.get("ROA") is None and market.get("roa") is not None:
        metrics["ROA"] = float(market["roa"]) * 100
    if metrics.get("時価総額（億円）") is None and market.get("market_cap") is not None:
        metrics["時価総額（億円）"] = float(market["market_cap"]) / 100_000_000
    if metrics.get("予想年間配当") is None and market.get("dividend_rate") is not None:
        metrics["予想年間配当"] = float(market["dividend_rate"])
    if metrics.get("配当利回り") is None:
        if metrics.get("予想年間配当") is not None and price:
            metrics["配当利回り"] = metrics["予想年間配当"] / price * 100
        elif market.get("dividend_yield") is not None:
            y = float(market["dividend_yield"])
            metrics["配当利回り"] = y * 100 if abs(y) <= 1 else y

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    st.session_state.history = merge_new_fy(
        st.session_state.history, code, summaries, now
    )

    step1 = analyze_step1(metrics)
    step2 = analyze_step2(st.session_state.history, code)
    step3 = calculate_step3(st.session_state.history, code)

    sector, cycle = classify(master.get("S33Nm"))
    comment = make_comment(step1, step2)
    rating = overall_rating(step1, step2)

    return {
        "code": code,
        "master": master,
        "price": price,
        "price_date": price_date,
        "metrics": metrics,
        "sector": sector,
        "cycle": cycle,
        "summaries_count": len(summaries),
    }, {
        "step1": step1,
        "step2": step2,
        "step3": step3,
        "comment": comment,
        "rating": rating,
    }

if "watchlist" not in st.session_state:
    st.session_state.watchlist = empty_watchlist()
if "history" not in st.session_state:
    st.session_state.history = empty_history()
if "last_data" not in st.session_state:
    st.session_state.last_data = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None

if not api_key():
    st.error("Streamlit SecretsにJQUANTS_API_KEYがありません。")
    st.stop()

uploaded = st.file_uploader(
    "最初に監視リストExcelをアップロード",
    type=["xlsx"],
    help="前回ダウンロードしたExcel、または初期テンプレートを選択します。",
)
if uploaded is not None:
    try:
        watchlist, history = read_workbook(uploaded)
        st.session_state.watchlist = watchlist
        st.session_state.history = history
        st.success(f"読込完了：監視銘柄 {len(watchlist)}件／履歴 {len(history)}行")
    except Exception as exc:
        st.error(str(exc))

tab1, tab2, tab3 = st.tabs(["銘柄分析・追加", "監視リスト", "全銘柄更新"])

with tab1:
    code = st.text_input("銘柄コード（4桁）", max_chars=4, placeholder="例：1605")
    if st.button("J-Quantsで分析・更新", type="primary", use_container_width=True):
        code = "".join(c for c in code if c.isdigit())
        if len(code) != 4:
            st.error("4桁の銘柄コードを入力してください。")
        else:
            try:
                with st.spinner("J-Quantsから取得中…"):
                    data, result = update_one(code)
                    st.session_state.last_data = data
                    st.session_state.last_result = result
            except JQuantsError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"更新に失敗しました：{exc}")

    if st.session_state.last_data:
        data = st.session_state.last_data
        result = st.session_state.last_result
        master = data["master"]
        metrics = data["metrics"]

        st.subheader(f"{data['code']}　{master.get('CoName', '')}")
        st.caption(
            f"業種：{master.get('S33Nm', '取得不可')} ｜ "
            f"セクター：{data['sector']} ｜ 景気区分：{data['cycle']} ｜ "
            f"J-Quants財務取得：{data['summaries_count']}件"
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("現在株価", fmt(data["price"], 0, "円"))
        c2.metric("予想年間配当", fmt(metrics["予想年間配当"], 2, "円"))
        c3.metric("現在利回り", fmt(metrics["配当利回り"], 2, "%"))
        c4.metric("総合判定", result["rating"])

        st.markdown("### Step1")
        rows = []
        units = {"PER": "倍", "PBR": "倍", "ROE": "%", "ROA": "%", "配当利回り": "%", "自己資本比率": "%", "時価総額": "億円"}
        for name, row in result["step1"]["rows"].items():
            rows.append({
                "項目": name,
                "実績": fmt(row["value"], 2, units[name]),
                "基準": row["criterion"],
                "判定": row["judge"],
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.write(f"**Step1総合：{result['step1']['overall']}**")

        st.markdown("### Step2")
        step2_rows = [
            {"項目": name, "確認結果": row["detail"], "判定": row["judge"]}
            for name, row in result["step2"]["rows"].items()
        ]
        st.dataframe(pd.DataFrame(step2_rows), hide_index=True, use_container_width=True)
        st.write(f"**Step2総合：{result['step2']['overall']}**")

        with st.expander("最新10期の実数"):
            history_view = result["step2"]["history"].copy()
            if not history_view.empty:
                history_view["決算期"] = history_view["決算期"].dt.strftime("%Y-%m-%d")
            st.dataframe(history_view, hide_index=True, use_container_width=True)

        st.markdown("### Step3")
        s1, s2, s3 = st.columns(3)
        s1.metric("過去10期EPS合計", fmt(result["step3"]["eps_sum"], 2, "円"))
        s2.metric("最新BPS", fmt(result["step3"]["latest_bps"], 2, "円"))
        s3.metric("目標株価", fmt(result["step3"]["target_price"], 2, "円"))

        st.markdown("### 所感")
        st.write(result["comment"])

        old = get_old(data["code"])
        forecast_dividend = metrics.get("予想年間配当")

        # 目標利回りは銘柄追加時のみ自動算定。保存済みなら再計算しない。
        has_saved_targets = all(
            old.get(k) not in (None, "", 0, 0.0)
            for k in ("第1目標利回り", "第2目標利回り", "第3目標利回り")
        )
        auto_reason = old.get("景気敏感判定理由") or ""
        if not has_saved_targets:
            try:
                eps_hist, div_hist = history_arrays(data["code"])
                targets = calculate_targets(
                    data["code"],
                    master.get("S33Nm"),
                    eps_history=eps_hist,
                    dividend_history=div_hist,
                )
                auto_y1, auto_y2, auto_y3 = targets.target1, targets.target2, targets.target3
                auto_reason = targets.reason
                st.success(
                    f"目標利回りを初回算定しました："
                    f"{auto_y1:.2f}%／{auto_y2:.2f}%／{auto_y3:.2f}% "
                    f"（{targets.cycle_class}、日次{targets.sample_daily}件＋年次{targets.sample_annual}件）"
                )
            except Exception as exc:
                auto_y1 = auto_y2 = auto_y3 = 0.0
                st.warning(f"目標利回りの自動算定に失敗しました：{exc}")
        else:
            auto_y1 = float(old.get("第1目標利回り") or 0)
            auto_y2 = float(old.get("第2目標利回り") or 0)
            auto_y3 = float(old.get("第3目標利回り") or 0)
            st.info("保存済みの目標利回りを使用します。通常更新では再計算しません。")

        auto_p1 = purchase_price(forecast_dividend, auto_y1) or 0.0
        auto_p2 = purchase_price(forecast_dividend, auto_y2) or 0.0
        auto_p3 = purchase_price(forecast_dividend, auto_y3) or 0.0

        with st.form(f"save_{data['code']}"):
            x1, x2 = st.columns(2)
            y1 = x1.number_input("第1目標利回り（%）", min_value=0.0, step=0.01, value=float(auto_y1))
            p1 = x2.number_input("第1目標株価（円）", min_value=0.0, step=1.0, value=float(auto_p1))
            x3, x4 = st.columns(2)
            y2 = x3.number_input("第2目標利回り（%）", min_value=0.0, step=0.01, value=float(auto_y2))
            p2 = x4.number_input("第2目標株価（円）", min_value=0.0, step=1.0, value=float(auto_p2))
            x5, x6 = st.columns(2)
            y3 = x5.number_input("第3目標利回り（%）", min_value=0.0, step=0.01, value=float(auto_y3))
            p3 = x6.number_input("第3目標株価（円）", min_value=0.0, step=1.0, value=float(auto_p3))
            save = st.form_submit_button("監視リストへ保存", type="primary")

        if save:
            targets = [p1 or None, p2 or None, p3 or None]
            row = {
                "コード": data["code"],
                "銘柄名": master.get("CoName"),
                "業種": master.get("S33Nm"),
                "セクター": data["sector"],
                "景気区分": data["cycle"],
                "景気敏感判定理由": auto_reason,
                "現在株価": data["price"],
                "株価日": data["price_date"],
                "予想年間配当": metrics["予想年間配当"],
                "現在利回り": metrics["配当利回り"],
                "PER": metrics["PER"],
                "PBR": metrics["PBR"],
                "ROE": metrics["ROE"],
                "ROA": metrics["ROA"],
                "自己資本比率": metrics["自己資本比率"],
                "時価総額（億円）": metrics["時価総額（億円）"],
                "Step1": result["step1"]["overall"],
                "Step2": result["step2"]["overall"],
                "過去10期EPS合計": result["step3"]["eps_sum"],
                "最新BPS": result["step3"]["latest_bps"],
                "Step3目標株価": result["step3"]["target_price"],
                "総合判定": result["rating"],
                "買い場判定": purchase_status(data["price"], p1 or None, p2 or None, p3 or None),
                "第1目標利回り": y1 or None, "第1目標株価": p1 or None,
                "第2目標利回り": y2 or None, "第2目標株価": p2 or None,
                "第3目標利回り": y3 or None, "第3目標株価": p3 or None,
                "所感": result["comment"],
                "最終更新": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            df = st.session_state.watchlist
            df = df[df["コード"].astype(str).str.zfill(4) != data["code"]]
            st.session_state.watchlist = normalize_watchlist(pd.concat([df, pd.DataFrame([row])], ignore_index=True))
            st.success("保存しました。最後にExcelをダウンロードしてください。")

with tab2:
    st.dataframe(st.session_state.watchlist, hide_index=True, use_container_width=True)

    excel = to_excel_bytes(st.session_state.watchlist, st.session_state.history)
    st.download_button(
        "更新済みExcelをダウンロード",
        data=excel,
        file_name=f"高配当株監視リスト_{datetime.now():%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )

with tab3:
    st.warning("Freeプランのレート上限を考慮し、銘柄ごとに待機します。銘柄数が多い場合は時間がかかります。")
    if st.button("登録済み全銘柄を更新", type="primary", use_container_width=True):
        codes = st.session_state.watchlist["コード"].dropna().astype(str).str.zfill(4).tolist()
        if not codes:
            st.info("監視銘柄がありません。")
        else:
            progress = st.progress(0)
            errors = []
            for i, current_code in enumerate(codes):
                try:
                    data, result = update_one(current_code)
                    old = get_old(current_code)
                    metrics = data["metrics"]
                    saved_y1 = old.get("第1目標利回り")
                    saved_y2 = old.get("第2目標利回り")
                    saved_y3 = old.get("第3目標利回り")
                    latest_dividend = metrics.get("予想年間配当")
                    recalculated_p1 = purchase_price(latest_dividend, saved_y1)
                    recalculated_p2 = purchase_price(latest_dividend, saved_y2)
                    recalculated_p3 = purchase_price(latest_dividend, saved_y3)
                    row = {
                        **old,
                        "コード": current_code,
                        "銘柄名": data["master"].get("CoName"),
                        "業種": data["master"].get("S33Nm"),
                        "セクター": data["sector"],
                        "景気区分": data["cycle"],
                        "現在株価": data["price"],
                        "株価日": data["price_date"],
                        "予想年間配当": metrics["予想年間配当"],
                        "現在利回り": metrics["配当利回り"],
                        "PER": metrics["PER"], "PBR": metrics["PBR"],
                        "ROE": metrics["ROE"], "ROA": metrics["ROA"],
                        "自己資本比率": metrics["自己資本比率"],
                        "時価総額（億円）": metrics["時価総額（億円）"],
                        "Step1": result["step1"]["overall"],
                        "Step2": result["step2"]["overall"],
                        "過去10期EPS合計": result["step3"]["eps_sum"],
                        "最新BPS": result["step3"]["latest_bps"],
                        "Step3目標株価": result["step3"]["target_price"],
                        "総合判定": result["rating"],
                        "第1目標株価": recalculated_p1,
                        "第2目標株価": recalculated_p2,
                        "第3目標株価": recalculated_p3,
                        "買い場判定": purchase_status(
                            data["price"], recalculated_p1, recalculated_p2, recalculated_p3
                        ),
                        "所感": result["comment"],
                        "最終更新": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    df = st.session_state.watchlist
                    df = df[df["コード"].astype(str).str.zfill(4) != current_code]
                    st.session_state.watchlist = normalize_watchlist(pd.concat([df, pd.DataFrame([row])], ignore_index=True))
                except Exception as exc:
                    errors.append(f"{current_code}: {exc}")
                progress.progress((i + 1) / len(codes))
                time.sleep(12)

            if errors:
                st.warning("一部失敗：" + " / ".join(errors))
            else:
                st.success("全銘柄更新が完了しました。監視リストタブからExcelをダウンロードしてください。")

st.divider()
st.caption("Excelが正本です。アプリ終了前に必ず更新済みExcelをダウンロードしてください。")
