"""KOFIA CP시가평가수익률 참조 데이터 (5사 평균).

데이터 출처: KOFIA 채권정보센터 CP시가평가수익률 > 평가사 평균(`23.1.9~)
캡처 일자: 2026-05-18

★ 향후 보강 방식:
  - 이 모듈의 KOFIA_CP_REFERENCE 상수는 첫 단추용 하드코드.
  - CP CSV 파일이 추가되면 cp_loader.py 로 동적 로드로 교체.
    (kd_loader.py 의 채권시가평가기준수익률 처리 패턴 그대로)

단위: 소수 (% / 100)
만기: "7일", "15일", "1월", "3월", "6월", "1년"
"""
from __future__ import annotations

# CP 단기 등급 (KOFIA 정확 표기)
VALID_CP_RATINGS = ("A1", "A2+", "A2", "A2-",
                    "A3+", "A3", "A3-",
                    "B+", "B", "B-", "C", "D")


# 2026-05-18 KOFIA "평가사 평균" 5사 평균치 — 캡처에서 확인 가능한 3개 등급만 수록.
# 다른 등급 (A2, A2-, A3, A3-, B+ 이하) 은 캡처에 미포함 → KeyError 로 폴백.
KOFIA_CP_REFERENCE: dict[str, dict[str, float]] = {
    "A1": {
        "7일":  0.02710, "15일": 0.02770, "1월":  0.02850,
        "3월":  0.03050, "6월":  0.03110, "1년":  0.03150,
    },
    "A2+": {
        "7일":  0.02810, "15일": 0.02890, "1월":  0.02960,
        "3월":  0.03140, "6월":  0.03230, "1년":  0.03280,
    },
    "A3+": {
        "7일":  0.04380, "15일": 0.04460, "1월":  0.04600,
        "3월":  0.04900, "6월":  0.05010, "1년":  0.05110,
    },
}

KOFIA_CP_AS_OF = "2026-05-18"           # 캡처 시점
KOFIA_CP_SOURCE = "KOFIA CP시가평가수익률 — 5사 평균(나이스/한국/KIS/에프앤/이지)"


def get_kofia_cp_yield(cp_rating: str, maturity: str = "1년") -> float:
    """KOFIA CP 평균 수익률 조회 (소수).

    Raises:
        KeyError: 캡처에 포함되지 않은 등급/만기.
    """
    if cp_rating not in KOFIA_CP_REFERENCE:
        raise KeyError(
            f"KOFIA CP 참조 데이터에 '{cp_rating}' 등급이 없습니다.\n"
            f"  현재 수록 등급 (캡처 기반): {sorted(KOFIA_CP_REFERENCE.keys())}\n"
            f"  다른 등급이 필요하면 KOFIA에서 CP CSV 추가 다운로드 필요.\n"
            f"  → cp_yield_data.py 의 KOFIA_CP_REFERENCE 보강 또는 "
            f"   별도 cp_loader.py 추가."
        )
    tier = KOFIA_CP_REFERENCE[cp_rating]
    if maturity not in tier:
        raise KeyError(
            f"CP 만기 '{maturity}' 가 KOFIA 표에 없음. "
            f"가능 만기: {sorted(tier.keys())}"
        )
    return tier[maturity]
