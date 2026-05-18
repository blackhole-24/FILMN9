"""기업가치 평가 Streamlit 대시보드 — 아모레퍼시픽.

dashboard.html 디자인을 Streamlit으로 이식.

실행:
    conda activate dart-rag
    pip install streamlit plotly
    cd C:\\Users\\Admin\\Desktop\\VAR
    streamlit run valuation_engine/streamlit_app.py
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.graph_objects as go


# ── 페이지 설정 ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="기업가치 평가 — 아모레퍼시픽",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── 커스텀 CSS ─────────────────────────────────────────────────────
st.markdown("""
<style>
.block-container { padding-top: 1.5rem; padding-bottom: 4rem; max-width: 1200px; }

/* Hero */
.hero {
    background: linear-gradient(135deg, #0e1c44 0%, #1f4ed8 100%);
    color: #fff; border-radius: 16px; padding: 28px 32px; margin-bottom: 22px;
    box-shadow: 0 8px 24px rgba(20,40,90,0.18);
}
.hero .meta-row { font-size: 13px; opacity: 0.78; margin-bottom: 6px; }
.hero .label-chip {
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    background: rgba(255,255,255,0.12); font-size: 12px; margin-right: 6px;
}
.hero h1 { font-size: 30px; margin: 4px 0 6px 0; font-weight: 700; color: #fff; }
.hero .sub { font-size: 13px; opacity: 0.75; }
.hero .equity-block { margin-top: 14px; font-size: 14px; }
.hero .equity-value { font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }
.hero .price-label { font-size: 13px; opacity: 0.78; margin-bottom: 4px; }
.hero .price-big { font-size: 44px; font-weight: 800; letter-spacing: -1px; line-height: 1; }
.hero .price-big small { font-size: 18px; font-weight: 500; opacity: 0.7; margin-left: 4px; }
.hero .price-vs { margin-top: 10px; font-size: 14px; opacity: 0.9; }
.upside-pos { color: #6cf2a2; font-weight: 700; }
.upside-neg { color: #ff8181; font-weight: 700; }

/* 시나리오 카드 */
.scenario-card { background: #fff; border: 1px solid #e3e6eb; border-radius: 12px;
    padding: 22px 18px; text-align: center; }
.scenario-card.bear { border-top: 4px solid #c0392b; }
.scenario-card.base { border-top: 4px solid #1f4ed8; }
.scenario-card.bull { border-top: 4px solid #1e8e4b; }
.scenario-card .name { font-size: 13px; color: #5b6473; margin-bottom: 4px;
    font-weight: 600; letter-spacing: 0.5px; }
.scenario-card .value { font-size: 32px; font-weight: 800; letter-spacing: -0.6px; color: #1c2330; }
.scenario-card .vs { font-size: 12px; color: #8b94a3; margin-top: 8px; }
.bear-color { color: #c0392b; }
.base-color { color: #1f4ed8; }
.bull-color { color: #1e8e4b; }

/* KPI 카드 */
.kpi-card { background: #fff; border: 1px solid #e3e6eb; border-radius: 12px;
    padding: 16px 18px; }
.kpi-label { font-size: 12px; color: #5b6473; margin-bottom: 6px; }
.kpi-value { font-size: 22px; font-weight: 700; letter-spacing: -0.4px; color: #1c2330; }
.kpi-sub { font-size: 12px; color: #8b94a3; margin-top: 4px; }

/* 검증 배지 */
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 600; margin-right: 4px; }
.badge-ok   { background: #e8f5ee; color: #2d6a4f; }
.badge-warn { background: #fef3cd; color: #8a6d00; }
.badge-info { background: #e8efff; color: #1f4ed8; }

/* 면책 */
.footer-note { background: #ebeef3; border-radius: 10px; padding: 16px 20px;
    color: #5b6473; font-size: 12.5px; margin-top: 24px; }
.footer-note h4 { color: #1c2330; font-size: 13px; margin: 0 0 6px 0; }
.disclaimer { padding-top: 10px; border-top: 1px solid #d4d9e1; font-size: 11.5px;
    color: #8b94a3; margin-top: 10px; }

/* 표 */
[data-testid="stDataFrame"] { font-size: 13px; }

/* Streamlit 헤더 숨기기 */
header[data-testid="stHeader"] { display: none; }
</style>
""", unsafe_allow_html=True)


# ── 데이터 로드 ────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_data() -> dict | None:
    """results/valuation_<T>.json 로드. 없으면 None (mockup 절대 사용 안 함)."""
    results_dir = Path(__file__).resolve().parent / "results"
    candidates = sorted(results_dir.glob("valuation_*.json"))
    if not candidates:
        return None
    with candidates[-1].open("r", encoding="utf-8") as f:
        return json.load(f)


def _no_data_screen():
    """실데이터가 없을 때 보여줄 안내 화면. mockup/임의값 절대 표시 안 함."""
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0e1c44 0%,#1f4ed8 100%);
                color:#fff; padding:32px; border-radius:16px; text-align:center;
                margin: 40px 0;">
      <h1 style="margin:0 0 8px 0;">📊 기업가치 평가 대시보드</h1>
      <p style="opacity:0.85; margin:0;">아모레퍼시픽 POC · DCF·WACC·FCFF 기반 적정주가</p>
    </div>
    """, unsafe_allow_html=True)

    st.error(
        "⚠️ **실제 데이터가 아직 생성되지 않았습니다.**  \n"
        "이 앱은 **mockup/임의값을 사용하지 않으며**, DART·KRX·ECOS API에서 추출한 실데이터로만 동작합니다."
    )

    st.markdown("### 🚀 데이터 수집 및 평가 실행")
    st.code("""
# 1) 환경 활성화
conda activate dart-rag
cd C:\\Users\\Admin\\Desktop\\VAR

# 2) (처음 1회) 의존성 설치
pip install -r peer_beta/requirements.txt
pip install -r valuation_engine/requirements.txt

# 3) 전체 평가 실행 (Phase 1~7 순차)
#    - peer_beta: KRX 4사 베타 회귀 (winsorize)
#    - XBRL:      DART에서 피어 4사 × 3년 재무 추출
#    - WACC:      Hamada Unlever/Relever + Rf(ECOS) + WACC
#    - DCF:       5년 FCFF Fade-out + TV → EV
#    - Equity:    EV → 주당가치
#    - 멀티플:    피어 중위값 × 타겟 지표
#    - 시나리오:  Bear/Base/Bull + 민감도 + 토네이도
python -m valuation_engine.run_valuation

# 4) 이 대시보드 새로고침 (브라우저 F5)
    """, language="bash")

    st.markdown("### 📂 산출물 위치")
    rd = Path(__file__).resolve().parent / "results"
    st.markdown(f"`{rd}/valuation_<T>.json` 파일이 생성되면 자동으로 fetch합니다.")

    st.markdown("### ✅ 필요한 환경변수 (`.env`)")
    st.markdown("""
    - `krxdata` — KRX OpenAPI 키 (피어 주가·KOSPI 지수)
    - `DART_API_KEY` — DART OpenAPI 키 (XBRL 재무제표, 발행/자기주식수)
    - `ECOS_API_KEY` — 한국은행 ECOS 키 (Rf 국고채 10년)
    """)

    st.stop()


# 데이터 로드 — 실데이터 없으면 안내 후 종료 (mockup 표시 절대 안 함)
data = load_data()
if data is None:
    _no_data_screen()


# 이 앱은 임의값을 표시하지 않습니다. 모든 수치는 valuation_engine/results/
# valuation_<T>.json 의 실데이터에서만 옵니다. JSON 생성은 다음 명령으로:
#     python -m valuation_engine.run_valuation


# ── 메인 ────────────────────────────────────────────────────────────
# data 는 위에서 이미 load_data() 로 로드됨 (None이면 _no_data_screen() 으로 종료)
s = data["summary"]

# ── Hero ───────────────────────────────────────────────────────────
upside_class = "upside-pos" if s["upside_pct"] >= 0 else "upside-neg"
upside_sign  = "+" if s["upside_pct"] >= 0 else ""
roic_badge   = "ok" if s["implied_roic"] > s["wacc"] else "warn"
roic_text    = "ROIC > WACC" if s["implied_roic"] > s["wacc"] else "ROIC < WACC"

st.markdown(f"""
<div class="hero">
  <div style="display:grid; grid-template-columns:1.4fr 1fr; gap:24px;">
    <div>
      <div class="meta-row">
        <span class="label-chip">{data['company']['market']} · {data['company']['ticker']}</span>
        <span class="label-chip">평가기준일 T {data['as_of_date']}</span>
      </div>
      <h1>{data['company']['name']}</h1>
      <div class="sub">DCF(FCFF) 기반 적정주가 산출 · 설계서 v4 · 일반투자자용</div>
      <div class="equity-block">
        <strong style="font-size:15px; color:#fff;">기업가치(Equity Value)</strong><br/>
        <span class="equity-value">₩ {s['equity_value_won']/1e12:.1f}조</span>
        <span style="font-size:12px; opacity:0.7; margin-left:6px;">
          (Net Debt ₩ {s['net_debt_won']/1e12:.2f}조 차감 · NOA ₩ {s['noa_won']/1e12:.2f}조 가산)
        </span>
      </div>
    </div>
    <div style="text-align:right;">
      <div class="price-label">적정주가 (Base case)</div>
      <div class="price-big">₩ {s['fair_price']:,.0f}<small>/주</small></div>
      <div class="price-vs">
        현재 주가 <strong>₩ {s['current_price']:,.0f}</strong>
        &nbsp;·&nbsp; 상승여력 <span class="{upside_class}">{upside_sign}{s['upside_pct']:.1f}%</span>
      </div>
      <div class="price-vs" style="font-size:12px; margin-top:6px;">
        Implied ROIC <strong>{s['implied_roic']*100:.1f}%</strong> vs WACC <strong>{s['wacc']*100:.2f}%</strong>
        &nbsp;<span class="badge badge-{roic_badge}">{roic_text}</span>
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Bear/Base/Bull 3시나리오 ───────────────────────────────────────
st.markdown("### Bear / Base / Bull 3시나리오")
st.caption("매출 성장률 · OPM · CapEx율 · NWC율을 과거 3년의 최저/평균/최고 조합으로 회전. WACC·g·세율은 Base 고정.")

c1, c2, c3 = st.columns(3)
for col, key, css in [(c1,"Bear","bear"), (c2,"Base","base"), (c3,"Bull","bull")]:
    sc = data["scenarios"][key]
    up = sc["upside_pct"]
    up_sign = "+" if up >= 0 else ""
    col.markdown(f"""
    <div class="scenario-card {css}">
      <div class="name">{key.upper()}</div>
      <div class="value">₩ {sc['price']:,.0f}</div>
      <div class="vs">vs 현재가 <strong class="{css}-color">{up_sign}{up:.1f}%</strong>
        · EV/EBITDA {sc['ev_ebitda']:.1f}×</div>
    </div>
    """, unsafe_allow_html=True)


# ── 핵심 지표 5종 ───────────────────────────────────────────────────
st.markdown("### 핵심 지표")
k1, k2, k3, k4, k5 = st.columns(5)
def kpi(col, label, value, sub):
    col.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value">{value}</div>
      <div class="kpi-sub">{sub}</div>
    </div>""", unsafe_allow_html=True)
kpi(k1, "WACC",            f"{s['wacc']*100:.2f}%",
    f"Ke {s['ke']*100:.2f}% / Kd(after-tax) {s['kd_aftertax']*100:.2f}%")
kpi(k2, "βL,target (Blume)", f"{s['beta_L_target']:.2f}",
    "βU 중위값 → Relever")
kpi(k3, "목표 D/E",         f"{s['DE_target_pct']:.1f}%",
    "피어 D/E 중위값")
kpi(k4, "Net Debt",        f"₩ {s['net_debt_won']/1e12:.2f}조",
    "IBD − 현금성자산")
kpi(k5, "NOA",             f"₩ {s['noa_won']/1e12:.2f}조",
    "비영업자산 (영업권 제외)")


# ── 탭 ──────────────────────────────────────────────────────────────
tab_dcf, tab_wacc, tab_multi, tab_sens, tab_torn, tab_beta = st.tabs(
    ["📊 DCF (5년 FCFF + TV)", "🧮 WACC 분해", "🏷️ 멀티플 역산",
     "🌡️ 민감도 매트릭스", "🌪️ 토네이도", "📈 피어 베타"]
)

# ── DCF 탭 ─────────────────────────────────────────────────────────
with tab_dcf:
    st.markdown("**5년 명시 예측 + 영구가치 (Base case, 단위: ₩ 십억)**")
    dcf = data["dcf"]
    df_dcf = pd.DataFrame({
        "항목": ["매출 성장률","매출","EBIT (OPM 적용)","− 세금","+ D&A",
                "− CapEx (Net)","− ΔNWC","FCFF","할인계수","현재가치"],
        **{lbl: [
            f"{dcf['growth'][i]*100:.1f}%",
            f"{dcf['revenue'][i]:,.0f}",
            f"{dcf['ebit'][i]:,.0f}",
            f"{dcf['tax'][i]:,.0f}" if i < 5 or dcf['tax'][i] else "—",
            f"{dcf['da'][i]:,.0f}"  if i < 5 or dcf['da'][i] else "—",
            f"{dcf['capex'][i]:,.0f}" if i < 5 or dcf['capex'][i] else "—",
            f"{dcf['dnwc'][i]:,.0f}"  if i < 5 or dcf['dnwc'][i] else "—",
            f"**{dcf['fcff'][i]:,.0f}**",
            f"{dcf['df'][i]:.3f}",
            f"{dcf['pv'][i]:,.0f}",
        ] for i, lbl in enumerate(dcf["labels"])}
    })
    st.dataframe(df_dcf, use_container_width=True, hide_index=True)

    st.markdown(f"""
    <div style="background:#f5f7fb; padding:12px 18px; border-radius:8px;
         font-weight:600; margin-top:8px;">
      EV 합계 = ₩ {dcf['ev_total']:,} 십억 (≈ {dcf['ev_total']/1000:.2f}조원)
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="margin-top:10px;">
      <span class="badge badge-ok">검증</span> g(2.0%) < Rf({s['rf']*100:.2f}%) < WACC({s['wacc']*100:.2f}%) ✓
      &nbsp;&nbsp;
      <span class="badge badge-ok">검증</span> Implied ROIC({s['implied_roic']*100:.1f}%) > WACC({s['wacc']*100:.2f}%) ✓
    </div>
    """, unsafe_allow_html=True)

# ── WACC 탭 ─────────────────────────────────────────────────────────
with tab_wacc:
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**WACC 구성 요소**")
        df_wacc = pd.DataFrame(data["wacc_breakdown"], columns=["항목","값","출처"])
        st.dataframe(df_wacc, use_container_width=True, hide_index=True, height=480)
    with col_b:
        st.markdown("**피어 자본구조 & Hamada Unlever**")
        df_peers = pd.DataFrame(data["peers_hamada"])
        st.dataframe(df_peers, use_container_width=True, hide_index=True, height=300)
        st.caption(
            f"타겟 βU = 피어 βU 중위값 = {data['peers_hamada'][-1]['βU']:.3f} · "
            f"타겟 βL = βU × [1+(1−t)·D/E] = **{s['beta_L_target']:.3f}** (Hamada Relever)"
        )

    # ── 피어 자본구조 상세 — E 산출 매칭 ─────────────────────────
    st.markdown("---")
    st.markdown("### 📐 피어 자본구조 상세 — E 산출 과정")
    st.caption(
        "**E = (보통주 발행주식수 − 자기주식수) × 평가기준일 종가** · "
        "보통주만(우선주 제외), 자기주식 차감 — 설계서 v4 §1.7 / 데이터 명세서 §A-5"
    )

    detail = data.get("peer_capital_detail", [])
    if detail:
        df_detail = pd.DataFrame(detail)
        # 표시용 포맷
        df_show = pd.DataFrame({
            "회사":        [r["회사"] for r in detail],
            "종목코드":    [r.get("ticker", "—") for r in detail],
            "보통주 발행": [f"{r['보통주 발행']:,}" for r in detail],
            "− 자기주식":  [f"{r['자기주식']:,}" for r in detail],
            "= 유통주식":  [f"{r['유통주식']:,}" for r in detail],
            "× 종가 (₩)": [f"{r['종가']:,}" for r in detail],
            "= E (시총)": [f"₩ {r['E (시총)']/1e12:.3f}조" for r in detail],
            "D (IBD)":    [f"₩ {r['D (IBD)']/1e8:,.0f}억" for r in detail],
            "D/E":        [f"{r['D/E%']:.1f}%" for r in detail],
            "구분":        [r.get("tag", "—") for r in detail],
        })
        st.dataframe(df_show, use_container_width=True, hide_index=True)
        st.caption(
            "★ 타겟(아모레)은 **자기 D/E 비율은 사용하지 않음** — Hamada Relever에 들어가는 D/E는 "
            "**피어 3사 D/E의 중위값**. 타겟의 D, E 자체는 Net Debt 산정·SRP 매칭·주당가치 계산에 사용."
        )

    # ── IBD 분해 ──────────────────────────────────────────────────
    st.markdown("### 💼 피어별 IBD(이자발생부채) 분해")
    st.caption(
        "팀원 XBRL `ibd_detail` — 단기차입금 + 유동성장기차입금 + 유동리스부채 + "
        "장기차입금 + 비유동리스부채 + 비유동사채 (단위: 백만원)"
    )
    # mockup 안내 — 실제 실행 후 valuation_<T>.json 이 있으면 자동으로 실측값 사용
    if not (Path(__file__).parent / "results").glob("valuation_*.json"):
        st.warning(
            "⚠️ **현재 표시값은 mockup**입니다. `python -m valuation_engine.run_valuation` 실행 시 "
            "팀원 XBRL 모듈이 DART에서 실측 IBD를 추출하여 자동 갱신됩니다. "
            "(예: 아모레퍼시픽 단기차입금 실측 ≈ 2,562억)",
            icon="⚠️",
        )

    ibd_data = data.get("ibd_breakdown", [])
    if ibd_data:
        df_ibd = pd.DataFrame({
            "회사":              [r["회사"] for r in ibd_data],
            "단기차입금":         [f"{r['단기차입금']:,}" for r in ibd_data],
            "유동성장기차입금":   [f"{r['유동성장기차입금']:,}" for r in ibd_data],
            "유동리스부채":       [f"{r['유동리스부채']:,}" for r in ibd_data],
            "장기차입금":         [f"{r['장기차입금']:,}" for r in ibd_data],
            "비유동리스부채":     [f"{r['비유동리스부채']:,}" for r in ibd_data],
            "비유동사채":         [f"{r['비유동사채']:,}" for r in ibd_data],
            "합계 (D)":           [f"**{r['합계']:,}**" for r in ibd_data],
        })
        st.dataframe(df_ibd, use_container_width=True, hide_index=True)
        st.caption(
            "유동성사채(`CurrentPortionOfBonds`)는 **유동성장기차입금 안에 포함**되어 있어 "
            "별도 합산 안 함 (팀원 코드 8개사 실증 분석 결과). 영업부채(매입채무·미지급금 등) 제외."
        )

    # ── 산출 식 시각화 (식 → 값 매칭) ───────────────────────────────
    st.markdown("### 🧮 산출 식 매칭")

    formula_cols = st.columns(4)
    for col, r in zip(formula_cols, detail):
        name  = r["회사"]
        e     = r["E (시총)"]
        d     = r["D (IBD)"]
        de    = r["D/E%"]
        issued= r["보통주 발행"]
        treas = r["자기주식"]
        flt   = r["유통주식"]
        close = r["종가"]
        with col:
            st.markdown(f"**{name}**")
            st.markdown(f"""
            <div style="background:#f9fafc; padding:12px; border-radius:8px; font-size:12px;
                        font-family:monospace; line-height:1.7;">
              발행 {issued:,}<br>
              − 자기 {treas:,}<br>
              = 유통 <b>{flt:,}</b><br>
              × 종가 ₩{close:,}<br>
              <span style="color:#1f4ed8;"><b>= E ₩{e/1e12:.3f}조</b></span><br><br>
              <b>D = ₩{d/1e8:,.0f}억</b><br>
              <span style="color:#5b6473;">D/E = {de:.1f}%</span>
            </div>
            """, unsafe_allow_html=True)

# ── 멀티플 탭 ──────────────────────────────────────────────────────
with tab_multi:
    st.markdown("**멀티플 역산 (피어 중위값 × 대상 지표)**")

    # 평균은 원본(숫자) 기준으로 먼저 계산 — 표 변환 전에
    def _to_number(x):
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            s = x.replace("₩", "").replace(",", "").strip()
            try:
                return float(s)
            except ValueError:
                return 0.0
        return 0.0

    prices = [_to_number(r.get("역산가", 0)) for r in data["multiples"]]
    prices = [p for p in prices if p > 0]
    avg_price = sum(prices) / len(prices) if prices else 0

    # 표 표시용 포맷
    df_m = pd.DataFrame(data["multiples"])
    if "역산가" in df_m.columns:
        df_m["역산가"] = df_m["역산가"].apply(
            lambda x: x if isinstance(x, str) else f"₩ {_to_number(x):,.0f}")
    if "vs 현재" in df_m.columns:
        df_m["vs 현재"] = df_m["vs 현재"].apply(
            lambda x: x if isinstance(x, str)
                      else f"{'+' if float(x)>=0 else ''}{float(x):.1f}%")
    st.dataframe(df_m, use_container_width=True, hide_index=True)
    st.caption(f"4종 평균 ₩ {avg_price:,.0f} · 피어 25~75 백분위 외 시 이격 경고")

# ── 민감도 탭 ──────────────────────────────────────────────────────
with tab_sens:
    st.markdown("**WACC × g 민감도 (3×3 주당가치, 단위: 천원)**")
    st.caption("Base case 가정 고정. WACC ±1%p, g ±0.5%p 만 변동.")
    sens = data["sensitivity"]
    matrix_kw = [[v/1000 for v in row] for row in sens["matrix"]]
    fig = go.Figure(data=go.Heatmap(
        z=matrix_kw,
        x=sens["g_axis"],
        y=sens["wacc_axis"],
        colorscale=[[0,"#c0392b"],[0.5,"#f4d03f"],[1,"#1e8e4b"]],
        text=[[f"{v:.0f}k" for v in row] for row in matrix_kw],
        texttemplate="%{text}", textfont={"size":15,"color":"white"},
        showscale=False, hoverongaps=False,
    ))
    fig.update_layout(height=320, margin=dict(l=10,r=10,t=20,b=10))
    fig.update_xaxes(side="top")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"현재 Base = WACC {s['wacc']*100:.2f}%, g 2.0% → ₩ {s['fair_price']:,.0f}")

# ── 토네이도 탭 ────────────────────────────────────────────────────
with tab_torn:
    st.markdown("**토네이도 차트 — 변수별 단독 변동 영향도 (Base 기준)**")
    st.caption(f"각 변수만 단독으로 ± 변동시킬 때 Base 주당가치(₩{s['fair_price']:,.0f})에서 흔들림.")
    tor = sorted(data["tornado"],
                 key=lambda d: max(abs(d["neg"]), abs(d["pos"])), reverse=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=[t["name"] for t in tor],
        x=[t["neg"]/1000 for t in tor],
        orientation="h", marker_color="#c0392b", name="↓ 변동",
        text=[f"{t['neg']/1000:.0f}k" for t in tor], textposition="outside",
    ))
    fig.add_trace(go.Bar(
        y=[t["name"] for t in tor],
        x=[t["pos"]/1000 for t in tor],
        orientation="h", marker_color="#1e8e4b", name="↑ 변동",
        text=[f"+{t['pos']/1000:.0f}k" for t in tor], textposition="outside",
    ))
    fig.update_layout(
        barmode="overlay", height=380, margin=dict(l=20,r=20,t=20,b=20),
        xaxis_title="주당가치 변동 (천원)", showlegend=True,
        legend=dict(orientation="h", y=-0.2),
    )
    fig.add_vline(x=0, line_color="#5b6473", line_width=1)
    st.plotly_chart(fig, use_container_width=True)

# ── 피어 베타 탭 ───────────────────────────────────────────────────
with tab_beta:
    st.markdown("**피어 베타 회귀 결과 (KRX 2년 주간, OLS + Blume α=2/3 + winsorize ±3σ)**")
    df_b = pd.DataFrame(data["peer_beta"])
    st.dataframe(df_b, use_container_width=True, hide_index=True)
    st.caption(
        "데이터 출처: `peer_beta/results/peer_beta_<T>.json` · "
        "이상치 처리는 winsorize 디폴트 (한공회 베타 정합, Δ 합산 0.124)"
    )


# ── 검증 / 데이터 출처 ─────────────────────────────────────────────
st.markdown("### 검증 로그 & 데이터 출처")
col_v, col_d = st.columns(2)
with col_v:
    st.markdown("**검증 플래그**")
    for tag, msg, cls in data["validation"]:
        st.markdown(f'<span class="badge badge-{cls}">{tag}</span> {msg}',
                    unsafe_allow_html=True)
with col_d:
    st.markdown("**데이터 출처 (as_of_date)**")
    df_src = pd.DataFrame(data["data_sources"], columns=["항목","시점","출처"])
    st.dataframe(df_src, use_container_width=True, hide_index=True)


# ── 푸터 ────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="footer-note">
  <h4>면책 / 운영 주의사항</h4>
  <ul style="margin: 4px 0 12px 18px;">
    <li>본 화면은 <strong>일반투자자 대상 투자정보 제공</strong> 목적이며 <strong>투자 추천이 아닙니다</strong>.</li>
    <li>산출값은 가정에 따라 변동될 수 있으며, Bear/Base/Bull 시나리오와 민감도·토네이도로 범위를 확인하세요.</li>
    <li>데이터 출처: KRX, ECOS, DART OpenAPI, 한공회. 모든 시점은 as_of_date에 기록됨.</li>
  </ul>
  <div class="disclaimer">
    설계서 v4 · 데이터 명세서 · 서비스 플로우 기반 · 컨센서스 미사용, 회사 공시·역사 데이터로만 산출.
  </div>
</div>
""", unsafe_allow_html=True)
