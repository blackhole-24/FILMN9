"""피어 산정용 WICS 섹터 매핑 데이터 — 외부 peer_group_finder_v7 wrapper.

설계:
  - peer_group_finder_v7.py (VAR 루트) 의 WICS 데이터를 import
  - 외부 파일 없을 시 fallback (현재 운영 종목만 커버)
  - peer_selector.py 가 본 모듈에서만 데이터 가져옴 (응집도 유지)

WICS 데이터 구조:
  WICS_SECTOR_MAP:        ticker → {name, sector(소섹터), mid(중섹터)}
  BIZ_TAG:                ticker → biz_tag (사업모델 태그)
  _CROSS_SECTOR_WHITELIST: frozenset(소섹터A, 소섹터B) 의 set — 인접 허용
  MONOPOLY_SET:           독점·초대형 회사 ticker set (필터 완화 대상)

갱신:
  - peer_group_finder_v7.py 한 곳만 갱신하면 본 모듈 자동 반영
  - 외부 파일 미존재 시 fallback 데이터 (소규모) 사용
"""
from __future__ import annotations

import sys
from pathlib import Path

# VAR 루트 sys.path 추가
_VAR_ROOT = Path(__file__).resolve().parent.parent
if str(_VAR_ROOT) not in sys.path:
    sys.path.insert(0, str(_VAR_ROOT))


# ─────────────────────────────────────────────────────────────
# Supplementary — 운영 표본 (peer_group_finder_v7 누락 보완)
#   설계: primary 와 항상 merge. primary 에 ticker 있으면 primary 우선.
# ─────────────────────────────────────────────────────────────
# 명명 규칙 — peer_group_finder_v7 과 100% 일치 필요 (mid 매칭 깨짐 방지):
#   증권:       sector="증권",          mid="금융"
#   소프트웨어: sector="IT서비스",      mid="IT"
#   식품:       sector="식품",          mid="필수소비재"
#   제약:       sector="제약",          mid="헬스케어"
#   건설:       sector="건설과엔지니어링", mid="자본재"
_SUPPLEMENTARY_WICS: dict[str, dict] = {
    # ── 운영 표본 누락 보완 (peer_group_finder_v7 부재 ticker만) ──
    # 소프트웨어 — 더존비즈온 (primary 누락)
    "012510": {"name": "더존비즈온",     "sector": "IT서비스",         "mid": "IT"},
    # 증권 — 유진투자증권 (primary 누락)
    "001200": {"name": "유진투자증권",   "sector": "증권",             "mid": "금융"},

    # ── primary 에 누락 가능한 건설 피어 (안전망) ──
    "000720": {"name": "현대건설",       "sector": "건설과엔지니어링", "mid": "자본재"},
    "047040": {"name": "대우건설",       "sector": "건설과엔지니어링", "mid": "자본재"},
    "006360": {"name": "GS건설",         "sector": "건설과엔지니어링", "mid": "자본재"},
    "003070": {"name": "코오롱글로벌",   "sector": "건설과엔지니어링", "mid": "자본재"},
    "028050": {"name": "삼성E&A",        "sector": "건설과엔지니어링", "mid": "자본재"},
    "000210": {"name": "DL",             "sector": "건설과엔지니어링", "mid": "자본재"},
}


# ─────────────────────────────────────────────────────────────
# Primary import + Supplementary merge
# ─────────────────────────────────────────────────────────────
try:
    from peer_group_finder_v7 import (
        WICS_SECTOR_MAP as _PRIMARY_WICS,
        BIZ_TAG,
        _CROSS_SECTOR_WHITELIST,
        MONOPOLY_SET,
    )
    # primary 우선, supplementary 는 누락 ticker 만 보완
    WICS_SECTOR_MAP: dict[str, dict] = dict(_PRIMARY_WICS)  # copy
    _added_from_supp = 0
    for _tic, _info in _SUPPLEMENTARY_WICS.items():
        if _tic not in WICS_SECTOR_MAP:
            WICS_SECTOR_MAP[_tic] = _info
            _added_from_supp += 1
    DATA_SOURCE = (
        f"peer_group_finder_v7.py ({len(_PRIMARY_WICS)}) "
        f"+ supplementary ({_added_from_supp}건 보완)"
    )
