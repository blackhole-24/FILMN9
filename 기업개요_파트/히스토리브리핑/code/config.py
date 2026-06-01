"""자동화 파이프라인 공통 설정.

모든 환경변수 / 경로 / 옵션은 여기서 단일 관리.
다른 모듈은 이 모듈만 import 하면 됨.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ─── 프로젝트 경로 ───────────────────────────────────────────────────────────
AUTO_DIR     = Path(__file__).parent.parent.resolve()    # automation/
PROJECT_ROOT = AUTO_DIR.parent                            # 상위 (DART/)
CODE_DIR     = AUTO_DIR / "code"
PROMPTS_DIR  = AUTO_DIR / "prompts"
DOCS_DIR     = AUTO_DIR / "docs"
LOG_DIR      = AUTO_DIR / "logs"

# ─── .env 로드 ───────────────────────────────────────────────────────────────
# 1순위: automation/.env (self-contained)
# 2순위: 프로젝트 루트 .env (기존 키 재사용)
# (둘 다 있으면 automation/.env 가 우선 — override=True 효과)
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(AUTO_DIR / ".env", override=True)

# ─── 시크릿 / API 키 ─────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
DART_API_KEY   = os.getenv("DART_API_KEY",   "").strip()
MONGO_URI      = os.getenv("MONGO_URI",      "").strip()
MONGO_DB       = os.getenv("MONGO_DB",       "filmn9").strip()
MONGO_COLL     = os.getenv("MONGO_COLLECTION", "histories").strip()

# ─── 저장 모드 ───────────────────────────────────────────────────────────────
STORAGE_MODE = os.getenv("STORAGE_MODE", "local").strip().lower()
if STORAGE_MODE not in ("local", "s3"):
    raise ValueError(f"STORAGE_MODE 는 'local' 또는 's3' 만 가능: {STORAGE_MODE}")

# ─── 로컬 저장 경로 ──────────────────────────────────────────────────────────
_local_data_dir = os.getenv("LOCAL_DATA_DIR", "").strip()
LOCAL_DATA_DIR = Path(_local_data_dir) if _local_data_dir else (AUTO_DIR / "data")

LOCAL_RAG_DIR     = LOCAL_DATA_DIR / "rag"        # JSONL 청크
LOCAL_RAW_DIR     = LOCAL_DATA_DIR / "raw"        # 원본 XML
LOCAL_BRIEFS_DIR  = LOCAL_DATA_DIR / "briefs"     # 최종 브리핑
LOCAL_EVAL_DIR    = LOCAL_DATA_DIR / "eval"       # 평가 결과
LOCAL_BRIEFS_1PASS_DIR = LOCAL_DATA_DIR / "briefs_1pass"
LOCAL_BRIEFS_2PASS_DIR = LOCAL_DATA_DIR / "briefs_2pass"
LOCAL_EVAL_1PASS_DIR   = LOCAL_DATA_DIR / "eval_1pass"
LOCAL_EVAL_2PASS_DIR   = LOCAL_DATA_DIR / "eval_2pass"

# ─── LLM 설정 ────────────────────────────────────────────────────────────────
LLM_MODEL_1PASS   = os.getenv("LLM_MODEL_1PASS", "gpt-5-mini").strip()
LLM_MODEL_2PASS   = os.getenv("LLM_MODEL_2PASS", "gpt-5.4-mini").strip()
LOW_SCORE_THRESHOLD = int(os.getenv("LOW_SCORE_THRESHOLD", "70"))

# ─── 실행 옵션 ───────────────────────────────────────────────────────────────
AUTO_CLEANUP = os.getenv("AUTO_CLEANUP", "false").strip().lower() == "true"

# ─── DART API 엔드포인트 ─────────────────────────────────────────────────────
DART_BASE       = "https://opendart.fss.or.kr/api"
DART_LIST_URL   = f"{DART_BASE}/list.json"
DART_DOC_URL    = f"{DART_BASE}/document.xml"
DART_CORP_URL   = f"{DART_BASE}/corpCode.xml"

PUBLNTF_TY = "A"   # 정기공시 (사업/반기/분기 보고서)

# ─── DART 수집 옵션 ──────────────────────────────────────────────────────────
RATE_LIMIT_SLEEP = 0.15        # 호출 사이 대기 (초)
HTTP_TIMEOUT     = 30          # 단일 호출 타임아웃 (초)
HTTP_RETRIES     = 3           # 재시도 횟수
LIST_PAGE_COUNT  = 50          # list.json 한 번에 받을 페이지 크기

# ─── 보고서 종류 + 매칭 규칙 ─────────────────────────────────────────────────
REPORT_TYPES = ["annual"]      # 사업보고서만 (분기/반기 필요 시 추가)

REPORT_PATTERNS = {
    "annual": {"keyword": "사업보고서", "year_suffix": ".12", "fiscal_year_offset": 0},
    "Q1":     {"keyword": "분기보고서", "year_suffix": ".03", "fiscal_year_offset": 1},
    "H1":     {"keyword": "반기보고서", "year_suffix": ".06", "fiscal_year_offset": 1},
    "Q3":     {"keyword": "분기보고서", "year_suffix": ".09", "fiscal_year_offset": 1},
}

# ─── 청킹 옵션 ───────────────────────────────────────────────────────────────
CHAR_LIMIT           = 1500
OVERLAP              = 200
PROSE_CELL_THRESHOLD = 300
PROSE_TABLE_TOTAL    = 600

# ─── 기존 코드 호환 alias ────────────────────────────────────────────────────
# data_pipeline 에서 옮겨온 코드가 cfg.RAW_DIR / cfg.RAG_DIR / cfg.LOG_DIR 로 참조
RAW_DIR = LOCAL_RAW_DIR
RAG_DIR = LOCAL_RAG_DIR

# ─── 회계연도 (런타임 결정) ──────────────────────────────────────────────────
# 자동: 현재 연도 - 1
# 명시: TARGET_FISCAL_YEAR 환경변수
_env_year = os.getenv("TARGET_FISCAL_YEAR", "").strip()
if _env_year:
    TARGET_FISCAL_YEAR = _env_year
else:
    TARGET_FISCAL_YEAR = str(datetime.now().year - 1)


def get_search_window() -> tuple[str, str]:
    """DART list.json 의 bgn_de / end_de.

    회계연도 다음 해의 1월~12월 범위 (사업보고서/분기/반기 모두 포함).
    """
    fy = int(TARGET_FISCAL_YEAR)
    return f"{fy + 1}0101", f"{fy + 1}1231"


def expected_report_label(report_type: str) -> str:
    """예: TARGET=2024, type=annual → '2024.12'"""
    pat = REPORT_PATTERNS[report_type]
    fy = int(TARGET_FISCAL_YEAR) + pat["fiscal_year_offset"]
    return f"{fy}{pat['year_suffix']}"


def jsonl_filename(stock_code: str, name: str, report_type: str) -> str:
    """파일명: {stock_code}_{name}_{year}_{type}_chunks.jsonl"""
    pat = REPORT_PATTERNS[report_type]
    fy  = int(TARGET_FISCAL_YEAR) + pat["fiscal_year_offset"]
    return f"{stock_code}_{name}_{fy}_{report_type}_chunks.jsonl"


def report_kind_label(report_type: str) -> str:
    """라벨: '2024-annual', '2025-Q1' 등"""
    pat = REPORT_PATTERNS[report_type]
    fy  = int(TARGET_FISCAL_YEAR) + pat["fiscal_year_offset"]
    return f"{fy}-{report_type}"


def get_briefs_dir(pass_num: int = 0) -> Path:
    """브리핑 저장 디렉토리 반환.

    pass_num: 0 = 최종(best-of-two), 1 = 1pass, 2 = 2pass
    """
    if pass_num == 1:
        return LOCAL_BRIEFS_1PASS_DIR
    if pass_num == 2:
        return LOCAL_BRIEFS_2PASS_DIR
    return LOCAL_BRIEFS_DIR


def get_eval_dir(pass_num: int = 1) -> Path:
    """평가 결과 저장 디렉토리 반환."""
    if pass_num == 2:
        return LOCAL_EVAL_2PASS_DIR
    return LOCAL_EVAL_1PASS_DIR


# ─── 디렉토리 자동 생성 ─────────────────────────────────────────────────────
def ensure_dirs():
    """필요한 디렉토리들 자동 생성."""
    for d in [
        LOCAL_DATA_DIR, LOCAL_RAG_DIR, LOCAL_RAW_DIR, LOCAL_BRIEFS_DIR,
        LOCAL_EVAL_DIR, LOCAL_BRIEFS_1PASS_DIR, LOCAL_BRIEFS_2PASS_DIR,
        LOCAL_EVAL_1PASS_DIR, LOCAL_EVAL_2PASS_DIR, LOG_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


# ─── 검증 ───────────────────────────────────────────────────────────────────
def validate() -> list[str]:
    """필수 환경변수 검증. 누락된 항목 리스트 반환."""
    errors = []
    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY 미설정")
    if not DART_API_KEY:
        errors.append("DART_API_KEY 미설정")
    if not MONGO_URI:
        errors.append("MONGO_URI 미설정")
    if STORAGE_MODE == "s3":
        errors.append("STORAGE_MODE='s3' 는 현재 미구현 (To-be). 'local' 사용 권장.")
    return errors


# ─── CLI: 현재 설정 확인 ────────────────────────────────────────────────────
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("FILMN9 자동화 파이프라인 설정")
    print("=" * 60)
    print(f"AUTO_DIR            : {AUTO_DIR}")
    print(f"STORAGE_MODE        : {STORAGE_MODE}")
    print(f"LOCAL_DATA_DIR      : {LOCAL_DATA_DIR}")
    print(f"TARGET_FISCAL_YEAR  : {TARGET_FISCAL_YEAR}")
    print(f"검색 기간            : {get_search_window()}")
    print(f"LLM_MODEL_1PASS     : {LLM_MODEL_1PASS}")
    print(f"LLM_MODEL_2PASS     : {LLM_MODEL_2PASS}")
    print(f"LOW_SCORE_THRESHOLD : {LOW_SCORE_THRESHOLD}")
    print(f"AUTO_CLEANUP        : {AUTO_CLEANUP}")
    print()
    print("환경변수 검증:")
    errors = validate()
    if errors:
        for e in errors:
            print(f"  [WARN] {e}")
    else:
        print("  [OK] 모든 필수 항목 정상")
