# FILMN9 컬럼명 레퍼런스

> 프로젝트에서 사용하는 주요 파일별 필드명 정리  
> 경로 기준: `C:\Users\Admin\Desktop\DART\`

---

## 1. ticker_universe.csv
> 경로: `prompt_test/ticker_universe.csv`  
> 전종목 기준 정보 (KOSPI + KOSDAQ)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `stock_code` | str (6자리) | 종목코드. 항상 문자열로 읽을 것 (`dtype={'stock_code': str}`) |
| `corp_name` | str | 기업명 |
| `market` | str | 상장시장 (`KOSPI` / `KOSDAQ`) |
| `industry` | str | 세부 업종명 |
| `wics` | str | WICS 섹터명 (브리핑 생성 시 `gics_sector`로 사용) |
| `is_spac` | bool | 스팩(SPAC) 여부 — 생성 대상 제외 |
| `is_preferred` | bool | 우선주 여부 — 생성 대상 제외 |
| `has_multi_sector` | bool | 멀티섹터 종목 여부 — True면 청크 필터링 적용 |
| `needs_rerun` | bool | 재실행 필요 플래그 |
| `rerun_reasons` | str/NaN | 재실행 사유 |

---

## 2. RAG JSONL 청크
> 경로: `RAG/{stock_code}_{corp_name}_{year}_annual_chunks.jsonl`  
> 사업보고서 파싱 결과. 한 줄 = 한 청크

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | str | 청크 고유 ID |
| `group` | str | 청크 그룹 분류 |
| `stock_code` | str | 종목코드 |
| `corp_code` | str | DART 고유번호 (8자리) |
| `corp_name` | str | 기업명 |
| `report_nm` | str | 공시명 (예: `사업보고서`) |
| `report_kind` | str | 보고서 종류 |
| `report_type` | str | 보고서 타입 |
| `rcept_no` | str | DART 접수번호 (14자리) — 원문 URL 생성에 사용 |
| `rcept_dt` | str | 접수일 (`YYYYMMDD`) |
| `fiscal_period` | str | 회계연도 |
| `source_url` | str | 원문 URL |
| `parse_mode` | str | 파싱 방식 |
| `kind` | str | 청크 유형 (`text` / `table`) |
| `section_path` | list | 섹션 경로 (리스트) |
| `section_path_str` | str | 섹션 경로 문자열 (예: `II. 사업의 내용 > 1. 사업의 개요`) |
| `char_len` | int | 텍스트 길이 (문자 수) |
| `text` | str | 본문 텍스트 |

---

## 3. 브리핑 JSON
> 경로: `output/briefs_final_1pass/{stock_code}_{corp_name}.json`  
> LLM이 생성한 종목 브리핑

### 최상위 필드
| 필드 | 타입 | 설명 |
|------|------|------|
| `stock_code` | str | 종목코드 |
| `corp_name` | str | 기업명 |
| `_llm_model` | str | 생성에 사용한 모델명 (예: `gpt-5-mini`) |
| `_generated_at` | str | 생성 일시 (`YYYY-MM-DD HH:MM`) |
| `meta` | dict | 메타 정보 (아래 참조) |
| `brief` | dict | 브리핑 본문 (아래 참조) |
| `usage` | dict | 토큰 사용량 |
| `warnings` | list | 검증 경고 목록 |

### meta 필드
| 필드 | 타입 | 설명 |
|------|------|------|
| `wics` | str | WICS 섹터 |
| `market` | str | 상장시장 |
| `has_revenue_data` | bool | 매출 데이터 존재 여부 (tier ≤ 2이면 True) |
| `tier` | int | 데이터 충실도 등급 (1~4, 낮을수록 데이터 풍부) |
| `tier_mode` | str | tier 판단 방식 (`exact_pct` / `calc_pct` / `narrative` 등) |
| `corp_type` | str | 기업 유형 (`general` / `holding` / `financial` 등) |

### brief 필드
| 필드 | 타입 | 설명 |
|------|------|------|
| `company_overview` | str | 기업 개요 |
| `business_model` | str | 사업 모델 설명 |
| `main_customers` | str | 주요 고객/매출처 |
| `price_factors` | str | 주가 영향 요인 |
| `key_evidence` | list | 근거 인용 목록 (아래 참조) |
| `confidence` | str | LLM 자체 평가 신뢰도 (`high` / `medium` / `low`) |

### key_evidence 항목
| 필드 | 타입 | 설명 |
|------|------|------|
| `field` | str | 인용된 브리핑 필드명 (예: `business_model`) |
| `source_section` | str | 출처 섹션 경로 |
| `evidence_text` | str | 원문 인용 텍스트 — Phase B 평가 기준 |

---

## 4. 평가 JSON
> 경로: `output/eval_final_1pass/{stock_code}.json`  
> 4-Phase 품질 평가 결과

### 최상위 필드
| 필드 | 타입 | 설명 |
|------|------|------|
| `stock_code` | str | 종목코드 |
| `overall_score` | float | 종합 점수 (0~100) — low 기준: < 70 |
| `level` | str | 등급 (`high` ≥ 85 / `medium` ≥ 70 / `low` < 70) |
| `metrics` | dict | Phase별 점수 요약 (아래 참조) |
| `details` | dict | Phase별 상세 결과 (아래 참조) |
| `tested_at` | str | 평가 일시 |
| `judge_model` | str | LLM Judge 모델명 |

### metrics 필드 (가중치)
| 필드 | 가중치 | 설명 |
|------|--------|------|
| `numerical_match` | 40% | Phase A — 수치 일치율 (0~100, 수치 없으면 None) |
| `citation_check` | 25% | Phase B — 인용 매칭률 (0~100) |
| `ragas_faithfulness` | 25% | Phase C — RAGAS 충실도 (0~100) |
| `llm_judge` | 10% | Phase D — LLM Judge 점수 (0~100) |

> overall_score = 각 Phase 점수 × 가중치 합산. None인 Phase는 나머지에 가중치 재분배.

### details.phase_a
| 필드 | 설명 |
|------|------|
| `score` | 0~1 |
| `total` | 검사한 수치 개수 |
| `found` | 일치한 수치 개수 |
| `missing` | 불일치 수치 목록 |

### details.phase_b
| 필드 | 설명 |
|------|------|
| `score` | 0~1 |
| `total` | key_evidence 총 개수 |
| `matched` | 원문에서 찾은 개수 |
| `failures` | 미매칭 항목 목록 (`field`, `evidence_text`) |

### details.phase_c
| 필드 | 설명 |
|------|------|
| `score` | 0~1 |
| `claims` | 검증된 주장 목록 (`claim`, `supported: bool`) |

### details.phase_d
| 필드 | 설명 |
|------|------|
| `score` | 평균 점수 (1~5) |
| `scores` | 5개 축별 점수 (사실정확성, 다시읽기욕구, 불필요한정보없음, 명확한구조, 투자연관성) |
| `verdict` | 판정 (`pass` / `partial` / `fail` 등) |
| `hallucinations` | 환각 탐지 목록 |

---

## 5. ChromaDB 메타데이터
> 경로: `임베딩_최종본/chroma_db/`  
> Collection: `annual_reports` | 총 ~192만 청크 | 임베딩 모델: `BAAI/bge-m3` (1024차원)

| 필드 | 예시 | 설명 |
|------|------|------|
| `ticker` | `"090430"` | 종목코드 6자리 — 필터링 키 |
| `corp_name` | `"아모레퍼시픽"` | 기업명 |
| `year` | `2025` | 회계연도 (int) |
| `section_main` | `"II. 사업의 내용"` | 대섹션 |
| `section_path_str` | `"I. 회사의 개요 > 1. 회사의 개요"` | 전체 섹션 경로 |
| `kind` | `"table"` / `"text"` | 청크 유형 |
| `rcept_no` | `"20260318000785"` | DART 접수번호 |

---

## 6. DART 공시 연결
> DART 원문 URL 패턴

```
https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}
```

| 필드 | 설명 |
|------|------|
| `corp_code` | DART 고유번호 8자리 — ticker_universe.csv에 포함 |
| `rcept_no` | 접수번호 14자리 — RAG JSONL과 ChromaDB에 있음 |
| `pblntf_detail_ty` | 공시 상세유형 (`A001`=사업보고서, `I001`=수시공시) |

---

## 7. 주요 경로 요약

```
DART/
├── prompt_test/
│   └── ticker_universe.csv          ← 전종목 기준 정보
├── RAG/
│   └── {stock_code}_{corp_name}_{year}_annual_chunks.jsonl  ← 사업보고서 청크
├── output/
│   ├── briefs_final_1pass/          ← 1pass 브리핑 JSON
│   ├── briefs_final_2pass/          ← 2pass 브리핑 JSON (low 종목 재생성)
│   ├── briefs_final/                ← 최종 best-of-two 브리핑
│   ├── eval_final_1pass/            ← 1pass 평가 결과
│   └── eval_final_2pass/            ← 2pass 평가 결과
└── 임베딩_최종본/
    └── chroma_db/                   ← BGE-M3 벡터 인덱스
```
