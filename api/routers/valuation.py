"""
api/routers/valuation.py
========================
밸류에이션 JSON 서빙 엔드포인트.

파일 탐색 구조
--------------
data/valuation_results/{code}_{name}/   ← run_valuation.py 출력 서브폴더
    dcf_result.json          : 요약 · 시나리오 · 검증
    fcff_result.json         : 연도별 DCF 테이블 (단위: billion KRW)
    wacc_result.json         : WACC 구성 + 피어 자본구조
    multiples_result.json    : 멀티플 역산 적정가
    peer_beta_result.json    : 피어 베타 회귀
    uncertainty_result.json  : 민감도 매트릭스 + 토네이도

폴더 없으면 is_mock=true 반환 → 프론트가 MOCK_VAL 사용.
태상님 결과 폴더 복사만 하면 서버 재시작 없이 실데이터 자동 전환.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

_ROOT        = Path(__file__).resolve().parent.parent.parent
_RESULTS_DIR = _ROOT / "data" / "valuation_results"


# ─── 파일 탐색 ─────────────────────────────────────────────────────────────

def _find_subfolder(stock_code: str) -> Path | None:
    """data/valuation_results/{code}_* 서브폴더 탐색 (최신 수정 우선)."""
    if not _RESULTS_DIR.exists():
        return None
    matches = sorted(
        [p for p in _RESULTS_DIR.iterdir()
         if p.is_dir() and p.name.startswith(stock_code + "_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def _load_json(folder: Path, filename: str) -> dict:
    path = folder / filename
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[valuation] JSON 로드 실패 {filename}: {e}")
        return {}


# ─── 변환 헬퍼 ─────────────────────────────────────────────────────────────

def _fmt_won(krw: float | None) -> str:
    """원화 금액 → 조/억 단위 레이블."""
    if krw is None:
        return "—"
    if krw >= 1e12:
        return f"₩{krw / 1e12:.1f}조"
    if krw >= 1e8:
        return f"₩{krw / 1e8:.0f}억"
    return f"₩{krw:,.0f}"


def _upside_str(price: float | None, current: float | None) -> str:
    if not price or not current:
        return "—"
    pct = (price - current) / current * 100
    return f"{pct:+.1f}%"


def _b2uk(val: float | None) -> int | None:
    """십억원(billion KRW) → 억원 변환 (×10)."""
    return round(val * 10) if val is not None else None


def _parse_wacc_label(label: str, base_wacc: float) -> float:
    """
    'WACC −1%p' → base_wacc - 1.0
    'WACC (Base)' → base_wacc
    'WACC +1%p'  → base_wacc + 1.0
    U+2212(−) 과 ASCII(-) 모두 처리.
    """
    if "Base" in label or "base" in label.lower():
        return round(base_wacc, 2)
    m = re.search(r"([+−\-])(\d+(?:\.\d+)?)%p", label)
    if m:
        sign = -1 if m.group(1) in ("−", "-") else 1
        return round(base_wacc + sign * float(m.group(2)), 2)
    return round(base_wacc, 2)


def _parse_g_label(label: str) -> float:
    """'g = 2.0%' → 2.0"""
    m = re.search(r"(\d+(?:\.\d+)?)%", label)
    return float(m.group(1)) if m else 0.0


# ─── 6파일 → Tab2 포맷 변환 ───────────────────────────────────────────────

def _convert_multi(
    dcf: dict,
    fcff: dict,
    wacc_data: dict,
    multiples: dict,
    peer_beta: dict,
    uncertainty: dict,
) -> dict:
    """
    run_valuation.py 6개 출력 파일 → Tab2 호환 포맷 변환.

    단위 주의
    ---------
    fcff_result unit = "billion" (십억원) → ×10 = 억원
    dcf_result  equity_value_billion / ev_billion / net_debt_billion = 십억원 → ×10 = 억원
    sensitivity, tornado 값 = KRW per share (원 단위)
    """
    current   = dcf.get("current_price")
    scenarios = dcf.get("scenarios", {})

    # ── 적정가·상승여력 ─────────────────────────────────────────────
    fair_prices = {
        "bear": scenarios.get("bear", {}).get("fair_value"),
        "base": scenarios.get("base", {}).get("fair_value") or dcf.get("fair_value_per_share"),
        "bull": scenarios.get("bull", {}).get("fair_value"),
    }
    upsides = {k: _upside_str(v, current) for k, v in fair_prices.items()}

    # ── 기업가치 레이블 ─────────────────────────────────────────────
    eq_billion    = dcf.get("equity_value_billion")
    eq_won_label  = _fmt_won(eq_billion * 1e9 if eq_billion else None)

    # ── DCF 테이블 ──────────────────────────────────────────────────
    labels = [l for l in fcff.get("fiscal_years", []) if l != "TV"][:5]

    def _row(
        key: str,
        label: str,
        bold: bool = False,
        fmt: str | None = None,
        source_list: list | None = None,
    ) -> dict:
        raw = (source_list if source_list is not None else fcff.get(key, []))[:5]
        if fmt == "decimal3":
            values = [round(v, 3) if v is not None else None for v in raw]
        elif fmt == "pct":
            values = [round(v, 1) if v is not None else None for v in raw]
        else:
            values = [_b2uk(v) for v in raw]   # billion → 억원
        return {
            "label" : label,
            "values": values,
            "bold"  : bold,
            **({"fmt": fmt} if fmt else {}),
        }

    dcf_rows = [
        _row("revenue",           "매출액 (억원)",     bold=True),
        _row("revenue_growth_pct","매출 성장률 (%)",   fmt="pct"),
        _row("ebit",              "EBIT (억원)"),
        _row("opm_pct",           "EBIT Margin (%)",   fmt="pct"),
        _row("tax",               "법인세 (억원)"),
        _row("da",                "D&A (억원)"),
        _row("capex_net",         "CapEx (억원)"),
        _row("delta_nwc",         "ΔNWC (억원)"),
        _row("fcff",              "FCFF (억원)",        bold=True),
        _row("discount_factor",   "할인계수",           fmt="decimal3"),
        _row("pv",                "PV of FCFF (억원)",  bold=True),
    ]

    # DCF Summary
    pv_list  = fcff.get("pv", [])
    pv_fcff  = _b2uk(sum(v for v in pv_list[:5] if v is not None)) if pv_list else None
    ev_total = _b2uk(fcff.get("ev_total_billion") or dcf.get("ev_billion"))
    net_debt = _b2uk(dcf.get("net_debt_billion"))
    eq_uk    = _b2uk(eq_billion)

    pv_tv = (ev_total - pv_fcff) if (ev_total and pv_fcff) else None

    # 발행주식수 역산 (만주): equityValue(억원) / base_price(원) × 100
    base_price         = fair_prices.get("base")
    shares_manshares   = None
    if eq_billion and base_price and base_price > 0:
        shares_manshares = round(eq_billion * 1e9 / base_price / 10_000)

    dcf_summary = {
        "pvFCFF"          : pv_fcff,
        "pvTerminalValue" : pv_tv,
        "enterpriseValue" : ev_total,
        "netDebt"         : net_debt,
        "equityValue"     : eq_uk,
        "shares"          : shares_manshares,
    }

    # ── WACC ────────────────────────────────────────────────────────
    comp     = wacc_data.get("components", {})
    wacc_pct = comp.get("wacc_pct") or dcf.get("wacc_pct") or 0.0
    ke_pct   = comp.get("ke_pct",   0.0)
    kd_pct   = comp.get("kd_pct",   0.0)
    tax_rate = comp.get("tax_rate_pct", 22.0)

    wacc_obj = {
        "rf"       : comp.get("rf_pct"),
        "beta"     : round(comp.get("beta_levered_target", 0), 2),
        "erp"      : comp.get("erp_pct"),
        "ke"       : round(ke_pct, 2),
        "kd"       : round(kd_pct, 2),
        "tax"      : tax_rate,
        "eWeight"  : round(comp.get("weight_equity_pct", 0), 1),
        "dWeight"  : round(comp.get("weight_debt_pct",   0), 1),
        "wacc"     : round(wacc_pct, 2),
        "terminalG": dcf.get("g_terminal_pct", 2.0),
        "srp"      : comp.get("srp_pct"),
        "crp"      : comp.get("crp_pct"),
        "sources"  : wacc_data.get("sources", {}),
        "breakdown": wacc_data.get("peer_capital_structure", []),
    }

    # ── 멀티플 역산 ─────────────────────────────────────────────────
    mult_result = []
    for m in multiples.get("multiples", []):
        if not isinstance(m, dict):
            continue
        implied_amt = m.get("implied_per_share") or 0
        vs_current  = m.get("vs_current_pct")
        peer_median = m.get("peer_median")
        mult_result.append({
            "metric"    : m.get("metric", ""),
            "peerAvg"   : f"{peer_median:.1f}x" if peer_median is not None else "—",
            "implied"   : f"₩{int(implied_amt):,}" if implied_amt else "—",
            "impliedAmt": int(implied_amt) if implied_amt else 0,
            "current"   : m.get("target_value", "—"),
            "premium"   : f"{vs_current:+.1f}%" if isinstance(vs_current, (int, float)) else "—",
            "inRange"   : m.get("in_range", None),
        })

    # ── 민감도 매트릭스 ─────────────────────────────────────────────
    # 원본: rows=["WACC −1%p","WACC (Base)","WACC +1%p"], cols=["g=1.5%",...], values=[[...],...]
    sens      = uncertainty.get("sensitivity_matrix", {})
    row_lbl   = sens.get("rows", [])
    col_lbl   = sens.get("cols", [])
    matrix    = sens.get("values", [])
    s_wacc    = [_parse_wacc_label(l, wacc_pct) for l in row_lbl]
    s_g       = [_parse_g_label(l) for l in col_lbl]

    # ── 토네이도 ────────────────────────────────────────────────────
    tornado_result = []
    for t in uncertainty.get("tornado", []):
        if not isinstance(t, dict):
            continue
        tornado_result.append({
            "variable": t.get("variable", ""),
            "low"     : round(t.get("neg", 0)),
            "high"    : round(t.get("pos", 0)),
        })

    # ── 피어 비교 ───────────────────────────────────────────────────
    # peer_beta_result: peer_betas[{name, beta_adj, r_squared, ...}]
    # wacc_result: peer_capital_structure[{name, beta_l, de_pct, ...}]
    # 멀티플(evEbitda, pe, pb, roe)은 파일에 없어 "—" 처리
    peers_result = []
    for i, pb in enumerate(peer_beta.get("peer_betas", [])):
        if not isinstance(pb, dict):
            continue
        beta = pb.get("beta_adj")
        peers_result.append({
            "name"    : pb.get("name", ""),
            "ticker"  : "",
            "beta"    : round(beta, 2) if beta is not None else "—",
            "evEbitda": "—",
            "pe"      : "—",
            "pb"      : "—",
            "roe"     : "—",
            "r2"      : pb.get("r_squared"),
            "isSelf"  : i == 0,    # peer_betas[0] = 분석 대상 종목
        })

    return {
        "is_mock"            : False,
        "as_of_date"         : dcf.get("as_of_date", ""),
        "dcf_valid"          : dcf.get("dcf_valid", True),
        "dcf_invalid_reason" : dcf.get("dcf_invalid_reason"),
        "dcf_confidence"     : dcf.get("dcf_confidence", ""),
        "equityValueLabel"   : eq_won_label,
        "fairPrices"         : fair_prices,
        "upsides"            : upsides,
        "dcfYears"           : labels,
        "dcfRows"            : dcf_rows,
        "dcfSummary"         : dcf_summary,
        "wacc"               : wacc_obj,
        "multiples"          : mult_result,
        "sensitivityWacc"    : s_wacc,
        "sensitivityG"       : s_g,
        "sensitivityPrices"  : matrix,
        "tornado"            : tornado_result,
        "peers"              : peers_result,
        "_file"              : None,    # 엔드포인트에서 채움
    }


# ─── 엔드포인트 ──────────────────────────────────────────────────────────────

@router.get("/valuation/{stock_code}")
def get_valuation(stock_code: str):
    """
    밸류에이션 데이터 반환.

    - data/valuation_results/{code}_*/ 서브폴더 탐색
    - 6개 JSON 파일 로드 → Tab2 호환 포맷 변환 후 반환
    - 폴더 없으면 {"is_mock": true} 반환 → 프론트가 MOCK_VAL 사용

    파일 구조
    ---------
    data/valuation_results/
      090430_아모레퍼시픽/
        dcf_result.json
        fcff_result.json
        multiples_result.json
        peer_beta_result.json
        uncertainty_result.json
        wacc_result.json
    """
    folder = _find_subfolder(stock_code)

    # 폴더 없음 → Mock 신호
    if folder is None:
        return {
            "is_mock"   : True,
            "stock_code": stock_code,
            "_meta"     : {
                "message"     : "valuation_results 서브폴더 없음 — Mock 데이터 표시 중",
                "expected_dir": str(_RESULTS_DIR / f"{stock_code}_*"),
                "checked_at"  : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    # 6개 파일 로드
    dcf        = _load_json(folder, "dcf_result.json")
    fcff       = _load_json(folder, "fcff_result.json")
    wacc_data  = _load_json(folder, "wacc_result.json")
    multiples  = _load_json(folder, "multiples_result.json")
    peer_beta  = _load_json(folder, "peer_beta_result.json")
    uncertainty= _load_json(folder, "uncertainty_result.json")

    # 필수 파일 체크
    if not dcf or not fcff:
        raise HTTPException(
            status_code=500,
            detail=f"dcf_result.json 또는 fcff_result.json 없음 — {folder.name}",
        )

    # 변환
    try:
        result = _convert_multi(dcf, fcff, wacc_data, multiples, peer_beta, uncertainty)
    except Exception as e:
        return {
            "is_mock"    : False,
            "stock_code" : stock_code,
            "_warning"   : f"포맷 변환 실패 — 원본 반환: {e}",
            "_folder"    : folder.name,
            "dcf"        : dcf,
            "fcff"       : fcff,
        }

    result["stock_code"] = stock_code
    result["_file"]      = folder.name
    result["_meta"] = {
        "source"      : str(folder.relative_to(_ROOT)),
        "loaded_at"   : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files_found" : [f.name for f in folder.glob("*.json")],
    }
    return result
