"""
api/routers/company.py
======================
회사 기본정보 + 재무 + 통합조회 엔드포인트 (SQLite 백엔드)

엔드포인트
----------
GET /api/company/{stock_code}        company_info 테이블
GET /api/financials/{stock_code}     financials 테이블 (연도 desc)
GET /api/overview/{stock_code}       company_info + financials 통합 응답 (기본형)
"""
from fastapi import APIRouter, HTTPException
from pathlib import Path
import sqlite3
import json

router = APIRouter()
_ROOT    = Path(__file__).resolve().parent.parent.parent   # FILMN9/
_DB_PATH = _ROOT / "data" / "filmn9.db"


def _conn():
    """SQLite 연결 (행을 dict 형태로 반환)."""
    if not _DB_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail="filmn9.db 없음. db/init_db.py 실행 필요"
        )
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


@router.get("/company/{stock_code}")
def get_company(stock_code: str):
    """기업 기본정보. company_info 테이블에서 단일 행 조회."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM company_info WHERE stock_code = ?",
            (stock_code,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"{stock_code} 종목 없음")

    return dict(row)


@router.get("/financials/{stock_code}")
def get_financials(stock_code: str):
    """
    재무정보 3년치. financials 테이블에서 연도 내림차순 조회.

    응답: { stock_code, fiscal_years, revenue, op_income, ... }
          (기존 financials.json 형식과 호환되도록 dict-of-dicts 형태로 재구성)
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM financials WHERE stock_code = ? ORDER BY fiscal_year DESC",
            (stock_code,)
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"{stock_code} 재무 데이터 없음")

    # 연도별 dict-of-dicts 재구성 (기존 financials.json 호환 형식)
    years        = [str(r["fiscal_year"]) for r in rows]
    metric_keys  = ["revenue", "op_income", "net_income",
                    "assets", "liabilities", "equity", "debt_ratio",
                    "cashflow_op", "cashflow_inv", "cashflow_fin"]
    result = {
        "stock_code"   : stock_code,
        "fiscal_years" : years,
        "unit"         : rows[0]["unit"] or "백만원",
    }
    for k in metric_keys:
        result[k] = {str(r["fiscal_year"]): r[k] for r in rows}

    return result


# /api/overview/{stock_code} 는 api/routers/overview.py 에서 통합 처리
