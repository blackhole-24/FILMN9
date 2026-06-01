"""XBRL XML 에서 자본·NCI·EPS 추출 (팀원 모듈이 처리 안 하는 5개 필드).

추출 대상 (FY2025 연결 기준):
  - equity_total       : ifrs-full:Equity (자본총계 = 지배+비지배)
  - equity_parent      : ifrs-full:EquityAttributableToOwnersOfParent (지배지분 자본)
  - minority_interest  : ifrs-full:NoncontrollingInterests (비지배지분)
  - preferred_capital  : ifrs-full:IssuedCapital + PreferenceSharesMember axis (우선주 자본금)
  - basic_eps          : ifrs-full:BasicEarningsLossPerShare (XBRL 직접 보고 EPS)

용도:
  - equity_value.py: minority_interest 차감 (방법 1 정합)
  - multiples_engine.py: Basic EPS (PER), BPS = (equity_parent − preferred_capital) / common_float (PBR)
  - dcf_engine.py: Invested Capital 정확 산출 (선택)

사용:
    from valuation_engine.extract_balance_sheet import extract_for_company

    bs = extract_for_company("000720", "현대건설", year=2025)
    # → {"equity_total": ..., "minority_interest": ..., "basic_eps": ...}

전제:
  XBRL raw 파일이 이미 VAR/xbrl_raw/<ticker>_<corp_name>_<year>/ 에 있어야 함.
  collect_xbrl_raw.py 로 사전 다운로드.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Optional

from lxml import etree


_VAR_ROOT = Path(__file__).resolve().parent.parent
XBRL_RAW = _VAR_ROOT / "xbrl_raw"
CACHE_DIR = _VAR_ROOT / "valuation_engine" / "data" / "xbrl_balance"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# contextRef 매칭 규칙
CTX_EXCLUDE = [
    "ComponentsOfEquity",      # 자본 분해 (자본금/이익잉여금 등) — 제외
    "ParentMember",             # 지배지분만 분리 — 제외 (별도 element 사용)
    "GeographicalArea",
    "OperatingSegment",
    "CurrencyAxis",
]


def _resolve_tag(tag: str, nsmap: dict) -> str:
    if ":" in tag:
        prefix, local = tag.split(":")
        ns_url = nsmap.get(prefix)
        if ns_url:
            return f"{{{ns_url}}}{local}"
    return tag


def _parse_xbrl(xbrl_path: Path) -> tuple[etree._ElementTree, dict]:
    """대용량 XBRL XML 파싱 + namespace 자동 추출."""
    parser = etree.XMLParser(huge_tree=True, recover=True)
    tree = etree.parse(str(xbrl_path), parser)
    nsmap = {k: v for k, v in tree.getroot().nsmap.items() if k}
    return tree, nsmap


def _extract_single(tree, nsmap: dict, *,
                    element: str,
                    ctx_must_contain: list[str],
                    ctx_must_exclude: list[str] = None) -> Optional[float]:
    """단일 element + contextRef 필터 → 값 반환.

    ctx_must_contain: contextRef 에 모두 포함되어야 함 (AND)
    ctx_must_exclude: contextRef 에 하나라도 있으면 제외 (NOT)
    """
    ctx_must_exclude = ctx_must_exclude or CTX_EXCLUDE
    resolved = _resolve_tag(element, nsmap)

    for el in tree.iterfind(f".//{resolved}"):
        ctx = el.get("contextRef", "")
        if not all(c in ctx for c in ctx_must_contain):
            continue
        if any(ex in ctx for ex in ctx_must_exclude):
            continue
        if el.text is None:
            continue
        try:
            return int(el.text)
        except (ValueError, TypeError):
            try:
                return float(el.text)
            except (ValueError, TypeError):
                return None
    return None


def _extract_preferred_capital(tree, nsmap: dict, year: int) -> int:
    """우선주 자본금 추출 — IssuedCapital + PreferenceSharesMember axis."""
    resolved = _resolve_tag("ifrs-full:IssuedCapital", nsmap)
    ctx_target = f"CFY{year}eFY"

    for el in tree.iterfind(f".//{resolved}"):
        ctx = el.get("contextRef", "")
        if ctx_target not in ctx:
            continue
        if "ConsolidatedMember" not in ctx:
            continue
        if "PreferenceSharesMember" not in ctx:
            continue
        if el.text is None:
            continue
        try:
            return int(el.text)
        except (ValueError, TypeError):
            return 0
    return 0    # 우선주 미발행 회사


def _extract_equity_method_income(tree, nsmap: dict, year: int) -> Optional[float]:
    """손익 — ifrs-full:ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod.

    D-8 신호 ②: 지분법손익(연결, 당기). 영업이익 대비 비중 계산용.
    부재 시 None — 회사가 보고 안 하면 0 으로 가정해도 무방하지만, 추출 실패와
    구분하기 위해 None 으로 유지 (호출자가 0 처리).
    """
    return _extract_single(
        tree, nsmap,
        element="ifrs-full:ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
        ctx_must_contain=[f"CFY{year}dFY",
                          "ConsolidatedAndSeparateFinancialStatementsAxis",
                          "ConsolidatedMember"],
    )


# ─────────────────────────────────────────────────────────────
# D-8 신호 ③: 사업부문(OperatingSegments) 매출 추출
# ─────────────────────────────────────────────────────────────
# contextRef 패턴:
#   ...SegmentConsolidationItemsAxis_ifrs-full_OperatingSegmentsMember
#   _ifrs-full_SegmentsAxis_<segment_member_name>
# segment_member_name 예:
#   entity00117212_DoosanBobcatIncMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember
#   ifrs-full_AllOtherSegmentsMember
import re as _re

_SEGMENT_CTX_REQUIRED = (
    "OperatingSegmentsMember",
    "SegmentsAxis_",
)
_SEGMENT_NAME_RE = _re.compile(
    r"SegmentsAxis_([A-Za-z0-9_]+?Member)"
)


def _segment_label(ctx: str) -> Optional[str]:
    """contextRef 에서 segment member 식별자만 잘라내기.

    실데이터는 영문 회사ID(엔지니어링 부문 등)·entity ID prefix 가 섞여 있음.
    HHI 계산엔 라벨 일관성만 있으면 충분 → 정확한 한글명 매핑은 추후 보강.
    """
    m = _SEGMENT_NAME_RE.search(ctx)
    if not m:
        return None
    raw = m.group(1)
    # 너무 긴 보고서 보일러플레이트 정리 — 핵심 식별자만 남김
    # 예) DoosanBobcatIncMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember
    # → DoosanBobcatInc
    for tail in (
        "MemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
        "MemberOfDisclosureOfOperatingSegmentsTableOfMember",
        "MemberOfReportableSegmentsMember",
        "SegmentMember",
        "Member",
    ):
        if raw.endswith(tail):
            raw = raw[: -len(tail)]
            break
    # entity prefix (entity00117212_) 제거
    raw = _re.sub(r"^(entity\d+|ifrs-full)_", "", raw)
    return raw or None


def _extract_segment_revenues(tree, nsmap: dict, year: int) -> dict:
    """OperatingSegments 차원의 ifrs-full:Revenue 매트릭스 → 부문별 매출.

    D-8 신호 ③ 입력: 1위 부문 비중 + HHI 계산.

    Returns:
        {
            "year": int,
            "segments": [{"label": str, "revenue": float, "share": float}, ...],
            "total": float,
            "n_segments": int,
            "top_share": float,       # 1위 부문 비중 (0~1)
            "hhi": float,             # Herfindahl-Hirschman 지수 (0~1)
        }
        세그먼트 미보고 시 segments=[], n_segments=0, top_share/hhi=None.

    주의 — 합계/조정 항목 제외:
        ifrs-full_AllOtherSegmentsMember 는 "기타" 합산 → 통상 1개 부문으로 취급(포함).
        MaterialReconcilingItemsMember(조정) / Eliminations / Total 라벨은 제외해야
        부문 비중 합 ≈ 1 보장.
    """
    resolved = _resolve_tag("ifrs-full:Revenue", nsmap)
    ctx_year   = f"CFY{year}dFY"
    ctx_consol = "ConsolidatedMember"
    seg_rev: dict[str, float] = {}

    for el in tree.iterfind(f".//{resolved}"):
        ctx = el.get("contextRef", "")
        if ctx_year not in ctx or ctx_consol not in ctx:
            continue
        if not all(req in ctx for req in _SEGMENT_CTX_REQUIRED):
            continue
        # 지역·통화 dim 등 다른 분류는 제외 — segments axis 가 있는 경우만 통과.
        if "MaterialReconcilingItemsMember" in ctx:
            continue
        if "EliminationOfIntersegment" in ctx or "EliminationsMember" in ctx:
            continue
        label = _segment_label(ctx)
        if not label:
            continue
        try:
            v = float(el.text)
        except (TypeError, ValueError):
            continue
        # 같은 부문에 중복 보고(예: 회사별 + 그룹별) 가능 — 최댓값 사용은
        # 합산 라벨과 중복 위험 → 첫 값만 채택 (raw 순서 = 보고서 순서).
        if label not in seg_rev:
            seg_rev[label] = v

    if not seg_rev:
        return {"year": year, "segments": [], "total": 0.0,
                "n_segments": 0, "top_share": None, "hhi": None}

    total = sum(abs(v) for v in seg_rev.values())
    if total <= 0:
        return {"year": year, "segments": [], "total": 0.0,
                "n_segments": 0, "top_share": None, "hhi": None}
    segments = sorted(
        ({"label": k, "revenue": v, "share": abs(v) / total}
         for k, v in seg_rev.items()),
        key=lambda d: -d["share"],
    )
    hhi = sum(s["share"] ** 2 for s in segments)
    return {
        "year":       year,
        "segments":   segments,
        "total":      total,
        "n_segments": len(segments),
        "top_share":  segments[0]["share"],
        "hhi":        hhi,
    }


def parse_xbrl_balance(xbrl_path: Path, year: int = 2025) -> dict:
    """XBRL XML 1개 파일 파싱 → 자본·NCI·EPS 5종 추출.

    Args:
        xbrl_path: .xbrl 파일 경로 (압축 해제 후)
        year:      추출 대상 연도 (당기말 — CFYxxxxeFY)

    Returns:
        {
            "equity_total":          int,  # 자본총계 (원)
            "equity_parent":         int,  # 지배지분 자본 (원)
            "minority_interest":     int,  # 비지배지분 (원)
            "preferred_capital":     int,  # 우선주 자본금 (원, 미발행 시 0)
            "basic_eps":             float,# 기본주당이익 (원/주)
            "year":                  int,
            "source_file":           str,
        }
    """
    tree, nsmap = _parse_xbrl(xbrl_path)

    # contextRef 패턴 — 시점(BS, eFY) vs 기간(IS, dFY)
    ctx_instant = [f"CFY{year}eFY",  "ConsolidatedAndSeparateFinancialStatementsAxis",
                   "ConsolidatedMember"]
    ctx_duration = [f"CFY{year}dFY", "ConsolidatedAndSeparateFinancialStatementsAxis",
                    "ConsolidatedMember"]

    equity_total = _extract_single(
        tree, nsmap, element="ifrs-full:Equity",
        ctx_must_contain=ctx_instant,
    )
    equity_parent = _extract_single(
        tree, nsmap, element="ifrs-full:EquityAttributableToOwnersOfParent",
        ctx_must_contain=ctx_instant,
    )
    minority_interest = _extract_single(
        tree, nsmap, element="ifrs-full:NoncontrollingInterests",
        ctx_must_contain=ctx_instant,
    )
    preferred_capital = _extract_preferred_capital(tree, nsmap, year)

    basic_eps = _extract_single(
        tree, nsmap, element="ifrs-full:BasicEarningsLossPerShare",
        ctx_must_contain=ctx_duration,
    )

    # D-8 신호 ② — 지분법손익(IS, 당기). 영업이익 대비 비중 산출용.
    equity_method_income = _extract_equity_method_income(tree, nsmap, year)

    # D-8 신호 ③ — 사업부문 매출 매트릭스 + HHI/top_share.
    segment_info = _extract_segment_revenues(tree, nsmap, year)

    # 실데이터 정책: None 은 추출 실패 (호출 측 RuntimeError), 0 은 정상 (단독법인의 NCI 등)
    return {
        "equity_total":      equity_total,
        "equity_parent":     equity_parent,
        "minority_interest": minority_interest,
        "preferred_capital": preferred_capital,
        "basic_eps":         basic_eps,
        "equity_method_income": equity_method_income,   # D-8 신호 ②
        "segment_revenues":  segment_info,              # D-8 신호 ③
        "year":              year,
        "source_file":       xbrl_path.name,
    }


def _load_from_unified_xbrl(corp_name: str, year: int) -> Optional[dict]:
    """v3 통합 JSON (xbrl_collector) 에서 자본·NCI·EPS 가져오기.

    팀원 fork 후엔 모든 데이터가 한 JSON 에 통합. 별도 XBRL XML 파싱 불필요.
    """
    try:
        from .xbrl_collector import load_cached, has_balance_sheet_fields
    except ImportError:
        return None
    data = load_cached(corp_name, year)
    if not data or not has_balance_sheet_fields(data):
        return None
    fin = data.get("financials", {})
    return {
        "equity_total":      fin.get("equity_total"),
        "equity_parent":     fin.get("equity_parent"),
        "minority_interest": fin.get("minority_interest"),
        "preferred_capital": fin.get("preferred_capital", 0),
        "basic_eps":         fin.get("basic_eps"),
        "year":              year,
        "source":            "xbrl_collector unified JSON",
    }


def _fill_equity_parent(d: Optional[dict]) -> Optional[dict]:
    """지배지분(equity_parent) 누락/0 보정 — 별도재무제표·무NCI 회사 대응.

    지배지분 태그가 없는 회사(케이씨텍 등)는 equity_parent=0/None 이지만 자본총계는 존재.
    지배지분 = 자본총계 − 비지배지분 (NCI 없으면 = 자본총계). 소비 시점 보정이라
    기존 캐시(재추출 전)에도 즉시 적용됨 → IC 음수 결함 방지.
    """
    if d and not d.get("equity_parent") and d.get("equity_total"):
        d["equity_parent"] = d["equity_total"] - (d.get("minority_interest") or 0)
        d["equity_parent_source"] = "derived: equity_total − NCI"
    return d


@functools.lru_cache(maxsize=512)
def extract_for_company(ticker: str, corp_name: str, year: int = 2025,
                         use_cache: bool = True) -> Optional[dict]:
    """자본·NCI·EPS 추출 — 3단계 폴백 + 프로세스 단위 메모이즈.

    1) v3 통합 JSON (xbrl_collector) — 가장 빠름 (이미 통합돼 있음)
    2) 캐시 JSON (extract_balance_sheet 자체)
    3) XBRL raw 파싱 (마지막 수단)

    Returns:
        dict (필드: equity_total, equity_parent, minority_interest, preferred_capital, basic_eps)
        또는 None (모든 소스 실패)

    Note: lru_cache 는 (ticker, corp_name, year, use_cache) 키로 같은 프로세스에서 N번 호출
    되어도 1번만 실제 조회. 평가 중 dcf/equity/multiples 가 같은 키로 8회 호출하던 비용 절감.
    DB 갱신 즉시 반영 필요 시 extract_for_company.cache_clear() 호출.
    """
    # 0) DB stock_code 키 조회 — 회사명 미해결 종목(케이씨텍=name'281820' 등)도 정확.
    #   financials 테이블은 stock_code 키라 이름 불일치(load_cached corp_name 미스)와 무관.
    try:
        from valuation_engine import db as _db
        _dbf = _db.get_financials(ticker, year)
        _fin = (_dbf or {}).get("financials") if _dbf else None
        if _fin and (_fin.get("equity_total") is not None or _fin.get("equity_parent") is not None):
            return _fill_equity_parent({
                "ticker": ticker, "corp_name": corp_name,
                "equity_total":      _fin.get("equity_total"),
                "equity_parent":     _fin.get("equity_parent"),
                "minority_interest": _fin.get("minority_interest"),
                "preferred_capital": _fin.get("preferred_capital", 0),
                "basic_eps":         _fin.get("basic_eps"),
                "source": "db_by_stock_code",
            })
    except Exception:
        pass

    # 1) v3 통합 JSON 우선 (회사명 기준)
    unified = _load_from_unified_xbrl(corp_name, year)
    if unified is not None:
        unified["ticker"] = ticker
        unified["corp_name"] = corp_name
        unified["source"] = "unified_v3_json"   # 실제 출처 기록 (대부분 이 경로)
        return _fill_equity_parent(unified)

    # 2) 자체 캐시
    cache_path = CACHE_DIR / f"{ticker}_{corp_name}_{year}.json"
    if use_cache and cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as f:
            cached = json.load(f)
        cached.setdefault("source", "balance_cache")
        return _fill_equity_parent(cached)

    # 3) XBRL raw 파싱
    folder = XBRL_RAW / f"{ticker}_{corp_name}_{year}"
    xbrl_files = list(folder.glob("*.xbrl"))
    if not xbrl_files:
        return None

    result = parse_xbrl_balance(xbrl_files[0], year=year)
    result["ticker"]    = ticker
    result["corp_name"] = corp_name
    result["source"]    = "xbrl_raw direct parse"
    result = _fill_equity_parent(result)

    # 자체 캐시 저장
    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    return result


def get_minority_interest(ticker: str, corp_name: str, year: int = 2025) -> Optional[int]:
    """비지배지분 단일 값 반환 — equity_value.py 헬퍼.

    실데이터 정책 (옵션 A):
      - data 자체가 None (XBRL 추출 실패) → None 반환
      - data["minority_interest"] 가 None (필드 누락) → None 반환
      - 0 또는 정상값 → 그대로 반환 (0 은 단독법인의 실데이터)

    호출 측에서 None 받으면 RuntimeError 처리 권장.
    """
    data = extract_for_company(ticker, corp_name, year)
    if not data:
        return None
    return data.get("minority_interest")   # 0 은 그대로, None 도 그대로


def get_basic_eps(ticker: str, corp_name: str, year: int = 2025) -> Optional[float]:
    """기본 EPS (원/주) 반환 — multiples_engine.py 헬퍼."""
    data = extract_for_company(ticker, corp_name, year)
    return data.get("basic_eps") if data else None


def get_bps(ticker: str, corp_name: str, common_float: int,
            year: int = 2025) -> Optional[float]:
    """BPS (원/주) 산출 — 우선주 자본금 차감 (옵션 B).

    BPS = (지배지분 자본 − 우선주 자본금) / 보통주 유통주식수

    multiples_engine.py 헬퍼.
    """
    data = extract_for_company(ticker, corp_name, year)
    if not data or not common_float:
        return None
    equity_parent     = data.get("equity_parent",     0) or 0
    preferred_capital = data.get("preferred_capital", 0) or 0
    common_equity = equity_parent - preferred_capital
    return common_equity / common_float if common_float > 0 else None


if __name__ == "__main__":
    # 5개 산업 표본 자체 테스트
    SAMPLES = [
        ("000720", "현대건설"),
        ("012510", "더존비즈온"),
        ("009420", "한올바이오파마"),
        ("001200", "유진투자증권"),
        ("003230", "삼양식품"),
    ]
    print("=" * 80)
    print(f"  자본·NCI·EPS 추출 검증 — 5개 표본 × FY2025")
    print("=" * 80)
    print(f"  {'회사':<14s} {'자본총계':>12s} {'지배지분':>12s} {'비지배':>10s} "
          f"{'우선주':>8s} {'EPS':>8s}")
    print(f"  {'-'*14} {'-'*12} {'-'*12} {'-'*10} {'-'*8} {'-'*8}")
    for ticker, name in SAMPLES:
        data = extract_for_company(ticker, name)
        if data is None:
            print(f"  {name:<14s} XBRL raw 파일 없음")
            continue
        et  = data.get("equity_total", 0) / 1e9
        ep  = data.get("equity_parent", 0) / 1e9
        mi  = data.get("minority_interest", 0) / 1e9
        pc  = data.get("preferred_capital", 0) / 1e9
        eps = data.get("basic_eps")
        eps_str = f"{eps:>8,.0f}" if eps is not None else "      —"
        print(f"  {name:<14s} {et:>10,.0f}억 {ep:>10,.0f}억 {mi:>8,.0f}억 "
              f"{pc:>6,.1f}억 {eps_str}")
    print(f"\n  캐시 저장: {CACHE_DIR}")
