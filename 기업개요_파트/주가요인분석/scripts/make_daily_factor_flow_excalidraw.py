"""Generate Excalidraw flow diagram for daily stock factor analysis."""

from __future__ import annotations

import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from make_excalidraw import _idx, arrow, box, cylinder, ellipse_node, label, save, sticky


def make_daily_factor_on_demand_flow() -> None:
    _idx[0] = 0
    el = []

    el += label(270, 20, "국내 주식 1D 수익률 요인 분석 — 처리 흐름 & 데이터 플로우", fontSize=30, w=1100)
    el += label(45, 72, "1) 사용자 요청/캐시 처리", fontSize=20, w=360)
    el += label(45, 370, "2) 근거 데이터 수집/결합", fontSize=20, w=360)

    # Top lane: user request and cache
    els, _, user = ellipse_node(45, 115, 170, 80, "사용자\n전체 종목 검색", accent="blue", font=15)
    el += els
    els, _, api = box(275, 105, 230, 100, "Backend API\nanalyze_stock_cached.py", accent="blue", font=16)
    el += els
    els, _, resolve = box(565, 105, 200, 100, "종목 매핑\n이름 → 코드", accent="amber", font=16)
    el += els
    els, _, cache_lookup = box(830, 105, 190, 100, "캐시 조회\n동일 거래일 결과", accent="green", font=15)
    el += els
    els, _, cache_store_top = cylinder(
        1080,
        82,
        260,
        125,
        "MongoDB Cache",
        "filmn9.daily_factor_reports\nstock_code + trade_date",
        accent="green",
    )
    el += els
    els, _, json_fallback = cylinder(
        800,
        255,
        220,
        100,
        "JSON Fallback",
        "기존 실험 결과\nlocal backup",
        accent="amber",
    )
    el += els
    els, _, saved_return = box(1085, 260, 250, 90, "저장 결과 반환\nOpenAI 추가 호출 없음", accent="green", font=15)
    el += els
    els, _, ui = box(1400, 120, 190, 120, "서비스 화면\n요약 · 요인 3개\n근거 · 비용", accent="purple", font=15)
    el += els

    el += arrow(user, api, accent="blue", label="검색")
    el += arrow(api, resolve, accent="blue", label="query")
    el += arrow(resolve, cache_lookup, accent="amber", label="code/date")
    el += arrow(cache_lookup, cache_store_top, accent="green", label="lookup")
    el += arrow(cache_lookup, saved_return, side_from="bottom", side_to="top", accent="green", label="hit")
    el += arrow(cache_lookup, json_fallback, side_from="bottom", side_to="top", accent="amber", dashed=True, label="mongo miss")
    el += arrow(json_fallback, saved_return, accent="amber", label="json hit + upsert")
    el += arrow(saved_return, ui, accent="green", label="return")

    # Data source lane
    els, _, ohlcv = cylinder(45, 430, 210, 115, "OHLCV", "현재 pykrx\nTo-be 팀원 DB", accent="blue")
    el += els
    els, _, market = ellipse_node(300, 430, 180, 95, "시장 지수\nFDR KOSPI/KOSDAQ", accent="blue", font=14)
    el += els
    els, _, news = ellipse_node(525, 430, 190, 95, "뉴스\nNaver Search API", accent="amber", font=14)
    el += els
    els, _, dart = ellipse_node(760, 430, 170, 95, "공시\nOpenDART", accent="red", font=15)
    el += els
    els, _, flow = ellipse_node(970, 430, 190, 95, "수급\n기관·외국인·개인", accent="purple", font=14)
    el += els
    els, _, peers = ellipse_node(1215, 430, 180, 95, "비교 종목\npeer returns", accent="ink", font=14)
    el += els

    els, _, price_calc = box(65, 610, 220, 95, "가격 지표 계산\n1D · 5D · 거래량\n패턴 분류", accent="blue", font=14)
    el += els
    els, _, evidence = box(
        505,
        630,
        430,
        125,
        "Evidence Pack\nprice + market + news + dart\n+ investor_flow + peers",
        accent="amber",
        font=16,
    )
    el += els
    els, _, llm = box(1015, 630, 260, 125, "OpenAI gpt-5.4-mini\n요인 3개 요약\n주의 문구 생성", accent="purple", font=15)
    el += els
    els, _, json_backup = cylinder(745, 835, 230, 105, "JSON 백업", "--storage both\n파일로도 저장", accent="amber")
    el += els
    els, _, json_store = cylinder(1045, 835, 260, 115, "MongoDB 저장", "report + evidence_pack\n토큰·비용 포함", accent="green")
    el += els
    els, _, new_return = box(1400, 650, 190, 115, "신규 결과 반환\nheadline\nfactors\nnotes", accent="purple", font=14)
    el += els

    el += arrow(json_fallback, evidence, side_from="bottom", side_to="top", accent="amber", dashed=True, label="miss/refresh", curve=70)
    el += arrow(ohlcv, price_calc, side_from="bottom", side_to="top", accent="blue")
    el += arrow(price_calc, evidence, accent="blue", label="price")
    el += arrow(market, evidence, side_from="bottom", side_to="top", accent="blue", label="market")
    el += arrow(news, evidence, side_from="bottom", side_to="top", accent="amber", label="news")
    el += arrow(dart, evidence, side_from="bottom", side_to="top", accent="red", label="disclosure")
    el += arrow(flow, evidence, side_from="bottom", side_to="right", accent="purple", label="flow")
    el += arrow(peers, evidence, side_from="bottom", side_to="right", accent="ink", label="peers")
    el += arrow(evidence, llm, accent="purple", label="prompt")
    el += arrow(llm, json_store, side_from="bottom", side_to="top", accent="green", label="save")
    el += arrow(json_store, json_backup, side_from="left", side_to="right", accent="amber", dashed=True, label="optional")
    el += arrow(json_store, cache_store_top, side_from="top", side_to="bottom", accent="green", dashed=True, label="reuse")
    el += arrow(llm, new_return, accent="purple", label="result")
    el += arrow(new_return, ui, side_from="top", side_to="bottom", accent="purple", label="return")

    # Notes
    el += sticky(
        45,
        815,
        300,
        105,
        "운영 기준",
        "장마감 후 trade_date 기준 생성.\n장중에는 최신 완료 거래일 리포트를 반환하거나 장마감 후 분석 안내.",
        color="yellow",
        rotate=-1,
    )
    el += sticky(
        385,
        835,
        300,
        95,
        "캐시 키",
        "MongoDB unique key:\nstock_code + trade_date + model + prompt_version",
        color="green",
        rotate=1,
    )
    el += sticky(
        1395,
        835,
        250,
        95,
        "실험 비용",
        "10종목: input 43,823 / output 5,993\n예상 비용 약 $0.059834, 약 80.78원.",
        color="blue",
        rotate=-1,
    )

    save(el, "daily_factor_on_demand_flow")


if __name__ == "__main__":
    make_daily_factor_on_demand_flow()
