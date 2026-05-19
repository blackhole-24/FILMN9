"""
routers/company.py
회사 기본정보 + 재무 하이라이트 엔드포인트
"""
from fastapi import APIRouter, HTTPException
from pathlib import Path
import json

router = APIRouter()
_ROOT = Path(__file__).resolve().parent.parent.parent   # FILMN9/
_PARSED = _ROOT / "data" / "parsed"


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"파일 없음: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/company/{code}")
def get_company(code: str):
    """
    기업 기본정보 반환.
    데이터: data/parsed/{code}/company_info.json
    """
    return _read_json(_PARSED / code / "company_info.json")


@router.get("/financials/{code}")
def get_financials(code: str):
    """
    재무정보 반환 (매출·영업이익·순이익·부채비율·현금흐름).
    데이터: data/parsed/{code}/financials.json
    """
    return _read_json(_PARSED / code / "financials.json")


@router.get("/overview/{code}")
def get_overview(code: str):
    """
    기업정보 + 재무정보 합친 단일 응답 (화면 첫 로딩용).
    """
    company    = _read_json(_PARSED / code / "company_info.json")
    financials = _read_json(_PARSED / code / "financials.json")
    return {"company": company, "financials": financials}
