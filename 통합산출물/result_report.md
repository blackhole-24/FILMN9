# FILMN9 브리핑 생성 결과 리포트

> 한국 상장사 2,526개 종목의 사업보고서 기반 히스토리 브리핑 생성 완료

작성일: 2026-05-26

---

## 1. 한눈에 보기

| 항목 | 결과 |
|------|------|
| 생성 종목 수 | **2,526개** (KOSPI + KOSDAQ) |
| 평균 품질 점수 | **77.1점** (100점 만점) |
| 산출물 경로 | `output/briefs_final/` |
| 파일 형식 | JSON (종목당 1개) |

**핵심 수치:**
- 등급 high (85점+): 약 30%
- 등급 medium (70-84점): 약 50%
- 등급 low (<70점): 약 20%

---

## 2. 작업 파이프라인

```
사업보고서 (DART)
    ↓
RAG 청크 추출
    ↓
1차 생성 (gpt-5-mini, 2,526개)
    ↓
품질 평가 (4-Phase)
    ↓
저점수 종목 재생성 (gpt-5.4-mini, 698개)
    ↓
품질 평가 (4-Phase)
    ↓
best-of-two 통합 (종목별 더 높은 점수 채택)
    ↓
최종 산출물: briefs_final/ (2,526개)
```

---

## 3. 채택 비율

![채택 비율](result_charts/02_adopt_ratio.png)

- **1pass (gpt-5-mini): 2,148개 (85%)** — 대부분의 종목에서 우수
- **2pass (gpt-5.4-mini): 378개 (15%)** — 1pass가 부족했던 일부 종목 개선

**평균 점수 변화**: 75.7점 → **77.1점** (+1.4점)

---

## 4. 품질 차원별 점수

![Phase별 점수](result_charts/01_phase_scores.png)

| Phase | 의미 | 평균 |
|-------|------|------|
| **A. 수치 일치** | 브리핑 숫자가 원본과 일치하는가 | ~83점 |
| **B. 인용 검증** | 인용한 텍스트가 원본에 존재하는가 | ~74점 |
| **C. RAGAS** | 사실적 충실도 (LLM 자동 평가) | ~70점 |
| **D. LLM Judge** | 5축 종합 평가 (가독성, 구조 등) | ~67점 |

**가중치**: A 40% + B 25% + C 25% + D 10% = overall_score

---

## 5. 점수 분포

![점수 분포](result_charts/04_score_histogram.png)

- best-of-two로 분포가 우측 시프트 (전반적으로 점수 상승)
- low 구간(<70) 비율 감소

---

## 6. 섹터별 품질

![섹터별 점수](result_charts/03_sector_scores.png)

**잘 된 섹터**: 표준 사업보고서 양식을 따르는 제조업/금융 위주

**아쉬운 섹터**: 사업 내용이 복잡하거나 매출 구조가 불분명한 IT서비스/창업투자/음료 등

→ 향후 섹터별 프롬프트 튜닝 시 우선순위

---

## 7. 브리핑 JSON 구조 (개발자용)

```json
{
  "stock_code": "005930",
  "corp_name": "삼성전자",
  "_llm_model": "gpt-5-mini",
  "_generated_at": "2026-05-22 09:15",
  "meta": {
    "wics": "반도체와반도체장비",
    "market": "KOSPI",
    "has_revenue_data": true,
    "tier": 1
  },
  "brief": {
    "company_overview": "...",   // 기업 개요
    "business_model": "...",     // 사업 모델
    "main_customers": "...",     // 주요 고객
    "price_factors": "...",      // 주가 요인
    "key_evidence": [            // 인용 근거
      {
        "field": "business_model",
        "source_section": "II. 사업의 내용 > 1. 사업의 개요",
        "evidence_text": "..."
      }
    ],
    "confidence": "high"         // LLM 자기 평가
  },
  "usage": {...},                // 토큰 사용량
  "warnings": [...]              // 검증 경고
}
```

**상세 컬럼 정의**: `docs/column_reference.md` 참조

---

## 8. 산출물 파일 구조

```
output/briefs_final/
├── 000020_동화약품.json          # 종목별 브리핑
├── 000040_KR모터스.json
├── ...                          (총 2,526개)
├── _summary.json                # 통합 요약
├── _selection_detail.csv        # 종목별 채택 정보 (1pass vs 2pass)
└── _distribution.png            # 등급 분포 차트
```

---

## 9. 한계점 (솔직하게)

### 9.1 Phase B (인용 검증)의 exact match 한계
- 평가 시 "인용 텍스트가 원본에 글자 그대로 있는가"를 봄
- gpt-5.4-mini는 패러프레이즈가 많아 실제 정확한 인용임에도 점수 손해
- 향후 semantic 평가로 개선 여지 있음

### 9.2 일부 누락 영역
- 사업보고서의 특정 표 형식이나 비정형 데이터는 청크 추출 시 손실 가능
- WICS 분류상 데이터 부족한 섹터 (음료, IT서비스 등) 점수 낮음

### 9.3 시점 한계
- 사업보고서는 연 1회 작성 → 실시간 정보 없음
- 별도로 뉴스 / 공시 데이터를 결합해야 최신성 확보 가능

---

## 10. 다음 단계

### 10.1 MongoDB 적재 (백엔드)
- 팀원 제공 `load_history_to_mongo.py` 스크립트로 `briefs_final/` 업로드
- 컬렉션: `history_briefings` (또는 합의된 명)

### 10.2 서비스 연동 (프론트)
- 종목 상세 페이지에 브리핑 4개 필드 표시:
  - 기업 개요 / 사업 모델 / 주요 고객 / 주가 요인
- `key_evidence` 인용 표시로 신뢰성 확보
- DART 원문 링크 연결 → `docs/dart_link_integration.md` 참조
- 공급계약 공시 섹션 → `docs/dart_supply_contract.md` 참조

### 10.3 추후 개선 후보
- News 데이터 결합 (실시간성)
- 임베딩 기반 RAG 챗봇 (`임베딩_최종본/chroma_db/` 활용)
- 저점수 섹터 프롬프트 재튜닝

---

## 11. 관련 문서

| 문서 | 내용 |
|------|------|
| `docs/column_reference.md` | 전체 컬럼명 정의 |
| `docs/dart_link_integration.md` | DART 원문 연결 |
| `docs/dart_supply_contract.md` | 공급계약 공시 연결 |
| `docs/result_charts/` | 본 리포트 차트 |