except ImportError:
    # peer_group_finder_v7 미발견 시 supplementary 만 사용
    WICS_SECTOR_MAP = dict(_SUPPLEMENTARY_WICS)
    BIZ_TAG: dict[str, str] = {}
    _CROSS_SECTOR_WHITELIST: set[frozenset] = set()
    MONOPOLY_SET: set[str] = set()
    DATA_SOURCE = f"supplementary only ({len(WICS_SECTOR_MAP)}건) — peer_group_finder_v7 미발견"


# ─────────────────────────────────────────────────────────────
# KRX 업종명 → WICS 소·중섹터 자동 매핑 (팀원 fullkrx_A 차용)
#   설계: WICS_SECTOR_MAP 미등록 ticker 도 KRX 업종 기반 자동 매핑
#   효과: 전종목 (KOSPI + KOSDAQ ~2000개) 자동 매핑 가능
# ─────────────────────────────────────────────────────────────
KRX_TO_WICS: dict[str, tuple[str, str]] = {
    # 반도체 / 전자부품
    "반도체 제조업":                                  ("반도체와반도체장비",   "기술하드웨어와장비"),
    "전자부품 제조업":                                 ("전자장비와기기",       "기술하드웨어와장비"),
    "통신 및 방송 장비 제조업":                        ("전자장비와기기",       "기술하드웨어와장비"),
    "컴퓨터 및 주변장치 제조업":                       ("전자장비와기기",       "기술하드웨어와장비"),
    "측정, 시험, 항해, 제어 및 기타 정밀기기 제조업; 광학기기 제외": ("전자장비와기기", "기술하드웨어와장비"),
    "사진장비 및 광학기기 제조업":                     ("전자장비와기기",       "기술하드웨어와장비"),
    "영상 및 음향기기 제조업":                         ("가전제품",             "기술하드웨어와장비"),
    "가정용 기기 제조업":                              ("가전제품",             "기술하드웨어와장비"),
    "전구 및 조명장치 제조업":                         ("전자장비와기기",       "기술하드웨어와장비"),
    "마그네틱 및 광학 매체 제조업":                    ("전자장비와기기",       "기술하드웨어와장비"),
    "기록매체 복제업":                                 ("전자장비와기기",       "기술하드웨어와장비"),
    # 배터리 / 전기장비
    "일차전지 및 이차전지 제조업":                     ("전기장비",             "자본재"),
    "전동기, 발전기 및 전기 변환 · 공급 · 제어 장치 제조업": ("전기장비", "자본재"),
    "기타 전기장비 제조업":                            ("전기장비",             "자본재"),
    "절연선 및 케이블 제조업":                         ("전기장비",             "자본재"),
    "전기 및 통신 공사업":                             ("전기장비",             "자본재"),
    # 소프트웨어 / IT서비스
    "소프트웨어 개발 및 공급업":                       ("IT서비스",             "IT"),
    "컴퓨터 프로그래밍, 시스템 통합 및 관리업":        ("IT서비스",             "IT"),
    "자료처리, 호스팅, 포털 및 기타 인터넷 정보매개 서비스업": ("양방향미디어와서비스", "커뮤니케이션서비스"),
    "기타 정보 서비스업":                              ("IT서비스",             "IT"),
    "기타 과학기술 서비스업":                          ("IT서비스",             "IT"),
    "그외 기타 전문, 과학 및 기술 서비스업":           ("IT서비스",             "IT"),
    "전문디자인업":                                    ("IT서비스",             "IT"),
    "시장조사 및 여론조사업":                          ("IT서비스",             "IT"),
    # 통신
    "전기 통신업":                                     ("통신서비스",           "커뮤니케이션서비스"),
    # 미디어 / 엔터 / 게임
    "영화, 비디오물, 방송프로그램 제작 및 배급업":     ("미디어와엔터테인먼트", "커뮤니케이션서비스"),
    "텔레비전 방송업":                                 ("미디어와엔터테인먼트", "커뮤니케이션서비스"),
    "영상·오디오물 제공 서비스업":                     ("미디어와엔터테인먼트", "커뮤니케이션서비스"),
    "오디오물 출판 및 원판 녹음업":                    ("미디어와엔터테인먼트", "커뮤니케이션서비스"),
    "서적, 잡지 및 기타 인쇄물 출판업":                ("미디어와엔터테인먼트", "커뮤니케이션서비스"),
    "창작 및 예술관련 서비스업":                       ("미디어와엔터테인먼트", "커뮤니케이션서비스"),
    "광고업":                                          ("광고",                 "커뮤니케이션서비스"),
    # 자동차
    "자동차용 엔진 및 자동차 제조업":                  ("자동차",               "경기관련소비재"),
    "자동차 신품 부품 제조업":                         ("자동차부품",           "경기관련소비재"),
    "자동차 부품 및 내장품 판매업":                    ("자동차부품",           "경기관련소비재"),
    "자동차 차체나 트레일러 제조업":                   ("자동차부품",           "경기관련소비재"),
    "자동차 재제조 부품 제조업":                       ("자동차부품",           "경기관련소비재"),
    "자동차 판매업":                                   ("자동차부품",           "경기관련소비재"),
    # 화학 / 소재
    "기초 화학물질 제조업":                            ("화학",                 "소재"),
    "기타 화학제품 제조업":                            ("화학",                 "소재"),
    "합성고무 및 플라스틱 물질 제조업":                ("화학",                 "소재"),
    "비료, 농약 및 살균, 살충제 제조업":               ("화학",                 "소재"),
    "화학섬유 제조업":                                 ("화학",                 "소재"),
    "플라스틱제품 제조업":                             ("화학",                 "소재"),
    "고무제품 제조업":                                 ("화학",                 "소재"),
    "유리 및 유리제품 제조업":                         ("건설자재",             "소재"),
    "시멘트, 석회, 플라스터 및 그 제품 제조업":        ("건설자재",             "소재"),
    "내화, 비내화 요업제품 제조업":                    ("건설자재",             "소재"),
    "기타 비금속 광물제품 제조업":                     ("건설자재",             "소재"),
    "기타 종이 및 판지 제품 제조업":                   ("화학",                 "소재"),
    "펄프, 종이 및 판지 제조업":                       ("화학",                 "소재"),
    "골판지, 종이 상자 및 종이용기 제조업":            ("화학",                 "소재"),
    # 철강 / 비철금속
    "1차 철강 제조업":                                 ("철강",                 "소재"),
    "구조용 금속제품, 탱크 및 증기발생기 제조업":      ("철강",                 "소재"),
    "기타 금속 가공제품 제조업":                       ("철강",                 "소재"),
    "금속 주조업":                                     ("철강",                 "소재"),
    "1차 비철금속 제조업":                             ("비철금속",             "소재"),
    # 건설 / 엔지니어링
    "건물 건설업":                                     ("건설과엔지니어링",     "자본재"),
    "토목 건설업":                                     ("건설과엔지니어링",     "자본재"),
    "실내건축 및 건축마무리 공사업":                   ("건설과엔지니어링",     "자본재"),
    "기반조성 및 시설물 축조관련 전문공사업":          ("건설과엔지니어링",     "자본재"),
    "건물설비 설치 공사업":                            ("건설과엔지니어링",     "자본재"),
    "건축기술, 엔지니어링 및 관련 기술 서비스업":      ("건설과엔지니어링",     "자본재"),
    # 기계 / 장비
    "특수 목적용 기계 제조업":                         ("기계",                 "자본재"),
    "일반 목적용 기계 제조업":                         ("기계",                 "자본재"),
    "산업용 기계 및 장비 임대업":                      ("기계",                 "자본재"),
    "기계장비 및 관련 물품 도매업":                    ("기계",                 "자본재"),
    "그외 기타 운송장비 제조업":                       ("기계",                 "자본재"),
    # 조선·항공우주
    "선박 및 보트 건조업":                             ("조선",                 "자본재"),
    "항공기,우주선 및 부품 제조업":                    ("항공기방위산업",       "자본재"),
    "무기 및 총포탄 제조업":                           ("항공기방위산업",       "자본재"),
    # 지주 / 복합
    "회사 본부 및 경영 컨설팅 서비스업":               ("복합기업",             "자본재"),
    "기타 사업지원 서비스업":                          ("전문서비스",           "자본재"),
    "경비, 경호 및 탐정업":                            ("전문서비스",           "자본재"),
    "사업시설 유지·관리 서비스업":                     ("전문서비스",           "자본재"),
    # 에너지·유틸리티
    "석유 정제품 제조업":                              ("석유와가스",           "에너지"),
    "연료용 가스 제조 및 배관공급업":                  ("가스유틸리티",         "유틸리티"),
    "전기업":                                          ("전기유틸리티",         "유틸리티"),
    "증기, 냉·온수 및 공기조절 공급업":                ("전기유틸리티",         "유틸리티"),
    "연료 소매업":                                     ("석유와가스",           "에너지"),
    # 운송
    "항공 여객 운송업":                                ("항공사",               "운송"),
    "해상 운송업":                                     ("해운",                 "운송"),
    "도로 화물 운송업":                                ("항공화물과물류",       "운송"),
    "기타 운송관련 서비스업":                          ("항공화물과물류",       "운송"),
    "운송장비 임대업":                                 ("항공화물과물류",       "운송"),
    "육상 여객 운송업":                                ("항공화물과물류",       "운송"),
    # 금융
    "은행 및 저축기관":                                ("은행",                 "금융"),
    "보험업":                                          ("보험",                 "금융"),
    "재 보험업":                                       ("보험",                 "금융"),
    "보험 및 연금관련 서비스업":                       ("보험",                 "금융"),
    "금융 지원 서비스업":                              ("증권",                 "금융"),
    "신탁업 및 집합투자업":                            ("다양한금융",           "금융"),
    "기타 금융업":                                     ("다양한금융",           "금융"),
    "상품 중개업":                                     ("다양한금융",           "금융"),
    # 부동산
    "부동산 임대 및 공급업":                           ("부동산",               "부동산"),
    "부동산 관련 서비스업":                            ("부동산",               "부동산"),
    # 유통 / 소매
    "종합 소매업":                                     ("음식료품소매",         "필수소비재"),
    "음·식료품 및 담배 소매업":                        ("음식료품소매",         "필수소비재"),
    "가전제품 및 정보통신장비 소매업":                 ("전문소매업",           "경기관련소비재"),
    "섬유, 의복, 신발 및 가죽제품 소매업":             ("전문소매업",           "경기관련소비재"),
    "기타 생활용품 소매업":                            ("전문소매업",           "경기관련소비재"),
    "무점포 소매업":                                   ("음식료품소매",         "필수소비재"),
    "기타 상품 전문 소매업":                           ("전문소매업",           "경기관련소비재"),
    # 도매 / 무역
    "상품 종합 도매업":                                ("무역회사와판매업자",   "자본재"),
    "기타 전문 도매업":                                ("무역회사와판매업자",   "자본재"),
    "음·식료품 및 담배 도매업":                        ("무역회사와판매업자",   "자본재"),
    "생활용품 도매업":                                 ("무역회사와판매업자",   "자본재"),
    "산업용 농·축산물 및 동·식물 도매업":              ("무역회사와판매업자",   "자본재"),
    # 식품 / 음료 / 담배
    "기타 식품 제조업":                                ("식품",                 "필수소비재"),
    "곡물가공품, 전분 및 전분제품 제조업":             ("식품",                 "필수소비재"),
    "동·식물성 유지 및 낙농제품 제조업":               ("식품",                 "필수소비재"),
    "도축, 육류 가공 및 저장 처리업":                  ("식품",                 "필수소비재"),
    "수산물 가공 및 저장 처리업":                      ("식품",                 "필수소비재"),
    "과실, 채소 가공 및 저장 처리업":                  ("식품",                 "필수소비재"),
    "도시락 및 식사용 조리식품 제조업":                ("식품",                 "필수소비재"),
    "동물용 사료 및 조제식품 제조업":                  ("식품",                 "필수소비재"),
    "떡, 빵 및 과자류 제조업":                         ("식품",                 "필수소비재"),
    "음식점업":                                        ("호텔레스토랑레저",     "경기관련소비재"),
    "알코올음료 제조업":                               ("음료",                 "필수소비재"),
    "비알코올음료 및 얼음 제조업":                     ("음료",                 "필수소비재"),
    "담배 제조업":                                     ("담배",                 "필수소비재"),
    # 제약 / 바이오 / 의료기기
    "의약품 제조업":                                   ("제약",                 "헬스케어"),
    "기초 의약물질 제조업":                            ("바이오로직스",         "헬스케어"),
    "의료용품 및 기타 의약 관련제품 제조업":           ("제약",                 "헬스케어"),
    "의료용 기기 제조업":                              ("의료기기",             "헬스케어"),
    "자연과학 및 공학 연구개발업":                     ("바이오로직스",         "헬스케어"),
    # 화장품 / 생활용품
    "비누, 세제, 광택제 및 방향제 제조업":             ("화장품과개인용품",     "생활용품"),
    # 섬유 / 의류
    "봉제의복 제조업":                                 ("섬유와의류",           "경기관련소비재"),
    "기타 섬유제품 제조업":                            ("섬유와의류",           "경기관련소비재"),
    "직물직조 및 직물제품 제조업":                     ("섬유와의류",           "경기관련소비재"),
    "편조원단 제조업":                                 ("섬유와의류",           "경기관련소비재"),
    "편조의복 제조업":                                 ("섬유와의류",           "경기관련소비재"),
    "방적 및 가공사 제조업":                           ("섬유와의류",           "경기관련소비재"),
    "의복 액세서리 제조업":                            ("섬유와의류",           "경기관련소비재"),
    "섬유제품 염색, 정리 및 마무리 가공업":            ("섬유와의류",           "경기관련소비재"),
    "신발 및 신발 부분품 제조업":                      ("섬유와의류",           "경기관련소비재"),
    "가죽, 가방 및 유사제품 제조업":                   ("섬유와의류",           "경기관련소비재"),
    # 레저 / 교육
    "유원지 및 기타 오락관련 서비스업":                ("호텔레스토랑레저",     "경기관련소비재"),
    "스포츠 서비스업":                                 ("호텔레스토랑레저",     "경기관련소비재"),
    "여행사 및 기타 여행보조 서비스업":                ("호텔레스토랑레저",     "경기관련소비재"),
    "일반 및 생활 숙박시설 운영업":                    ("호텔레스토랑레저",     "경기관련소비재"),
    "일반 교습 학원":                                  ("교육서비스",           "경기관련소비재"),
    "기타 교육기관":                                   ("교육서비스",           "경기관련소비재"),
    "교육지원 서비스업":                               ("교육서비스",           "경기관련소비재"),
    "초등 교육기관":                                   ("교육서비스",           "경기관련소비재"),
    # 기타 제조
    "가구 제조업":                                     ("전문소매업",           "경기관련소비재"),
    "나무제품 제조업":                                 ("화학",                 "소재"),
    "제재 및 목재 가공업":                             ("화학",                 "소재"),
    "운동 및 경기용구 제조업":                         ("호텔레스토랑레저",     "경기관련소비재"),
    "악기 제조업":                                     ("호텔레스토랑레저",     "경기관련소비재"),
    "귀금속 및 장신용품 제조업":                       ("전문소매업",           "경기관련소비재"),
    "인쇄 및 인쇄관련 산업":                           ("미디어와엔터테인먼트", "커뮤니케이션서비스"),
    "그외 기타 제품 제조업":                           ("기계",                 "자본재"),
    # 농업 / 환경
    "작물 재배업":                                     ("식품",                 "필수소비재"),
    "어로 어업":                                       ("식품",                 "필수소비재"),
    "해체, 선별 및 원료 재생업":                       ("화학",                 "소재"),
    "폐기물 처리업":                                   ("화학",                 "소재"),
    # 기타 서비스
    "개인 및 가정용품 임대업":                         ("전문서비스",           "자본재"),
    "개인 및 가정용품 수리업":                         ("전문서비스",           "자본재"),
    "기타 전문 서비스업":                              ("전문서비스",           "자본재"),
    "그외 기타 개인 서비스업":                         ("전문서비스",           "자본재"),
    "건축자재, 철물 및 난방장치 도매업":               ("건설자재",             "소재"),
}


