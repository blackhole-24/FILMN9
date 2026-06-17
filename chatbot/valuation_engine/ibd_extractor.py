"""IBD(유이자부채) 3계층 앙상블 추출 — 회사별 XBRL 택소노미 편차에 강건.

설계(사용자 결정):
  1단계 B (주축): 표준 재무제표(DART fnlttSinglAcntAll)의 표준계정명 합산.
                  회사별 확장태그 편차와 무관 → 견고·결정적. (검증: 태그방식 ±28~48%
                  오차 대비 표준계정 합산은 실제 보고 라인과 일치)
  2단계 A (교차검증): 팀원 XBRL 태그 IBD 와 대조 → 신뢰도(high/medium/low) 산정.
  3단계 C (뉘앙스):  RCPS(상환전환우선주)·하이브리드는 주석 RAG+LLM 으로
                     '금융부채 분류분'을 확인해 보정. (표준 합산이 못 잡는 부분)

이론: 유이자부채는 차입금·사채·리스부채 + 부채로 분류된 상환우선주(debt-like, Damodaran).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

_VAR_ROOT = Path(__file__).resolve().parent.parent
_FNLTT = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

# 표준계정명 포함/제외 키워드 (강건 매칭 — '이자발생부채' 의미 중심).
#  핵심: '금융부채'(상각후원가) 포함. 셀트리온·LG디스플레이·코스맥스처럼 차입금을 별도 라인
#  없이 '단기금융부채/기타금융부채'로 표기하는 회사가 다수 → 이를 잡아야 IBD가 0으로 왜곡되지
#  않는다. (실증: 셀트리온 3.74조·LG디스플레이 12.73조·코스맥스 1.00조 모두 금융부채=차입)
#  · 포함: 차입·사채·리스부채·유동성장기부채·금융부채(상각후원가)·기업어음·RCPS(부채분류).
#  · 제외(비이자성): 파생/FVTPL(당기손익·공정가치·위험회피)·금융보증·매입채무·미지급·예수/보증금·
#    선수·계약부채·충당·법인세·환불·정부보조 / 자산오인(리스채권·사용권·운용리스·리스료·대여) /
#    자본금(우선주자본금) / 차감계정(할인발행차금·할인차금·전환권/신주인수권조정).
#  ※ '기타'는 뭉툭해서 제거 — 기타금융부채(이자성)까지 잘못 제외하던 범인. '기타유동부채' 등
#    비금융부채는 애초에 _INC 미매칭이라 자동 제외되므로 '기타' 키워드 불필요.
#  ※ 할증금/할증발행차금은 data_tp="X"(양수, 차입 장부가 가산)이므로 제외하지 않는다.
_INC = ["차입", "사채", "금융부채", "리스부채", "유동성장기부채", "기업어음",
        "상환전환우선주", "전환상환우선주", "우선주부채"]
_EXC = ["파생", "당기손익", "공정가치", "위험회피", "금융보증",
        "충당", "매입", "미지급", "선수금", "선수수익", "예수", "보증금",
        "계약부채", "환불", "정부보조", "법인세", "대여",
        "리스채권", "사용권", "운용리스", "리스료",
        "할인발행차금", "할인차금", "전환권조정", "신주인수권조정", "자본금"]
# IFRS/DART 표준 태그(account_id) 보강 — DART xbrlTaxonomy(BS1/BS3) 공식 계정사전 근거.
#  ※ fnltt 는 account_id 가 '-표준계정코드 미사용-'인 라인이 많아(예: 삼성전자 단기차입금
#    17.6조) account_nm 키워드가 주축. account_id 는 합집합 보강(누락 보완)으로만 사용.
#  · 포함(substring): 차입(Shortterm/Longterm/CurrentPortionOf...Borrowings),
#    사채(Bonds/Convertible/BondWithWarrant/Exchangeable), 리스부채(Current/Noncurrent
#    LeaseLiabilities·FinanceLeaseLiabilities), RCPS 부채(ConvertibleRedeemablePreferred),
#    전자단기사채(CommercialPaper)·사채(Debenture).
#  · 제외(substring): 택소노미 data_tp="(X)" 차감계정 = Discount·PresentValue·Adjustment
#    (할인발행차금·현재가치할인차금·전환권조정) — 이 3개가 모든 (X) IBD계정을 정확히 덮음.
#    ※ Premium/RedemptionPremium(할증금)은 data_tp="X"(양수)이므로 제외하지 않는다.
#    그 외: 채권/자산(Receivable·LeaseholdDeposit·RightofuseAsset), 혼재 기타금융부채
#    (OtherCurrent/NoncurrentFinancialLiabilities), 파생·보증·확정급여·충당·이연법인세.
_INC_ID = ("Borrowing", "Bond", "LeaseLiabilit", "RedeemablePreferred",
           "CommercialPaper", "Debenture")
_EXC_ID = ("Receivable", "Discount", "PresentValue", "Adjustment",
           "LeaseholdDeposit", "RightofuseAsset", "RightofUseAsset",
           "FinancialGuarantee", "Derivative", "DeferredTax", "Provision",
           "OtherCurrentFinancialLiabilit", "OtherNoncurrentFinancialLiabilit",
           "FairValueThroughProfitOrLoss", "HeldForTrading")


def _amt(x) -> Optional[float]:
    v = (x.get("thstrm_amount") or "").replace(",", "").strip()
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────
# 1단계 B — 표준 재무제표 IBD
# ─────────────────────────────────────────────────────────────
def ibd_from_fnltt(corp_code: str, year: int, reprt_code: str = "11011") -> Optional[dict]:
    """표준 재무제표(fnltt)에서 IBD 합산. {ibd, items, fs_div} 또는 None.

    연결(CFS) 우선, 없으면 별도(OFS). BS 부채 항목 중 차입금/사채/리스부채/RCPS(부채) 합산.
    """
    load_dotenv(_VAR_ROOT / ".env")
    key = os.getenv("DART_API_KEY")
    if not (key and corp_code):
        return None
    for fs in ("CFS", "OFS"):
        try:
            r = requests.get(_FNLTT, params={
                "crtfc_key": key, "corp_code": corp_code, "bsns_year": str(year),
                "reprt_code": reprt_code, "fs_div": fs}, timeout=60).json()
        except Exception:
            continue
        if r.get("status") != "000":
            continue
        items, tot = [], 0.0
        rcps_detected = False
        rcps_amount = 0.0   # IBD 합계에 포함된 RCPS 금액 (Step2: 자본분류 시 차감용)
        for x in r.get("list", []):
            if x.get("sj_div") != "BS":
                continue
            nm = (x.get("account_nm") or "").replace(" ", "")
            aid = (x.get("account_id") or "")
            is_rcps = any(k in nm for k in ("상환전환우선주", "전환상환우선주", "상환우선주"))
            if is_rcps:
                rcps_detected = True   # 부채/자본 분류는 키워드로 확신 불가 → 플래그(Step2 LLM 판정)
            inc = (any(k in nm for k in _INC) and not any(e in nm for e in _EXC)) or \
                  (any(t in aid for t in _INC_ID) and not any(t in aid for t in _EXC_ID))
            if not inc:
                continue
            v = _amt(x)
            if v and v > 0:
                tot += v
                if is_rcps:
                    rcps_amount += v
                items.append({"name": nm or aid, "amount": v})
        if tot > 0:
            return {"ibd": tot, "items": items, "fs_div": fs,
                    "rcps_detected": rcps_detected, "rcps_amount": rcps_amount}
    return None


# ─────────────────────────────────────────────────────────────
# 1단계 A' — 원본 XBRL 태그 IBD (택소노미 근거 + 팀원 검증 동의어)
#   · 표준 IFRS/DART account_id 태그를 '카테고리 first-of(+사채 additive)'로 합산.
#   · 이중계상 방지: 유동성사채는 유동성장기차입금에 포함되므로 별도 합산 안 함(팀원 실증).
#   · 컨텍스트 선택은 팀원 get_value(연결·당기말 plain-context 우선)를 재사용 → 차원 중복 회피.
#   · RCPS: '...PreferredStockLiabilities'(회사가 BS에서 부채로 분류한 분)만 합산(재분류 아님).
#   ※ 한계: 회사별 entity 확장태그(예: 삼성전자 단기차입금=CurrentLoansReceivedOf...)는
#     표준태그가 아니므로 누락될 수 있음 → fnltt(한글 account_nm) 방식이 이를 보완.
# ─────────────────────────────────────────────────────────────
# 카테고리(상호배타·additive across) — 팀원 _IBD_TAGS_* + 택소노미 RCPS 보강
_XT_단기차입금 = ["ShorttermBorrowings", "CurrentBorrowings", "ShortTermBorrowings"]
_XT_유동성장기 = ["CurrentPortionOfLongtermBorrowings", "CurrentPortionOfNoncurrentBorrowings",
                "CurrentMaturitiesOfLongTermDebt"]
_XT_유동리스   = ["CurrentLeaseLiabilities", "CurentPortionOfFinanceLeaseLiabilities"]
_XT_유동RCPS  = ["CurrentPortionOfConvertibleRedeemablePreferredStockLiabilities"]
_XT_장기차입금 = ["LongtermBorrowings", "NoncurrentBorrowings", "BorrowingsNoncurrent",
                "LongTermBorrowings", "NonCurrentBorrowings",
                "NoncurrentPortionOfNoncurrentLoansReceived", "LongTermLoansNet"]
_XT_비유동리스 = ["NoncurrentLeaseLiabilities", "NonCurrentFinanceLeaseLiabilities"]
_XT_비유동사채 = ["BondsIssued", "ConvertibleBonds", "BondWithWarrant", "ExchangeableBonds",
                "NoncurrentBorrowingsInTypeOfBonds", "LongtermBorrowingsInTypeOfBonds",
                "NoncurrentPortionOfNoncurrentBondsIssued"]
_XT_비유동RCPS = ["ConvertibleRedeemablePreferredStockLiabilities"]


def ibd_from_xbrl_raw(xbrl_path, year: int) -> Optional[dict]:
    """원본 .xbrl(인스턴스 문서)에서 표준태그 IBD 합산. {ibd, detail, rcps} 또는 None."""
    import sys
    from lxml import etree
    import pandas as pd
    sys.path.insert(0, str(_VAR_ROOT / "XBRL"))
    try:
        from xbrl_financials_v4 import (get_value_first_of, get_value_sum_of, detect_member)
    except Exception:
        return None
    p = Path(xbrl_path)
    if p.is_dir():
        cands = list(p.glob("*.xbrl"))
        if not cands:
            return None
        p = max(cands, key=lambda f: f.stat().st_size)
    try:
        root = etree.parse(str(p)).getroot()
    except Exception:
        return None
    rec = []
    for el in root.iter():
        if el.get("contextRef") and el.text and el.text.strip():
            rec.append({"tag": el.tag.split("}")[-1], "value": el.text.strip(),
                        "contextRef": el.get("contextRef")})
    df = pd.DataFrame(rec)
    if df.empty:
        return None
    m = detect_member(df)
    yl = f"CFY{year}"

    def f(tags):
        return get_value_first_of(df, tags, "BS", yl, m)

    def s(tags):
        return get_value_sum_of(df, tags, "BS", yl, m) or None

    detail = {
        "단기차입금":       f(_XT_단기차입금),
        "유동성장기차입금": f(_XT_유동성장기),     # 유동성사채 포함(이중계상 방지)
        "유동리스부채":     f(_XT_유동리스),
        "유동성RCPS부채":   f(_XT_유동RCPS),
        "장기차입금":       f(_XT_장기차입금),
        "비유동리스부채":   f(_XT_비유동리스),
        "비유동사채":       s(_XT_비유동사채),
        "비유동RCPS부채":   f(_XT_비유동RCPS),
    }
    ibd = sum(v or 0 for v in detail.values())
    rcps = (detail["유동성RCPS부채"] or 0) + (detail["비유동RCPS부채"] or 0)
    if ibd <= 0:
        return None
    return {"ibd": ibd, "detail": detail, "rcps": rcps, "member": m}


# ─────────────────────────────────────────────────────────────
# 2단계 A — 태그 IBD 교차검증 → 신뢰도
# ─────────────────────────────────────────────────────────────
def crosscheck(fnltt_ibd: Optional[float], tag_ibd: Optional[float],
               tol: float = 0.10) -> tuple[str, str]:
    """(method, confidence). fnltt 주축, 태그와의 일치도로 신뢰도 산정."""
    if fnltt_ibd is None:
        return ("tag_only", "low") if tag_ibd else ("none", "none")
    if not tag_ibd:
        return ("fnltt", "medium")
    dev = abs(tag_ibd - fnltt_ibd) / fnltt_ibd if fnltt_ibd else 1.0
    if dev <= tol:
        return ("fnltt", "high")      # 두 독립 방식 일치 → 고신뢰
    if dev <= 0.30:
        return ("fnltt", "medium")
    return ("fnltt", "low")           # 크게 불일치 → 주석 확인 권장


# ─────────────────────────────────────────────────────────────
# Step 2 — RCPS '부채/자본' 분류 (RAG + LLM, 범주 판단만)
#   ※ 금액은 키워드(BS)가 확정. LLM은 '부채/자본' 범주만 판정(숫자 추출·계산 금지).
#     실증: 숫자 추출/차감은 환각(매입채무 12조 등)으로 실패 → 범주 분류만 신뢰 가능.
#     예) 한화에어로스페이스 — 주석의 "부채요소는 상각후원가로 측정"을 읽어 '부채' 정확 판정.
# ─────────────────────────────────────────────────────────────
def classify_rcps(ticker: Optional[str], year: int, corp_name: Optional[str] = None,
                  model: str = "gpt-5.4-mini") -> tuple[Optional[str], Optional[str]]:
    """RCPS 부채/자본 분류. 반환 (classification, evidence). 실패/불명 시 (None, None).

    RAG(사업보고서 주석) + LLM 범주 판정. OPENAI_API_KEY·임베딩 부재 시 graceful None.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not (api_key and ticker):
        return None, None
    # 1) RAG — RCPS 관련 주석 청크
    try:
        import sys as _sys
        _sys.path.insert(0, str(_VAR_ROOT))
        from embedding.retrieval import retrieve_for_keyword
        chunks = retrieve_for_keyword(
            keywords=["상환전환우선주", "전환상환우선주", "우선주 부채 자본 분류",
                      "상환전환우선주 회계처리", "전환상환우선주부채"],
            ticker=ticker, year=year, top_k=10)
        notes = [c.get("text", "") for c in (chunks or []) if c.get("text")]
    except Exception:
        return None, None
    if not notes:
        return None, None
    # 2) LLM — 범주만 (숫자 금지)
    sys_p = ("너는 K-IFRS 회계 분석가다. 주어진 상환전환우선주(RCPS)가 재무제표에서 '부채'로 "
             "분류됐는지 '자본'으로 분류됐는지 범주만 판정한다. ★금액 추출·계산 금지. 근거 인용만.\n"
             '판단 단서: "부채요소는 상각후원가로 측정"→부채, "자본으로 분류"→자본.\n'
             'JSON: {"classification":"부채|자본|불명","evidence_quote":"<주석 인용>"}')
    user_p = (f"회사: {corp_name or ticker}\n아래 주석에서 RCPS의 부채/자본 분류를 판정:\n===\n"
              + "\n---\n".join(notes[:10]) + "\n===\nJSON으로만:")
    try:
        from openai import OpenAI
        cl = OpenAI(api_key=api_key)
        kw = dict(model=model,
                  messages=[{"role": "system", "content": sys_p},
                            {"role": "user", "content": user_p}],
                  response_format={"type": "json_object"})
        try:
            rsp = cl.chat.completions.create(temperature=0, **kw)
        except Exception:
            rsp = cl.chat.completions.create(**kw)   # gpt-5.x temperature 폴백
        import json as _json
        txt = rsp.choices[0].message.content
        res = _json.loads(txt) if txt else {}
        cls = res.get("classification")
        return (cls if cls in ("부채", "자본") else None), res.get("evidence_quote")
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────
# 통합 — B(표준) 주축 + A(태그) 교차검증 + RCPS LLM 분류(Step2)
# ─────────────────────────────────────────────────────────────
def compute_ibd(corp_code: str, year: int, reprt_code: str = "11011",
                tag_ibd: Optional[float] = None,
                ticker: Optional[str] = None, corp_name: Optional[str] = None) -> dict:
    """IBD = fnltt 표준계정 합산(주축) + 태그 교차검증(신뢰도).

    Returns: {ibd, ibd_method, ibd_confidence, fnltt_ibd, tag_ibd, fnltt_items, fnltt_fs_div}
    """
    b = ibd_from_fnltt(corp_code, year, reprt_code)
    fnltt_ibd = b["ibd"] if b else None
    method, confidence = crosscheck(fnltt_ibd, tag_ibd)
    ibd = fnltt_ibd if fnltt_ibd is not None else (tag_ibd or 0.0)
    out = {
        "ibd": ibd, "ibd_method": method, "ibd_confidence": confidence,
        "fnltt_ibd": fnltt_ibd, "tag_ibd": tag_ibd,
        "fnltt_items": b["items"] if b else [], "fnltt_fs_div": b["fs_div"] if b else None,
    }
    # ── Step 2: RCPS 탐지 시 — LLM '부채/자본' 범주 분류 (금액은 키워드 확정) ──
    if b and b.get("rcps_detected"):
        rcps_amt = b.get("rcps_amount", 0.0) or 0.0
        cls, evidence = classify_rcps(ticker, year, corp_name)
        out["rcps_detected"] = True
        out["rcps_amount"] = rcps_amt
        out["rcps_classification"] = cls or "불명"
        out["rcps_evidence"] = evidence
        if cls == "자본":
            # 자본분류 RCPS는 IBD 아님 → 키워드가 잡은 RCPS 금액 차감
            out["ibd"] = max(0.0, ibd - rcps_amt)
            out["ibd_note"] = (f"RCPS 자본분류(LLM) → IBD에서 {rcps_amt/1e8:.0f}억 제외")
            # 분류 확정 → crosscheck 신뢰도 유지 (low 강제 안 함)
        elif cls == "부채":
            out["ibd_note"] = "RCPS 부채분류(LLM 확인) — IBD 포함 유지"
            # 분류 확정 → 신뢰도 유지
        else:
            # 분류 불명(LLM/RAG 부재·실패) → 보수적: 신뢰도 하향 + 수동확인 권고
            out["ibd_confidence"] = "low"
            out["ibd_note"] = "RCPS 보유 — 부채/자본 분류 미확정(LLM), 수동 확인 권장"
    return out


