"""분기 손익 수집 + TTM(Trailing Twelve Months) 재구성 — 손익 신선도 갱신용.

설계 (사용자 결정 1a: 손익 TTM + 자본항목 연간 하이브리드):
  · 데이터 소스: DART fnlttSinglAcntAll (단일회사 전체 재무제표) — 분기 XBRL 보다
    항목이 안정적이고 손익을 일관 제공.
  · ★ 실측 확인: fnlttSinglAcntAll 의 CIS(연결포괄손익) thstrm_amount 는 '당기 3개월
    (분기 단독)' 이다 (누적 YTD 아님). → 분해 불필요, 4개 분기 단독값을 그대로 합산.
       1Q=11013, 2Q=11012(반기보고서 당기3개월), 3Q=11014,
       4Q = 사업보고서(11011, 연간) − (1Q+2Q+3Q)
  · TTM = 최신 분기 기준 직전 4개 분기 단독 합 → 계절성 제거 + 최신성.

자본항목(CapEx·NWC·D&A)은 분기 XBRL 불완전 → 연간 사업보고서 유지(dcf_engine).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests

_VAR_ROOT = Path(__file__).resolve().parent.parent
_API = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

# ── .env 자동 로드 (DART_API_KEY) — 모듈 단독 import 시에도 보장 ──
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_VAR_ROOT / ".env", override=False)
except ImportError:
    pass

# reprt_code (분기/반기/사업)
_RC = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}

# 계정명 후보 (회사별 표기 차이 대응) — CIS(연결포괄손익) 우선, 없으면 IS
_REV_NAMES = ("매출액", "수익(매출액)", "영업수익", "매출")
_EBIT_NAMES = ("영업이익", "영업이익(손실)")
# Phase 3+: 당기순이익(총) — TTM EPS 용. 첫 매칭(총 순이익, 귀속분리 전) 우선.
_NI_NAMES = ("당기순이익", "당기순이익(손실)", "분기순이익", "분기순이익(손실)",
             "반기순이익", "반기순이익(손실)", "당기순이익(당기손실)", "연결당기순이익")

# 분기 단독값 메모리 캐시 (corp_code, year, q) → (revenue, ebit)
_Q_CACHE: dict[tuple, tuple] = {}

# Phase 3: 최신 분기 BS(net_debt) 프로세스 메모리 캐시 — (corp_code, annual_year) → dict|None.
#   같은 평가 내 타깃·피어가 동일 회사를 중복 조회하지 않도록. 분기 BS 는 분기
#   공시마다 갱신되므로 디스크 영구캐시는 stale 위험 → 프로세스 메모리만(최신성 보장).
_QBS_CACHE: dict[tuple, object] = {}

# Phase 3+: 비교표시 누적 TTM 캐시 — (corp_code, year, q) → dict|None. 분기 손익도
#   분기 공시마다 갱신되므로 프로세스 메모리만(최신성). 피어 TTM 중복 조회 방지.
_TTM_CACHE: dict[tuple, object] = {}


def _dart_key() -> str:
    k = os.getenv("DART_API_KEY")
    if not k:
        raise RuntimeError("환경변수 'DART_API_KEY' 미설정")
    return k


def _to_float(v) -> Optional[float]:
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _fetch_income(corp_code: str, year: int, reprt_code: str
                  ) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """fnlttSinglAcntAll → (당기매출, 당기영업이익, 전년동기매출). CFS 우선, 실패 시 OFS.

    전년동기매출(frmtrm_q_amount) = 분기보고서의 비교표시 값 → sanity 교차검증용.
    """
    for fs_div in ("CFS", "OFS"):
        try:
            d = requests.get(_API, params={
                "crtfc_key": _dart_key(), "corp_code": corp_code,
                "bsns_year": str(year), "reprt_code": reprt_code, "fs_div": fs_div},
                timeout=30).json()
        except Exception:
            continue
        if d.get("status") != "000":
            continue
        rev = ebit = prev_q_rev = None
        for it in d.get("list", []):
            if it.get("sj_div") not in ("CIS", "IS"):
                continue
            nm = (it.get("account_nm") or "").strip()
            if rev is None and nm in _REV_NAMES:
                rev = _to_float(it.get("thstrm_amount"))
                prev_q_rev = _to_float(it.get("frmtrm_q_amount"))   # 전년동기(비교표시)
            if ebit is None and nm in _EBIT_NAMES:
                ebit = _to_float(it.get("thstrm_amount"))
        if rev is not None or ebit is not None:
            return rev, ebit, prev_q_rev
    return None, None, None


def _quarter_standalone(corp_code: str, year: int, q: int) -> tuple[Optional[float], Optional[float]]:
    """특정 (연도, 분기) 단독 손익 (3개월). 4Q는 연간 − (1Q+2Q+3Q)."""
    ck = (corp_code, year, q)
    if ck in _Q_CACHE:
        return _Q_CACHE[ck]
    if q in (1, 2, 3):
        r, e, _ = _fetch_income(corp_code, year, _RC[q])
        res = (r, e)
    else:  # 4Q = 연간 − 직전 3개 분기 단독
        fy_r, fy_e, _ = _fetch_income(corp_code, year, _RC[4])
        if fy_r is None:
            res = (None, None)
        else:
            sr = se = 0.0
            ok = True
            for qq in (1, 2, 3):
                r, e = _quarter_standalone(corp_code, year, qq)
                if r is None or e is None:
                    ok = False
                    break
                sr += r; se += e
            res = (fy_r - sr, (fy_e - se) if (fy_e is not None and ok) else None) if ok else (None, None)
    _Q_CACHE[ck] = res
    return res


def _prev_quarters(year: int, q: int, n: int = 4) -> list[tuple[int, int]]:
    """(year,q) 포함 직전 n개 분기 (year,q) 리스트 — 최신→과거."""
    out = []
    y, qq = year, q
    for _ in range(n):
        out.append((y, qq))
        qq -= 1
        if qq == 0:
            qq = 4; y -= 1
    return out


def compute_ttm(corp_code: str, latest_year: int, latest_q: int,
                verbose: bool = False) -> Optional[dict]:
    """최신 분기 기준 TTM(최근 4개 분기 단독 합) 매출·영업이익.

    Returns:
        {"ttm_revenue", "ttm_ebit", "ttm_opm", "quarters": [(y,q,rev,ebit)...],
         "as_of_period": "YYYY.Qn"} 또는 데이터 부족 시 None.
    """
    qs = _prev_quarters(latest_year, latest_q, 4)
    tot_r = tot_e = 0.0
    detail = []
    for (y, qq) in qs:
        r, e = _quarter_standalone(corp_code, y, qq)
        if r is None or e is None:
            if verbose:
                print(f"  [TTM] {y}Q{qq} 결측 → TTM 산출 불가")
            return None
        tot_r += r; tot_e += e
        detail.append((y, qq, r, e))
    opm = tot_e / tot_r if tot_r else None

    # ── Sanity: 비교표시(전년동기) 교차검증 — 분기 수집 정합성 보증 ──
    #   최신 보고서의 전년동기 매출(frmtrm_q) == 우리가 1년 전 동분기로 수집한 매출 ?
    #   불일치(>1%)면 정정공시·수집오류 의심 → 경고. (4Q는 연간기준이라 제외)
    sanity = None
    if latest_q in (1, 2, 3):
        try:
            _, _, rep_prev = _fetch_income(corp_code, latest_year, _RC[latest_q])
            our_prev, _ = _quarter_standalone(corp_code, latest_year - 1, latest_q)
            if rep_prev and our_prev:
                diff = abs(rep_prev - our_prev) / our_prev
                sanity = {"report_prev_q_rev": rep_prev, "collected_prev_q_rev": our_prev,
                          "diff_pct": round(diff * 100, 3), "ok": diff < 0.01}
        except Exception:
            pass

    if verbose:
        print(f"  [TTM] {latest_year}Q{latest_q} 기준 4개 분기 합: "
              f"매출 {tot_r/1e12:.3f}조, 영업이익 {tot_e/1e12:.3f}조, OPM {opm*100:.2f}%")
        for (y, qq, r, e) in detail:
            print(f"        {y}Q{qq}: 매출 {r/1e12:.3f}조  영업이익 {e/1e12:.3f}조")
        if sanity:
            tag = "OK" if sanity["ok"] else "⚠ MISMATCH"
            print(f"  [sanity] 전년동기 비교표시 {sanity['report_prev_q_rev']/1e12:.3f}조 vs "
                  f"수집 {sanity['collected_prev_q_rev']/1e12:.3f}조 "
                  f"(Δ{sanity['diff_pct']}%) → {tag}")
    return {
        "ttm_revenue": tot_r, "ttm_ebit": tot_e, "ttm_opm": opm,
        "quarters": detail, "as_of_period": f"{latest_year}.Q{latest_q}",
        "sanity_yoy": sanity,
    }


# ═════════════════════════════════════════════════════════════
# Phase 3+: 비교표시 누적 방식 TTM (매출·영업이익·순이익)
#   한국 분기/반기 보고서는 비교표시 원칙상 '당기 누적'(thstrm_add_amount)과
#   '전기 동기 누적'(frmtrm_add_amount)을 함께 싣는다. 이를 이용하면:
#     TTM = 당기누적 + 전기연간 − 전기동기누적   (분기/반기)
#         = 연간                                  (사업보고서가 최신)
#   → 최신 분기보고서 1개(당기·전기동기 누적) + 직전 사업보고서 1개 = 2개 조회.
#     (단독 4분기 합산 대비 조회 절감 + 정정공시 누적오차 없음 → 피어에도 적용 가능)
# ═════════════════════════════════════════════════════════════
def _fetch_income_cumulative(corp_code: str, year: int, reprt_code: str) -> dict:
    """손익 비교표시 누적 → {rev_acc, rev_prev_acc, ebit_acc, ebit_prev_acc,
    ni_acc, ni_prev_acc}. 사업보고서(11011)는 acc=연간(thstrm_amount), prev_acc=None.
    CFS 우선, 실패 시 OFS. 미발견 항목은 None.
    """
    is_annual = (reprt_code == "11011")
    acc_field = "thstrm_amount" if is_annual else "thstrm_add_amount"
    for fs_div in ("CFS", "OFS"):
        try:
            d = requests.get(_API, params={
                "crtfc_key": _dart_key(), "corp_code": corp_code,
                "bsns_year": str(year), "reprt_code": reprt_code, "fs_div": fs_div},
                timeout=30).json()
        except Exception:
            continue
        if d.get("status") != "000":
            continue
        out: dict = {}
        for it in d.get("list", []):
            if it.get("sj_div") not in ("CIS", "IS"):
                continue
            nm = (it.get("account_nm") or "").strip()
            if "rev_acc" not in out and nm in _REV_NAMES:
                out["rev_acc"] = _to_float(it.get(acc_field))
                out["rev_prev_acc"] = None if is_annual else _to_float(it.get("frmtrm_add_amount"))
            if "ebit_acc" not in out and nm in _EBIT_NAMES:
                out["ebit_acc"] = _to_float(it.get(acc_field))
                out["ebit_prev_acc"] = None if is_annual else _to_float(it.get("frmtrm_add_amount"))
            if "ni_acc" not in out and nm in _NI_NAMES:
                out["ni_acc"] = _to_float(it.get(acc_field))
                out["ni_prev_acc"] = None if is_annual else _to_float(it.get("frmtrm_add_amount"))
        if out.get("rev_acc") is not None or out.get("ebit_acc") is not None:
            return out
    return {}


def compute_ttm_comparative(corp_code: str, latest_year: int, latest_q: int,
                            verbose: bool = False) -> Optional[dict]:
    """비교표시 누적 방식 TTM (매출·영업이익·순이익) — 보고서 2개.

    Returns: {ttm_revenue, ttm_ebit, ttm_ni, ttm_opm, as_of_period, method} 또는 None.
      method: 'annual'(최신=사보) / 'comparative_cumulative'(분기/반기).
    """
    if not corp_code:
        return None
    _ck = (corp_code, latest_year, latest_q)
    if _ck in _TTM_CACHE:
        return _TTM_CACHE[_ck]

    def _finish(res):
        _TTM_CACHE[_ck] = res
        return res

    # 사업보고서가 최신 → TTM = 연간 그대로
    if latest_q == 4:
        cur = _fetch_income_cumulative(corp_code, latest_year, "11011")
        if cur.get("rev_acc") is None:
            return _finish(None)
        rev, ebit, ni = cur.get("rev_acc"), cur.get("ebit_acc"), cur.get("ni_acc")
        opm = (ebit / rev) if (ebit is not None and rev) else None
        return _finish({"ttm_revenue": rev, "ttm_ebit": ebit, "ttm_ni": ni,
                        "ttm_opm": opm, "as_of_period": f"{latest_year}.Q4",
                        "method": "annual"})

    # 분기/반기: 당기누적 + 전기연간 − 전기동기누적
    cur = _fetch_income_cumulative(corp_code, latest_year, _RC[latest_q])
    prev_annual = _fetch_income_cumulative(corp_code, latest_year - 1, "11011")
    if not cur or not prev_annual:
        return _finish(None)

    def _ttm(acc, prev_acc, prev_ann):
        if acc is None or prev_acc is None or prev_ann is None:
            return None
        return acc + prev_ann - prev_acc

    ttm_rev  = _ttm(cur.get("rev_acc"),  cur.get("rev_prev_acc"),  prev_annual.get("rev_acc"))
    ttm_ebit = _ttm(cur.get("ebit_acc"), cur.get("ebit_prev_acc"), prev_annual.get("ebit_acc"))
    ttm_ni   = _ttm(cur.get("ni_acc"),   cur.get("ni_prev_acc"),   prev_annual.get("ni_acc"))
    if ttm_rev is None or ttm_rev <= 0:
        return _finish(None)
    opm = (ttm_ebit / ttm_rev) if ttm_ebit is not None else None
    if verbose:
        print(f"  [TTM 비교표시] {latest_year}Q{latest_q}: 매출 {ttm_rev/1e12:.3f}조 "
              f"영업이익 {ttm_ebit/1e12:.3f}조 OPM {opm*100:.2f}% "
              f"(당기누적+전기연간−전기동기누적, 보고서 2개)")
    return _finish({"ttm_revenue": ttm_rev, "ttm_ebit": ttm_ebit, "ttm_ni": ttm_ni,
                    "ttm_opm": opm, "as_of_period": f"{latest_year}.Q{latest_q}",
                    "method": "comparative_cumulative"})


# report_detector 의 period("YYYY.MM") → (year, q) 변환
_MM_TO_Q = {"03": 1, "06": 2, "09": 3, "12": 4}


def compute_ttm_8q_weighted(corp_code: str, latest_year: int, latest_q: int,
                            verbose: bool = False) -> Optional[dict]:
    """C2 — 8분기 가중평균 TTM (호황 정점/바닥 쏠림 완화).

    가중치: 최근일수록 높게 (1,2,3,4,5,6,7,8) — 분기별 OPM에 적용.
    매출/영업이익 시계열은 단순합도 같이 제공 (비교용).

    Returns:
      {"ttm8w_opm", "ttm8_revenue", "ttm8_ebit", "quarters":[...],
       "as_of_period", "weights"} 또는 가용 분기 <6 시 None.
    """
    qs = _prev_quarters(latest_year, latest_q, 8)
    valid = []
    for (y, qq) in qs:
        r, e = _quarter_standalone(corp_code, y, qq)
        if r is not None and e is not None and r > 0:
            valid.append((y, qq, r, e))
    if len(valid) < 6:    # 최소 6분기 가용
        if verbose:
            print(f"  [TTM 8Q] 가용 분기 부족 ({len(valid)}/8) → None")
        return None

    # 시계열은 오래된→최신 순으로 정렬 (가중치 1~8 부여)
    valid.sort(key=lambda x: (x[0], x[1]))
    n = len(valid)
    weights = list(range(1, n + 1))     # 가중치 1~n
    w_sum = sum(weights)

    # 분기 OPM 가중평균
    opm_w = sum(((e / r) * w) for (_, _, r, e), w in zip(valid, weights)) / w_sum
    tot_r = sum(r for _, _, r, _ in valid)
    tot_e = sum(e for _, _, _, e in valid)
    simple_opm = tot_e / tot_r if tot_r else None

    if verbose:
        print(f"  [TTM 8Q 가중평균] {latest_year}Q{latest_q} 기준 {n}개 분기")
        print(f"    OPM 가중평균(weights={weights}): {opm_w*100:.2f}%")
        print(f"    OPM 단순합:                     {simple_opm*100:.2f}%")
    return {
        "ttm8w_opm":   opm_w,           # 가중평균 OPM (cyclical 종목 평탄화)
        "ttm8_opm":    simple_opm,      # 8분기 단순합 OPM
        "ttm8_revenue": tot_r,          # 8분기 매출 합 (참고)
        "ttm8_ebit":   tot_e,
        "quarters":    valid,
        "weights":     weights,
        "as_of_period": f"{latest_year}.Q{latest_q}",
        "n_quarters":  n,
    }


def ttm_from_period(corp_code: str, period: str, verbose: bool = False) -> Optional[dict]:
    """report_detector period('2026.03') → TTM."""
    yr, mm = period.split(".")
    q = _MM_TO_Q.get(mm)
    if not q:
        return None
    return compute_ttm(corp_code, int(yr), q, verbose=verbose)


# ─────────────────────────────────────────────────────────────
# 재무상태표 시점 최신화 — 최신 분기/반기 보고서의 IBD·현금 → net_debt
#   BS 는 '시점(as-of)' 정보이므로, 가장 최근 정기보고서(2026.03 등)의 BS 를 쓰면
#   연말(2025.12) 기준보다 신선하다. 손익은 compute_ttm(별도), BS 는 본 함수.
# ─────────────────────────────────────────────────────────────
def latest_quarter_bs(corp_code: str, annual_fiscal_year: int,
                      verbose: bool = False) -> Optional[dict]:
    """최신 정기보고서 BS → {ibd, cash, net_debt, period, reprt_code, fs_div, kind}.

    report_detector 로 최신 보고서를 찾아, 연간(YYYY.12)보다 최신(분기/반기)일 때만
    그 보고서의 fnltt BS 에서 IBD·현금을 추출해 반환. 아니면 None(연간 유지).
    """
    from .report_detector import list_periodic_reports
    from .ibd_extractor import ibd_from_fnltt
    if not corp_code:
        return None
    # Phase 3: 프로세스 메모리 캐시 — 같은 평가 내 중복 조회(타깃+피어) 방지.
    _ck = (corp_code, annual_fiscal_year)
    if _ck in _QBS_CACHE:
        return _QBS_CACHE[_ck]
    _res = _latest_quarter_bs_impl(corp_code, annual_fiscal_year, verbose)
    _QBS_CACHE[_ck] = _res
    return _res


def _latest_quarter_bs_impl(corp_code: str, annual_fiscal_year: int,
                            verbose: bool = False) -> Optional[dict]:
    """latest_quarter_bs 실제 구현 (캐시 미적용). 위 wrapper 가 메모리 캐시."""
    from .report_detector import list_periodic_reports
    from .ibd_extractor import ibd_from_fnltt
    try:
        reps = list_periodic_reports(corp_code)
    except Exception as e:
        if verbose:
            print(f"  [latest_bs] 보고서 목록 조회 실패: {str(e)[:80]}")
        return None
    if not reps:
        return None
    latest = reps[0]                       # period 최신순 정렬
    period = latest["period"]; year = int(latest["year"]); rc = latest["reprt_code"]
    if period <= f"{annual_fiscal_year}.12":
        return None                        # 최신 보고서가 연간 이하 → 갱신 불필요
    b = ibd_from_fnltt(corp_code, year, rc)   # IBD (Step1/2 fnltt)
    if not b:
        return None
    fs = b["fs_div"]
    cash = 0.0                             # 같은 보고서·fs_div 의 현금성자산
    cash_found = False
    equity_parent_q = None                 # Phase 3+: 분기 지배지분 자본 (BPS 분기화용)
    try:
        d = requests.get(_API, params={
            "crtfc_key": _dart_key(), "corp_code": corp_code,
            "bsns_year": str(year), "reprt_code": rc, "fs_div": fs}, timeout=30).json()
        if d.get("status") == "000":
            for it in d.get("list", []):
                if it.get("sj_div") != "BS":
                    continue
                _acc = (it.get("account_nm") or "").replace(" ", "")
                # Phase 3: 현금성 항목명 매칭 확장 — 번호접두("Ⅰ.현금및현금성자산")·공백
                #   변형을 in 으로 포섭하되, '단기금융상품' 합산 항목은 제외해 연간
                #   XBRL(CashAndCashEquivalents=현금및현금성자산) 정의와 일치 유지.
                if (not cash_found) \
                   and ("현금및현금성자산" in _acc or "현금및현금등가물" in _acc) \
                   and "단기금융" not in _acc:
                    cash = _to_float(it.get("thstrm_amount")) or 0.0
                    cash_found = True
                # Phase 3+: 분기 지배지분 자본 — BPS(=지배지분−우선주/보통주) 분기화용.
                #   '지배기업의 소유주에게 귀속되는 자본'(연결 BS 표준 표기). 추가 API 0.
                if equity_parent_q is None \
                   and ("지배기업의소유주에게귀속되는자본" in _acc
                        or "지배기업소유주지분" in _acc):
                    equity_parent_q = _to_float(it.get("thstrm_amount"))
    except Exception:
        pass
    if verbose:
        print(f"  [latest_bs] {period} {latest['kind']} ({rc}/{fs}): "
              f"IBD={b['ibd']/1e12:.3f}조 현금={cash/1e12:.3f}조 "
              f"→ net_debt={(b['ibd']-cash)/1e12:.3f}조")
    return {"ibd": b["ibd"], "cash": cash, "net_debt": b["ibd"] - cash,
            "equity_parent": equity_parent_q,   # Phase 3+: 분기 지배지분 (None 가능)
            "period": period, "reprt_code": rc, "fs_div": fs, "kind": latest["kind"]}


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(_VAR_ROOT / ".env")
    cc = sys.argv[1] if len(sys.argv) > 1 else "00126371"   # 삼성전기
    period = sys.argv[2] if len(sys.argv) > 2 else "2026.03"
    print(f"corp_code={cc}, 최신기간={period}")
    r = ttm_from_period(cc, period, verbose=True)
    print("\n결과:", {k: v for k, v in (r or {}).items() if k != "quarters"})