def lookup_wics_by_krx_industry(krx_industry: str) -> tuple[str, str] | None:
    """KRX 업종명 → (WICS 소섹터, WICS 중섹터). 미매핑 시 None.

    팀원 fullkrx_A 의 161개 KRX 업종 매핑을 통한 전종목 자동 분류.
    primary WICS_SECTOR_MAP 에 없는 ticker 도 KRX 업종만 알면 매핑 가능.
    """
    if not krx_industry:
        return None
    return KRX_TO_WICS.get(krx_industry.strip())


# ─────────────────────────────────────────────────────────────
# 헬퍼 — peer_selector 가 사용할 통일된 인터페이스
# ─────────────────────────────────────────────────────────────
def get_company_info(ticker: str, krx_industry: str | None = None) -> dict | None:
    """ticker → WICS dict 반환.

    탐색 순서:
      1. primary WICS_SECTOR_MAP (255건)
      2. supplementary (운영 표본 추가)
      3. KRX_TO_WICS (krx_industry 인자 제공 시) — 전종목 자동 매핑
      4. None

    Args:
        ticker:       6자리 종목코드
        krx_industry: KRX 표준산업분류 업종명 (선택). 없으면 1·2단계만 시도.
    """
    info = WICS_SECTOR_MAP.get(ticker)
    if info is not None:
        return info

    # ★ KRX 업종명 알면 자동 매핑 시도 (전종목 대응)
    if krx_industry:
        wics = lookup_wics_by_krx_industry(krx_industry)
        if wics is not None:
            # 실데이터 정책 — name 은 호출 측에서 정확한 값 주입 필요 (krx_desc.csv 의 Name)
            return {
                "name":         None,    # 호출 측에서 채워야 함
                "sector":       wics[0],
                "mid":          wics[1],
                "source":       "krx_industry_auto",
                "krx_industry": krx_industry,
            }
    return None


