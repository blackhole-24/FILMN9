"""C1 — 산업 3분류(성숙/경기민감/고성장) 룰 기반 매핑.

용도:
  DCF OPM 정상화 윈도우의 사전(prior)으로 사용. 자기 OPM 시계열의 사후 패턴(B1+)과
  결합해 최종 윈도우 결정.

전제:
  · 입력은 krx_desc.csv 의 Industry 컬럼(한국표준산업분류 KSIC 기반). WICS 보다 coverage 큼.
  · 회사명 보조 보정 — 복합기업(삼성전자 등)이 Industry 코드만으로 misleading 한 경우 대응.
  · 2,500종목에 7~10 세분류 적용은 분류 오류율>모델 오류율 위험 → 3분류부터.

3분류:
  · cyclical: 매크로 사이클 노출(반도체·화학·철강·조선·자동차·건설·운송·정유·전자부품·기계·고무·시멘트)
  · mature:   수요 비탄력/규제(통신·전기가스·은행·보험·식음료·필수소비재·담배·유통)
  · growth:   사업진화·저변동·소형 비사이클(IT SW·플랫폼·바이오·콘텐츠·헬스케어·소형 임대)
  · unknown:  Industry 결측 → 보수적으로 'growth' 동치 처리 (3년 윈도우)
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import csv

_VAR_ROOT = Path(__file__).resolve().parent.parent

# ── 키워드 룰 ────────────────────────────────────────────────────────
_MATURE_KW = [
    "통신", "방송", "전기, 가스", "수도", "스팀", "냉온수",
    "은행", "보험", "증권", "신탁",
    "음·식료품", "음료", "식품", "주류", "담배",
    "백화점", "슈퍼마켓", "체인화 편의점", "도매 및 상품 중개업",
    "농산물", "축산물", "수산물 도매업",
]
_CYCLICAL_KW = [
    "반도체", "디스플레이", "광 전기", "전자부품",
    "화학", "정유", "석유 정제", "기초의약물질",
    "철강", "1차 철강", "비철금속", "금속 가공",
    "조선", "자동차", "자동차 부품", "자동차용 엔진",
    "건설", "토목", "건축",
    "운송", "해운", "항공", "철도", "물류 창고",
    "기계", "특수 목적용 기계", "일반 목적용 기계", "산업기계",
    "타이어", "고무", "유리", "시멘트", "도자기",
    "전선", "케이블", "전기 장비",
]
# 회사명 강제 보정 — Industry 코드만으로 misleading한 복합기업
_FORCE_CYCLICAL_NAMES = {
    "삼성전자", "SK하이닉스", "LG디스플레이", "삼성SDI",
    "LG에너지솔루션", "포스코홀딩스", "HD현대중공업", "현대제철",
    "현대모비스", "한화에어로스페이스",
}

# ── krx_desc 인덱스 캐시 ─────────────────────────────────────────────
_DESC_CACHE: dict[str, dict] = {}


def _load_desc() -> dict[str, dict]:
    """krx_desc.csv → {Code: {Name, Industry}} 인덱스 (메모리 캐시)."""
    global _DESC_CACHE
    if _DESC_CACHE:
        return _DESC_CACHE
    p = _VAR_ROOT / "krx_desc.csv"
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8-sig") as f:   # BOM 처리
            rdr = csv.DictReader(f)
            for row in rdr:
                code = (row.get("Code") or "").strip()
                if not code:
                    continue
                code = code.zfill(6)
                _DESC_CACHE[code] = {
                    "Name": (row.get("Name") or "").strip(),
                    "Industry": (row.get("Industry") or "").strip(),
                }
    except Exception:
        pass
    return _DESC_CACHE


def classify_by_keywords(industry: str, name: str = "") -> str:
    """krx_desc Industry(+회사명) → {mature, cyclical, growth, unknown}."""
    if name in _FORCE_CYCLICAL_NAMES:
        return "cyclical"
    if not isinstance(industry, str) or not industry:
        return "unknown"
    for kw in _MATURE_KW:
        if kw in industry:
            return "mature"
    for kw in _CYCLICAL_KW:
        if kw in industry:
            return "cyclical"
    return "growth"


def classify_ticker(ticker: str, name: Optional[str] = None,
                    industry: Optional[str] = None) -> dict:
    """단일 종목 분류 — 외부 호출용.

    Returns: {category, name, industry, source}
      source: 'name_force' / 'industry_kw' / 'fallback'
    """
    desc = _load_desc()
    info = desc.get(str(ticker).zfill(6), {})
    nm = name or info.get("Name", "")
    ind = industry or info.get("Industry", "")
    cat = classify_by_keywords(ind, nm)
    src = "name_force" if nm in _FORCE_CYCLICAL_NAMES else (
        "industry_kw" if ind else "fallback")
    return {"category": cat, "name": nm, "industry": ind, "source": src}


# ── OPM 정상화 윈도우 (산업 prior) ────────────────────────────────────
# ── DCF 부적합 업종 라우팅 (Phase 0 — 2026-05-28) ─────────────────────
#   금융업(은행·보험·증권·신탁·금융지원·여신전문)은 FCFF 공식이 정상 작동하지 않음:
#     · 이자수익이 영업의 핵심이므로 EBIT 정의가 일반 사업회사와 다름
#     · IBD 가 운영 핵심이라 net_debt 차감이 비논리적
#     · 자본규제 영향으로 자유 CapEx 가정 불가
#   → DCF 대신 DDM·RIM·자기자본가치모형(P/B-ROE) 권장.
#   지주회사는 별도 영업이 없어 NAV/SOTP 가 적합.
#   본 함수는 라우팅 신호만 제공 — 실제 분기는 dcf_engine 진입부에서.
_FINANCE_KW = ("은행", "보험", "재 보험", "신탁", "금융 지원", "기타 금융",
               "신용카드", "할부금융", "여신", "증권")


def is_dcf_unsuitable(ticker: str, name: Optional[str] = None,
                      industry: Optional[str] = None,
                      products: Optional[str] = None,
                      financials_signals: Optional[dict] = None,
                      ) -> tuple[bool, Optional[str]]:
    """DCF 적용 부적합 종목 판정.

    Args:
        financials_signals: D-8 재무구조 신호 dict (옵션).
                            inv_assoc_ratio 키 — 지분법투자/자본총계.
                            없으면 키워드 신호만 사용.

    Returns: (부적합 여부, 사유 또는 None)

    부적합:
      · 금융업 — DCF 대신 DDM/RIM/P-B-ROE 권장
      · 지주회사 (키워드 또는 D-8 재무구조 신호) — NAV/SOTP 권장
    """
    desc = _load_desc()
    info = desc.get(str(ticker).zfill(6), {})
    nm = name or info.get("Name", "")
    ind = industry or info.get("Industry", "")
    pr = products or ""

    # 1) 금융업 — KRX Industry 키워드 매칭
    #   Phase 9: 일반투자자 평이화 — 전문 모형명은 괄호 원어 병기.
    for kw in _FINANCE_KW:
        if kw in ind:
            return True, (f"금융업({ind.strip()}) — 이자수익이 본업이라 일반 현금흐름 평가"
                          f"(DCF)가 안 맞습니다. 배당·자본 기반 평가(DDM·RIM) 권장")

    # 2) 지주회사 — peer_selector 의 _is_holding_company 재사용 (키워드 신호)
    try:
        from .peer_selector import _is_holding_company
        if _is_holding_company(nm, pr, ind):
            return True, ("지주회사 — 자체 사업이 적어 일반 현금흐름 평가(DCF)가 안 맞습니다. "
                          "자회사 가치를 합산하는 방식(NAV·SOTP) 권장")
    except Exception:
        pass

    # 3) D-8: 재무구조 기반 지주 판정 (옵션 — financials_signals 가용 시)
    #   지분법투자 / 자본총계 ≥ 40% 이면 holding 의심 (키워드 누락 보강)
    if financials_signals:
        try:
            from .peer_selector import _is_holding_by_financials
            is_h, reason = _is_holding_by_financials(financials_signals)
            if is_h:
                return True, f"{reason} — DCF 부적합 (NAV/SOTP 권장)"
        except Exception:
            pass

    return False, None


def industry_window_prior(category: str) -> dict:
    """산업 카테고리 → OPM 정상화 윈도우 prior + 설명.

    cyclical: 8년 (사이클 한 바퀴 평탄화)
    mature:   3년 (변동 작음 — 굳이 길게 안 봐도 됨)
    growth:   3년 (사업 진화 빠름 — 옛 데이터 오염 위험)
    """
    if category == "cyclical":
        return {"window_yrs": 8, "reason": "경기민감 — 8년으로 사이클 평탄화"}
    if category == "mature":
        return {"window_yrs": 3, "reason": "성숙 안정 — 단기 평균 충분"}
    return {"window_yrs": 3, "reason": "성장·고변동 — 옛 데이터 오염 회피"}


if __name__ == "__main__":
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else "005930"
    r = classify_ticker(tk)
    print(f"  {tk}  {r['name']}  → category={r['category']}  (source={r['source']})")
    print(f"  Industry: {r['industry']}")
    print(f"  Window prior: {industry_window_prior(r['category'])}")
