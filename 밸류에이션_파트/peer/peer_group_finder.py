"""
peer_group_finder.py
====================
국내 상장기업명 또는 종목코드를 입력하면 유사기업(Peer Group) 리스트를 반환하는 스크립트.

[데이터 소스]
  - pykrx          : KRX 전종목 시가총액, 종목명 (네트워크 필요)
  - KRX 섹터 API   : WICS 업종분류 (네트워크 필요)
  - 내장 WICS 매핑  : 네트워크 없이도 동작하는 fallback

[실행 방법]
  pip install pykrx requests pandas
  python peer_group_finder.py              # 대화형 모드
  python peer_group_finder.py 005930       # 종목코드 직접 입력
  python peer_group_finder.py 삼성전자     # 종목명 직접 입력

[알고리즘 설계]
  Step 1. KRX에서 전종목 시총 + 종목명 수집
  Step 2. KRX WICS 섹터 분류 수집 (소섹터 레벨)
  Step 3. 입력 기업의 소섹터 식별
  Step 4. 동일 소섹터 기업 추출 → 1차 후보군
  Step 5. 시총 구간 필터 (±2 구간) → 2차 후보군
  Step 6. 유사도 스코어 계산 후 상위 N개 반환
      score = 소섹터_일치(0.5) + 시총_유사도(0.3) + 중섹터_일치_보너스(0.2)
"""

from __future__ import annotations

import sys
import math
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
import pandas as pd

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TOP_N        = 5          # 반환할 유사기업 수
MKTCAP_BANDS = 5          # 허용 시총 구간 차이 (양방향)
REQUEST_TIMEOUT = 15      # HTTP 타임아웃(초)