def get_biz_tag(ticker: str) -> str | None:
    """ticker → BIZ_TAG (사업모델 태그). 없으면 None."""
    return BIZ_TAG.get(ticker)


def is_monopoly(ticker: str) -> bool:
    """독점·초대형 회사 여부 (피어 부족 → 인접 섹터 확장 허용)."""
    return ticker in MONOPOLY_SET


def is_adjacent_sector(sector_a: str, sector_b: str) -> bool:
    """두 소섹터가 _CROSS_SECTOR_WHITELIST 화이트리스트에 있는지."""
    return frozenset({sector_a, sector_b}) in _CROSS_SECTOR_WHITELIST


def get_same_sector_tickers(sector: str) -> list[str]:
    """같은 소섹터 모든 ticker 리스트."""
    return [t for t, info in WICS_SECTOR_MAP.items() if info["sector"] == sector]


def get_same_mid_tickers(mid: str, exclude_sector: str | None = None) -> list[str]:
    """같은 중섹터 ticker. exclude_sector 지정 시 소섹터 다른 것만."""
    return [t for t, info in WICS_SECTOR_MAP.items()
            if info["mid"] == mid
            and (exclude_sector is None or info["sector"] != exclude_sector)]


def get_adjacent_tickers(sector: str) -> list[str]:
    """화이트리스트 인접 섹터의 모든 ticker."""
    adjacent_sectors = set()
    for pair in _CROSS_SECTOR_WHITELIST:
        if sector in pair:
            adjacent_sectors.update(pair - {sector})
    return [t for t, info in WICS_SECTOR_MAP.items()
            if info["sector"] in adjacent_sectors]


