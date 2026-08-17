import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Wall Street 14D Swing Radar", layout="wide", initial_sidebar_state="collapsed")

# 1. 글로벌 증권사 신뢰도 티어 정의
TIER_1_FIRMS = ["GOLDMAN SACHS", "MORGAN STANLEY", "JP MORGAN", "JPMORGAN", "BANK OF AMERICA", "BOFA", "CITIGROUP", "BARCLAYS", "UBS", "DEUTSCHE BANK"]
TIER_2_FIRMS = ["WEDBUSH", "NEEDHAM", "PIPER SANDLER", "JEFFERIES", "EVERCORE ISI", "BAIRD", "OPPENHEIMER", "MIZUHO", "STIFEL", "COWEN", "BERNSTEIN", "CANTOR FITZGERALD", "RAYMOND JAMES", "WELLS FARGO", "RBC CAPITAL", "KEYBANC"]

WATCHLIST_POOL = [
    "PLTR", "CRWD", "ARM", "IONQ", "SMCI", "RKLB", "NET", "SNOW",
    "NVDA", "TSLA", "AMD", "COIN", "SOFI", "PATH", "CELH", "SYM",
    "MRVL", "APP", "ASTS", "TEM", "HOOD", "RDDT"
]

# 구글 스프레드시트 커넥션 연결
conn = st.connection("gsheets", type=GSheetsConnection)

def load_portfolio():
    """구글 시트에서 포트폴리오 불러오기"""
    try:
        df = conn.read(worksheet="Sheet1", ttl=0)
        if df is not None and not df.empty:
            df = df.dropna(how="all")
            required_cols = ["티커", "매수가", "수량"]
            if all(col in df.columns for col in required_cols):
                df["티커"] = df["티커"].astype(str).str.strip().str.upper()
                df["매수가"] = pd.to_numeric(df["매수가"], errors="coerce").fillna(0.0)
                df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(0.0)
                return df[df["티커"] != ""][required_cols]
    except Exception as e:
        st.error(f"구글 시트 읽기 에러: {e}")
    return pd.DataFrame(columns=["티커", "매수가", "수량"])


def save_portfolio(df):
    """구글 시트에 포트폴리오 업데이트"""
    try:
        conn.update(worksheet="Sheet1", data=df)
        return True
    except Exception as e:
        st.error(f"구글 시트 저장 실패: {e}")
        return False

def classify_grade(grade_str):
    g = str(grade_str).upper()
    if any(k in g for k in ["BUY", "OUTPERFORM", "OVERWEIGHT", "POSITIVE", "ADD", "ACCUMULATE", "TOP PICK"]):
        return "BUY"
    elif any(k in g for k in ["SELL", "UNDERPERFORM", "UNDERWEIGHT", "NEGATIVE", "REDUCE"]):
        return "SELL"
    elif any(k in g for k in ["HOLD", "NEUTRAL", "EQUAL", "PERFORM", "IN-LINE", "SECTOR WEIGHT"]):
        return "HOLD"
    return "HOLD"

