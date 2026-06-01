"""
FILMN9 VEDA — WACC 상수값 (ERP · SRP)
출처: 한국공인회계사회
⚠️ 연 1회 업데이트 필요 (kicpa.or.kr 확인)
최근 기준: 2024년 6월 5일 발표
"""

# ERP (시장위험프리미엄)
# 한공회 2024: 7%~9%, 중위값 8%
ERP_TABLE = {
    "한공회_중위값": 0.08,   # 기본값 (실무 관행)
    "한공회_하한"  : 0.07,
    "한공회_상한"  : 0.09,
    "source": "한국공인회계사회 2024.06.05 시장위험프리미엄 가이던스",
}

# SRP (기업규모위험프리미엄)
# 한공회 3분위 기준, 시가총액 단위: 억원
SRP_TABLE = [
    {"tier": 1, "mktcap_max_bil": 300,    "srp": 0.0500, "label": "초소형"},
    {"tier": 2, "mktcap_max_bil": 1_000,  "srp": 0.0400, "label": "소형"},
    {"tier": 3, "mktcap_max_bil": 5_000,  "srp": 0.0335, "label": "중소형"},
    {"tier": 4, "mktcap_max_bil": 20_000, "srp": 0.0150, "label": "중형"},
    {"tier": 5, "mktcap_max_bil": None,   "srp": 0.0050, "label": "대형"},
]
SRP_SOURCE = "한국공인회계사회 기업규모위험프리미엄 연구결과 3분위"


def get_erp(method: str = "한공회_중위값") -> dict:
    """ERP 반환"""
    return {
        "erp"   : ERP_TABLE[method],
        "method": method,
        "source": ERP_TABLE["source"]
    }


def get_srp(mktcap: float) -> dict:
    """시가총액(원 단위) → SRP 반환"""
    mktcap_bil = mktcap / 1e8
    for row in SRP_TABLE:
        if row["mktcap_max_bil"] is None or mktcap_bil <= row["mktcap_max_bil"]:
            return {
                "srp"       : row["srp"],
                "srp_pct"   : row["srp"] * 100,
                "tier"      : row["tier"],
                "label"     : row["label"],
                "mktcap_bil": round(mktcap_bil, 0),
                "source"    : SRP_SOURCE
            }
    return {"srp": 0.005, "source": SRP_SOURCE}