# ─────────────────────────────────────────────────────────────
# 통계 (디버깅용)
# ─────────────────────────────────────────────────────────────
def validate_naming_consistency() -> dict:
    """WICS 명명 규칙 일관성 검증 — primary vs supplementary (H-5).

    Returns:
        {
            "errors":   [(ticker, info, reason), ...],  # primary 와 다른 mid/sector
            "warnings": [...],
            "ok": bool,
        }
    """
    # primary 와 supplementary 매핑 추출
    primary_sectors = {}   # sector → mid
    for info in WICS_SECTOR_MAP.values():
        sec = info.get("sector")
        mid = info.get("mid")
        if sec and mid:
            # 같은 sector 가 여러 mid 에 매핑되어 있으면 일관성 오류
            if sec in primary_sectors and primary_sectors[sec] != mid:
                primary_sectors[sec] = None   # 충돌 표시
            elif sec not in primary_sectors:
                primary_sectors[sec] = mid

    errors = []
    warnings_ = []
    for sec, mid in primary_sectors.items():
        if mid is None:
            errors.append((sec, "여러 mid 에 매핑됨 — 일관성 오류"))

    # supplementary 가 primary 와 다른 mid 사용하는 항목
    for t, info in _SUPPLEMENTARY_WICS.items():
        sec = info.get("sector")
        mid = info.get("mid")
        if sec in primary_sectors and primary_sectors[sec] not in (None, mid):
            warnings_.append(
                (t, info["name"], f"supplementary mid='{mid}' vs primary mid='{primary_sectors[sec]}'")
            )

    return {
        "errors":   errors,
        "warnings": warnings_,
        "ok":       len(errors) == 0,
        "primary_sectors": len(primary_sectors),
    }


