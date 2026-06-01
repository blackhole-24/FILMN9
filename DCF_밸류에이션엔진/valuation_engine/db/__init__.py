"""DB 통합 접근 계층 — 'DB 우선 + 파일 폴백' 도메인 API.

다른 모듈은 이 패키지만 import 하면 됨:
    from valuation_engine import db
    fin = db.get_financials("009150", 2025)   # DB 우선, 없으면 None (호출자 파일 폴백)
    db.save_financials("009150", 2025, data)   # DB 적재(원본 파일은 별도 보존)

핵심 원칙:
  · financials 등은 원본 파일 형태({meta, financials})를 raw_json 으로 무손실 보관 →
    get_* 는 원본과 동일한 dict 를 돌려줘 기존 소비 코드가 그대로 동작.
  · 구조화 컬럼은 SQL 질의/프리워밍 검증용(중복 저장이지만 의도된 설계).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from . import mongo_json, store

# ─────────────────────────────────────────────────────────────
# financials (연간 XBRL) — 원본 {meta, financials} 무손실 왕복
# ─────────────────────────────────────────────────────────────
# financials['<한글키>'] → SQL 컬럼
_FIN_MAP = {
    "매출액": "revenue", "영업이익": "operating_income",
    "당기순이익": "net_income", "지배순이익": "net_income_parent",
    "da": "da", "ebitda": "ebitda", "nwc_cur": "nwc_cur", "nwc_pfy": "nwc_pfy",
    "delta_nwc": "delta_nwc", "capex": "capex", "ibd": "ibd", "noa": "noa",
    "한계세율": "marginal_tax_rate", "세율구간": "tax_bracket",
    "nopat": "nopat", "fcff": "fcff", "equity_total": "equity_total",
    "equity_parent": "equity_parent", "minority_interest": "minority_interest",
    "preferred_capital": "preferred_capital", "basic_eps": "basic_eps",
    "재무제표기준": "fs_basis",
}


def save_financials(ticker: str, year: int, data: dict) -> None:
    """{meta, financials} 형태를 financials 테이블에 적재(raw_json 무손실 포함)."""
    import json
    fin = data.get("financials", {}) or {}
    meta = data.get("meta", {}) or {}
    row: dict[str, Any] = {
        "stock_code": str(ticker).zfill(6),
        "fiscal_year": int(year),
        "corp_name": meta.get("corp_name"),
        "rcept_no": meta.get("rcept_no"),
        "rcept_dt": meta.get("rcept_dt"),
        "reprt_code": meta.get("reprt_code"),
        "unit": meta.get("단위"),
        "source": fin.get("balance_sheet_source") or meta.get("비고"),
        "raw_json": json.dumps(data, ensure_ascii=False),
    }
    for k_src, col in _FIN_MAP.items():
        if k_src in fin:
            row[col] = fin.get(k_src)
    # 상세 dict 는 JSON 컬럼
    if "ibd_detail" in fin:
        row["ibd_detail"] = fin.get("ibd_detail")
    if "noa_items" in fin:
        row["noa_items"] = fin.get("noa_items")
    store.upsert("financials", row)


def get_financials(ticker: str, year: int) -> Optional[dict]:
    """원본 {meta, financials} dict 반환 (DB). 없으면 None → 호출자 파일 폴백."""
    import json
    r = store.query_one(
        "SELECT raw_json FROM financials WHERE stock_code=? AND fiscal_year=?",
        (str(ticker).zfill(6), int(year)))
    if r and r.get("raw_json"):
        try:
            return json.loads(r["raw_json"])
        except Exception:
            return None
    return None


def save_ttm(ticker: str, ttm: dict, rcept_no: Optional[str] = None) -> None:
    """평가 중 산출된 TTM(최근 4분기 손익)을 ttm_financials 테이블에 영속화."""
    import json
    if not ttm or not ttm.get("as_of_period"):
        return
    sanity = ttm.get("sanity_yoy")
    prev_q = (sanity or {}).get("collected_prev_q_rev") if isinstance(sanity, dict) else None
    store.upsert("ttm_financials", {
        "stock_code":  str(ticker).zfill(6),
        "period":      ttm["as_of_period"],
        "revenue_ttm": ttm.get("ttm_revenue"),
        "ebit_ttm":    ttm.get("ttm_ebit"),
        "opm":         ttm.get("ttm_opm"),
        "prev_q_rev":  prev_q,
        "sanity_yoy":  sanity or {},
        "rcept_no":    rcept_no,
        "raw_json":    json.dumps(ttm, ensure_ascii=False),
    })


def get_ttm(ticker: str, period: Optional[str] = None) -> Optional[dict]:
    """저장된 TTM 조회 — period 미지정 시 최신."""
    tk = str(ticker).zfill(6)
    if period:
        return store.query_one(
            "SELECT * FROM ttm_financials WHERE stock_code=? AND period=?", (tk, period))
    return store.query_one(
        "SELECT * FROM ttm_financials WHERE stock_code=? ORDER BY period DESC LIMIT 1", (tk,))


def has_financials(ticker: str, year: int) -> bool:
    r = store.query_one(
        "SELECT 1 FROM financials WHERE stock_code=? AND fiscal_year=?",
        (str(ticker).zfill(6), int(year)))
    return r is not None


# ─────────────────────────────────────────────────────────────
# credit_ratings
# ─────────────────────────────────────────────────────────────
def save_credit_rating(ticker: str, year: int, *, bond_rating: Optional[str] = None,
                       cp_rating: Optional[str] = None, kd_applied: Optional[float] = None,
                       detail: Optional[dict] = None, source: str = "") -> None:
    store.upsert("credit_ratings", {
        "stock_code": str(ticker).zfill(6), "year": int(year),
        "bond_rating": bond_rating, "cp_rating": cp_rating,
        "kd_applied": kd_applied, "detail": detail or {}, "source": source})


def get_credit_rating(ticker: str, year: int) -> Optional[dict]:
    return store.query_one(
        "SELECT * FROM credit_ratings WHERE stock_code=? AND year=?",
        (str(ticker).zfill(6), int(year)))


# ─────────────────────────────────────────────────────────────
# rf_rates (ECOS), kofia_bond_yields (Kd 매핑표)
# ─────────────────────────────────────────────────────────────
def save_rf(rate_date: str, rf: float, source: str = "ECOS",
            detail: Optional[dict] = None) -> None:
    store.upsert("rf_rates", {"rate_date": rate_date, "rf": rf,
                              "source": source, "detail": detail or {}})


def get_rf(rate_date: str) -> Optional[dict]:
    return store.query_one("SELECT * FROM rf_rates WHERE rate_date=?", (rate_date,))


def save_kofia_yields(rows: list[dict]) -> int:
    """rows: [{yield_date, rating, maturity, yield_pct}, ...]"""
    return store.upsert_many("kofia_bond_yields", rows)


def get_kofia_yields(yield_date: str) -> list[dict]:
    return store.query("SELECT * FROM kofia_bond_yields WHERE yield_date=?", (yield_date,))


# ─────────────────────────────────────────────────────────────
# report_registry (DB 우선 — report_detector 가 사용)
# ─────────────────────────────────────────────────────────────
def save_registry_entry(ticker: str, period: str, rec: dict) -> None:
    store.upsert("report_registry", {
        "stock_code": str(ticker).zfill(6), "period": period,
        "corp_code": rec.get("corp_code"), "reprt_code": rec.get("reprt_code"),
        "kind": rec.get("kind"), "rcept_no": rec.get("rcept_no"),
        "rcept_dt": rec.get("rcept_dt"),
        "xbrl_done": rec.get("xbrl_done", False),
        "embed_done": rec.get("embed_done", False)})


def get_registry(ticker: str) -> dict:
    """report_detector.load_registry 호환 형태({ticker:{corp_code, reports:{period:{...}}}})."""
    rows = store.query("SELECT * FROM report_registry WHERE stock_code=?",
                       (str(ticker).zfill(6),))
    if not rows:
        return {}
    reports = {}
    corp_code = ""
    for r in rows:
        corp_code = r.get("corp_code") or corp_code
        reports[r["period"]] = {
            "rcept_no": r.get("rcept_no"), "reprt_code": r.get("reprt_code"),
            "kind": r.get("kind"), "rcept_dt": r.get("rcept_dt"),
            "xbrl_done": bool(r.get("xbrl_done")), "embed_done": bool(r.get("embed_done")),
            "updated_at": r.get("updated_at")}
    return {str(ticker).zfill(6): {"corp_code": corp_code, "reports": reports}}


# ─────────────────────────────────────────────────────────────
# companies (마스터)
# ─────────────────────────────────────────────────────────────
def save_company(ticker: str, **fields) -> None:
    row = {"stock_code": str(ticker).zfill(6)}
    row.update({k: v for k, v in fields.items() if v is not None})
    store.upsert("companies", row)


def get_company(ticker: str) -> Optional[dict]:
    return store.query_one("SELECT * FROM companies WHERE stock_code=?",
                           (str(ticker).zfill(6),))


# ─────────────────────────────────────────────────────────────
# shares (발행/자기/유통주식수 — 사업보고서 RAG 산출의 DB 미러)
# ─────────────────────────────────────────────────────────────
def save_shares(ticker: str, year: int, data: dict) -> None:
    """발행/자기/유통주식수 → shares 테이블 (파일 캐시의 DB 미러; SQL 질의·일관성용).

    원본은 data/rag_cache/shares_{ticker}_{year}.json 이 무손실 보관 →
    여기는 구조화 컬럼만 적재(financials 와 동일 'DB 우선 + 파일 폴백' 정책).
    값이 None 인 키는 적재 제외(부분 갱신 보존).
    """
    row = {"stock_code": str(ticker).zfill(6), "fiscal_year": int(year)}
    for k in ("common_issued", "common_treasury", "common_float",
              "corp_code", "rcept_no", "source", "source_quote", "confidence"):
        v = data.get(k)
        if v is not None:
            row[k] = v
    store.upsert("shares", row)


def get_shares(ticker: str, year: int) -> Optional[dict]:
    return store.query_one(
        "SELECT * FROM shares WHERE stock_code=? AND fiscal_year=?",
        (str(ticker).zfill(6), int(year)))


# ─────────────────────────────────────────────────────────────
# market_snapshot
# ─────────────────────────────────────────────────────────────
def save_market_snapshot(rows: list[dict]) -> int:
    return store.upsert_many("market_snapshot", rows)


# ─────────────────────────────────────────────────────────────
# 평가 산출물 (wacc/dcf/equity/diagnostics) + 통합 결과
# ─────────────────────────────────────────────────────────────
def _ed(eval_date) -> str:
    if isinstance(eval_date, date):
        return eval_date.isoformat()
    return str(eval_date)


def save_beta(eval_date, beta_result: dict) -> int:
    """run_beta 결과 → beta_results 테이블(피어·타깃별 행). 평가 시 자동저장용."""
    ed = _ed(eval_date)
    roles = {p.get("ticker"): p.get("role")
             for p in (beta_result.get("peers_input") or []) if isinstance(p, dict)}
    rows = []
    for name, pr in (beta_result.get("peers", {}) or {}).items():
        if not isinstance(pr, dict) or not pr.get("ticker"):
            continue
        rows.append({
            "stock_code":    str(pr["ticker"]).zfill(6), "eval_date": ed,
            "role":          roles.get(pr["ticker"]),
            "beta_raw":      pr.get("beta_raw"),
            "beta_adjusted": pr.get("beta_adjusted"),
            "r_squared":     pr.get("r_squared"),
            "n_obs":         pr.get("n_weeks_used"),
            "detail":        pr,
        })
    return store.upsert_many("beta_results", rows) if rows else 0


def save_wacc(ticker: str, eval_date, wacc: dict) -> None:
    store.upsert("wacc_results", {
        "stock_code": str(ticker).zfill(6), "eval_date": _ed(eval_date),
        "wacc": wacc.get("WACC") or wacc.get("wacc"),
        "ke": wacc.get("ke") or wacc.get("Ke"),
        "kd_pretax": wacc.get("kd_pretax") or wacc.get("Kd_pretax"),
        "kd_aftertax": wacc.get("kd_aftertax") or wacc.get("Kd_aftertax"),
        "rf": wacc.get("rf") or wacc.get("Rf"),
        "erp": wacc.get("erp") or wacc.get("ERP"),
        "beta_relevered": wacc.get("beta_relevered") or wacc.get("beta"),
        "weight_e": wacc.get("weight_e") or wacc.get("we"),
        "weight_d": wacc.get("weight_d") or wacc.get("wd"),
        "tax_rate": wacc.get("tax_rate"),
        "credit_rating": wacc.get("credit_rating"),
        "detail": wacc})


def save_dcf(ticker: str, eval_date, dcf: dict) -> None:
    # 키 매칭 — dcf_engine result는 EV/TV(대문자) 사용. 옛 키도 호환 폴백.
    store.upsert("dcf_results", {
        "stock_code": str(ticker).zfill(6), "eval_date": _ed(eval_date),
        "fair_price": dcf.get("fair_price") or dcf.get("fair_value_per_share"),
        "ev": dcf.get("EV") or dcf.get("enterprise_value") or dcf.get("ev"),
        "equity_value": dcf.get("equity_value"),
        "nopat_normalized": dcf.get("nopat_normalized"),
        "sgr": dcf.get("sgr"),
        "terminal_value": dcf.get("TV") or dcf.get("terminal_value"),
        # scenarios/sensitivity/tornado 는 dcf 가 아니라 uncertainty_engine 산출물 — dcf 안에 없음
        # detail에 전체 dcf 보존 → 후속 분석은 detail JSON path 사용
        "detail": dcf})


def save_equity(ticker: str, eval_date, eqv: dict) -> None:
    # market_cap = current_price × common_float (eqv 에는 직접 없으므로 산출)
    _cp = eqv.get("current_price") or 0
    _cf = eqv.get("common_float") or 0
    _mc = _cp * _cf if (_cp and _cf) else None
    store.upsert("equity_results", {
        "stock_code": str(ticker).zfill(6), "eval_date": _ed(eval_date),
        "market_cap": _mc,
        "common_float": _cf or None,
        "net_debt": eqv.get("net_debt"),
        "noa_clean": eqv.get("noa_clean"),
        "minority_interest": eqv.get("minority_interest"),
        "current_price": _cp or None,
        "detail": eqv})


def save_diagnostics(ticker: str, eval_date, dg: dict) -> None:
    store.upsert("diagnostics_results", {
        "stock_code": str(ticker).zfill(6), "eval_date": _ed(eval_date),
        "epv_price": dg.get("epv_price"), "epv_equity": dg.get("epv_equity"),
        "epv_operating": dg.get("epv_operating"),
        "growth_premium": dg.get("growth_premium"),
        "implied_growth": dg.get("implied_growth"),
        "expectations_gap": dg.get("expectations_gap"),
        "margin_of_safety": dg.get("margin_of_safety"),
        "headline": dg.get("headline"), "detail": dg})


def save_valuation_result(result: dict, result_path: str = "") -> str:
    """통합 평가 결과 → valuation_runs(인덱스) + diagnostics + Mongo 문서.

    Returns: run_id ("<ticker>_<eval_date>").
    """
    comp = result.get("company", {}) or {}
    ticker = str(comp.get("ticker") or "").zfill(6)
    eval_date = result.get("as_of_date") or _ed(date.today())
    run_id = f"{ticker}_{eval_date}"
    summary = result.get("summary", {}) or {}
    peers = result.get("peer_beta") or result.get("peers") or []
    try:
        peer_names = [p.get("회사") or p.get("name") for p in peers if isinstance(p, dict)]
    except Exception:
        peer_names = []

    # Mongo 문서 (텍스트 포함 전체 결과)
    doc = dict(result)
    doc["_id"] = run_id
    mongo_json.upsert_doc("valuation_results", doc)

    # 구조화 산출물
    dg = result.get("valuation_diagnostics")
    if isinstance(dg, dict):
        save_diagnostics(ticker, eval_date, dg)

    store.upsert("valuation_runs", {
        "run_id": run_id, "stock_code": ticker, "corp_name": comp.get("name"),
        "eval_date": eval_date,
        "fair_price": summary.get("fair_price"),
        "current_price": summary.get("current_price"),
        "upside_pct": summary.get("upside_pct"),
        "wacc": summary.get("wacc"),
        "peers": peer_names,
        "mongo_doc_id": run_id, "result_path": result_path,
        "created_at": store._now()})
    return run_id


def get_latest_result(ticker: str) -> Optional[dict]:
    """최신 통합 평가 결과(Mongo 문서) — DB 우선. 없으면 None → 호출자 파일 폴백.

    입력은 종목코드(009150) 또는 회사명(삼성전기) 모두 허용 — 회사명으로 조회해도
    캐시가 코드로 저장돼 있어 미스 나던 문제(전체 재평가로 빠짐)를 폴백으로 해소.
    """
    s = str(ticker).strip()
    tk = s.zfill(6) if s.isdigit() else s
    # 1) 종목코드 정확 일치
    r = store.query_one(
        "SELECT mongo_doc_id FROM valuation_runs WHERE stock_code=? "
        "ORDER BY eval_date DESC LIMIT 1", (tk,))
    # 2) 회사명 정확 일치 폴백 (사용자가 코드 대신 이름 입력)
    if not r:
        r = store.query_one(
            "SELECT mongo_doc_id FROM valuation_runs WHERE corp_name=? "
            "ORDER BY eval_date DESC LIMIT 1", (s,))
    if not r or not r.get("mongo_doc_id"):
        return None
    return mongo_json.get_doc("valuation_results", r["mongo_doc_id"])


def list_recent_runs(limit: int = 30) -> list[dict]:
    """최근 평가 목록 (ticker별 최신 1건)."""
    rows = store.query(
        "SELECT stock_code, corp_name, eval_date FROM valuation_runs "
        "GROUP BY stock_code HAVING eval_date = MAX(eval_date) "
        "ORDER BY eval_date DESC LIMIT ?", (limit,))
    return rows


# ─────────────────────────────────────────────────────────────
# 진단/검증
# ─────────────────────────────────────────────────────────────
def health() -> dict:
    return {"sqlite": store.table_counts(), "mongo": mongo_json.counts(),
            "db_path": str(store.DB_PATH)}
