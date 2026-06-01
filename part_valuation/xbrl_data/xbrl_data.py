# -*- coding: utf-8 -*-
"""
xbrl_financials_v3.py
=====================
[v3 변경사항]
- get_value_lafa(): LiabilitiesArisingFromFinancingActivities 축 기반
  폴백 추출 함수 추가 (비유동사채/장기차입금 plain context 미존재 대응)
- get_financials(): 비유동사채(BondsIssued)·장기차입금(LongtermBorrowings)
  추출 시 plain context 실패 → LaFA axis 폴백 로직 추가
- 기존 아모레퍼시픽 동작 완전 보존 (plain context 우선순위 1~3 불변)
DART OpenAPI 의 XBRL 재무제표 원본파일 + XBRL 택사노미를 이용해
코스피 / 코스닥 상장 기업의 핵심 재무지표를 범용적으로 추출하는 모듈.

amorepacific.ipynb 에서 시행착오를 거쳐 확정된 추출 로직
( get_value 우선순위 폴백 / NOA_RULES_FINAL_V3 / get_financials / 한계세율 )
을 그대로 함수화하고, 종목명·종목코드·조회연도만 입력하면
전체 파이프라인이 자동으로 돌아가도록 만든 것.

추출 항목
---------
매출액, 영업이익, 당기순이익, da, ebitda,
nwc_cur, nwc_pfy, delta_nwc, capex, ibd, ibd_detail, noa, noa_items

사용 예
-------
    from xbrl_financials import extract_company

    result = extract_company("아모레퍼시픽", 2024)   # 종목명
    result = extract_company("090430", 2024)         # 종목코드
    # -> 작업폴더에 "아모레퍼시픽_2024.json" 저장 + result dict 반환

CLI
---
    python xbrl_financials.py 아모레퍼시픽 2024
    python xbrl_financials.py 090430 2024 --outdir ./out

요구 패키지 : requests, pandas, lxml, python-dotenv
필요 환경변수 : DART_API_KEY  (.env 파일 또는 OS 환경변수)

단위 : 모든 금액은 원(KRW) 단위. 조회연도(year)는 회계연도 기준
       (예: 2024 입력 -> 2024 회계연도 사업보고서, 2025년에 공시된 것).
재무제표 기준 : 연결(Consolidated) 우선, 연결 context 가 없으면 개별(Separate) 자동 대체.
"""

from __future__ import annotations

import io
import os
import sys
import json
import zipfile
import tempfile
import argparse
import glob as _glob

import requests
import pandas as pd
from lxml import etree

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv 미설치 시 OS 환경변수만 사용
    pass


# ════════════════════════════════════════════════════════════════════
#  추출 규칙 (amorepacific.ipynb 에서 확정된 최종본)
# ════════════════════════════════════════════════════════════════════

# ── NOA 분류 규칙 (노트북 셀 42: NOA_RULES_FINAL_V3) ──────────────────
NOA_RULES_FINAL_V3 = {
    "DEFINITE_NOA": [
        "InvestmentProperty",                                   # 투자부동산
    ],
    "DEFAULT_NOA": [
        "CashAndCashEquivalents",                               # 현금및현금성자산
        "ShorttermDepositsNotClassifiedAsCashEquivalents",      # 단기금융기관예치금
        "LongtermDeposits",                                     # 장기금융기관예치금
        "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",     # 유동 FVTPL
        "NoncurrentFinancialAssetsAtFairValueThroughProfitOrLoss",  # 비유동 FVTPL
        "CurrentFinancialAssetsAtAmortisedCost",                # 유동 AC금융자산
        "NoncurrentFinancialAssetsAtAmortisedCost",             # 비유동 AC금융자산
        "NoncurrentInvestmentsInEquityInstrumentsDesignatedAtFairValueThroughOtherComprehensiveIncome",  # FVOCI
        "InvestmentAccountedForUsingEquityMethod",              # 관계기업투자주식
    ],
    "COND_NOA": [
        # 순확정급여자산/부채 (재무상태표 표시 기준)
        "NoncurrentRecognisedAssetsDefinedBenefitPlan",                 # 순확정급여자산 (+)
        ("NoncurrentRecognisedLiabilitiesDefinedBenefitPlan", -1),      # 순확정급여부채 (-)
        # 기타비유동부채 계열 (비영업성)
        ("OtherNoncurrentLiabilities",          -1),            # 기타비유동부채
        ("OtherNoncurrentFinancialLiabilities", -1),            # 기타비유동금융부채
        ("NoncurrentProvisions",                -1),            # 비유동충당부채
    ],
}

# NOA 항목 한글 라벨 (택사노미 라벨이 없을 때의 폴백)
_NOA_KOR_MAP = {
    "InvestmentProperty":               "투자부동산",
    "CashAndCashEquivalents":           "현금및현금성자산",
    "ShorttermDepositsNotClassifiedAsCashEquivalents": "단기금융기관예치금",
    "LongtermDeposits":                 "장기금융기관예치금",
    "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss":    "유동 FVTPL금융자산",
    "NoncurrentFinancialAssetsAtFairValueThroughProfitOrLoss": "비유동 FVTPL금융자산",
    "CurrentFinancialAssetsAtAmortisedCost":   "유동 AC금융자산",
    "NoncurrentFinancialAssetsAtAmortisedCost": "비유동 AC금융자산",
    "NoncurrentInvestmentsInEquityInstrumentsDesignatedAtFairValueThroughOtherComprehensiveIncome": "FVOCI금융자산",
    "InvestmentAccountedForUsingEquityMethod": "관계기업투자주식",
    "NoncurrentRecognisedAssetsDefinedBenefitPlan":      "순확정급여자산",
    "NoncurrentRecognisedLiabilitiesDefinedBenefitPlan": "순확정급여부채",
    "OtherNoncurrentLiabilities":           "기타비유동부채",
    "OtherNoncurrentFinancialLiabilities":  "기타비유동금융부채",
    "NoncurrentProvisions":                 "비유동충당부채",
}

