"""
processors/data_aggregator.py
───────────────────────────────
모든 수집/처리 모듈 결과를 단일 딕셔너리로 통합.
HTML 리포트 생성기(report_generator.py)가 이 함수 하나만 호출하면 됨.

사용 예시
─────────
from src.processors.data_aggregator import aggregate
data = aggregate("090430")
# data["price_info"]["현재가"] → 130200
# data["highlight"]["연결"]   → DataFrame
# data["ratios"]["부채비율"]  → {"value": 11.23, ...}
"""

from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app_config import SAMPLE, CHART_PERIODS
from src.collectors.yfinance_collector  import get_price_info, get_price_history
from src.collectors.dart_api_collector  import get_company_info, get_major_shareholders, get_recent_disclosures
from src.collectors.naver_scraper       import get_foreign_ratio
from src.processors.financial_parser   import get_financial_highlight, get_financial_detail, get_executive_table
from src.processors.ratio_calculator   import calculate_ratios


def aggregate(
    stock_code: str  = SAMPLE["stock_code"],
    corp_code:  str  = SAMPLE["corp_code"],
    ticker_yf:  str  = SAMPLE["ticker_yf"],
    n_disclosures: int = 10,
) -> dict:
    """
    전체 데이터를 수집·가공하여 딕셔너리로 반환.

    Returns
    -------
    {
      "meta"         : 기업 기본 메타 정보,
      "price_info"   : 현재가·등락·시총 등,
      "price_history": {기간키: DataFrame},
      "highlight"    : {"연결": df, "별도": df},  재무 하이라이트
      "detail"       : {"연결재무제표": df, "별도재무제표": df},
      "ratios"       : 5개 재무비율 dict,
      "company"      : DART 기업개요,
      "shareholders" : 주요 주주 리스트 + 외국인 보유비율,
      "disclosures"  : 최근 공시 리스트,
      "executives"   : 임원 DataFrame,
      "generated_at" : 생성 시각 str,
    }
    """
    print(f"[aggregator] 데이터 수집 시작 — {stock_code}")

    # ── 1) 주가 ─────────────────────────────────────────────
    print("  → 주가 수집 (yfinance)...")
    price_info    = get_price_info(ticker_yf)
    price_history = {k: get_price_history(ticker_yf, k) for k in CHART_PERIODS}

    # ── 2) 재무 (JSONL) ───────────────────────────────────
    print("  → 재무 파싱 (JSONL)...")
    highlight = get_financial_highlight(stock_code)
    detail    = get_financial_detail(stock_code)
    exec_df   = get_executive_table(stock_code)

    # ── 3) 재무비율 ───────────────────────────────────────
    print("  → 재무비율 계산...")
    ratios = calculate_ratios(stock_code)

    # ── 4) DART API ───────────────────────────────────────
    print("  → DART API (기업개요·주주·공시)...")
    company      = get_company_info(corp_code)
    shareholders = get_major_shareholders(corp_code)
    disclosures  = get_recent_disclosures(corp_code, n_disclosures)

    # ── 5) 외국인 보유비율 ────────────────────────────────
    print("  → 외국인 보유비율 (naver/yfinance)...")
    foreign = get_foreign_ratio(stock_code)
    price_info["외국인보유"] = (
        f"{foreign['foreign_ratio']:.2f}%" if foreign["foreign_ratio"] else "-"
    )

    # ── 6) 주주 구성 — 도넛 차트용 정리 ───────────────────
    # 주요주주 + 외국인 + 기타 = 100%
    sh_total = sum(h["ratio"] for h in shareholders)
    foreign_pct = foreign["foreign_ratio"] or 0.0
    # 외국인이 이미 주요주주에 포함 안 되어 있으면 추가
    sh_names = [h["name"] for h in shareholders]
    shareholder_chart = list(shareholders)  # 복사

    # 기타 = 100 - 주요주주 합 - 외국인(미포함분)
    already_foreign = any("외국" in n for n in sh_names)
    if not already_foreign and foreign_pct > 0:
        shareholder_chart.append({
            "name": "외국인", "ratio": foreign_pct, "shares": foreign.get("foreign_shares")
        })

    total_known = sum(h["ratio"] for h in shareholder_chart)
    others = round(max(0, 100 - total_known), 2)
    if others > 0:
        shareholder_chart.append({"name": "기타", "ratio": others, "shares": None})

    print(f"[aggregator] 완료 — {datetime.now().strftime('%H:%M:%S')}")

    return {
        "meta"          : {"stock_code": stock_code, "corp_code": corp_code,
                           "name": company.get("corp_name", SAMPLE["name"])},
        "price_info"    : price_info,
        "price_history" : price_history,
        "highlight"     : highlight,
        "detail"        : detail,
        "ratios"        : ratios,
        "company"       : company,
        "shareholders"  : shareholder_chart,
        "disclosures"   : disclosures,
        "executives"    : exec_df,
        "generated_at"  : datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


if __name__ == "__main__":
    data = aggregate()
    print("\n=== 통합 데이터 요약 ===")
    print(f"기업명     : {data['meta']['name']}")
    print(f"현재가     : {data['price_info']['현재가']:,}원  ({data['price_info']['변동률']:+.2f}%)")
    print(f"시가총액   : {data['price_info']['시가총액']}")
    print(f"주가 히스토리: {list(data['price_history'].keys())}")
    print(f"재무 하이라이트: {list(data['highlight'].keys())}")
    print(f"재무 상세   : {[(k, v.shape) for k,v in data['detail'].items()]}")
    print(f"부채비율   : {data['ratios']['부채비율']['value']}%")
    print(f"주주 구성  : {[(h['name'], h['ratio']) for h in data['shareholders']]}")
    print(f"공시 건수  : {len(data['disclosures'])}건")
    print(f"임원 수    : {len(data['executives'])}명")
    print(f"생성 시각  : {data['generated_at']}")
    print("\n✅ data_aggregator 검증 완료")