@st.cache_data(ttl=1800)
def analyze_stock_full(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        upgrades = stock.upgrades_downgrades
        hist = stock.history(period="3mo", interval="1d")

        now = datetime.datetime.now()
        seven_days_ago = now - datetime.timedelta(days=7)
        fourteen_days_ago = now - datetime.timedelta(days=14)
        
        top_14d_buy, top_14d_hold, top_14d_sell = 0, 0, 0
        all_14d_buy, all_14d_hold, all_14d_sell = 0, 0, 0
        
        top_tier_buyers_7d = []
        top_tier_buyers_14d = []
        recent_7d_events = []
        recent_14d_events = []
        recent_downgrades_7d = []
        target_prices_14d = []
        
        score = 40.0
        
        if upgrades is not None and not upgrades.empty:
            if upgrades.index.tz is not None:
                upgrades.index = upgrades.index.tz_localize(None)
                
            valid_data = upgrades[upgrades.index >= fourteen_days_ago].sort_index(ascending=False)
            seen_firms = set()
            
            for date, row in valid_data.iterrows():
                firm = str(row.get('Firm', '')).strip()
                to_grade = str(row.get('ToGrade', ''))
                action = str(row.get('Action', '')).lower()
                
                for col in ['TargetPrice', 'Target_Price', 'PriceTarget', 'currentPriceTarget']:
                    if col in row and pd.notnull(row[col]) and float(row[col]) > 0:
                        target_prices_14d.append(float(row[col]))
                        break
                
                if not firm or firm in seen_firms:
                    continue
                seen_firms.add(firm)
                
                firm_upper = firm.upper()
                is_tier1 = any(t1 in firm_upper for t1 in TIER_1_FIRMS)
                is_tier2 = any(t2 in firm_upper for t2 in TIER_2_FIRMS)
                is_top_tier = is_tier1 or is_tier2
                
                category = classify_grade(to_grade)
                is_within_7d = (date >= seven_days_ago)
                
                event_text = f"[{date.strftime('%m/%d')}] {firm}: {to_grade} ({action.upper()})"
                
                if is_within_7d:
                    recent_7d_events.append(event_text)
                    if category == "SELL" or "down" in action:
                        recent_downgrades_7d.append(f"{firm} ({to_grade})")
                else:
                    recent_14d_events.append(event_text)
                
                if is_within_7d:
                    if category == "BUY":
                        if is_tier1: score += 25.0
                        elif is_tier2: score += 18.0
                        else: score += 10.0
                    elif category == "HOLD": score -= 2.0
                    elif category == "SELL": score -= 25.0
                else:
                    if category == "BUY":
                        if is_tier1: score += 12.0
                        elif is_tier2: score += 8.0
                        else: score += 4.0
                    elif category == "HOLD": score -= 1.0
                    elif category == "SELL": score -= 12.0

                if category == "BUY":
                    all_14d_buy += 1
                    if is_top_tier:
                        top_14d_buy += 1
                        if is_within_7d: top_tier_buyers_7d.append(firm)
                        else: top_tier_buyers_14d.append(firm)
                elif category == "HOLD":
                    all_14d_hold += 1
                    if is_top_tier: top_14d_hold += 1
                elif category == "SELL":
                    all_14d_sell += 1
                    if is_top_tier: top_14d_sell += 1

        current_price = info.get('currentPrice', info.get('regularMarketPrice', 0))
        target_mean = info.get('targetMeanPrice', 0)
        target_median = info.get('targetMedianPrice', target_mean)
        target_high = info.get('targetHighPrice', 0)
        target_low = info.get('targetLowPrice', 0)
        
        if target_prices_14d:
            avg_14d = round(sum(target_prices_14d) / len(target_prices_14d), 2)
            high_14d = max(target_prices_14d)
            low_14d = min(target_prices_14d)
        else:
            avg_14d, high_14d, low_14d = target_mean, target_high, target_low
            
        upside_median = round(((target_median - current_price) / current_price) * 100, 1) if (target_median and current_price) else 0.0
        
        if upside_median > 0:
            score += min(20.0, (upside_median / 20.0) * 20.0)
            
        total_14d_reports = all_14d_buy + all_14d_hold + all_14d_sell
        if total_14d_reports == 0:
            score = max(0.0, score - 15.0)

        final_score = int(max(0, score))
        
        top_buyers_all = []
        if top_tier_buyers_7d: top_buyers_all.append(f"🔥7일: {', '.join(top_tier_buyers_7d)}")
        if top_tier_buyers_14d: top_buyers_all.append(f"8~14일: {', '.join(top_tier_buyers_14d)}")
        buyers_display = " | ".join(top_buyers_all) if top_buyers_all else "-"

        return {
            "티커": ticker,
            "모멘텀 스코어": final_score,
            "raw_price": current_price,
            "현재가": f"${current_price:.2f}",
            "탑티어 14D (B/H/S)": f"{top_14d_buy} / {top_14d_hold} / {top_14d_sell}",
            "전체 14D (B/H/S)": f"{all_14d_buy} / {all_14d_hold} / {all_14d_sell}",
            "총 중앙값 (상승여력)": f"${target_median:.2f} (+{upside_median}%)" if target_median else "-",
            "14D 목표가 평균": f"${avg_14d:.2f}" if avg_14d else "-",
            "14D 최고/최저": f"${high_14d:.2f} / ${low_14d:.2f}" if (high_14d and low_14d) else "-",
            "탑티어 매수사": buyers_display,
            "최근7일내역": recent_7d_events,
            "8~14일내역": recent_14d_events,
            "downgrades_7d": recent_downgrades_7d,
            "hist": hist,
            "raw_score": final_score,
            "has_7d": len(recent_7d_events) > 0,
            "has_14d": total_14d_reports > 0
        }
    except Exception:
        return None

def render_stock_chart(ticker, hist):
    if hist.empty or len(hist) < 20:
        st.warning("차트 데이터를 불러올 수 없습니다.")
        return
    hist['MA20'] = hist['Close'].rolling(20).mean()
    hist['MA50'] = hist['Close'].rolling(50).mean()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'], name="일봉"), row=1, col=1)
    fig.add_trace(go.Scatter(x=hist.index, y=hist['MA20'], line=dict(color='orange', width=1.5), name="20일선"), row=1, col=1)
    fig.add_trace(go.Scatter(x=hist.index, y=hist['MA50'], line=dict(color='blue', width=1.2), name="50일선"), row=1, col=1)
    colors = ['red' if row['Close'] < row['Open'] else 'green' for _, row in hist.iterrows()]
    fig.add_trace(go.Bar(x=hist.index, y=hist['Volume'], marker_color=colors, name="거래량"), row=2, col=1)
    fig.update_layout(title=f"📊 {ticker} 일봉 차트 (20/50일 이평선)", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=40, b=10), height=420)
    st.plotly_chart(fig, use_container_width=True)

