"""
수집 대상 회사 마스터 리스트.

⭐ 회사 추가/변경 시 이 파일만 수정하면 됩니다.
   다른 파일 (config / pipeline / README) 자동 인식.

형식:
    (그룹라벨, 종목코드 6자리, 한글 회사명)

규칙:
- 종목코드는 문자열 6자리 ("064350" 처럼 0 패딩 유지)
- 회사명은 DART 공시상의 정확한 표기 (특수문자 주의)
- 그룹라벨은 자유 ("G1", "방산", "Auto" 등 무엇이든 가능)
- 중복 종목코드 금지
"""

COMPANIES = [
    # ── G1. 방산 ──
    ("G1", "064350", "현대로템"),
    ("G1", "047810", "한국항공우주"),
    ("G1", "272210", "한화시스템"),
    ("G1", "079550", "LIG넥스원"),

    # ── G2. 중공업 ──
    ("G2", "034020", "두산에너빌리티"),

    # ⭐ 여기에 한 줄씩 추가하면 끝.
    # 예시:
    # ("G3", "005930", "삼성전자"),
    # ("G3", "000660", "SK하이닉스"),
    # ("G4", "035420", "NAVER"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼 — pipeline.py / pipeline.ipynb 가 사용
# ─────────────────────────────────────────────────────────────────────────────
def get_company_count() -> int:
    return len(COMPANIES)


def get_groups() -> list:
    """회사 리스트에서 그룹 라벨 unique 추출 (입력 순서 유지)."""
    seen, out = set(), []
    for grp, _, _ in COMPANIES:
        if grp not in seen:
            seen.add(grp); out.append(grp)
    return out


def filter_by_group(group_label: str) -> list:
    """특정 그룹만 필터링 — 일부 회사만 우선 처리할 때."""
    return [(g, sc, n) for g, sc, n in COMPANIES if g == group_label]


def validate() -> dict:
    """리스트 무결성 검증 — 종목코드 중복·길이 체크."""
    errors = []
    codes_seen = {}
    for i, (grp, sc, name) in enumerate(COMPANIES, 1):
        if not isinstance(sc, str) or len(sc) != 6 or not sc.isdigit():
            errors.append(f"L{i} 종목코드 형식 오류: '{sc}' ({name})")
        if sc in codes_seen:
            errors.append(f"L{i} 중복 종목코드: '{sc}' ({name}, 이전 L{codes_seen[sc]})")
        codes_seen[sc] = i
        if not name or not isinstance(name, str):
            errors.append(f"L{i} 회사명 비어있음: 종목 {sc}")
    return {
        "ok":      len(errors) == 0,
        "n_total": len(COMPANIES),
        "n_groups": len(get_groups()),
        "errors":  errors,
    }


if __name__ == "__main__":
    res = validate()
    print(f"회사 수: {res['n_total']}, 그룹 수: {res['n_groups']}")
    if res["ok"]:
        print("✅ 무결성 OK")
    else:
        print("❌ 오류:")
        for e in res["errors"]:
            print(f"  - {e}")
