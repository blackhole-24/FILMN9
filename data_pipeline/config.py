"""
파이프라인 설정 — 회계연도, 보고서 종류, 경로, 옵션.

⭐ 보고서 종류 / 회계연도 변경 시 이 파일만 수정.
   companies.py 의 COMPANIES 리스트와 함께, 팀원이 손대는 두 파일 중 하나입니다.
"""
from pathlib import Path


# ═════════════════════════════════════════════════════════════════════════════
# ① 대상 회계연도 (한 줄로 모드 전환)
# ═════════════════════════════════════════════════════════════════════════════
TARGET_FISCAL_YEAR = "2025"
#   "2024" → 2024 사업보고서 + 2025 분기·반기보고서 (테스트 — 둘 다 공시 완료)
#   "2025" → 2025 사업보고서 + 2026 분기·반기보고서 (운영 — Q1은 2026.05.15 이후)


# ═════════════════════════════════════════════════════════════════════════════
# ② 어떤 보고서를 수집할지 (필요한 것만 활성화)
# ═════════════════════════════════════════════════════════════════════════════
REPORT_TYPES = [
    "annual",     # 사업보고서   (회계연도 종료 +90일 / 3월말)  ← 2025년도 사업보고서
    # "Q1",       # 1분기보고서  (분기말 +45일 / 5월 중순)   ← 2026.05.15 이후 활성화
    # "H1",       # 반기보고서   (반기말 +45일 / 8월 중순)   ← 주석 풀면 활성화
    # "Q3",       # 3분기보고서  (분기말 +45일 / 11월 중순)
]


# ═════════════════════════════════════════════════════════════════════════════
# ③ 보고서 매칭 규칙 (자동, 보통 수정 불필요)
#    — DART list.json 응답의 report_nm 패턴
# ═════════════════════════════════════════════════════════════════════════════
REPORT_PATTERNS = {
    "annual": {"keyword": "사업보고서", "year_suffix": ".12", "fiscal_year_offset": 0},
    "Q1":     {"keyword": "분기보고서", "year_suffix": ".03", "fiscal_year_offset": 1},
    "H1":     {"keyword": "반기보고서", "year_suffix": ".06", "fiscal_year_offset": 1},
    "Q3":     {"keyword": "분기보고서", "year_suffix": ".09", "fiscal_year_offset": 1},
    # fiscal_year_offset:
    #   0 = TARGET_FISCAL_YEAR 와 같은 해 (사업보고서)
    #   1 = TARGET_FISCAL_YEAR + 1 의 분기/반기 (예: 2024 사업보고서 → 2025 Q1)
}


# ═════════════════════════════════════════════════════════════════════════════
# ④ 경로
# ═════════════════════════════════════════════════════════════════════════════
PROJECT_DIR = Path(__file__).parent
RAG_DIR     = Path(r"C:\Users\Admin\FILMN9\data\RAG")            # 임베딩용 JSONL 출력
RAW_DIR     = Path(r"C:\Users\Admin\FILMN9\data\raw")            # 원본·정제 XML 보관
LOG_DIR     = PROJECT_DIR / "outputs"


# ═════════════════════════════════════════════════════════════════════════════
# ⑤ 청킹 옵션
# ═════════════════════════════════════════════════════════════════════════════
CHAR_LIMIT           = 1500   # 청크당 최대 글자
OVERLAP              = 200    # 분할 시 오버랩
PROSE_CELL_THRESHOLD = 300    # 단일 셀 텍스트가 이보다 길면 prose-table 로 처리
PROSE_TABLE_TOTAL    = 600    # 1×1, 1×2 표 총 글자


# ═════════════════════════════════════════════════════════════════════════════
# ⑥ DART API 엔드포인트
# ═════════════════════════════════════════════════════════════════════════════
DART_BASE       = "https://opendart.fss.or.kr/api"
DART_LIST_URL   = f"{DART_BASE}/list.json"
DART_DOC_URL    = f"{DART_BASE}/document.xml"
DART_CORP_URL   = f"{DART_BASE}/corpCode.xml"

PUBLNTF_TY = "A"   # 정기공시 (사업/반기/분기 보고서)


# ═════════════════════════════════════════════════════════════════════════════
# ⑦ rate limit / 안정성
# ═════════════════════════════════════════════════════════════════════════════
RATE_LIMIT_SLEEP = 0.15        # 호출 사이 대기 (초)
HTTP_TIMEOUT     = 30          # 단일 호출 타임아웃 (초)
HTTP_RETRIES     = 3           # 재시도 횟수
LIST_PAGE_COUNT  = 50          # list.json 한 번에 받을 페이지 크기


# ─────────────────────────────────────────────────────────────────────────────
# 자동 파생 — TARGET_FISCAL_YEAR + REPORT_TYPES 에서 자동 계산
# 호출하는 쪽: pipeline.py / pipeline.ipynb / dart_downloader.py
# ─────────────────────────────────────────────────────────────────────────────
def get_search_window() -> tuple:
    """
    DART list.json 의 bgn_de / end_de.
    가장 빠른 보고서 (사업보고서 = TARGET_FISCAL_YEAR + 1 의 1월) ~
    가장 늦은 보고서 (3분기 = TARGET_FISCAL_YEAR + 1 의 12월) 를 모두 커버.
    """
    fy = int(TARGET_FISCAL_YEAR)
    return f"{fy + 1}0101", f"{fy + 1}1231"


def expected_report_label(report_type: str) -> str:
    """
    예시:
        TARGET_FISCAL_YEAR = "2024", report_type = "annual" → "2024.12"
        TARGET_FISCAL_YEAR = "2024", report_type = "Q1"     → "2025.03"
    """
    pat = REPORT_PATTERNS[report_type]
    fy = int(TARGET_FISCAL_YEAR) + pat["fiscal_year_offset"]
    return f"{fy}{pat['year_suffix']}"


def jsonl_filename(stock_code: str, name: str, report_type: str) -> str:
    """
    파일명 컨벤션:
        {stock_code}_{name}_{fiscal_year}_{report_type}_chunks.jsonl
    예: 064350_현대로템_2024_annual_chunks.jsonl
        064350_현대로템_2025_Q1_chunks.jsonl
    """
    pat = REPORT_PATTERNS[report_type]
    fy  = int(TARGET_FISCAL_YEAR) + pat["fiscal_year_offset"]
    return f"{stock_code}_{name}_{fy}_{report_type}_chunks.jsonl"


def report_kind_label(report_type: str) -> str:
    """메타데이터에 들어갈 라벨 (예: '2024-annual', '2025-Q1')."""
    pat = REPORT_PATTERNS[report_type]
    fy  = int(TARGET_FISCAL_YEAR) + pat["fiscal_year_offset"]
    return f"{fy}-{report_type}"


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"TARGET_FISCAL_YEAR : {TARGET_FISCAL_YEAR}")
    print(f"REPORT_TYPES       : {REPORT_TYPES}")
    print(f"검색 기간          : {get_search_window()}")
    print(f"\n각 보고서 매칭 라벨·파일명:")
    for rt in REPORT_TYPES:
        label = expected_report_label(rt)
        fn = jsonl_filename("064350", "현대로템", rt)
        print(f"  {rt:<8} → report_nm 매칭 '{label}'  →  {fn}")
    print(f"\n출력 폴더:")
    print(f"  RAG (JSONL): {RAG_DIR}")
    print(f"  raw (XML)  : {RAW_DIR}")