_NOA_CLS_LABEL = {
    "DEFINITE_NOA": "확실한 NOA",
    "DEFAULT_NOA":  "기본 NOA",
    "COND_NOA":     "조건부 NOA",
}

# IBD 구성 태그 (노트북 셀 49 get_financials)
# ── 단일 태그 항목 ──────────────────────────────────────────────────────
_IBD_SINGLE_TAGS = {
    # 유동성 차입 부채
    "단기차입금":           "ShorttermBorrowings",
    "유동성장기차입금":      "CurrentPortionOfLongtermBorrowings",
    "유동리스부채":         "CurrentLeaseLiabilities",
    # 비유동성 차입 부채
    "장기차입금":           "LongtermBorrowings",          # ← 신규 추가
    "비유동리스부채":        "NoncurrentLeaseLiabilities",
}

# ── 단기사채 계열 (유동성, 여러 태그 합산) ──────────────────────────────
# K-IFRS XBRL에서 단기사채는 'CurrentPortionOf*' 외에도 아래 태그로 보고됨
_IBD_BOND_CUR = [
    "CurrentPortionOfBonds",
    "CurrentPortionOfConvertibleBonds",
    "CurrentPortionOfBondWithWarrant",
    "CurrentPortionOfExchangeableBond",
    "ShorttermBorrowingsInTypeOfBonds",       # ← 신규: 단기사채(기업어음 포함)
]

# ── 비유동사채 계열 ──────────────────────────────────────────────────────
# [v3] 기업별 XBRL 태그 차이 대응:
# - 아모레퍼시픽 등: BondsIssued (plain context에 직접 존재)
# - 현대건설 등:     NoncurrentPortionOfNoncurrentBondsIssued (비유동부분 명시)
#                    (CurrentPortionOfLongtermBorrowings가 이미 유동사채 포함)
_IBD_BOND_NONCUR = [
    "BondsIssued",
    "NoncurrentPortionOfNoncurrentBondsIssued",   # ← v3 신규: 현대건설형
    "ConvertibleBonds",
    "BondWithWarrant",
    "ExchangeableBonds",
    "NoncurrentBorrowingsInTypeOfBonds",           # ← 신규: 비유동사채 폴백
]

# ── 장기차입금 폴백 태그 (plain context에 LongtermBorrowings 없을 때) ──
# [v3] 현대건설형: NoncurrentPortionOfNoncurrentLoansReceived
_IBD_LONGTERM_BORROWINGS_FALLBACK = [
    "NoncurrentPortionOfNoncurrentLoansReceived",  # ← v3 신규
]

# ── 단기금융부채 계열 (위 태그에 잡히지 않는 유동 금융부채) ──────────────
# 개별 태그들이 0이거나 None일 때 CurrentFinancialLiabilities 합계로 폴백
_IBD_FINANCIAL_CUR = [
    "CurrentFinancialLiabilities",            # ← 신규: 단기금융부채 합계
    "OtherCurrentFinancialLiabilities",       # ← 신규: 기타유동금융부채
]

# ── 장기금융부채 계열 (위 태그에 잡히지 않는 비유동 금융부채) ────────────
_IBD_FINANCIAL_NONCUR = [
    "NoncurrentFinancialLiabilities",         # ← 신규: 장기금융부채 합계
    "OtherNoncurrentFinancialLiabilities",    # ← 신규: 기타비유동금융부채
]

DART_BASE = "https://opendart.fss.or.kr/api"


# ════════════════════════════════════════════════════════════════════
#  0. 공통 유틸
# ════════════════════════════════════════════════════════════════════

def _get_api_key(api_key: str | None = None) -> str:
    """API 키를 인자 -> .env/환경변수(DART_API_KEY) 순으로 확보."""
    key = api_key or os.getenv("DART_API_KEY")
    if not key:
        raise RuntimeError(
            "DART API 키를 찾을 수 없습니다. .env 에 DART_API_KEY 를 설정하거나 "
            "api_key 인자로 직접 전달하세요."
        )
    return key


