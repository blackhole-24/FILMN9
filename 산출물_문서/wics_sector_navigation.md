# WICS 섹터 기반 종목 탐색 기능

> 홈페이지에 WICS 섹터를 보여주고, 클릭 시 섹터 내 종목 목록 → 종목 상세 페이지로 이동하는 기능

작성일: 2026-05-26

---

## 1. 목적

사용자가 종목명을 정확히 모르더라도 **섹터를 통해 종목을 탐색**할 수 있도록 한다.

기존 흐름: 종목명/티커 직접 검색 → 상세 페이지  
추가 흐름: 섹터 클릭 → 섹터 내 종목 목록 → 종목 클릭 → **기존 상세 페이지로 이동**

---

## 2. 사용자 흐름 (UX Flow)

```
[홈]
  ↓
[WICS 섹터 78개 목록 화면]
   ├─ 반도체와반도체장비 (162)
   ├─ 제약 (160)
   ├─ 자동차부품 (148)
   └─ ... (78개)
  ↓ 섹터 클릭
[해당 섹터 종목 목록]
   ├─ 005930 삼성전자
   ├─ 000660 SK하이닉스
   └─ ...
  ↓ 종목 클릭
[종목 상세 페이지]
   = 검색창에서 검색한 것과 동일 (브리핑 + 밸류에이션 등)
```

---

## 3. 데이터 소스

### 3.1 원본 파일
- 경로: `prompt_test/ticker_universe.csv`
- 컬럼 정의는 `docs/column_reference.md` 참조

### 3.2 필터링 규칙
- `is_spac = True` 제외 (SPAC 종목)
- `is_preferred = True` 제외 (우선주)
- 결과: 활성 종목 **2,588개**

### 3.3 사용 컬럼
| 컬럼 | 용도 |
|------|------|
| `stock_code` | 종목코드 (6자리) |
| `corp_name` | 종목명 |
| `wics` | **섹터 분류 (78개)** |
| `market` | KOSPI / KOSDAQ |

### 3.4 사전 계산된 데이터
`docs/wics_sector_data.json` 참조 (섹터별 종목 수 포함)

---

## 4. API 엔드포인트 설계

### 4.1 섹터 목록 조회

```
GET /api/sectors
```

**응답:**
```json
{
  "total_stocks": 2588,
  "total_sectors": 78,
  "sectors": [
    { "sector_name": "반도체와반도체장비", "count": 162 },
    { "sector_name": "제약",              "count": 160 },
    { "sector_name": "자동차부품",         "count": 148 },
    "..."
  ]
}
```

**정렬:** 종목 수 내림차순 (기본)

---

### 4.2 특정 섹터의 종목 목록 조회

```
GET /api/sectors/{sector_name}/stocks
```

**예시:**
```
GET /api/sectors/반도체와반도체장비/stocks
```

**응답:**
```json
{
  "sector_name": "반도체와반도체장비",
  "count": 162,
  "stocks": [
    { "stock_code": "005930", "corp_name": "삼성전자",    "market": "KOSPI" },
    { "stock_code": "000660", "corp_name": "SK하이닉스",   "market": "KOSPI" },
    "..."
  ]
}
```

**정렬:** stock_code 오름차순 (기본)

> ⚠️ `sector_name`은 한글 포함이므로 URL 인코딩 필요  
> `반도체와반도체장비` → `%EB%B0%98%EB%8F%84%EC%B2%B4%EC%99%80%EB%B0%98%EB%8F%84%EC%B2%B4%EC%9E%A5%EB%B9%84`

---

### 4.3 종목 상세 페이지 (기존 라우트 재사용)

```
GET /api/overview/{stock_code}   ← 이미 존재
```

섹터에서 종목 클릭 시 → **기존 라우트로 이동**. 새로 만들 필요 없음.

---

## 5. 백엔드 구현 가이드 (FastAPI 예시)