# ──────────────────────────────────────────────
# WICS 섹터 코드 내장 매핑 테이블 (Fallback용)
# 실제 KRX API 응답 구조와 동일한 포맷
# 출처: WICS(WiseFn Industry Classification Standard) 공개 분류 기준
# ──────────────────────────────────────────────
WICS_SECTOR_MAP: dict[str, dict] = {
    # 반도체 / IT
    "005930": {"name": "삼성전자",     "sector": "반도체와반도체장비", "mid": "기술하드웨어와장비"},
    "000660": {"name": "SK하이닉스",   "sector": "반도체와반도체장비", "mid": "기술하드웨어와장비"},
    "009150": {"name": "삼성전기",     "sector": "전자장비와기기",     "mid": "기술하드웨어와장비"},
    "009830": {"name": "한화솔루션",   "sector": "화학",              "mid": "소재"},
    "042700": {"name": "한미반도체",   "sector": "반도체와반도체장비", "mid": "기술하드웨어와장비"},
    "000990": {"name": "DB하이텍",     "sector": "반도체와반도체장비", "mid": "기술하드웨어와장비"},
    "066970": {"name": "LG이노텍",     "sector": "전자장비와기기",     "mid": "기술하드웨어와장비"},
    "066570": {"name": "LG전자",       "sector": "가전제품",          "mid": "기술하드웨어와장비"},
    "000100": {"name": "유한양행",     "sector": "제약",              "mid": "헬스케어"},
    "003550": {"name": "LG",           "sector": "복합기업",          "mid": "자본재"},
    "003490": {"name": "대한항공",     "sector": "항공사",            "mid": "운송"},
    "035720": {"name": "카카오",       "sector": "양방향미디어와서비스","mid": "커뮤니케이션서비스"},
    "035420": {"name": "NAVER",        "sector": "양방향미디어와서비스","mid": "커뮤니케이션서비스"},
    "036570": {"name": "엔씨소프트",   "sector": "게임엔터테인먼트",   "mid": "커뮤니케이션서비스"},
    "251270": {"name": "넷마블",       "sector": "게임엔터테인먼트",   "mid": "커뮤니케이션서비스"},
    "293490": {"name": "카카오게임즈", "sector": "게임엔터테인먼트",   "mid": "커뮤니케이션서비스"},
    "263750": {"name": "펄어비스",     "sector": "게임엔터테인먼트",   "mid": "커뮤니케이션서비스"},
    "112040": {"name": "위메이드",     "sector": "게임엔터테인먼트",   "mid": "커뮤니케이션서비스"},
    # 화장품
    "090430": {"name": "아모레퍼시픽", "sector": "화장품과개인용품",   "mid": "생활용품"},
    "051900": {"name": "LG생활건강",   "sector": "화장품과개인용품",   "mid": "생활용품"},
    "192820": {"name": "코스맥스",     "sector": "화장품과개인용품",   "mid": "생활용품"},
    "024720": {"name": "한국콜마",     "sector": "화장품과개인용품",   "mid": "생활용품"},
    "002790": {"name": "아모레G",      "sector": "화장품과개인용품",   "mid": "생활용품"},
    "078520": {"name": "에이블씨엔씨", "sector": "화장품과개인용품",   "mid": "생활용품"},
    "950130": {"name": "에이피알",     "sector": "화장품과개인용품",   "mid": "생활용품"},
    "388790": {"name": "달바글로벌",   "sector": "화장품과개인용품",   "mid": "생활용품"},
    "084110": {"name": "휴온스글로벌", "sector": "화장품과개인용품",   "mid": "생활용품"},
    # 건설
    "000720": {"name": "현대건설",     "sector": "건설과엔지니어링",   "mid": "자본재"},
    "047040": {"name": "대우건설",     "sector": "건설과엔지니어링",   "mid": "자본재"},
    "006360": {"name": "GS건설",       "sector": "건설과엔지니어링",   "mid": "자본재"},
    "028050": {"name": "삼성E&A",      "sector": "건설과엔지니어링",   "mid": "자본재"},
    "003070": {"name": "코오롱글로벌", "sector": "건설과엔지니어링",   "mid": "자본재"},
    "000210": {"name": "DL",           "sector": "건설과엔지니어링",   "mid": "자본재"},
    "007010": {"name": "DL이앤씨",     "sector": "건설과엔지니어링",   "mid": "자본재"},
    "012630": {"name": "HDC현대산업개발","sector":"건설과엔지니어링",  "mid": "자본재"},
    "010140": {"name": "삼성중공업",   "sector": "조선",              "mid": "자본재"},
    # 증권
    "006800": {"name": "미래에셋증권", "sector": "증권",              "mid": "금융"},
    "005940": {"name": "NH투자증권",   "sector": "증권",              "mid": "금융"},
    "071050": {"name": "한국금융지주", "sector": "증권",              "mid": "금융"},
    "016360": {"name": "삼성증권",     "sector": "증권",              "mid": "금융"},
    "039490": {"name": "키움증권",     "sector": "증권",              "mid": "금융"},
    "003460": {"name": "유화증권",     "sector": "증권",              "mid": "금융"},
    "001270": {"name": "부국증권",     "sector": "증권",              "mid": "금융"},
    "030210": {"name": "DB금융투자",   "sector": "증권",              "mid": "금융"},
    "001500": {"name": "현대차증권",   "sector": "증권",              "mid": "금융"},
    # 은행
    "105560": {"name": "KB금융",       "sector": "은행",              "mid": "금융"},
    "055550": {"name": "신한지주",     "sector": "은행",              "mid": "금융"},
    "086790": {"name": "하나금융지주", "sector": "은행",              "mid": "금융"},
    "316140": {"name": "우리금융지주", "sector": "은행",              "mid": "금융"},
    "024110": {"name": "기업은행",     "sector": "은행",              "mid": "금융"},
    # 자동차
    "005380": {"name": "현대차",       "sector": "자동차",            "mid": "경기관련소비재"},
    "000270": {"name": "기아",         "sector": "자동차",            "mid": "경기관련소비재"},
    "012330": {"name": "현대모비스",   "sector": "자동차부품",        "mid": "경기관련소비재"},
    "011210": {"name": "현대위아",     "sector": "자동차부품",        "mid": "경기관련소비재"},
    "018880": {"name": "한온시스템",   "sector": "자동차부품",        "mid": "경기관련소비재"},
    "007070": {"name": "GS리테일",     "sector": "음식료품소매",      "mid": "필수소비재"},
    # 철강/소재
    "005490": {"name": "POSCO홀딩스",  "sector": "철강",              "mid": "소재"},
    "004020": {"name": "현대제철",     "sector": "철강",              "mid": "소재"},
    "001080": {"name": "만호제강",     "sector": "철강",              "mid": "소재"},
    "010780": {"name": "아이에스동서", "sector": "건설과엔지니어링",   "mid": "자본재"},
    # 바이오/제약
    "207940": {"name": "삼성바이오로직스","sector":"바이오로직스",    "mid": "헬스케어"},
    "068270": {"name": "셀트리온",     "sector": "바이오로직스",      "mid": "헬스케어"},
    "128940": {"name": "한미약품",     "sector": "제약",              "mid": "헬스케어"},
    "000100": {"name": "유한양행",     "sector": "제약",              "mid": "헬스케어"},
    "185750": {"name": "종근당",       "sector": "제약",              "mid": "헬스케어"},
    "009290": {"name": "광동제약",     "sector": "제약",              "mid": "헬스케어"},
    "003030": {"name": "세아제강지주", "sector": "철강",              "mid": "소재"},
    # 에너지
    "010950": {"name": "S-Oil",        "sector": "석유와가스",        "mid": "에너지"},
    "096770": {"name": "SK이노베이션", "sector": "석유와가스",        "mid": "에너지"},
    "267250": {"name": "HD현대",       "sector": "복합기업",          "mid": "자본재"},
    # 통신
    "017670": {"name": "SK텔레콤",     "sector": "통신서비스",        "mid": "커뮤니케이션서비스"},
    "030200": {"name": "KT",           "sector": "통신서비스",        "mid": "커뮤니케이션서비스"},
    "032640": {"name": "LG유플러스",   "sector": "통신서비스",        "mid": "커뮤니케이션서비스"},
    # 유통/리테일
    "069960": {"name": "현대백화점",   "sector": "백화점",            "mid": "경기관련소비재"},
    "004170": {"name": "신세계",       "sector": "백화점",            "mid": "경기관련소비재"},
    "023530": {"name": "롯데쇼핑",     "sector": "백화점",            "mid": "경기관련소비재"},
    "139480": {"name": "이마트",       "sector": "음식료품소매",      "mid": "필수소비재"},
    # 식품
    "097950": {"name": "CJ제일제당",   "sector": "식품",              "mid": "필수소비재"},
    "004370": {"name": "농심",         "sector": "식품",              "mid": "필수소비재"},
    "005180": {"name": "빙그레",       "sector": "식품",              "mid": "필수소비재"},
    "271560": {"name": "오리온",       "sector": "식품",              "mid": "필수소비재"},
    "003230": {"name": "삼양식품",     "sector": "식품",              "mid": "필수소비재"},
    # 조선
    "009540": {"name": "HD한국조선해양","sector": "조선",             "mid": "자본재"},
    "042660": {"name": "한화오션",     "sector": "조선",              "mid": "자본재"},
    "010140": {"name": "삼성중공업",   "sector": "조선",              "mid": "자본재"},
    # 디스플레이
    "034220": {"name": "LG디스플레이", "sector": "디스플레이",        "mid": "기술하드웨어와장비"},
    "096770": {"name": "SK이노베이션", "sector": "석유와가스",        "mid": "에너지"},
}

