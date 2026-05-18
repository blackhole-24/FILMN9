"""
components/html_builder.py
────────────────────────────
data_aggregator 결과 → 완성된 HTML 문자열 생성.
Plotly.js (CDN) 차트 포함, 단일 파일로 브라우저에서 바로 열림.
"""
from __future__ import annotations
import json, math
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# 색상 팔레트
# ─────────────────────────────────────────────────────────────────────────────
C_UP   = "#EF4444"
C_DOWN = "#2563EB"
C_FLAT = "#6B7280"
C_GREEN= "#10B981"
C_GOLD = "#F59E0B"
DONUT_COLORS = ["#F97316", "#3B82F6", "#10B981", "#8B5CF6", "#EC4899", "#64748B"]


def _num(v, default="-"):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return default
    return v


def _fmt_krw_str(v) -> str:
    if v is None: return "-"
    v = int(v)
    조 = v // 1_000_000_000_000
    억 = (v % 1_000_000_000_000) // 100_000_000
    if 조 > 0:
        return f"{조:,}조 {억:,}억" if 억 else f"{조:,}조"
    return f"{억:,}억" if 억 else f"{v:,}"


def _fmt_mil(v) -> str:
    """백만원 단위 숫자 → 표시용 문자열
    1조  = 1,000,000 백만원
    1억  = 100       백만원
    """
    if v is None: return "-"
    v = float(v)
    sign = ""
    a = abs(v)
    if v < 0: sign = "▼"
    if a >= 1_000_000:
        return f"{sign}{a/1_000_000:,.2f}조"
    if a >= 100:
        return f"{sign}{a/100:,.0f}억"
    return f"{sign}{a:,.0f}백만"


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Pretendard','Apple SD Gothic Neo','Segoe UI',sans-serif;
  background:#F8FAFC;color:#1E293B;font-size:13px;line-height:1.6;}
.page{max-width:1400px;margin:0 auto;padding:20px 24px;}

