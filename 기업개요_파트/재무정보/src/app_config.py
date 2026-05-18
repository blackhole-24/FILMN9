"""
FILMN9 앱 설정 — 주가·재무정보 탭
경로, API 키, 상수 등 앱 전역 설정.
"""
from pathlib import Path
import os

# ─────────────────────────────────────────────────────────────────────────────
# 경로
# ─────────────────────────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).parent.parent.parent.parent  # C:/Users/Admin/FILMN9
RAG_DIR    = ROOT_DIR / "data" / "RAG"             # 통합 JSONL 폴더 (2,596개)
CACHE_DIR  = ROOT_DIR / "outputs" / "cache"        # SQLite 캐시
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DB   = CACHE_DIR / "filmn9_cache.db"

# ─────────────────────────────────────────────────────────────────────────────
# .env 로드 (수동 파싱 — python-dotenv 없어도 동작)
# ─────────────────────────────────────────────────────────────────────────────
def _load_env(env_path: Path = ROOT_DIR / ".env") -> None:
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

_load_env()

# ─────────────────────────────────────────────────────────────────────────────
# DART API
# ─────────────────────────────────────────────────────────────────────────────
DART_API_KEY  = os.environ.get("DART_API_KEY", "")
DART_BASE_URL = "https://opendart.fss.or.kr/api"

# ─────────────────────────────────────────────────────────────────────────────
# 샘플 기업 (POC — 아모레퍼시픽)
# ─────────────────────────────────────────────────────────────────────────────
SAMPLE = {
    "stock_code" : "090430",
    "corp_code"  : "00583424",
    "name"       : "아모레퍼시픽",
    "ticker_yf"  : "090430.KS",          # yfinance 심볼
    "jsonl_file" : "090430_아모레퍼시픽_2025_annual_chunks.jsonl",
}

# ─────────────────────────────────────────────────────────────────────────────
# 주가 차트 기간 옵션
# ─────────────────────────────────────────────────────────────────────────────
CHART_PERIODS = {
    "최근30분": {"period": "1d",  "interval": "30m"},
    "최근1개월": {"period": "1mo", "interval": "1d"},
    "최근3개월": {"period": "3mo", "interval": "1d"},
    "최근1년":  {"period": "1y",  "interval": "1d"},
    "최근3년":  {"period": "3y",  "interval": "1wk"},
}

# ─────────────────────────────────────────────────────────────────────────────
# 한국식 주가 색상
# ─────────────────────────────────────────────────────────────────────────────
COLOR_UP   = "#EF4444"   # 상승 — 빨강
COLOR_DOWN = "#2563EB"   # 하락 — 파랑
COLOR_FLAT = "#6B7280"   # 보합 — 회색

# ─────────────────────────────────────────────────────────────────────────────
# JSONL 섹션 경로 키 (section_path_str 필터용)
# ─────────────────────────────────────────────────────────────────────────────
SECTION = {
    "요약재무정보"  : "III. 재무에 관한 사항 > 1. 요약재무정보",
    "연결재무제표"  : "III. 재무에 관한 사항 > 2. 연결재무제표",
    "별도재무제표"  : "III. 재무에 관한 사항 > 4. 재무제표",
    "주주정보"     : "VII. 주주에 관한 사항",
    "임원현황"     : "VIII. 임원 및 직원 등에 관한 사항 > 1. 임원 및 직원 등의 현황",
}

# ─────────────────────────────────────────────────────────────────────────────
# 캐시 TTL (초)
# ─────────────────────────────────────────────────────────────────────────────
CACHE_TTL = {
    "stock_realtime" : 60,       # 주가 실시간 — 1분
    "stock_history"  : 3600,     # 주가 히스토리 — 1시간
    "dart_company"   : 86400,    # 기업개요 — 1일
    "dart_major"     : 86400,    # 주주구성 — 1일
    "dart_list"      : 3600,     # 최근공시 — 1시간
    "naver_foreign"  : 3600,     # 외국인 보유비율 — 1시간
    "jsonl_parsed"   : 604800,   # JSONL 파싱 결과 — 7일
}

if __name__ == "__main__":
    print(f"RAG_DIR    : {RAG_DIR}")
    print(f"CACHE_DB   : {CACHE_DB}")
    print(f"DART_KEY   : {DART_API_KEY[:8]}...")
    print(f"샘플 기업  : {SAMPLE['name']} ({SAMPLE['stock_code']})")
    print(f"JSONL 파일 : {SAMPLE['jsonl_file']}")
    jsonl_path = RAG_DIR / SAMPLE["jsonl_file"]
    print(f"JSONL 존재 : {jsonl_path.exists()}")