# 종목명 → 종목코드 역매핑
NAME_TO_CODE: dict[str, str] = {v["name"]: k for k, v in WICS_SECTOR_MAP.items()}

# ──────────────────────────────────────────────
# 시가총액 근사값 내장 테이블 (2024~2025년 기준, 단위: 백만원)
# KRX 실시간 데이터가 없을 때 Fallback으로 사용
# 실시간 데이터가 있으면 이 값은 무시됨
# ──────────────────────────────────────────────
MKTCAP_APPROX: dict[str, float] = {
    # 반도체 / IT
    "005930": 350_000_000,   # 삼성전자  ~350조
    "000660": 130_000_000,   # SK하이닉스 ~130조
    "066570":  18_000_000,   # LG전자    ~18조
    "009150":   8_000_000,   # 삼성전기   ~8조
    "042700":  10_000_000,   # 한미반도체 ~10조
    "000990":   2_000_000,   # DB하이텍   ~2조
    "066970":   9_000_000,   # LG이노텍   ~9조
    "034220":   3_000_000,   # LG디스플레이 ~3조
    # 화장품
    "090430":   6_000_000,   # 아모레퍼시픽 ~6조
    "051900":   8_000_000,   # LG생활건강  ~8조
    "192820":   3_500_000,   # 코스맥스   ~3.5조
    "024720":   2_000_000,   # 한국콜마   ~2조
    "002790":   1_200_000,   # 아모레G    ~1.2조
    "950130":   2_000_000,   # 에이피알   ~2조
    "388790":     800_000,   # 달바글로벌  ~0.8조
    "084110":     300_000,   # 휴온스글로벌 ~0.3조
    "078520":     200_000,   # 에이블씨엔씨 ~0.2조
    # 건설
    "000720":   3_000_000,   # 현대건설   ~3조
    "047040":   2_000_000,   # 대우건설   ~2조
    "006360":   1_500_000,   # GS건설    ~1.5조
    "028050":   3_000_000,   # 삼성E&A   ~3조
    "003070":     500_000,   # 코오롱글로벌 ~0.5조
    "012630":   1_800_000,   # HDC현대산업개발 ~1.8조
    "007010":   1_200_000,   # DL이앤씨  ~1.2조
    "000210":   1_000_000,   # DL        ~1조
    "010780":     400_000,   # 아이에스동서 ~0.4조
    # 증권
    "006800":   4_500_000,   # 미래에셋증권 ~4.5조
    "005940":   3_500_000,   # NH투자증권 ~3.5조
    "071050":   4_000_000,   # 한국금융지주 ~4조
    "016360":   3_000_000,   # 삼성증권  ~3조
    "039490":   3_500_000,   # 키움증권  ~3.5조
    "001500":     400_000,   # 현대차증권 ~0.4조
    "030210":     300_000,   # DB금융투자 ~0.3조
    "001270":     100_000,   # 부국증권  ~0.1조
    "003460":      50_000,   # 유화증권  ~0.05조
    # 은행
    "105560":  25_000_000,   # KB금융    ~25조
    "055550":  22_000_000,   # 신한지주  ~22조
    "086790":  15_000_000,   # 하나금융지주 ~15조
    "316140":   8_000_000,   # 우리금융지주 ~8조
    "024110":   4_000_000,   # 기업은행  ~4조
    # 자동차
    "005380":  55_000_000,   # 현대차    ~55조
    "000270":  35_000_000,   # 기아      ~35조
    "012330":  25_000_000,   # 현대모비스 ~25조
    "011210":   2_500_000,   # 현대위아  ~2.5조
    "018880":   2_000_000,   # 한온시스템 ~2조
    # 통신
    "017670":  12_000_000,   # SK텔레콤  ~12조
    "030200":   8_000_000,   # KT        ~8조
    "032640":   4_000_000,   # LG유플러스 ~4조
    # IT 플랫폼
    "035420":  20_000_000,   # NAVER     ~20조
    "035720":  10_000_000,   # 카카오    ~10조
    "036570":   3_000_000,   # 엔씨소프트 ~3조
    "251270":   1_500_000,   # 넷마블    ~1.5조
    "293490":   1_200_000,   # 카카오게임즈 ~1.2조
    "263750":     800_000,   # 펄어비스  ~0.8조
    "112040":     300_000,   # 위메이드  ~0.3조
    # 바이오/제약
    "207940":  50_000_000,   # 삼성바이오로직스 ~50조
    "068270":  20_000_000,   # 셀트리온  ~20조
    "128940":   6_000_000,   # 한미약품  ~6조
    "185750":   2_000_000,   # 종근당    ~2조
    "000100":   3_000_000,   # 유한양행  ~3조
    # 조선
    "009540":  12_000_000,   # HD한국조선해양 ~12조
    "042660":   8_000_000,   # 한화오션  ~8조
    "010140":   4_000_000,   # 삼성중공업 ~4조
    # 소재/철강
    "005490":  30_000_000,   # POSCO홀딩스 ~30조
    "004020":   5_000_000,   # 현대제철  ~5조
    # 에너지
    "010950":   8_000_000,   # S-Oil     ~8조
    "096770":  15_000_000,   # SK이노베이션 ~15조
    # 유통
    "069960":   3_000_000,   # 현대백화점 ~3조
    "004170":   2_000_000,   # 신세계    ~2조
    "023530":   2_500_000,   # 롯데쇼핑  ~2.5조
    "139480":   2_000_000,   # 이마트    ~2조
    # 식품
    "097950":   4_000_000,   # CJ제일제당 ~4조
    "004370":   2_000_000,   # 농심      ~2조
    "271560":   3_000_000,   # 오리온    ~3조
    "003230":   4_000_000,   # 삼양식품  ~4조
}