/* 헤더 */
.hdr{background:linear-gradient(135deg,#0A1628,#1a3a5c);
  border-radius:14px;padding:20px 28px;margin-bottom:20px;
  display:flex;align-items:center;justify-content:space-between;}
.hdr-left h1{font-size:22px;font-weight:800;color:#fff;}
.hdr-left h1 span{color:#F97316;}
.hdr-left p{font-size:12px;color:#94A3B8;margin-top:3px;}
.hdr-right{text-align:right;}
.price-big{font-size:32px;font-weight:800;color:#fff;}
.price-change{font-size:14px;font-weight:600;margin-top:2px;}
.price-meta{display:flex;gap:20px;margin-top:10px;flex-wrap:wrap;}
.pm-item{text-align:center;}
.pm-item .lbl{font-size:10px;color:#64748B;}
.pm-item .val{font-size:12px;font-weight:700;color:#E2E8F0;}

/* 카드 그리드 */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px;}
.grid4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px;margin-bottom:16px;}
.card{background:#fff;border-radius:12px;padding:18px 20px;
  box-shadow:0 1px 4px rgba(0,0,0,.06);border:1px solid #E2E8F0;}
.card-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;}
.card-title{font-size:14px;font-weight:700;color:#1E293B;display:flex;align-items:center;gap:6px;}
.card-sub{font-size:11px;color:#94A3B8;}
.card-badge{background:#FFF7ED;color:#F97316;border:1px solid #FED7AA;
  border-radius:12px;padding:2px 10px;font-size:10px;font-weight:700;}

/* 주가 차트 */
.chart-full{background:#fff;border-radius:12px;padding:20px;
  box-shadow:0 1px 4px rgba(0,0,0,.06);border:1px solid #E2E8F0;margin-bottom:16px;}
.period-btns{display:flex;gap:6px;margin-bottom:12px;}
.pb{padding:5px 14px;border-radius:8px;border:1px solid #E2E8F0;
  font-size:12px;font-weight:600;cursor:pointer;background:#fff;color:#64748B;}
.pb.active,.pb:hover{background:#F97316;color:#fff;border-color:#F97316;}

/* 재무 하이라이트 */
.hl-value{font-size:22px;font-weight:800;color:#1E293B;margin:8px 0 2px;}
.hl-yoy{font-size:12px;font-weight:600;}
.hl-yoy.up{color:#EF4444;}
.hl-yoy.dn{color:#2563EB;}

/* 재무 상세 탭 */
.tabs{display:flex;gap:0;border-bottom:2px solid #E2E8F0;margin-bottom:14px;}
.tab{padding:8px 16px;font-size:12px;font-weight:600;color:#64748B;
  cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;}
.tab.active{color:#F97316;border-bottom-color:#F97316;}
.tab-content{display:none;}
.tab-content.active{display:block;}
.fin-table{width:100%;border-collapse:collapse;font-size:11.5px;}
.fin-table th{background:#F8FAFC;padding:7px 10px;text-align:right;
  font-weight:700;color:#475569;border-bottom:2px solid #E2E8F0;white-space:nowrap;}
.fin-table th:first-child{text-align:left;}
.fin-table td{padding:6px 10px;border-bottom:1px solid #F1F5F9;
  text-align:right;color:#374151;}
.fin-table td:first-child{text-align:left;color:#1E293B;font-weight:500;}
.fin-table tr:hover td{background:#FFFBF5;}
.fin-table .section-row td{background:#F8FAFC;font-weight:700;color:#475569;font-size:11px;}

/* 건전성 */
.ratio-row{display:flex;align-items:center;gap:10px;padding:8px 0;
  border-bottom:1px solid #F1F5F9;}
.ratio-row:last-child{border-bottom:none;}
.ratio-name{width:90px;font-size:12px;font-weight:600;color:#374151;flex-shrink:0;}
.ratio-bar-wrap{flex:1;height:8px;background:#F1F5F9;border-radius:4px;overflow:hidden;}
.ratio-bar{height:100%;border-radius:4px;transition:width .6s;}
.ratio-val{width:80px;text-align:right;font-size:12px;font-weight:700;color:#1E293B;flex-shrink:0;}
.ratio-detail{width:200px;font-size:10px;color:#94A3B8;flex-shrink:0;}

/* 기업 개요 */
.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 20px;}
.info-row{display:flex;gap:8px;padding:5px 0;border-bottom:1px solid #F1F5F9;font-size:12px;}
.info-row:last-child{border-bottom:none;}
.info-lbl{width:90px;color:#64748B;flex-shrink:0;}
.info-val{color:#1E293B;font-weight:500;word-break:break-all;}
.info-val a{color:#F97316;text-decoration:none;}

/* 주주 구성 */
.sh-legend{margin-top:10px;}
.sh-item{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px;}
.sh-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}
.sh-name{flex:1;color:#374151;}
.sh-pct{font-weight:700;color:#1E293B;}

/* 경영인 */
.exec-table{width:100%;border-collapse:collapse;font-size:12px;}
.exec-table th{background:#F8FAFC;padding:7px 10px;text-align:left;
  font-weight:700;color:#475569;border-bottom:2px solid #E2E8F0;}
.exec-table td{padding:7px 10px;border-bottom:1px solid #F1F5F9;color:#374151;}
.exec-table tr:hover td{background:#FFFBF5;}

/* 공시 */
.disc-list{list-style:none;}
.disc-item{display:flex;align-items:flex-start;gap:12px;padding:10px 0;
  border-bottom:1px solid #F1F5F9;font-size:12px;}
.disc-item:last-child{border-bottom:none;}
.disc-dt{color:#94A3B8;white-space:nowrap;flex-shrink:0;}
.disc-nm a{color:#1E293B;text-decoration:none;font-weight:500;}
.disc-nm a:hover{color:#F97316;}
.disc-badge{background:#FFF7ED;color:#F97316;border:1px solid #FED7AA;
  border-radius:4px;padding:1px 6px;font-size:10px;margin-left:6px;}

/* 섹션 타이틀 */
.sec-hdr{font-size:16px;font-weight:800;color:#1E293B;margin:24px 0 12px;
  display:flex;align-items:center;gap:8px;}
.sec-hdr::after{content:'';flex:1;height:2px;background:#F1F5F9;}

.badge-yn{display:inline-block;padding:2px 8px;border-radius:4px;
  font-size:10px;font-weight:700;background:#F0FDF4;color:#16A34A;}
.ftr{text-align:center;padding:20px;color:#94A3B8;font-size:11px;margin-top:20px;}
"""


# ─────────────────────────────────────────────────────────────────────────────
# 컴포넌트별 HTML 빌더
# ─────────────────────────────────────────────────────────────────────────────

def _build_header(data: dict) -> str:
    pi = data["price_info"]
    name = data["meta"]["name"].replace("(주)", "").strip()
    code = data["meta"]["stock_code"]
    price = pi.get("현재가")
    chg = pi.get("변동", 0) or 0
    chg_pct = pi.get("변동률", 0) or 0
    color = pi.get("색상", C_FLAT)
    sign = "▲" if chg > 0 else ("▼" if chg < 0 else "")

    meta_items = [
        ("전일종가", f"{pi.get('전일종가', '-'):,}" if pi.get('전일종가') else "-"),
        ("시가",    f"{pi.get('시가', '-'):,}"     if pi.get('시가') else "-"),
        ("고가",    f"<span style='color:{C_UP}'>{pi.get('고가','-'):,}</span>" if pi.get('고가') else "-"),
        ("저가",    f"<span style='color:{C_DOWN}'>{pi.get('저가','-'):,}</span>" if pi.get('저가') else "-"),
        ("거래량",  f"{pi.get('거래량',0):,}주"),
        ("거래대금", pi.get("거래대금", "-")),
        ("시가총액", pi.get("시가총액", "-")),
        ("52주최고", f"{pi.get('52주최고','-'):,}" if pi.get('52주최고') else "-"),
        ("52주최저", f"{pi.get('52주최저','-'):,}" if pi.get('52주최저') else "-"),
        ("PER/EPS", f"{pi.get('PER','-')} / {int(pi.get('EPS',0) or 0):,}" if pi.get('PER') else "-"),
        ("외국인보유", pi.get("외국인보유", "-")),
    ]

    meta_html = "".join(
        f'<div class="pm-item"><div class="lbl">{k}</div><div class="val">{v}</div></div>'
        for k, v in meta_items
    )

    return f"""
<div class="hdr">
  <div class="hdr-left">
    <h1>{name} <span>({code})</span></h1>
    <p>한국거래소(KRX) · {pi.get('기준시각', data['generated_at'])}</p>
  </div>
  <div class="hdr-right">
    <div class="price-big" style="color:{color}">{price:,}원</div>
    <div class="price-change" style="color:{color}">
      {sign} {abs(chg):,}원 &nbsp; ({chg_pct:+.2f}%)
    </div>
    <div class="price-meta">{meta_html}</div>
  </div>
</div>"""


def _build_stock_chart(data: dict) -> str:
    history = data["price_history"]
    pi = data["price_info"]
    color = pi.get("색상", C_FLAT)

    # 각 기간 데이터를 JSON으로 변환
    datasets = {}
    for k, df in history.items():
        if df.empty:
            datasets[k] = {"x": [], "close": [], "volume": []}
            continue
        datasets[k] = {
            "x"     : [str(i)[:16] for i in df.index],
            "close" : [round(float(v), 0) if not math.isnan(float(v)) else None for v in df["Close"]],
            "volume": [int(v) for v in df["Volume"]],
        }

    ds_json = json.dumps(datasets, ensure_ascii=False)
    default_key = "최근1년"

    btns = "".join(
        '<button class="pb{act}" onclick="showPeriod(\'{k}\')">{k}</button>'.format(
            act=" active" if k == default_key else "", k=k
        )
        for k in history
    )

    return f"""
<div class="chart-full">
  <div class="card-hdr">
    <div class="card-title">📈 주가</div>
    <div class="period-btns" id="periodBtns">{btns}</div>
  </div>
  <div id="stockChart" style="height:300px;"></div>
  <div id="volChart"   style="height:80px;margin-top:6px;"></div>
</div>
<script>
const DS = {ds_json};
function showPeriod(key) {{
  const d = DS[key] || {{x:[],close:[],volume:[]}};
  const lineColor = '{color}';
  const fillColor = lineColor === '{C_UP}' ? 'rgba(239,68,68,.15)' : 'rgba(37,99,235,.15)';

  Plotly.newPlot('stockChart', [{{
    x: d.x, y: d.close, type: 'scatter', mode: 'lines',
    line: {{color: lineColor, width: 2}},
    fill: 'tozeroy', fillcolor: fillColor,
    hovertemplate: '%{{x}}<br>%{{y:,.0f}}원<extra></extra>'
  }}], {{
    margin: {{t:10,b:30,l:70,r:10}},
    paper_bgcolor: 'white', plot_bgcolor: 'white',
    xaxis: {{showgrid:false, tickfont:{{size:10}}}},
    yaxis: {{tickformat:',.0f', tickfont:{{size:10}}, ticksuffix:'원'}},
    hovermode: 'x unified'
  }}, {{displayModeBar: false, responsive: true}});

  const volColors = d.close.map((v,i) =>
    i===0 ? '#94A3B8' : (v >= (d.close[i-1]||v) ? '{C_UP}' : '{C_DOWN}'));
  Plotly.newPlot('volChart', [{{
    x: d.x, y: d.volume, type: 'bar',
    marker: {{color: volColors}},
    hovertemplate: '%{{x}}<br>%{{y:,}}주<extra></extra>'
  }}], {{
    margin: {{t:0,b:30,l:70,r:10}},
    paper_bgcolor: 'white', plot_bgcolor: 'white',
    xaxis: {{showgrid:false, tickfont:{{size:9}}}},
    yaxis: {{tickfont:{{size:9}}}},
    showlegend: false, hovermode: 'x unified'
  }}, {{displayModeBar: false, responsive: true}});

  document.querySelectorAll('.pb').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
}}
showPeriod('{default_key}');
</script>"""


def _build_highlight(data: dict) -> str:
    hl = data["highlight"]
    df = hl.get("연결", hl.get("별도", pd.DataFrame()))
    if df.empty:
        return ""

    year_cols = [c for c in df.columns if str(c).isdigit()]
    cards = []
    labels = {"매출액": ("💰", "#10B981"), "영업이익": ("📊", "#F97316"), "당기순이익": ("💵", "#8B5CF6")}

    for _, row in df.iterrows():
        구분 = row["구분"]
        icon, bar_color = labels.get(구분, ("📌", "#64748B"))
        latest = row.get(year_cols[0]) if year_cols else None
        yoy = row.get("yoy_pct")

        yoy_html = ""
        if yoy is not None:
            cls = "up" if yoy > 0 else "dn"
            sign = "▲" if yoy > 0 else "▼"
            yoy_html = f'<div class="hl-yoy {cls}">{sign} {abs(yoy):.2f}% YoY</div>'

        # 바차트 데이터
        bar_vals = []
        bar_lbls = []
        for y in reversed(year_cols):
            v = row.get(y)
            if v is not None:
                bar_vals.append(float(v))
                bar_lbls.append(str(y))

        chart_id = f"hl_{구분.replace('·','_')}"
        bar_json  = json.dumps(bar_vals)
        lbl_json  = json.dumps(bar_lbls)

        cards.append(f"""
<div class="card">
  <div class="card-hdr">
    <div class="card-title">{icon} {구분}</div>
    <div class="card-badge">연결·2025.12</div>
  </div>
  <div class="hl-value">{_fmt_mil(latest)}</div>
  {yoy_html}
  <div id="{chart_id}" style="height:120px;margin-top:10px;"></div>
  <script>
  Plotly.newPlot('{chart_id}', [{{
    x:{lbl_json}, y:{bar_json}, type:'bar',
    marker:{{color:'{bar_color}'}},
    text:{bar_json}.map(v=>v>=1e6?(v/1e6).toFixed(2)+'조':(v>=100?(v/100).toFixed(0)+'억':v.toFixed(0)+'백만')),
    textposition:'outside', textfont:{{size:9}},
    hovertemplate:'%{{x}}<br>%{{y:,.0f}}백만원<extra></extra>'
  }}], {{
    margin:{{t:20,b:20,l:5,r:5}},
    paper_bgcolor:'white', plot_bgcolor:'white',
    xaxis:{{tickfont:{{size:9}}, showgrid:false}},
    yaxis:{{visible:false}},
    showlegend:false
  }}, {{displayModeBar:false, responsive:true}});
  </script>
</div>""")

    return f'<div class="grid3">{"".join(cards)}</div>'


def _build_financial_detail(data: dict) -> str:
    detail = data["detail"]
    tabs_html, contents_html = "", ""
    tab_ids = []

    tab_labels = {
        "포괄손익계산서(연결)": "포괄손익계산서(연결)",
        "재무상태표(연결)": "재무상태표(연결)",
    }

    for i, (label, df) in enumerate(detail.items()):
        tab_id = f"ftab_{i}"
        tab_ids.append(tab_id)
        display_label = tab_labels.get(label, label)
        active = "active" if i == 0 else ""
        tabs_html += f'<div class="tab {active}" onclick="switchTab(\'{tab_id}\')">{display_label}</div>'

        # 테이블 HTML
        year_cols = [c for c in df.columns if str(c).isdigit()]
        th_years = "".join(f"<th>{y}</th>" for y in year_cols)

        rows_html = ""
        for _, row in df.head(60).iterrows():
            구분 = str(row.get("구분", "")).strip()
            if not 구분:
                continue
            tds = ""
            for y in year_cols:
                v = row.get(y)
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    tds += "<td>-</td>"
                else:
                    tds += f"<td>{float(v):,.0f}</td>"
            rows_html += f"<tr><td>{구분}</td>{tds}</tr>"

        contents_html += f"""
<div class="tab-content {active}" id="{tab_id}">
  <div style="font-size:10px;color:#94A3B8;margin-bottom:6px;">단위: 백만원</div>
  <div style="max-height:420px;overflow-y:auto;">
  <table class="fin-table">
    <thead><tr><th>구분</th>{th_years}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  </div>
</div>"""

    return f"""
<div class="card">
  <div class="card-hdr">
    <div class="card-title">📋 재무정보</div>
    <div class="card-sub">2025.12 기준</div>
  </div>
  <div class="tabs">{tabs_html}</div>
  {contents_html}
</div>
<script>
function switchTab(id) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  event.target.classList.add('active');
}}
</script>"""


def _build_ratios(data: dict) -> str:
    ratios = data["ratios"]
    RATIO_DEFS = [
        ("부채비율",   "%",  100,   "#EF4444", "부채총계 / 자본총계 × 100",    "낮을수록 안전"),
        ("유동비율",   "%",  300,   "#10B981", "유동자산 / 유동부채 × 100",    "100% 이상 양호"),
        ("이자보상배율","배",  20,   "#F97316", "영업이익 / 금융비용",          "1배 이상 안전"),
        ("당좌비율",   "%",  200,   "#3B82F6", "(유동자산-재고) / 유동부채×100","100% 이상 양호"),
        ("유보율",     "%",  5000,  "#8B5CF6", "(자본잉여금+이익잉여금) / 자본금×100", "높을수록 좋음"),
    ]

    rows = ""
    for name, unit, max_val, bar_color, formula, comment in RATIO_DEFS:
        r = ratios.get(name, {})
        val = r.get("value")
        if val is None:
            continue
        bar_pct = min(100, abs(val) / max_val * 100)
        rows += f"""
<div class="ratio-row">
  <div class="ratio-name">{name}</div>
  <div class="ratio-bar-wrap">
    <div class="ratio-bar" style="width:{bar_pct:.1f}%;background:{bar_color};"></div>
  </div>
  <div class="ratio-val">{val:,.2f}{unit}</div>
  <div class="ratio-detail">{comment}</div>
</div>"""

    return f"""
<div class="card">
  <div class="card-hdr">
    <div class="card-title">💪 기업 건전성</div>
    <div class="card-sub">2025.12 기준 · 연결재무제표</div>
  </div>
  {rows}
</div>"""


def _build_company_info(data: dict) -> str:
    co = data["company"]
    fields = [
        ("대표이사",   co.get("ceo_nm", "-")),
        ("설립일",     co.get("est_dt", "-")),
        ("법인구분",   co.get("corp_cls", "-")),
        ("결산월",     f"{co.get('acc_mt','-')}월"),
        ("법인등록번호", co.get("jurir_no", "-")),
        ("사업자번호",  co.get("bizr_no", "-")),
        ("전화번호",   co.get("phn_no", "-")),
        ("팩스번호",   co.get("fax_no", "-")),
        ("홈페이지",   ('<a href="http://' + co.get("hm_url","") + '" target="_blank">' + co.get("hm_url","-") + '</a>') if co.get("hm_url") else "-"),
        ("주소",       co.get("adres", "-")),
    ]
    rows = "".join(
        f'<div class="info-row"><div class="info-lbl">{k}</div><div class="info-val">{v}</div></div>'
        for k, v in fields
    )
    return f"""
<div class="card">
  <div class="card-hdr">
    <div class="card-title">🏢 기업 개요</div>
    <div class="card-sub">2025.12 기준</div>
  </div>
  <div class="info-grid" style="grid-template-columns:1fr;">{rows}</div>
</div>"""


def _build_shareholders(data: dict) -> str:
    holders = data["shareholders"]
    colors_json = json.dumps(DONUT_COLORS[:len(holders)])
    labels_json = json.dumps([h["name"] for h in holders])
    values_json = json.dumps([h["ratio"] for h in holders])

    legend = "".join(
        f'<div class="sh-item">'
        f'<div class="sh-dot" style="background:{DONUT_COLORS[i%len(DONUT_COLORS)]}"></div>'
        f'<div class="sh-name">{h["name"]}</div>'
        f'<div class="sh-pct">{h["ratio"]:.2f}%</div>'
        f'</div>'
        for i, h in enumerate(holders)
    )

    return f"""
<div class="card">
  <div class="card-hdr">
    <div class="card-title">🍩 주주 구성</div>
    <div class="card-sub">2025.12 기준</div>
  </div>
  <div id="donutChart" style="height:200px;"></div>
  <div class="sh-legend">{legend}</div>
</div>
<script>
Plotly.newPlot('donutChart', [{{
  labels: {labels_json},
  values: {values_json},
  type: 'pie', hole: 0.55,
  marker: {{colors: {colors_json}}},
  textinfo: 'percent',
  hovertemplate: '%{{label}}<br>%{{value:.2f}}%<extra></extra>'
}}], {{
  margin:{{t:10,b:10,l:10,r:10}},
  paper_bgcolor:'white',
  showlegend: false
}}, {{displayModeBar:false, responsive:true}});
</script>"""


def _build_executives(data: dict) -> str:
    # 출처: financial_parser.py get_executive_table() → 사업보고서 "임원현황" 섹션
    # 지분율 출처: dart_api_collector.py get_major_shareholders() → DART majorstock.json
    df = data["executives"]
    if df.empty:
        return ""

    # 주주 지분율 매핑 (경영인 이름 → 지분율)
    sh_map = {h["name"]: h["ratio"] for h in data.get("shareholders", [])}

    rows_visible = ""   # 상위 5명 (기본 표시)
    rows_hidden  = ""   # 나머지 (접기)

    for idx, (_, r) in enumerate(df.iterrows()):
        name     = r.get("성명", "-")
        직위     = r.get("직위", "-")
        담당업무 = r.get("담당업무", "-")
        재직기간 = r.get("재직기간", "-")
        관계     = r.get("최대주주와의관계", "")
        own_pct  = sh_map.get(name)
        own_html = f"{own_pct:.2f}%" if own_pct else ("-" if not 관계 else "-")
        rel_html = f'<span style="font-size:10px;color:#94A3B8;">{관계}</span>' if 관계 else ""

        row = f"""<tr>
          <td>{name}{rel_html}</td>
          <td>{직위}</td>
          <td>{담당업무}</td>
          <td>{재직기간}</td>
          <td style="text-align:right;font-weight:700;color:#F97316;">{own_html}</td>
        </tr>"""
        if idx < 5:
            rows_visible += row
        else:
            rows_hidden += row

    hidden_block = ""
    toggle_btn   = ""
    if rows_hidden:
        hidden_block = f'<tbody id="execHidden" style="display:none;">{rows_hidden}</tbody>'
        toggle_btn   = f"""
  <div style="text-align:center;margin-top:8px;">
    <button onclick="toggleExec()" id="execToggleBtn"
      style="padding:4px 16px;border:1px solid #E2E8F0;border-radius:6px;
             font-size:11px;cursor:pointer;background:#fff;color:#64748B;">
      전체 보기 ({len(df)}명)
    </button>
  </div>
  <script>
  function toggleExec() {{
    const h = document.getElementById('execHidden');
    const b = document.getElementById('execToggleBtn');
    if (h.style.display === 'none') {{
      h.style.display = ''; b.textContent = '접기';
    }} else {{
      h.style.display = 'none'; b.textContent = '전체 보기 ({len(df)}명)';
    }}
  }}
  </script>"""

    return f"""
<div class="card">
  <div class="card-hdr">
    <div class="card-title">👤 경영인</div>
    <div class="card-sub">2025.12 기준 · 사업보고서</div>
  </div>
  <table class="exec-table">
    <thead><tr><th>성명</th><th>직위</th><th>담당업무</th><th>재직기간</th><th style="text-align:right;">지분율</th></tr></thead>
    <tbody>{rows_visible}</tbody>
    {hidden_block}
  </table>
  {toggle_btn}
</div>"""


def _build_disclosures(data: dict) -> str:
    items = ""
    for d in data["disclosures"]:
        nm = d["report_nm"].strip()
        tag = ""
        if "사업보고서" in nm:  tag = '<span class="disc-badge">사업보고서</span>'
        elif "분기" in nm:      tag = '<span class="disc-badge">분기</span>'
        elif "감사" in nm:      tag = '<span class="disc-badge">감사</span>'
        items += f"""
<li class="disc-item">
  <div class="disc-dt">{d['rcept_dt']}</div>
  <div class="disc-nm">
    <a href="{d['dart_url']}" target="_blank">{nm}</a>{tag}
    <span style="color:#94A3B8;font-size:10px;margin-left:6px;">{d.get('flr_nm','')}</span>
  </div>
</li>"""
    return f"""
<div class="card" style="grid-column:span 2;">
  <div class="card-hdr">
    <div class="card-title">📰 최근 공시</div>
    <div class="card-sub">DART 연동</div>
  </div>
  <ul class="disc-list">{items}</ul>
</div>"""


# ─────────────────────────────────────────────────────────────────────────────
# 메인 빌더
# ─────────────────────────────────────────────────────────────────────────────

def build_html(data: dict) -> str:
    hdr         = _build_header(data)
    chart       = _build_stock_chart(data)
    highlight   = _build_highlight(data)
    fin_detail  = _build_financial_detail(data)
    ratios      = _build_ratios(data)
    company     = _build_company_info(data)
    shareholders= _build_shareholders(data)
    executives  = _build_executives(data)
    disclosures = _build_disclosures(data)

    name = data["meta"]["name"].replace("(주)","").strip()
    code = data["meta"]["stock_code"]

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FILMN9 — {name}({code}) 기업 리포트</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>{CSS}</style>
</head>
<body>
<div class="page">

{hdr}

<div class="sec-hdr">주가</div>
{chart}

<div class="sec-hdr">재무 하이라이트</div>
{highlight}

<div class="sec-hdr">재무 정보 상세</div>
{fin_detail}

<div class="sec-hdr">기업 현황</div>
<div class="grid2">
  <div style="display:flex;flex-direction:column;gap:16px;">
    {company}
    {ratios}
  </div>
  <div style="display:flex;flex-direction:column;gap:16px;">
    {shareholders}
    {executives}
  </div>
</div>

<div class="sec-hdr">최근 공시</div>
{disclosures}

<div class="ftr">FILMN9 POC · {data['generated_at']} 생성 · 데이터 출처: DART / yfinance / KRX</div>
</div>
</body>
</html>"""