def _to_int(value) -> int | None:
    """XBRL value 문자열을 정수로 변환. 변환 불가하면 None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def billions(val) -> float:
    """원 -> 억원."""
    return (val or 0) / 1e8


# ════════════════════════════════════════════════════════════════════
#  1. corp_code 조회  (종목명 또는 종목코드 -> 8자리 고유번호)
# ════════════════════════════════════════════════════════════════════

def get_corp_code(name_or_code: str, api_key: str | None = None) -> dict:
    """
    종목명 또는 6자리 종목코드로 DART corp_code(8자리) 를 찾는다.

    Returns: {"corp_code", "corp_name", "stock_code"}
    """
    key = _get_api_key(api_key)
    res = requests.get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    res.raise_for_status()

    z = zipfile.ZipFile(io.BytesIO(res.content))
    xml_data = z.read(z.namelist()[0])
    df = pd.read_xml(io.BytesIO(xml_data), dtype=str)

    # 컬럼 정리
    for col in ("corp_code", "corp_name", "stock_code"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
    df["corp_code"] = df["corp_code"].str.zfill(8)

    query = str(name_or_code).strip()

    # 종목코드(숫자 6자리)로 들어온 경우
    if query.isdigit():
        code = query.zfill(6)
        hit = df[df["stock_code"] == code]
        if hit.empty:
            raise ValueError(f"종목코드 '{code}' 에 해당하는 상장기업을 찾을 수 없습니다.")
    else:
        # 종목명: 상장사(stock_code 존재)만 우선 -> 정확히 일치 -> 부분 일치
        listed = df[df["stock_code"] != ""]
        hit = listed[listed["corp_name"] == query]
        if hit.empty:
            hit = listed[listed["corp_name"].str.contains(query, na=False)]
        if hit.empty:
            raise ValueError(f"종목명 '{query}' 에 해당하는 상장기업을 찾을 수 없습니다.")
        if len(hit) > 1:
            names = ", ".join(hit["corp_name"].head(10))
            print(f"  ⚠️  '{query}' 와 일치하는 기업이 여러 개입니다: {names}")
            print(f"      -> 첫 번째 '{hit.iloc[0]['corp_name']}' 를 사용합니다.")

    row = hit.iloc[0]
    return {
        "corp_code": row["corp_code"],
        "corp_name": row["corp_name"],
        "stock_code": row["stock_code"],
    }


# ════════════════════════════════════════════════════════════════════
#  2. 접수번호(rcept_no) 조회  (corp_code + 회계연도 -> 사업보고서 rcept_no)
# ════════════════════════════════════════════════════════════════════

def get_rcept_no(corp_code: str, year: int, api_key: str | None = None) -> dict:
    """
    회계연도(year)의 사업보고서 접수번호를 찾는다.
    사업보고서는 보통 다음 해(year+1) 3월경 공시되므로 year+1~year+2 구간을 검색.
    [기재정정] 등 정정 보고서가 있으면 가장 최근 접수분을 사용.

    Returns: {"rcept_no", "report_nm", "rcept_dt"}
    """
    key = _get_api_key(api_key)
    params = {
        "crtfc_key": key,
        "corp_code": corp_code,
        "pblntf_ty": "A",                       # 정기공시
        "bgn_de": f"{year + 1}0101",
        "end_de": f"{year + 2}1231",
        "page_count": "100",
    }
    res = requests.get(f"{DART_BASE}/list.json", params=params, timeout=60)
    res.raise_for_status()
    data = res.json()

    if data.get("status") not in ("000", "013"):
        raise RuntimeError(f"DART list API 오류: {data.get('status')} {data.get('message')}")

    items = data.get("list", [])
    # '사업보고서' 이고 해당 회계연도를 포함하는 건만 선별
    # 허용 패턴 예시:
    #   "사업보고서 (2024.01)"          <- 일반적
    #   "[기재정정]사업보고서 (2024.01)" <- 정정 보고서
    #   "사업보고서 (2024년도)"          <- 일부 금융사
    #   "사업보고서 (2024)"              <- 연도만 표기
    def _match_year(report_nm: str, yr: int) -> bool:
        nm = report_nm.strip()
        if "사업보고서" not in nm:
            return False
        yr_s = str(yr)
        # 가장 넓은 패턴: 보고서명 내 연도 숫자가 등장하면 허용
        # 단, yr-1 이나 yr+1 이 포함된 건은 제외하지 않음 — 뒤에서 날짜로 다시 정렬
        return yr_s in nm

    cand = [it for it in items if _match_year(it.get("report_nm", ""), year)]

    # 1차 필터: 연도 문자열이 완전히 없는 경우 -> 빈 결과
    # 2차 안전망: 없으면 '사업보고서'만으로 재시도 (연도 판별 포기하고 날짜로만 구분)
    if not cand:
        cand_fallback = [
            it for it in items if "사업보고서" in it.get("report_nm", "")
        ]
        if cand_fallback:
            import warnings
            warnings.warn(
                f"corp_code={corp_code}: '{year}' 회계연도 패턴 매칭 실패. "
                f"'사업보고서' 전체 목록({len(cand_fallback)}건)을 대상으로 최신 접수분을 사용합니다.",
                stacklevel=2,
            )
            cand = cand_fallback

    if not cand:
        raise ValueError(
            f"corp_code={corp_code} 의 {year} 회계연도 사업보고서를 찾을 수 없습니다. "
            f"(검색 구간: {year + 1}0101 ~ {year + 2}1231, 전체 공시 {len(items)}건)"
        )

    # 가장 최근 접수분 (정정 보고서 우선)
    cand.sort(key=lambda it: it.get("rcept_dt", ""), reverse=True)
    top = cand[0]
    return {
        "rcept_no": top["rcept_no"],
        "report_nm": top["report_nm"].strip(),
        "rcept_dt": top["rcept_dt"],
    }


# ════════════════════════════════════════════════════════════════════
#  3. XBRL 원본파일 다운로드 & 파싱  -> DataFrame
# ════════════════════════════════════════════════════════════════════

def download_xbrl_df(rcept_no: str, reprt_code: str = "11011",
                     api_key: str | None = None) -> pd.DataFrame:
    """
    XBRL 원본파일(zip) 을 받아 압축 해제 후 .xbrl 인스턴스 문서를 파싱.

    reprt_code: 11011=사업보고서(연간). 본 모듈은 사업보고서만 대상으로 한다.

    Returns: DataFrame[tag, value, contextRef, decimals, unitRef]
    """
    key = _get_api_key(api_key)
    params = {"crtfc_key": key, "rcept_no": rcept_no, "reprt_code": reprt_code}
    res = requests.get(f"{DART_BASE}/fnlttXbrl.xml", params=params, timeout=120)
    res.raise_for_status()

    if not (res.content[:2] == b"PK" or "zip" in res.headers.get("Content-Type", "")):
        # 에러 응답은 XML 텍스트로 옴
        raise RuntimeError(f"XBRL 다운로드 실패: {res.text[:300]}")

    with tempfile.TemporaryDirectory() as tmpdir:
        zipfile.ZipFile(io.BytesIO(res.content)).extractall(tmpdir)
        xbrl_files = _glob.glob(os.path.join(tmpdir, "**", "*.xbrl"), recursive=True)
        if not xbrl_files:
            raise RuntimeError("zip 안에서 .xbrl 인스턴스 문서를 찾을 수 없습니다.")
        # 여러 개면 가장 큰 파일(메인 인스턴스 문서)을 사용
        xbrl_path = max(xbrl_files, key=os.path.getsize)

        tree = etree.parse(xbrl_path)
        root = tree.getroot()

        records = []
        for elem in root.iter():
            if elem.get("contextRef") and elem.text and elem.text.strip():
                records.append({
                    "tag": elem.tag.split("}")[-1],     # 네임스페이스 제거
                    "value": elem.text.strip(),
                    "contextRef": elem.get("contextRef"),
                    "decimals": elem.get("decimals", ""),
                    "unitRef": elem.get("unitRef", ""),
                })

    df = pd.DataFrame(records)
    if df.empty:
        raise RuntimeError("XBRL 파싱 결과가 비어 있습니다.")
    return df


# ════════════════════════════════════════════════════════════════════
#  4. XBRL 택사노미 조회  -> tag -> 한글 라벨 매핑
# ════════════════════════════════════════════════════════════════════

def build_taxonomy_labels(api_key: str | None = None,
                           sj_divs=("BS1", "IS1", "CF1")) -> dict:
    """
    XBRL 택사노미 API 로 계정 tag -> 한글 출력명(label_kor) 매핑 테이블 구축.
    결과 항목에 공식 한글 라벨을 붙이는 용도. 실패해도 추출 자체에는 영향 없음.
    """
    key = _get_api_key(api_key)
    tag_to_kor = {}
    for sj in sj_divs:
        try:
            res = requests.get(
                f"{DART_BASE}/xbrlTaxonomy.json",
                params={"crtfc_key": key, "sj_div": sj}, timeout=60,
            )
            rows = res.json().get("list", []) or []
        except Exception:
            continue
        for r in rows:
            acc_id = r.get("account_id", "")
            # account_id 접두사(ifrs_, dart_, entity 등) 제거 -> XBRL tag
            tag = acc_id.split("_", 1)[-1] if "_" in acc_id else acc_id
            label = r.get("label_kor", "")
            if tag and label and tag not in tag_to_kor:
                tag_to_kor[tag] = label
    return tag_to_kor


# ════════════════════════════════════════════════════════════════════
#  5. 핵심 추출 로직  (노트북 셀 26·28·39·44·49 확정본)
# ════════════════════════════════════════════════════════════════════

def detect_member(df: pd.DataFrame) -> str:
    """연결(Consolidated) context 존재 여부 판단. 없으면 개별(Separate)."""
    if df["contextRef"].str.contains("ConsolidatedMember", na=False).any():
        return "Consolidated"
    if df["contextRef"].str.contains("SeparateMember", na=False).any():
        return "Separate"
    return "Consolidated"   # 기본값


def get_value(df: pd.DataFrame, tag: str, ctx_type: str = "BS",
              year_label: str = "CFY2024", member: str = "Consolidated"):
    """
    tag 의 값을 'context 우선순위 폴백' 으로 추출 (노트북 셀 28).

    ctx_type   : "BS"(eFY, 시점) / "IS"·"CF"(dFY, 기간)
    year_label : "CFY2024"(당기) / "PFY2023"(전기) 등
    member     : "Consolidated"(연결) / "Separate"(개별)

    우선순위
      1) 단순 context (정확히 {member}Member 로 끝남)
      2) ReportedAmountMember (성격별분류 D&A 등)
      3) {year}{fy} + {member}Member 포함 (반대 member 제외) 중 첫 번째
    """
    fy = "eFY" if ctx_type == "BS" else "dFY"
    matched = df[df["tag"] == tag]
    if matched.empty:
        return None

    member_tag = f"{member}Member"
    other_tag = "SeparateMember" if member == "Consolidated" else "ConsolidatedMember"

    # 우선순위 1: 단순 context
    plain_ctx = (f"{year_label}{fy}_ifrs-full_"
                 f"ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_{member_tag}")
    p1 = matched[matched["contextRef"] == plain_ctx]
    if not p1.empty:
        return _to_int(p1.iloc[0]["value"])

    # 우선순위 2: ReportedAmountMember
    p2 = matched[
        matched["contextRef"].str.contains(f"{year_label}{fy}", na=False) &
        matched["contextRef"].str.contains(member_tag, na=False) &
        ~matched["contextRef"].str.contains(other_tag, na=False) &
        matched["contextRef"].str.contains("ReportedAmountMember", na=False)
    ]
    if not p2.empty:
        return _to_int(p2.iloc[0]["value"])

    # 우선순위 3: year+member 포함 첫 번째
    p3 = matched[
        matched["contextRef"].str.contains(f"{year_label}{fy}", na=False) &
        matched["contextRef"].str.contains(member_tag, na=False) &
        ~matched["contextRef"].str.contains(other_tag, na=False)
    ]
    if not p3.empty:
        return _to_int(p3.iloc[0]["value"])

    return None


def get_marginal_tax_rate(ebit_won) -> tuple[float, str]:
    """
    한국 법인세 한계세율 (2024년 기준, 과세표준 구간별 누진세율). 단위: 원.
    (노트북 셀 48)
    """
    ebit_uk = (ebit_won or 0) / 1e8     # 억원
    if ebit_uk <= 2:
        return 0.110, "2억 이하"
    elif ebit_uk <= 200:
        return 0.220, "2억~200억"
    elif ebit_uk <= 3000:
        return 0.242, "200억~3000억"
    else:
        return 0.275, "3000억 초과"


def get_value_lafa(df: pd.DataFrame, lafa_axis_suffix: str,
                   year_label: str = "CFY2024", member: str = "Consolidated") -> int | None:
    """
    [v3 신규] LiabilitiesArisingFromFinancingActivities 축에서 특정 차입금 분류 추출.

    일부 기업(현대건설 등)은 BondsIssued / LongtermBorrowings 를
    plain context 대신 LiabilitiesArisingFromFinancingActivitiesAxis 하위
    member context 에만 보고한다. 이 함수는 그 폴백으로 사용된다.

    Parameters
    ----------
    lafa_axis_suffix : str
        탐색할 축 member suffix. 예시:
          - "dart_BondsIssuedMember"          ← 비유동사채
          - "ifrs-full_LongtermBorrowingsMember" ← 장기차입금

    반환값: 원(KRW) 단위 정수, 없으면 None
    """
    fy = "eFY"   # 재무상태표 시점
    member_tag = f"{member}Member"
    other_tag  = "SeparateMember" if member == "Consolidated" else "ConsolidatedMember"

    matched = df[df["tag"] == "LiabilitiesArisingFromFinancingActivities"]
    if matched.empty:
        return None

    # year_label + member + LaFA axis suffix 포함, 반대 member 제외
    hits = matched[
        matched["contextRef"].str.contains(f"{year_label}{fy}", na=False) &
        matched["contextRef"].str.contains(member_tag, na=False) &
        ~matched["contextRef"].str.contains(other_tag, na=False) &
        matched["contextRef"].str.contains(
            "LiabilitiesArisingFromFinancingActivitiesAxis", na=False
        ) &
        matched["contextRef"].str.contains(lafa_axis_suffix, na=False)
    ]
    if not hits.empty:
        return _to_int(hits.iloc[0]["value"])
    return None


def calc_noa(df: pd.DataFrame, year_label: str, member: str = "Consolidated",
             rules: dict = NOA_RULES_FINAL_V3, tag_to_kor: dict | None = None):
    """
    NOA(순영업자산) 계산 — 재무상태표 기준 순액 (노트북 셀 42 calc_noa_v3).
    부호 -1 태그(부채성)는 차감.

    Returns: (noa_items: list[dict], total_won: float)
      noa_items 각 항목 val 은 '원' 단위.
    """
    tag_to_kor = tag_to_kor or {}
    noa_items = []
    total = 0.0

    for cls, tags in rules.items():
        for tag_item in tags:
            if isinstance(tag_item, tuple):
                tag, sign = tag_item[0], tag_item[1]
            else:
                tag, sign = tag_item, 1

            val = get_value(df, tag, "BS", year_label, member)
            if val is None:
                continue
            val_signed = val * sign
            total += val_signed
            noa_items.append({
                "cls": _NOA_CLS_LABEL[cls],
                "tag": tag,
                "kor": tag_to_kor.get(tag) or _NOA_KOR_MAP.get(tag, tag),
                "val": val_signed,          # 원 단위
            })

    return noa_items, total


def get_financials(df: pd.DataFrame, year_cur: int, year_pfy: int | None = None,
                   member: str | None = None, tag_to_kor: dict | None = None) -> dict:
    """
    XBRL DataFrame -> 핵심 재무지표 dict (노트북 셀 49 get_financials 확정본).

    year_cur : 당기 회계연도 (예: 2024)
    year_pfy : 전기 회계연도 (기본값: year_cur - 1)
    member   : "Consolidated"/"Separate". None 이면 자동 판별.

    반환 dict 의 모든 금액 단위는 '원'.
    """
    if year_pfy is None:
        year_pfy = year_cur - 1
    if member is None:
        member = detect_member(df)

    yc = f"CFY{year_cur}"
    yp = f"PFY{year_pfy}"

    def g(tag, ctx="BS", year_label=yc):
        return get_value(df, tag, ctx, year_label, member)

    # ── 손익계산서 ────────────────────────────────────────────
    매출액    = g("Revenue",            "IS")
    영업이익   = g("OperatingIncomeLoss", "IS")
    당기순이익  = g("ProfitLoss",          "IS")
    지배순이익  = g("ProfitLossAttributableToOwnersOfParent", "IS")

    # D&A : 통합표시 태그 있으면 사용, 없으면 개별 3종 합산
    DA_통합  = g("DepreciationAndAmortisationExpense", "IS")
    DA_유형  = g("DepreciationExpense",                "IS")
    DA_무형  = g("AmortisationExpense",                "IS")
    DA_사용권 = g("DepreciationRightofuseAssets",       "IS")
    DA = DA_통합 if DA_통합 else sum(x or 0 for x in [DA_유형, DA_무형, DA_사용권])

    # ── NWC (당기/전기) ───────────────────────────────────────
    def _nwc(year_label):
        ar = (g("CurrentTradeReceivables",                      "BS", year_label) or
              g("ShortTermTradeReceivable",                     "BS", year_label) or
              g("TradeAndOtherCurrentReceivables",              "BS", year_label))
        inv = g("Inventories", "BS", year_label)
        ap = (g("TradeAndOtherCurrentPayablesToTradeSuppliers", "BS", year_label) or
              g("ShortTermTradePayables",                       "BS", year_label) or
              g("TradeAndOtherCurrentPayables",                 "BS", year_label))
        return {
            "매출채권": ar, "재고자산": inv, "매입채무": ap,
            "NWC": (ar or 0) + (inv or 0) - (ap or 0),
        }

    nwc_cur = _nwc(yc)
    nwc_pfy = _nwc(yp)
    delta_nwc = nwc_cur["NWC"] - nwc_pfy["NWC"]

    # ── CAPEX (현금흐름표, 유형자산의 취득) ──────────────────────
    capex = g("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "CF")

    # ── IBD (이자부부채) ──────────────────────────────────────
    ibd_detail = {k: g(tag, "BS") for k, tag in _IBD_SINGLE_TAGS.items()}

    # [v3] 장기차입금 폴백: LongtermBorrowings plain ctx 없으면 fallback 태그 시도
    # 현대건설형: NoncurrentPortionOfNoncurrentLoansReceived
    if not ibd_detail.get("장기차입금"):
        for fb_tag in _IBD_LONGTERM_BORROWINGS_FALLBACK:
            val = g(fb_tag, "BS")
            if val:
                ibd_detail["장기차입금"] = val
                break

    # 유동사채 (CurrentPortionOf* 계열 합산)
    # [v3] 이중계산 방지: 일부 기업(현대건설 등)은 CurrentPortionOfLongtermBorrowings가
    # 유동성사채(CurrentPortionOfBonds)를 이미 포함한 상위 계정으로 보고함.
    # 이 경우 CurrentPortionOfBonds를 별도로 더하면 이중계산 발생.
    #
    # 판별 기준: CurrentPortionOfLongtermBorrowings 값이 존재하고
    #           CurrentPortionOfBonds 값도 존재하며
    #           전자가 후자보다 크고 (즉, 사채 외에 추가 차입금 포함)
    #           NoncurrentPortionOfNoncurrentBondsIssued 태그가 존재 (비유동사채가 별도 보고)
    # → 이 조건들이 모두 충족될 때만 유동성사채 이중계산을 방지
    _cur_portion_ltb   = ibd_detail.get("유동성장기차입금") or 0
    _cur_portion_bonds = g("CurrentPortionOfBonds", "BS") or 0
    _has_noncur_bond_tag = bool(g("NoncurrentPortionOfNoncurrentBondsIssued", "BS"))
    _is_bonds_in_ltb = (
        _cur_portion_ltb > _cur_portion_bonds > 0
        and _has_noncur_bond_tag
    )

    ibd_사채_유동 = sum(g(t, "BS") or 0 for t in _IBD_BOND_CUR)
    if _is_bonds_in_ltb:
        # 유동성장기부채에 유동성사채가 포함된 구조 → 유동성사채 이중계산 차감
        ibd_사채_유동 = max(ibd_사채_유동 - _cur_portion_bonds, 0)
    ibd_detail["유동성사채"] = ibd_사채_유동 or None

    # 비유동사채: _IBD_BOND_NONCUR 계열 순서대로 시도 (첫 번째 값 사용)
    # [v3] NoncurrentPortionOfNoncurrentBondsIssued 추가로 현대건설형 대응
    ibd_사채_비유동 = 0
    for bond_tag in _IBD_BOND_NONCUR:
        val = g(bond_tag, "BS")
        if val:
            ibd_사채_비유동 = val
            break
    # 여전히 0이면 LaFA axis 폴백 (최후 수단)
    if not ibd_사채_비유동:
        lafa_bond = get_value_lafa(df, "dart_BondsIssuedMember", yc, member)
        if lafa_bond:
            # LaFA BondsIssuedMember는 사채 전체(유동+비유동) 잔액일 수 있으므로
            # CurrentPortionOfBonds 차감
            ibd_사채_비유동 = max(lafa_bond - _cur_portion_bonds, 0)
    ibd_detail["비유동사채"] = ibd_사채_비유동 or None

    # ── 단기금융부채: _IBD_FINANCIAL_CUR 계열 ──────────────────────────
    # CurrentFinancialLiabilities 가 있으면 그것이 이미 단기사채+단기차입금 합계일 수 있음
    # → 이미 잡힌 항목 합과 비교해 초과분만 기타유동금융부채로 반영 (이중계산 방지)
    _already_cur = (
        (ibd_detail.get("단기차입금") or 0)
        + (ibd_detail.get("유동성장기차입금") or 0)
        + (ibd_detail.get("유동리스부채") or 0)
        + ibd_사채_유동
    )
    _cur_fin_total = sum(g(t, "BS") or 0 for t in _IBD_FINANCIAL_CUR)
    _cur_fin_extra = max(_cur_fin_total - _already_cur, 0)
    ibd_detail["기타단기금융부채"] = _cur_fin_extra or None

    # ── 장기금융부채: _IBD_FINANCIAL_NONCUR 계열 ────────────────────────
    _already_noncur = (
        (ibd_detail.get("장기차입금") or 0)
        + (ibd_detail.get("비유동리스부채") or 0)
        + ibd_사채_비유동
    )
    _noncur_fin_total = sum(g(t, "BS") or 0 for t in _IBD_FINANCIAL_NONCUR)
    _noncur_fin_extra = max(_noncur_fin_total - _already_noncur, 0)
    ibd_detail["기타장기금융부채"] = _noncur_fin_extra or None

    IBD = sum(v or 0 for v in ibd_detail.values())

    # ── NOA (순영업자산) ──────────────────────────────────────
    noa_items, NOA = calc_noa(df, yc, member, tag_to_kor=tag_to_kor)

    # ── 파생 지표 ─────────────────────────────────────────────
    ebit_val = 영업이익 or 0
    한계세율, 세율구간 = get_marginal_tax_rate(ebit_val)
    NOPAT  = ebit_val * (1 - 한계세율)
    EBITDA = ebit_val + (DA or 0)
    FCFF   = NOPAT + (DA or 0) - abs(capex or 0) - delta_nwc

    return {
        "year": year_cur,
        "재무제표기준": "연결" if member == "Consolidated" else "개별",
        # 손익계산서
        "매출액":    매출액,
        "영업이익":  영업이익,
        "당기순이익": 당기순이익,
        "지배순이익": 지배순이익,
        "da":        DA,
        "ebitda":    EBITDA,
        # NWC
        "nwc_cur":   nwc_cur,
        "nwc_pfy":   nwc_pfy,
        "delta_nwc": delta_nwc,
        # CAPEX (현금흐름표 원본값 — 통상 음수)
        "capex":     capex,
        # IBD
        "ibd":        IBD,
        "ibd_detail": ibd_detail,
        # NOA
        "noa":        NOA,
        "noa_items":  noa_items,
        # 참고 지표
        "한계세율":   한계세율,
        "세율구간":   세율구간,
        "nopat":     NOPAT,
        "fcff":      FCFF,
    }


# ════════════════════════════════════════════════════════════════════
#  6. 출력 / 저장
# ════════════════════════════════════════════════════════════════════

def print_summary(meta: dict, fin: dict) -> None:
    """추출 결과를 억원 단위로 콘솔 출력 (노트북 셀 49 print 블록)."""
    line = "=" * 60
    print(line)
    print(f"  {meta['corp_name']}({meta['stock_code']}) "
          f"{fin['year']} {fin['재무제표기준']}재무제표 (단위: 억원)")
    print(line)

    print("\n【 손익계산서 】")
    print(f"  매출액            {billions(fin['매출액']):>12,.0f}")
    print(f"  영업이익(EBIT)    {billions(fin['영업이익']):>12,.0f}")
    print(f"  D&A               {billions(fin['da']):>12,.0f}")
    print(f"  EBITDA            {billions(fin['ebitda']):>12,.0f}")
    print(f"  당기순이익        {billions(fin['당기순이익']):>12,.0f}")
    print(f"  지배주주순이익    {billions(fin['지배순이익']):>12,.0f}")

    print("\n【 NWC 변동 】")
    print(f"  {'항목':10s} {'전기':>12} {'당기':>12} {'변동':>12}")
    print(f"  {'-' * 48}")
    for k in ("매출채권", "재고자산", "매입채무"):
        pfy = billions(fin["nwc_pfy"][k])
        cur = billions(fin["nwc_cur"][k])
        print(f"  {k:10s} {pfy:>12,.0f} {cur:>12,.0f} {cur - pfy:>+12,.0f}")
    print(f"  {'-' * 48}")
    npf, ncu = billions(fin["nwc_pfy"]["NWC"]), billions(fin["nwc_cur"]["NWC"])
    print(f"  {'NWC':10s} {npf:>12,.0f} {ncu:>12,.0f} {billions(fin['delta_nwc']):>+12,.0f}")
    print(f"  -> ΔNWC = {billions(fin['delta_nwc']):+,.0f}억  "
          f"({'현금유출↑' if fin['delta_nwc'] > 0 else '현금유입↑'})")

    print("\n【 CAPEX 】")
    print(f"  유형자산취득      {abs(billions(fin['capex'])):>12,.0f}")

    print("\n【 IBD 】")
    for k, v in fin["ibd_detail"].items():
        if v:
            print(f"  {k:14s}  {billions(v):>12,.0f}")
    print(f"  {'-' * 28}")
    print(f"  IBD 합계          {billions(fin['ibd']):>12,.0f}")

    print("\n【 NOA 】")
    for cls in ("확실한 NOA", "기본 NOA", "조건부 NOA"):
        items = [x for x in fin["noa_items"] if x["cls"] == cls]
        if not items:
            continue
        sub = sum(x["val"] for x in items)
        print(f"  [{cls}]  소계: {billions(sub):,.0f}억")
        for x in items:
            sign = "(-)" if x["val"] < 0 else "   "
            print(f"    {sign} {x['kor']:24s} {billions(x['val']):>10,.0f}")
    print(f"  {'-' * 36}")
    print(f"  NOA 합계          {billions(fin['noa']):>12,.0f}")

    print("\n【 참고 지표 】")
    print(f"  세율구간   {fin['세율구간']}  ({fin['한계세율'] * 100:.1f}%)")
    print(f"  NOPAT      {billions(fin['nopat']):>12,.0f}억")
    print(f"  FCFF       {billions(fin['fcff']):>12,.0f}억")
    print(line)


def save_json(result: dict, outdir: str | None = None) -> str:
    """결과를 '종목명_연도.json' 으로 저장. outdir 기본값은 현재 작업 폴더."""
    outdir = outdir or os.getcwd()
    os.makedirs(outdir, exist_ok=True)
    fname = f"{result['meta']['corp_name']}_{result['meta']['year']}.json"
    path = os.path.join(outdir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


# ════════════════════════════════════════════════════════════════════
#  7. 전체 파이프라인 오케스트레이터
# ════════════════════════════════════════════════════════════════════

def extract_company(name_or_code: str, year: int,
                    api_key: str | None = None,
                    outdir: str | None = None,
                    save: bool = True,
                    verbose: bool = True) -> dict:
    """
    종목명/종목코드 + 회계연도 -> 재무지표 추출 -> (옵션) JSON 저장.

    Parameters
    ----------
    name_or_code : "아모레퍼시픽" 또는 "090430"
    year         : 회계연도 (예: 2024). 2024 입력 시 2024 회계연도 사업보고서 사용.
    api_key      : None 이면 .env/환경변수 DART_API_KEY 사용.
    outdir       : JSON 저장 폴더. None 이면 현재 작업 폴더.
    save         : True 면 종목명_연도.json 저장.
    verbose      : True 면 진행상황 및 요약 콘솔 출력.

    Returns
    -------
    dict : {"meta": {...}, "financials": {...}}  (모든 금액 단위: 원)
    """
    key = _get_api_key(api_key)

    # 1. corp_code
    if verbose:
        print(f"[1/5] corp_code 조회: {name_or_code}")
    corp = get_corp_code(name_or_code, key)

    # 2. rcept_no
    if verbose:
        print(f"[2/5] {year} 사업보고서 접수번호 조회: {corp['corp_name']}")
    rcept = get_rcept_no(corp["corp_code"], year, key)

    # 3. XBRL 다운로드 & 파싱
    if verbose:
        print(f"[3/5] XBRL 원본파일 다운로드/파싱: {rcept['rcept_no']} ({rcept['report_nm']})")
    df = download_xbrl_df(rcept["rcept_no"], "11011", key)

    # 4. 택사노미 라벨
    if verbose:
        print(f"[4/5] XBRL 택사노미 라벨 매핑")
    tag_to_kor = build_taxonomy_labels(key)

    # 5. 재무지표 추출
    member = detect_member(df)
    if verbose:
        print(f"[5/5] 재무지표 추출 ({'연결' if member == 'Consolidated' else '개별'} 기준)")
    fin = get_financials(df, year, year - 1, member, tag_to_kor)

    meta = {
        "corp_name": corp["corp_name"],
        "stock_code": corp["stock_code"],
        "corp_code": corp["corp_code"],
        "year": year,
        "rcept_no": rcept["rcept_no"],
        "report_nm": rcept["report_nm"],
        "rcept_dt": rcept["rcept_dt"],
        "reprt_code": "11011",
        "재무제표기준": "연결" if member == "Consolidated" else "개별",
        "단위": "원(KRW)",
        "비고": "capex 는 현금흐름표 원본값(통상 음수). 사용 시 abs() 권장.",
    }
    result = {"meta": meta, "financials": fin}

    if verbose:
        print()
        print_summary(meta, fin)

    if save:
        path = save_json(result, outdir)
        if verbose:
            print(f"\n✅ 저장 완료: {path}")
        result["meta"]["saved_path"] = path

    return result


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

def _main():
    parser = argparse.ArgumentParser(
        description="DART XBRL 재무제표 + 택사노미 기반 핵심 재무지표 추출기"
    )
    parser.add_argument("name_or_code", help="종목명 또는 6자리 종목코드 (예: 아모레퍼시픽 / 090430)")
    parser.add_argument("year", type=int, help="회계연도 (예: 2024)")
    parser.add_argument("--outdir", default=None, help="JSON 저장 폴더 (기본: 현재 폴더)")
    parser.add_argument("--api-key", default=None, help="DART API 키 (기본: .env 의 DART_API_KEY)")
    parser.add_argument("--no-save", action="store_true", help="JSON 저장 안 함")
    args = parser.parse_args()

    try:
        extract_company(
            args.name_or_code, args.year,
            api_key=args.api_key, outdir=args.outdir,
            save=not args.no_save, verbose=True,
        )
    except Exception as e:
        print(f"\n❌ 오류: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()