# ──────────────────────────────────────────────
# 시가총액 구간 분류 (소/중/대형주 세분화)
# ──────────────────────────────────────────────
MKTCAP_TIERS = [
    (0,          50_000),       # Tier 0: 나노캡  (0 ~ 500억)
    (50_000,     300_000),      # Tier 1: 소형주  (500억 ~ 3천억)
    (300_000,    1_000_000),    # Tier 2: 중소형  (3천억 ~ 1조)
    (1_000_000,  5_000_000),    # Tier 3: 중형주  (1조 ~ 5조)
    (5_000_000,  20_000_000),   # Tier 4: 대형주  (5조 ~ 20조)
    (20_000_000, float("inf")), # Tier 5: 메가캡  (20조 이상)
]


def get_mktcap_tier(mktcap_million: float) -> int:
    """시총(백만원 단위)을 받아 Tier 인덱스 반환."""
    for i, (lo, hi) in enumerate(MKTCAP_TIERS):
        if lo <= mktcap_million < hi:
            return i
    return len(MKTCAP_TIERS) - 1


# ──────────────────────────────────────────────
# KRX 데이터 수집 레이어
# ──────────────────────────────────────────────

def _get_recent_trading_day(offset: int = 0) -> str:
    """최근 거래일 반환 (주말 보정). offset=1이면 하루 전."""
    d = datetime.today() - timedelta(days=offset)
    while d.weekday() >= 5:  # 토(5), 일(6) 제외
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def fetch_krx_market_cap(date: Optional[str] = None) -> pd.DataFrame:
    """
    KRX에서 전종목 시가총액 데이터를 가져옵니다.
    pykrx 라이브러리 사용. 실패 시 빈 DataFrame 반환.
    
    Returns:
        DataFrame: columns = [ticker, name, mktcap, market]
    """
    try:
        from pykrx import stock as krx_stock

        if date is None:
            date = _get_recent_trading_day()
        
        print(f"  [데이터 수집] KRX 시가총액 조회 중... (기준일: {date})")
        
        records = []
        for market in ("KOSPI", "KOSDAQ"):
            tickers = krx_stock.get_market_ticker_list(date=date, market=market)
            for ticker in tickers:
                try:
                    name = krx_stock.get_market_ticker_name(ticker)
                    df_cap = krx_stock.get_market_cap_by_ticker(date=date, market=market)
                    if ticker in df_cap.index:
                        mktcap = df_cap.loc[ticker, "시가총액"] / 1_000_000  # 원 → 백만원
                    else:
                        mktcap = 0
                    records.append({"ticker": ticker, "name": name,
                                    "mktcap": mktcap, "market": market})
                except Exception:
                    continue
        
        df = pd.DataFrame(records)
        print(f"  [데이터 수집] 완료: {len(df):,}개 종목")
        return df

    except ImportError:
        print("  [경고] pykrx 미설치. 'pip install pykrx' 후 재시도.")
        return pd.DataFrame(columns=["ticker", "name", "mktcap", "market"])
    except Exception as e:
        print(f"  [경고] KRX 시가총액 조회 실패: {e}")
        return pd.DataFrame(columns=["ticker", "name", "mktcap", "market"])