def stats() -> dict:
    """WICS 데이터 통계."""
    sectors = {}
    mids = {}
    for info in WICS_SECTOR_MAP.values():
        sectors[info["sector"]] = sectors.get(info["sector"], 0) + 1
        mids[info["mid"]] = mids.get(info["mid"], 0) + 1
    return {
        "data_source": DATA_SOURCE,
        "total_tickers": len(WICS_SECTOR_MAP),
        "unique_sectors": len(sectors),
        "unique_mids": len(mids),
        "biz_tag_count": len(BIZ_TAG),
        "whitelist_pairs": len(_CROSS_SECTOR_WHITELIST),
        "monopoly_count": len(MONOPOLY_SET),
        "top_sectors": sorted(sectors.items(), key=lambda x: -x[1])[:10],
    }


def diagnose_peer_pool(target_ticker: str, top_n: int = 4) -> dict:
    """타깃 ticker 의 피어 후보 풀 충분성 진단.

    Returns:
        {
            "target_info": {...},
            "same_sector_count": 같은 소섹터 N사,
            "same_mid_count":    같은 중섹터 N사 (다른 소섹터),
            "adjacent_count":    화이트리스트 인접 N사,
            "total_pool":        총 후보 풀,
            "is_sufficient":     top_n 충족 여부,
            "warning":           부족 시 경고 메시지,
        }
    """
    target = WICS_SECTOR_MAP.get(target_ticker)
    if not target:
        return {"target_info": None, "warning": f"WICS 매핑 없음: {target_ticker}"}

    same_sector = get_same_sector_tickers(target["sector"])
    same_sector = [t for t in same_sector if t != target_ticker]
    same_mid    = get_same_mid_tickers(target["mid"], exclude_sector=target["sector"])
    adjacent    = get_adjacent_tickers(target["sector"])

    total_pool = len(set(same_sector + same_mid + adjacent))
    is_sufficient = total_pool >= top_n

    warning = None
    if not is_sufficient:
        warning = (f"⚠ {target['name']} ({target_ticker}) 피어 후보 부족: "
                  f"{total_pool}사 < {top_n}사. "
                  + ("MONOPOLY 처리 권장." if target_ticker in MONOPOLY_SET
                     else "화이트리스트 추가 또는 mid 섹터 후보 확장 필요."))

    return {
        "target_info":       {**target, "ticker": target_ticker},
        "same_sector_count": len(same_sector),
        "same_mid_count":    len(same_mid),
        "adjacent_count":    len(adjacent),
        "total_pool":        total_pool,
        "is_sufficient":     is_sufficient,
        "is_monopoly":       target_ticker in MONOPOLY_SET,
        "warning":           warning,
    }