def refresh_cached_ibd(min_year: int = 2023, verbose: bool = True) -> dict:
    """기존 캐시 financials 의 IBD 를 fnltt 표준값으로 일괄 갱신 (XBRL 재다운로드 없이).

    data/xbrl/*.json 의 financials.ibd 교체(+ibd_tag/method/confidence) + DB 동기화.
    min_year 이상 연도만(평가에 쓰이는 FISCAL_YEARS) → fnltt 호출 절약.
    """
    import glob
    import json
    from valuation_engine import db
    files = []
    for p in (_VAR_ROOT / "data" / "xbrl", _VAR_ROOT / "valuation_engine" / "data" / "xbrl"):
        files += [f for f in glob.glob(str(p / "*.json")) if "all_financials" not in f]
    ok = changed = skip = 0
    for fp in files:
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        meta = d.get("meta", {}) or {}
        fin = d.get("financials", {})
        cc = meta.get("corp_code"); yr = meta.get("year")
        if not (cc and yr and isinstance(fin, dict)):
            continue
        if int(yr) < min_year:
            skip += 1; continue
        res = compute_ibd(cc, int(yr), meta.get("reprt_code", "11011"),
                          tag_ibd=fin.get("ibd"), ticker=meta.get("stock_code"),
                          corp_name=meta.get("corp_name"))
        if res.get("fnltt_ibd") is None:
            continue   # fnltt 실패 → 기존 태그 IBD 유지
        old = fin.get("ibd")
        fin["ibd_tag"] = old
        fin["ibd"] = res["ibd"]
        fin["ibd_method"] = res["ibd_method"]
        fin["ibd_confidence"] = res["ibd_confidence"]
        fin["ibd_fnltt_items"] = res["fnltt_items"]
        try:
            json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
            db.save_financials(meta.get("stock_code"), int(yr), d)
            ok += 1
            if old and res["ibd"] and abs(old - res["ibd"]) / (res["ibd"] or 1) > 0.15:
                changed += 1
        except Exception:
            pass
        if verbose and ok % 50 == 0 and ok:
            print(f"  ...{ok}개 갱신", flush=True)
    if verbose:
        print(f"refresh 완료: {ok}개 IBD 갱신 / {changed}개 15%+ 변경 / {skip}개 스킵(연도)")
    return {"updated": ok, "changed": changed}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(_VAR_ROOT / ".env")
    refresh_cached_ibd()