def fetch_krx_sector(date: Optional[str] = None) -> pd.DataFrame:
    """
    KRX에서 WICS 업종 분류 데이터를 가져옵니다.
    pykrx의 get_market_sector_classifications 사용.
    
    Returns:
        DataFrame: columns = [ticker, sector, mid_sector]
    """
    try:
        from pykrx import stock as krx_stock

        if date is None:
            date = _get_recent_trading_day()

        print(f"  [데이터 수집] KRX WICS 섹터 분류 조회 중...")

        records = []
        for market in ("KOSPI", "KOSDAQ"):
            try:
                df = krx_stock.get_market_sector_classifications(date=date, market=market)
                # 컬럼명: '티커', '기업명', '종가', '시가총액', '거래량', '등락률', '업종명'
                # 실제 컬럼은 pykrx 버전마다 다를 수 있으므로 유연하게 처리
                if df is None or df.empty:
                    continue
                df = df.reset_index()
                # 티커 컬럼 탐지
                ticker_col = next((c for c in df.columns if "티커" in c or "종목" in c), df.columns[0])
                sector_col = next((c for c in df.columns if "업종" in c or "섹터" in c or "Sector" in c), None)
                if sector_col is None:
                    continue
                for _, row in df.iterrows():
                    records.append({
                        "ticker": str(row[ticker_col]).zfill(6),
                        "sector": str(row[sector_col]),
                        "mid_sector": "",  # pykrx는 중섹터 미제공; 내장 테이블로 보완
                    })
            except Exception:
                continue

        if records:
            print(f"  [데이터 수집] 섹터 분류 완료: {len(records):,}개 종목")
            return pd.DataFrame(records)
        else:
            return pd.DataFrame(columns=["ticker", "sector", "mid_sector"])

    except ImportError:
        return pd.DataFrame(columns=["ticker", "sector", "mid_sector"])
    except Exception as e:
        print(f"  [경고] KRX 섹터 조회 실패: {e}")
        return pd.DataFrame(columns=["ticker", "sector", "mid_sector"])