if __name__ == "__main__":
    import sys

    s = stats()
    print("=" * 60)
    print("  WICS 섹터 매핑 통계")
    print("=" * 60)
    print(f"  데이터 소스    : {s['data_source']}")
    print(f"  전체 ticker    : {s['total_tickers']:,}개")
    print(f"  소섹터 종류    : {s['unique_sectors']}개")
    print(f"  중섹터 종류    : {s['unique_mids']}개")
    print(f"  BIZ_TAG       : {s['biz_tag_count']}개")
    print(f"  화이트리스트 쌍 : {s['whitelist_pairs']}개")
    print(f"  MONOPOLY      : {s['monopoly_count']}개")
    print(f"\n  Top 10 소섹터:")
    for sec, n in s["top_sectors"]:
        print(f"    {n:>3}사  {sec}")

    # 명령행 인자로 ticker 주면 진단
    if len(sys.argv) > 1:
        ticker = sys.argv[1]
        print(f"\n" + "=" * 60)
        print(f"  [{ticker}] 피어 후보 풀 진단")
        print("=" * 60)
        d = diagnose_peer_pool(ticker, top_n=4)
        if d["target_info"]:
            t = d["target_info"]
            print(f"  타깃         : {t.get('name')} ({ticker})")
            print(f"  소섹터       : {t.get('sector')}")
            print(f"  중섹터       : {t.get('mid')}")
            print(f"  MONOPOLY     : {d['is_monopoly']}")
            print(f"\n  후보 풀 분석:")
            print(f"    같은 소섹터 : {d['same_sector_count']:>3}사")
            print(f"    같은 중섹터 (다른 소섹터): {d['same_mid_count']:>3}사")
            print(f"    화이트리스트 인접: {d['adjacent_count']:>3}사")
            print(f"    총 후보 풀  : {d['total_pool']:>3}사")
            print(f"    충분성      : {'✓ 충분' if d['is_sufficient'] else '⚠ 부족'}")
            if d["warning"]:
                print(f"\n  {d['warning']}")
        else:
            print(f"  ⚠ {d.get('warning', 'WICS 매핑 없음')}")