```python
# api/routers/sectors.py
from fastapi import APIRouter, HTTPException
from pathlib import Path
import pandas as pd

router = APIRouter()
UNIVERSE_CSV = Path("data/ticker_universe.csv")

def _load_universe() -> pd.DataFrame:
    df = pd.read_csv(UNIVERSE_CSV, dtype={"stock_code": str})
    df = df[~df["is_spac"].fillna(False) & ~df["is_preferred"].fillna(False)]
    return df

@router.get("/api/sectors")
def list_sectors():
    df = _load_universe()
    counts = df["wics"].value_counts().reset_index()
    counts.columns = ["sector_name", "count"]
    return {
        "total_stocks":  len(df),
        "total_sectors": len(counts),
        "sectors":       counts.to_dict("records"),
    }

@router.get("/api/sectors/{sector_name}/stocks")
def list_stocks_in_sector(sector_name: str):
    df = _load_universe()
    subset = df[df["wics"] == sector_name].sort_values("stock_code")
    if subset.empty:
        raise HTTPException(404, f"섹터 '{sector_name}' 없음")
    return {
        "sector_name": sector_name,
        "count":       len(subset),
        "stocks":      subset[["stock_code", "corp_name", "market"]].to_dict("records"),
    }
```

---

## 6. 프론트엔드 와이어프레임

### 6.1 섹터 목록 화면

```
┌─────────────────────────────────────────────┐
│ 섹터별 탐색                                  │
│ 총 2,588 종목 / 78 섹터                      │
│ ─────────────────────────────                │
│ 정렬: [종목수 ▼]                              │
│                                              │
│ ┌─ 반도체와반도체장비 ──── 162 종목 →─┐     │
│ ├─ 제약 ──────────────── 160 종목 →─┤     │
│ ├─ 자동차부품 ──────────── 148 종목 →─┤     │
│ ├─ 화학 ──────────────── 113 종목 →─┤     │
│ ├─ IT서비스 ──────────── 106 종목 →─┤     │
│ ...                                          │
│ ├─ 담배 ──────────────── 1 종목 →─┤     │
│ └─ 복합유틸리티 ─────────── 1 종목 →─┘     │
└─────────────────────────────────────────────┘
```

**구현 포인트:**
- 카드형 또는 리스트형 자유
- 클릭 시 `/sectors/{sector_name}` 페이지로 이동

### 6.2 섹터 내 종목 목록 화면

```
┌─────────────────────────────────────────────┐
│ ← 섹터 목록으로                              │
│                                              │
│ 반도체와반도체장비                            │
│ 162 종목                                     │
│ ─────────────────────────────                │
│                                              │
│ 005930  삼성전자       KOSPI    →           │
│ 000660  SK하이닉스     KOSPI    →           │
│ 042700  한미반도체     KOSDAQ   →           │
│ ...                                          │
└─────────────────────────────────────────────┘
```

**구현 포인트:**
- 종목 클릭 → **기존 종목 상세 페이지로 라우팅** (`/overview/{stock_code}`)
- 검색창에서 직접 검색한 것과 동일한 결과 화면

---

## 7. 라우팅 (프론트)

| 경로 | 화면 | 기존/신규 |
|------|------|----------|
| `/sectors` | 섹터 목록 (78개) | 🆕 신규 |
| `/sectors/{sector_name}` | 섹터 내 종목 목록 | 🆕 신규 |
| `/stocks/{stock_code}` 또는 기존 라우트 | **종목 상세** | ✅ 기존 재사용 |

---

## 8. 첨부 데이터

**`docs/wics_sector_data.json`** — 78개 섹터 + 종목 수 사전 계산
```json
{
  "total_stocks": 2588,
  "total_sectors": 78,
  "sectors": [
    { "sector_name": "반도체와반도체장비", "count": 162 },
    { "sector_name": "제약",              "count": 160 },
    "..."
  ]
}
```

API 구현 전이라도 이 파일로 프론트엔드 mock-up 가능.

---

## 9. 향후 확장 (참고)

- **검색 필터**: 섹터 목록 상단에 검색창 추가 (78개 중 빠른 탐색)
- **2단계 분류**: `industry` (29개) → `wics` (78개) 트리 구조
- **섹터별 평균 점수**: `docs/result_charts/` 활용해 섹터별 품질 표시
- **즐겨찾기**: 자주 보는 섹터/종목 핀 고정