# ──────────────────────────────────────────────
# 데이터 통합 + 캐시 레이어
# ──────────────────────────────────────────────

class CompanyUniverse:
    """
    전종목 데이터를 보관하고 조회 인터페이스를 제공하는 클래스.
    KRX 실시간 데이터 + 내장 WICS 매핑을 합산하여 사용.
    """

    def __init__(self):
        self._df: Optional[pd.DataFrame] = None

    def load(self, force_refresh: bool = False) -> "CompanyUniverse":
        """데이터 로드. 이미 로드된 경우 캐시 사용."""
        if self._df is not None and not force_refresh:
            return self

        print("\n[Universe] 전종목 데이터 로딩 중...")

        # 1) KRX 시총 데이터 수집
        df_cap  = fetch_krx_market_cap()
        df_sect = fetch_krx_sector()

        # 2) 내장 WICS 매핑 테이블을 기본 DataFrame으로 구성
        builtin_rows = []
        for ticker, info in WICS_SECTOR_MAP.items():
            builtin_rows.append({
                "ticker":      ticker,
                "name":        info["name"],
                "sector":      info["sector"],
                "mid_sector":  info["mid"],
                "mktcap":      MKTCAP_APPROX.get(ticker, 0.0),  # 내장 근사값
                "market":      "KRX",
                "source":      "builtin",
            })
        df_builtin = pd.DataFrame(builtin_rows)

        # 3) KRX 실시간 데이터가 있으면 병합, 없으면 내장 테이블로 fallback
        if not df_cap.empty:
            # 시총 데이터 병합
            df_merged = df_builtin.copy()
            cap_map = df_cap.set_index("ticker")["mktcap"].to_dict()
            df_merged["mktcap"] = df_merged["ticker"].map(cap_map).fillna(0.0)
            df_merged["source"] = "krx+builtin"

            # KRX에서 가져온 종목 중 내장 테이블에 없는 종목 추가
            existing_tickers = set(df_merged["ticker"])
            extra_rows = []
            for _, row in df_cap.iterrows():
                if row["ticker"] not in existing_tickers:
                    # 섹터 데이터 매핑 시도
                    sect_row = (
                        df_sect[df_sect["ticker"] == row["ticker"]].iloc[0]
                        if not df_sect.empty and row["ticker"] in df_sect["ticker"].values
                        else None
                    )
                    extra_rows.append({
                        "ticker":     row["ticker"],
                        "name":       row["name"],
                        "sector":     sect_row["sector"] if sect_row is not None else "기타",
                        "mid_sector": sect_row.get("mid_sector", "") if sect_row is not None else "",
                        "mktcap":     row["mktcap"],
                        "market":     row["market"],
                        "source":     "krx",
                    })
            if extra_rows:
                df_merged = pd.concat([df_merged, pd.DataFrame(extra_rows)], ignore_index=True)
        else:
            # fallback: 내장 테이블만 사용 (시총 근사값 포함)
            print("  [안내] KRX 실시간 데이터 없음 → 내장 테이블(섹터+시총 근사값) 사용.")
            df_merged = df_builtin.copy()

        # 4) 중복 ticker 제거 (source='krx+builtin' 우선)
        df_merged = (
            df_merged
            .sort_values("source", ascending=False)  # krx+builtin 우선
            .drop_duplicates(subset="ticker", keep="first")
            .reset_index(drop=True)
        )

        # 5) 시총 구간(tier) 계산
        df_merged["mktcap_tier"] = df_merged["mktcap"].apply(get_mktcap_tier)

        self._df = df_merged
        print(f"[Universe] 로딩 완료: {len(self._df):,}개 종목\n")
        return self

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self.load()
        return self._df

    def resolve_ticker(self, query: str) -> Optional[str]:
        """기업명 또는 종목코드 → 종목코드 반환."""
        query = query.strip()

        # 1) 숫자 6자리 → 종목코드로 직접 처리
        if query.isdigit():
            code = query.zfill(6)
            if code in self.df["ticker"].values:
                return code
            print(f"[오류] 종목코드 {code} 를 찾을 수 없습니다.")
            return None

        # 2) 종목명 완전 일치
        match = self.df[self.df["name"] == query]
        if not match.empty:
            return match.iloc[0]["ticker"]

        # 3) 종목명 부분 일치
        match = self.df[self.df["name"].str.contains(query, na=False)]
        if not match.empty:
            if len(match) == 1:
                return match.iloc[0]["ticker"]
            print(f"[안내] '{query}'에 해당하는 기업이 여러 개입니다:")
            for _, r in match.head(10).iterrows():
                print(f"  {r['ticker']}  {r['name']}")
            choice = input("종목코드를 입력하세요: ").strip()
            return choice.zfill(6) if choice.isdigit() else None

        print(f"[오류] '{query}' 기업을 찾을 수 없습니다.")
        return None

    def get_company(self, ticker: str) -> Optional[dict]:
        """종목코드로 기업 정보 딕셔너리 반환."""
        row = self.df[self.df["ticker"] == ticker]
        if row.empty:
            return None
        return row.iloc[0].to_dict()