# ==================== UI 렌더링 ====================
st.title("⚡ 미국 주식 14일 기관 레이더 & 포트폴리오")

tab_my, tab1, tab2, tab3 = st.tabs(["💼 내 투자 (구글시트 연동)", "🔥 7일 내 긴급 상향", "🏆 14일 모멘텀 랭킹", "🔍 미국 전 종목 직접 검색 & 차트"])

# ==================== 탭 0: 내 투자 (구글 시트 연동) ====================
with tab_my:
    st.subheader("💼 내 보유 종목 실시간 모니터링 & 긴급 변동 감지")
    
    port_df = load_portfolio()
    
    with st.expander("➕ 보유 종목 추가 / 수정 / 삭제", expanded=port_df.empty):
        col_in1, col_in2, col_in3, col_in4 = st.columns([2, 2, 2, 1.5])
        in_ticker = col_in1.text_input("티커 (예: NVDA)", key="in_t").strip().upper()
        in_price = col_in2.number_input("매수 평단가 ($)", min_value=0.0, step=0.1, key="in_p")
        in_qty = col_in3.number_input("보유 수량 (주)", min_value=0.0, step=1.0, key="in_q")
        
        if col_in4.button("구글시트에 저장", use_container_width=True):
            if in_ticker and in_price > 0 and in_qty > 0:
                port_df = port_df[port_df["티커"] != in_ticker]
                new_row = pd.DataFrame([{"티커": in_ticker, "매수가": in_price, "수량": in_qty}])
                port_df = pd.concat([port_df, new_row], ignore_index=True)
                if save_portfolio(port_df):
                    st.success(f"{in_ticker} 구글 시트에 영구 저장 완료!")
                    st.rerun()
                
        if not port_df.empty:
            del_ticker = st.selectbox("삭제할 종목 선택", options=["선택 안 함"] + list(port_df["티커"].unique()))
            if st.button("선택 종목 구글시트에서 삭제") and del_ticker != "선택 안 함":
                port_df = port_df[port_df["티커"] != del_ticker]
                if save_portfolio(port_df):
                    st.warning(f"{del_ticker} 삭제 완료")
                    st.rerun()

    if not port_df.empty:
        my_holdings_data = []
        alerts_upgrade = []
        alerts_downgrade = []
        
        total_invested = 0.0
        total_eval = 0.0
        
        for _, row in port_df.iterrows():
            t = row["티커"]
            b_price = float(row["매수가"])
            qty = float(row["수량"])
            
            res = analyze_stock_full(t)
            if res:
                c_price = res["raw_price"]
                invested = b_price * qty
                eval_val = c_price * qty
                pnl_val = eval_val - invested
                pnl_pct = ((c_price - b_price) / b_price) * 100 if b_price > 0 else 0.0
                
                total_invested += invested
                total_eval += eval_val
                
                if res["downgrades_7d"]:
                    alerts_downgrade.append(f"🚨 **{t}**: {', '.join(res['downgrades_7d'])} 매도/하향 발생!")
                if res["has_7d"] and res["raw_score"] >= 80:
                    alerts_upgrade.append(f"🔥 **{t}**: 최근 7일 내 신규 매수 상향 포착 (모멘텀 스코어: {res['모멘텀 스코어']}점)")
                
                my_holdings_data.append({
                    "티커": t,
                    "매수가": f"${b_price:.2f}",
                    "현재가": f"${c_price:.2f}",
                    "수익률": f"{pnl_pct:+.2f}%",
                    "평가손익": f"${pnl_val:+.2f}",
                    "평가금액": f"${eval_val:.2f}",
                    "14D 스코어": res["모멘텀 스코어"],
                    "탑티어 14D (B/H/S)": res["탑티어 14D (B/H/S)"],
                    "전체 14D (B/H/S)": res["전체 14D (B/H/S)"],
                    "목표가 중앙값": res["총 중앙값 (상승여력)"]
                })
        
        if alerts_downgrade:
            st.error("### ⚠️ [긴급 경고] 보유 종목 중 최근 7일 내 하향/매도 리포트 발생\n" + "\n\n".join(alerts_downgrade))
        if alerts_upgrade:
            st.success("### 🔥 [호재 발생] 보유 종목 중 최근 7일 내 신규 매수 리포트 집중\n" + "\n\n".join(alerts_upgrade))
            
        total_pnl_val = total_eval - total_invested
        total_pnl_pct = ((total_eval - total_invested) / total_invested) * 100 if total_invested > 0 else 0.0
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 투입 금액", f"${total_invested:,.2f}")
        m2.metric("총 평가 금액", f"${total_eval:,.2f}")
        m3.metric("총 평가 손익", f"${total_pnl_val:+,.2f}")
        m4.metric("총 수익률", f"{total_pnl_pct:+.2f}%")
        
        st.markdown("---")
        
        st.dataframe(
            pd.DataFrame(my_holdings_data).style.background_gradient(subset=["14D 스코어"], cmap="Blues"),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("현재 구글 시트에 등록된 보유 종목이 없습니다. 위의 '보유 종목 추가' 메뉴를 통해 입력해보세요.")

# ==================== 탭 1, 2, 3: 시장 모니터링 ====================
@st.cache_data(ttl=1800)
def get_all_watchlist_results():
    results = [analyze_stock_full(t) for t in WATCHLIST_POOL]
    return [r for r in results if r is not None]

with tab1:
    ...
    with st.spinner("7일 이내 긴급 상향 종목 분석 중..."):
        valid_results = get_all_watchlist_results()

with tab1:
    st.subheader("🔥 7일 이내 신규 평가 발표 종목")
    urgent_stocks = [r for r in valid_results if r["has_7d"]]
    if urgent_stocks:
        urgent_stocks = sorted(urgent_stocks, key=lambda x: x["raw_score"], reverse=True)
        for s in urgent_stocks:
            with st.container():
                c1, c2, c3 = st.columns([1.2, 2.3, 2.5])
                c1.metric(f"**{s['티커']}**", f"{s['모멘텀 스코어']}점", s["총 중앙값 (상승여력)"])
                c2.write(f"• **현재가:** `{s['현재가']}`")
                c2.write(f"• **탑티어 14D (B/H/S):** `{s['탑티어 14D (B/H/S)']}`")
                c2.write(f"• **전체 14D (B/H/S):** `{s['전체 14D (B/H/S)']}`")
                c2.write(f"• **14D 목표가 평균:** {s['14D 목표가 평균']} (범위: {s['14D 최고/최저']})")
                c2.write(f"• **탑티어 매수사:** {s['탑티어 매수사']}")
                details = [f"🔥 {e}" for e in s["최근7일내역"]]
                if s["8~14일내역"]: details.extend([f"⏱️ {e}" for e in s["8~14일내역"]])
                c3.info("**14일 내 리포트 이력:**\n" + "\n".join(details))
                st.markdown("---")
    else:
        st.info("현재 모니터링 풀 내에 최근 7일간 신규 평가가 발표된 종목이 없습니다.")

with tab2:
    st.subheader("🏆 최근 14일 기관 평가 종합 순위")
    if valid_results:
        df = pd.DataFrame(valid_results)
        df_sorted = df.sort_values(by="raw_score", ascending=False).drop(
            columns=["최근7일내역", "8~14일내역", "downgrades_7d", "hist", "raw_score", "raw_price", "has_7d", "has_14d"]
        )
        st.dataframe(df_sorted.style.background_gradient(subset=["모멘텀 스코어"], cmap="Blues"), use_container_width=True, hide_index=True)

with tab3:
    st.subheader("🔍 미국 전 종목 직접 검색 & 차트")
    search_ticker = st.text_input("분석할 미국 주식 티커 입력 (예: PLTR, CRWD, TSLA, HOOD 등)", value="PLTR").strip().upper()
    if search_ticker:
        with st.spinner(f"{search_ticker} 데이터 수집 중..."):
            res = analyze_stock_full(search_ticker)
        if res:
            c1, c2, c3 = st.columns(3)
            c1.metric("14D 모멘텀 스코어", f"{res['모멘텀 스코어']}점")
            c2.metric("탑티어 14D (B/H/S)", res["탑티어 14D (B/H/S)"])
            c3.metric("전체 14D (B/H/S)", res["전체 14D (B/H/S)"])
            st.markdown("---")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("현재가", res["현재가"])
            m2.metric("총 중앙값(Median)", res["총 중앙값 (상승여력)"])
            m3.metric("14일 이내 목표가 평균", res["14D 목표가 평균"])
            m4.metric("14일 이내 최고 / 최저", res["14D 최고/최저"])
            st.write(f"• **탑티어 매수 추천 증권사:** {res['탑티어 매수사']}")
            if res["최근7일내역"]: st.success("🔥 **최근 7일 이내 긴급 리포트:**\n" + "\n".join([f"- {e}" for e in res["최근7일내역"]]))
            if res["8~14일내역"]: st.info("⏱️ **8~14일 전 리포트:**\n" + "\n".join([f"- {e}" for e in res["8~14일내역"]]))
            if not res["has_14d"]: st.warning("⚠️ 최근 14일 이내에 발표된 신규 월가 리포트가 없습니다.")
            render_stock_chart(search_ticker, res["hist"])
        else:
            st.error("종목 정보를 불러올 수 없습니다. 올바른 티커인지 확인해주세요.")