# ──────────────────────────────────────────────
# 유사도 계산 엔진
# ──────────────────────────────────────────────

def _mktcap_similarity(tier_a: int, tier_b: int, max_diff: int = MKTCAP_BANDS) -> float:
    """
    시총 구간 차이를 0~1 점수로 변환.
    같은 구간=1.0, 1구간 차=0.8, 2구간 차=0.5, 이상=0 (필터링)
    """
    diff = abs(tier_a - tier_b)
    if diff == 0:
        return 1.0
    elif diff == 1:
        return 0.8
    elif diff == 2:
        return 0.5
    elif diff <= max_diff:
        return 0.2
    return 0.0


def compute_similarity(
    target: dict,
    candidate: dict,
    use_mktcap: bool = True,
) -> float:
    """
    두 기업 간 유사도 스코어(0~1) 계산.

    가중치:
      - 소섹터(sector) 일치:  0.55
      - 시총 구간 유사도:      0.30
      - 중섹터(mid) 일치 보너스: 0.15
    """
    score = 0.0

    # 소섹터 일치 (핵심 기준)
    if target["sector"] and candidate["sector"]:
        if target["sector"] == candidate["sector"]:
            score += 0.55
        elif target["mid_sector"] and target["mid_sector"] == candidate["mid_sector"]:
            # 중섹터만 같으면 절반 점수 (밸류체인 인접)
            score += 0.15

    # 중섹터 일치 보너스
    if target["mid_sector"] and candidate["mid_sector"]:
        if target["mid_sector"] == candidate["mid_sector"]:
            score += 0.15

    # 시총 유사도
    if use_mktcap and target["mktcap"] > 0 and candidate["mktcap"] > 0:
        sim = _mktcap_similarity(target["mktcap_tier"], candidate["mktcap_tier"])
        score += sim * 0.30
    else:
        # 시총 정보 없으면 섹터만으로 정규화
        score = score / 0.70 if score > 0 else 0.0

    return round(min(score, 1.0), 4)


# ──────────────────────────────────────────────
# 메인 유사기업 탐색 함수
# ──────────────────────────────────────────────

def find_peer_group(
    query: str,
    universe: CompanyUniverse,
    top_n: int = TOP_N,
    verbose: bool = True,
) -> list[dict]:
    """
    기업명 또는 종목코드를 입력받아 유사기업 리스트를 반환합니다.

    Args:
        query   : 기업명(예: '삼성전자') 또는 종목코드(예: '005930')
        universe: CompanyUniverse 인스턴스
        top_n   : 반환할 유사기업 수 (기본 5개)
        verbose : 중간 과정 출력 여부

    Returns:
        list of dict: [{ticker, name, sector, mktcap, score}, ...]
    """
    # 1. 종목코드 확정
    ticker = universe.resolve_ticker(query)
    if ticker is None:
        return []

    target = universe.get_company(ticker)
    if target is None:
        print(f"[오류] {ticker} 기업 정보를 찾을 수 없습니다.")
        return []

    if verbose:
        mktcap_str = (
            f"{target['mktcap']:,.0f}백만원"
            if target["mktcap"] > 0
            else "시총정보없음"
        )
        print(f"\n{'='*55}")
        print(f"  입력 기업  : {target['name']} ({ticker})")
        print(f"  소섹터     : {target['sector']}")
        print(f"  중섹터     : {target['mid_sector']}")
        print(f"  시가총액   : {mktcap_str}")
        print(f"  시총 Tier  : T{target['mktcap_tier']}")
        print(f"{'='*55}")

    # 2. 자기 자신 제외 + 유사도 계산
    use_mktcap = target["mktcap"] > 0

    candidates = []
    for _, row in universe.df.iterrows():
        if row["ticker"] == ticker:
            continue  # 자기 자신 제외

        # 소섹터가 전혀 없는 종목은 스킵
        if not row["sector"] or row["sector"] == "기타":
            continue

        score = compute_similarity(target, row.to_dict(), use_mktcap=use_mktcap)
        if score > 0:
            candidates.append({
                "ticker":     row["ticker"],
                "name":       row["name"],
                "sector":     row["sector"],
                "mid_sector": row["mid_sector"],
                "mktcap":     row["mktcap"],
                "mktcap_tier":row["mktcap_tier"],
                "score":      score,
            })

    # 3. 스코어 내림차순 정렬 → 상위 N개
    candidates.sort(key=lambda x: (-x["score"], -x["mktcap"]))
    result = candidates[:top_n]

    # 4. 출력
    if verbose:
        if not result:
            print("  유사기업을 찾을 수 없습니다.")
        else:
            print(f"\n  [유사기업 Top {top_n}]")
            print(f"  {'순위':<4}{'종목코드':<10}{'기업명':<18}{'소섹터':<22}{'시총(백만원)':<18}{'유사도'}")
            print(f"  {'-'*85}")
            for i, c in enumerate(result, 1):
                mktcap_str = f"{c['mktcap']:>14,.0f}" if c["mktcap"] > 0 else "       정보없음"
                print(
                    f"  {i:<4}{c['ticker']:<10}{c['name']:<18}"
                    f"{c['sector']:<22}{mktcap_str}   {c['score']:.4f}"
                )
            print()
            print(f"  Peer Group: {', '.join(c['name'] for c in result)}")
        print(f"{'='*55}\n")

    return result


# ──────────────────────────────────────────────
# CLI 엔트리포인트
# ──────────────────────────────────────────────

def main():
    universe = CompanyUniverse()
    universe.load()

    # 커맨드라인 인자가 있으면 바로 처리
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        find_peer_group(query, universe)
        return

    # 대화형 모드
    print("=" * 55)
    print("  유사기업(Peer Group) 탐색기")
    print("  기업명 또는 종목코드를 입력하세요. (종료: q)")
    print("=" * 55)

    while True:
        try:
            query = input("\n  검색: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  종료합니다.")
            break

        if not query:
            continue
        if query.lower() in ("q", "quit", "exit", "종료"):
            print("  종료합니다.")
            break

        find_peer_group(query, universe)


if __name__ == "__main__":
    main()
