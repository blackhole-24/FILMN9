# 계열회사 시각화 및 검증 인수인계

이 문서는 다른 AI 또는 개발자가 `계열회사시각화` 작업을 이어받을 수 있도록, 현재 시각화 방식과 검증 전략을 정리한 인수인계 문서입니다.

## 현재 목표

DART 사업보고서의 계열회사 관련 정보를 이용해 기업별 관계회사 구조를 시각화한다.

우선순위는 다음과 같다.

1. DART 원문에 소유지분도/출자계통도 이미지가 있으면 원본 이미지를 저장한다.
2. 이미지가 없으면 JSONL 표/본문에서 관계회사 정보를 추출해 SVG 구조도를 생성한다.
3. 지분율이 없더라도 계열회사 목록은 directory 형태로 보여준다.
4. 잘못된 회사명, 표 헤더, 기준일, 합계, 문장 조각이 그래프에 들어가지 않도록 검증한다.
5. 최종적으로는 DART 원문과 생성 결과의 정합성까지 검증한다.

## 주요 입력

```text
C:\Users\Admin\Desktop\DART\RAG\*_annual_chunks.jsonl
```

각 JSONL chunk에는 대체로 다음 필드가 있다.

- `stock_code`
- `corp_code`
- `corp_name`
- `report_nm`
- `rcept_no`
- `section_path_str`
- `kind`
- `text`
- `id`

시각화는 `section_path_str`와 `text`에서 계열회사, 출자계통도, 타법인출자, 연결대상 종속회사, 재무제표 주석 관련 표를 탐색해 만든다.

## 주요 출력

```text
C:\Users\Admin\Desktop\DART\output\affiliate_visualization\
C:\Users\Admin\Desktop\DART\output\affiliate_structure_batch\
C:\Users\Admin\Desktop\DART\output\affiliate_validation_report.json
C:\Users\Admin\Desktop\DART\output\affiliate_validation_issues.csv
```

기업별 산출물 예시는 다음과 같다.

```text
output/affiliate_visualization/005490_POSCO홀딩스/
  affiliate_visual_metadata.json
  affiliate_visual_data.json
  affiliate_investment_graph.svg

output/affiliate_structure_batch/005490_POSCO홀딩스/
  005490_POSCO홀딩스_visual_data.json
  005490_POSCO홀딩스_affiliate_structure.svg
```

## 관련 스크립트

```text
계열회사시각화/scripts/build_affiliate_visualization.py
계열회사시각화/scripts/build_affiliate_structure_diagrams.py
계열회사시각화/scripts/build_affiliate_visual_manifest.py
계열회사시각화/scripts/refresh_affiliate_original_image_candidates.py
계열회사시각화/scripts/validate_affiliate_graph_outputs.py
계열회사시각화/scripts/sync_affiliate_visualizations_to_mongo.py
```

루트의 `scripts/build_affiliate_visualization.py`에도 같은 로직을 맞춰 두었다. 수정 시 두 파일의 차이가 생기지 않게 주의한다.

## 시각화 생성 흐름

전체 처리 흐름은 다음과 같다.

```text
RAG JSONL
  -> DART 원본 이미지 탐색
  -> 원본 이미지 있으면 original_dart_image 저장
  -> 없으면 JSONL 표/본문 파싱
  -> source_type 결정
  -> SVG + metadata JSON + extracted data JSON 저장
  -> structure diagram batch 생성
  -> validation 실행
```

## source_type 기준

`build_affiliate_visualization.py`는 데이터 신뢰도와 구조성에 따라 다음 순서로 시각화 유형을 선택한다.

1. `original_dart_image`
   DART 원문에서 실제 소유지분도 이미지를 내려받은 경우.

2. `generated_ownership_graph`
   계열회사 섹션의 출자계통도 표에서 `출자사 -> 피출자사 -> 지분율`을 직접 읽은 경우.
   가장 신뢰도가 높은 생성형 그래프다.

3. `generated_control_investment_graph`
   타법인출자 현황 중 구조 근거가 있는 항목만 사용한 경우.
   기준은 `경영참여`, `계열회사`, 또는 일반/단순투자가 아닌 20% 이상 지분이다.

4. `generated_investment_note_graph`
   재무제표 주석의 종속기업투자주식 블록을 이용한 경우.

5. `generated_subsidiary_graph`
   연결대상 종속회사 현황 표에서 지분율을 읽은 경우.

6. `generated_numeric_subsidiary_graph`
   재무제표 주석의 숫자형 종속기업 현황을 이용한 경우.

7. `generated_plain_subsidiary_graph`
   재무제표 주석의 줄글형 종속기업 상세목록을 이용한 경우.

8. `generated_affiliate_directory`
   지분율/방향 정보가 부족하고 계열회사 목록만 있는 경우.

9. `insufficient_data`
   시각화할 근거가 부족한 경우.

## 그래프 방향 규칙

source별 화살표 방향은 반드시 다르게 해석해야 한다.

```text
출자계통도 표:
  출자사 -> 피출자사

타법인출자 현황:
  보고서 회사 -> 출자 대상 회사

연결대상 종속회사/종속기업 현황:
  보고서 회사 -> 종속회사

계열회사 목록만 있는 경우:
  엣지 없음
  목록 또는 directory 형태로 표시
```

## 데이터 사용 원칙

메인 구조도는 KT 소유지분도처럼 기업집단 구조를 보여주는 것이 목적이다.

따라서 타법인출자 전체를 무조건 구조도로 쓰지 않는다.

메인 그래프에 포함하는 타법인출자:

- `경영참여`
- `계열회사`
- 목적이 일반/단순투자가 아니고 지분율이 20% 이상인 항목

메인 그래프에서 제외하는 타법인출자:

- `일반투자`
- `단순투자`
- 20% 미만 소액 지분
- 펀드, 투자조합, 단순 보유성 투자

## 현재 적용된 회사명 필터

그래프에는 확실히 회사명인 값만 올린다.

현재 필터는 다음 값을 회사명에서 제외한다.

- `합 계`, `합계`, `계`
- `외`
- `상장`, `비상장`, `국내`, `해외`, `기타`
- `수량`, `금액`, `법인명`, `회사명`, `상장여부`, `구분`
- `출자사`, `피출자사`, `지분율`, `당사 지분율`, `소유지분율`
- `기준일`, `본문으로 이동`
- `금리 Reset`, `국고채`, `사채권자`
- `자기주식`, `의결권 주식`, `장부금액`
- `2025년`, `12월`, `100%` 같은 날짜/퍼센트 문구
- `Co., Ltd.`, `Inc.`, `LLC`처럼 법적 접미사만 남은 값
- 한 글자 또는 회사명 핵심 텍스트가 1자 이하인 값

중요한 주의점:

`계`를 단순 포함 조건으로 막으면 `계룡건설` 같은 정상 회사명이 빠질 수 있다. 그래서 `계`는 exact match만 제외하고, `합계`/`합 계`는 contains로 제외한다.

## 현재 완료된 검증

현재 완료된 검증은 형식/품질 검증이다.

검증 스크립트:

```text
계열회사시각화/scripts/validate_affiliate_graph_outputs.py
```

실행 명령:

```powershell
cd C:\Users\Admin\Desktop\DART
python 계열회사시각화\scripts\validate_affiliate_graph_outputs.py --strict
```

최종 확인 결과:

```text
issues_total: 0
```

이 검증은 다음을 확인한다.

- metadata JSON이 정상인지
- SVG 파일이 존재하는지
- extracted data JSON이 존재하는지
- source_type이 알려진 값인지
- edge count가 metadata와 맞는지
- 노드/엣지/텍스트에 표 헤더, 기준일, 합계, 한 글자, 잘린 회사명, 법적 접미사만 남은 값이 없는지
- structure diagram의 SVG와 JSON이 깨지지 않았는지

이 검증이 통과했다는 뜻:

```text
그래프 파일과 메타데이터의 형식 품질은 통과했다.
화면에 보이는 노드/엣지에 명백한 쓰레기 라벨은 없다.
```

이 검증이 아직 보장하지 않는 것:

```text
DART 원문과 100% 같은 관계회사 구조를 뽑았다는 뜻은 아니다.
누락이 없는 것도 아직 보장하지 않는다.
지분율과 방향이 원문과 완전히 일치하는지도 별도 검증이 필요하다.
```

## 다음에 필요한 정합성 검증

다음 단계는 DART 원문 근거 기반 정합성 검증이다.

추천 스크립트 이름:

```text
계열회사시각화/scripts/validate_affiliate_source_consistency.py
```

추천 출력:

```text
output/affiliate_source_validation_report.json
output/affiliate_source_validation_issues.csv
output/affiliate_source_validation_summary.md
output/affiliate_manual_review_samples.csv
```

## 정합성 검증 항목

### 1. source_chunk_id 존재 검증

각 edge와 affiliate가 가진 `source_chunk_id`가 원본 JSONL에 실제로 존재하는지 확인한다.

검증 대상:

- `edges[].source_chunk_id`
- `affiliate_companies[].source_chunk_id`
- `supporting_*_edges[].source_chunk_id`

이슈 예시:

```text
missing_source_chunk_id
source_chunk_not_found
```

### 2. 회사명 근거 검증

각 회사명이 source chunk의 `text` 안에 실제로 존재하는지 확인한다.

검증 대상:

- edge `from`
- edge `to`
- affiliate `name`

주의:

회사명은 표기 차이가 있을 수 있다.

예:

```text
삼성전자(주)
삼성전자㈜
삼성전자 주식회사
Samsung Electronics Co., Ltd.
```

따라서 단순 문자열 매칭만 쓰지 말고 정규화 매칭을 병행한다.

정규화 예:

- `(주)`, `㈜`, `주식회사` 제거
- 공백 제거
- 대소문자 무시
- 쉼표/마침표 일부 제거
- `Co., Ltd.`, `Inc.`, `Corporation` 접미사 정규화

이슈 예시:

```text
company_not_found_in_source_chunk
company_match_only_after_normalization
```

### 3. 지분율 근거 검증

edge에 `ownership_rate`가 있으면 source chunk에 같은 숫자가 있는지 확인한다.

검증 방식:

- `100`과 `100.00`은 같은 값으로 본다.
- `%`가 없어도 숫자 컬럼이면 후보로 본다.
- 허용 오차는 `0.01` 정도로 둔다.

이슈 예시:

```text
ownership_rate_not_found_in_source_chunk
ownership_rate_ambiguous
```

### 4. 방향 검증

source_type별 방향 규칙을 검증한다.

검증 기준:

```text
generated_ownership_graph:
  source chunk 표가 출자사/피출자사/지분율 구조이면 from은 출자사, to는 피출자사여야 한다.

generated_control_investment_graph:
  from은 보고서 회사, to는 타법인출자 대상이어야 한다.

generated_subsidiary_graph:
generated_numeric_subsidiary_graph:
generated_plain_subsidiary_graph:
  from은 보고서 회사 또는 확인된 모회사, to는 종속회사여야 한다.

generated_affiliate_directory:
  edge가 없어야 한다.
```

이슈 예시:

```text
edge_direction_unverifiable
edge_direction_mismatch
directory_has_edges
```

### 5. 계열회사 수량 비교 검증

DART 요약 표에 계열회사 수가 있으면, 추출된 `affiliate_companies` 수와 비교한다.

예:

```text
DART 요약: 상장 10 / 비상장 51 / 계 61
추출 결과: affiliate_companies 61
=> 정상 가능성 높음

DART 요약: 계 61
추출 결과: affiliate_companies 12
=> 누락 가능성 높음
```

완전 일치만 강제하지는 않는다.

이유:

- 일부 보고서는 계열회사 수와 표의 상세 목록이 분리되어 있다.
- 원본 이미지 사용 기업은 목록이 비어 있을 수 있다.
- 해외 법인 표기가 여러 줄로 쪼개질 수 있다.

권장 기준:

```text
차이 0~5개: 정상 가능성
차이 6~20개: warning
차이 20개 초과 또는 추출률 50% 미만: manual_review
```

이슈 예시:

```text
affiliate_count_summary_missing
affiliate_count_mismatch_warning
affiliate_count_mismatch_manual_review
```

### 6. source_type별 신뢰도 등급

결과마다 신뢰도 등급을 부여하면 발표와 서비스 설명에 유리하다.

추천 등급:

```text
A: original_dart_image
A-: generated_ownership_graph
B+: generated_control_investment_graph
B: generated_subsidiary_graph / generated_numeric_subsidiary_graph
B-: generated_plain_subsidiary_graph
C: generated_affiliate_directory
D: insufficient_data 또는 근거 불충분
```

단, `original_dart_image`는 원본 이미지 자체는 신뢰도가 높지만, 이미지 내부의 노드/엣지를 구조화한 것은 아니다. DB에는 이미지 경로와 DART URL을 저장하고, 그래프 질의에는 사용할 수 없다고 명시한다.

### 7. 원본 이미지 검증

`original_dart_image`는 다음을 확인한다.

- `visual_path` 파일 존재
- 이미지 크기 0보다 큼
- `dart_main_url` 존재
- `dart_section_url` 존재
- `dart_image_url` 존재
- MIME type이 image 계열

가능하면 샘플 수동 확인도 한다.

이슈 예시:

```text
original_image_file_missing
original_image_url_missing
original_image_too_small
```

### 8. 수동 검토 샘플 추출

자동 검증만으로는 DART 표 구조의 모든 예외를 보장할 수 없다.

따라서 source_type별 샘플을 자동 추출한다.

추천 샘플:

- original image 5개
- generated_ownership_graph 10개
- generated_control_investment_graph 10개
- generated_subsidiary_graph 계열 10개
- generated_affiliate_directory 10개
- insufficient_data/skipped 10개
- 복잡한 그룹사 5개

수동 검토 CSV 컬럼:

```text
stock_code
corp_name
source_type
confidence_grade
visual_path
dart_main_url
source_chunk_id
review_reason
```

## 정합성 검증 리포트 권장 컬럼

CSV 이슈 컬럼:

```text
severity
scope
code
stock_code
corp_name
source_type
message
source_chunk_id
visual_path
metadata_path
```

JSON summary 필드:

```json
{
  "checked_at": "...",
  "records_checked": 2599,
  "edges_checked": 0,
  "affiliates_checked": 0,
  "issues_total": 0,
  "severity_counts": {},
  "source_type_counts": {},
  "confidence_grade_counts": {},
  "issues": []
}
```

## 검증 우선순위

문제가 생겼을 때 우선순위는 다음과 같다.

1. `node`, `edge_from`, `edge_to`, `source`, `target`, `text` 문제
   화면에 바로 보이는 오류라 최우선 수정한다.

2. edge 방향/지분율 오류
   화면에는 자연스러워 보여도 의미가 틀릴 수 있으므로 중요하다.

3. affiliate 목록 누락/오염
   directory와 DB 검색 품질에 영향을 준다.

4. 수량 불일치
   원문 추출 누락 가능성을 보여주는 warning/manual review 대상이다.

5. 검증기 오탐
   정상 회사명인데 검증기가 잡는 경우는 검증기를 완화한다.
   단, 생성 파서 오류를 검증기 무시로 덮으면 안 된다.

## 최종 실행 명령

전체 재생성:

```powershell
cd C:\Users\Admin\Desktop\DART
python 계열회사시각화\scripts\build_affiliate_visualization.py --all --refresh
python 계열회사시각화\scripts\build_affiliate_structure_diagrams.py --all
python 계열회사시각화\scripts\validate_affiliate_graph_outputs.py --strict
```

현재 형식 검증의 최종 기대값:

```text
issues_total: 0
```

특정 종목만 재생성:

```powershell
python 계열회사시각화\scripts\build_affiliate_visualization.py 005490 --refresh --no-dart
python 계열회사시각화\scripts\build_affiliate_structure_diagrams.py --code 005490 --out-dir output\affiliate_structure_batch
python 계열회사시각화\scripts\validate_affiliate_graph_outputs.py --strict --stock-code 005490 --no-write
```

## 추가 보완 검증 후보

현재는 형식 검증이 `issues_total: 0`으로 통과된 상태다.
다만 아래 항목은 원문 정합성과 그래프 논리 검증을 더 강화하려면 추가할 수 있다.

권장 전략:

```text
옵션 A: 문서에 보완 항목만 반영하고 주가 영향 요인 분석으로 이동
옵션 B: A+D만 구현한 뒤 주가 영향 요인 분석으로 이동
옵션 C: 계열회사 검증을 잠시 두고 주가 영향 요인 분석부터 진행
```

현재 추천은 옵션 A다.
계열회사 시각화는 형식 검증을 통과했으므로, 추가 검증은 후속 개선 항목으로 남기고 별도 핵심 기능인 주가 영향 요인 분석으로 넘어가는 것이 효율적이다.

### A. 그래프 위상 검증

우선순위: high

그래프 자체의 구조적 이상을 탐지한다.

검증 항목:

- 자기 참조 엣지: `A -> A`
- 순환 참조: `A -> B -> C -> A`
- 중복 엣지: 같은 `from/to/rate` 반복
- 모순 엣지: 같은 `from/to`인데 지분율이 서로 다름

권장 이슈 코드:

```text
graph_self_loop
graph_cycle_detected
graph_duplicate_edge
graph_conflicting_ownership_rate
```

severity 기준:

- `graph_self_loop`: `warning`
- `graph_cycle_detected`: `manual_review`
- `graph_duplicate_edge`: `warning`
- `graph_conflicting_ownership_rate`: `warning` 또는 `manual_review`

주의:

한국 기업집단에는 순환출자/교차보유가 실제로 존재할 수 있다.
따라서 cycle은 무조건 error로 처리하지 않는다.
메시지에는 "순환출자 구조는 정상일 수 있으므로 원문 확인 필요"라고 명시한다.

### B. 지분율 합계 검증

우선순위: mid

같은 피출자사 `to`에 대해 여러 `from`의 지분율 합이 100%를 크게 초과하는지 확인한다.

기준:

```text
sum(to ownership_rate) <= 100.5: 정상
sum(to ownership_rate) > 100.5: warning
sum(to ownership_rate) > 120: manual_review
```

주의:

모든 주주가 추출되지 않을 수 있으므로 100% 미만은 정상으로 본다.
우선주/보통주, 직접/간접 보유, 연결실체 기준 표가 섞이면 false positive가 생길 수 있다.

권장 이슈 코드:

```text
ownership_sum_exceeds_100
ownership_sum_exceeds_120
```

### C. 시점/기준일 일관성 검증

우선순위: low

한 기업의 시각화 안에 서로 다른 `fiscal_period` 또는 보고서 기준일이 섞였는지 확인한다.

검증 방식:

- 사용된 모든 `source_chunk_id`의 원본 chunk를 찾는다.
- `fiscal_period`, `report_kind`, `rcept_no`가 동일한지 확인한다.
- 섞여 있으면 manual review 대상으로 표시한다.

권장 이슈 코드:

```text
mixed_fiscal_period_warning
mixed_report_reference_warning
```

### D. 회사명 중복 노드 검증

우선순위: high

같은 회사를 표기만 다르게 여러 노드로 만든 경우를 탐지한다.

예:

```text
삼성전자(주)
삼성전자
Samsung Electronics Co., Ltd.
```

검증 방식:

- 모든 node name을 정규화한다.
- 정규화 결과가 같은 노드가 2개 이상이면 warning 처리한다.
- 한글/영문 번역명 매칭은 자동화가 어려우므로 처음에는 단순 정규화 기준으로만 본다.

권장 이슈 코드:

```text
node_likely_duplicate_after_normalization
```

### E. 노드와 stock_code 매핑 검증

우선순위: low

노드 회사명이 상장사라면 상장사 마스터와 매핑 가능한지 확인한다.

검증 방식:

- KRX 또는 프로젝트 내 회사 마스터를 사용한다.
- 한글 회사명이 매우 유사한데 매핑되지 않으면 이름 추출 오류 가능성을 표시한다.
- 해외/비상장 회사는 매핑 실패가 정상일 수 있으므로 error로 보지 않는다.

권장 이슈 코드:

```text
possibly_misnamed_listed_company
listed_company_mapping_ambiguous
```

### F. 누락 감지 검증

우선순위: low

원문에는 근거가 있는데 추출 결과가 빈약한 경우를 잡는다.

예:

- 원문에 `출자계통도`가 있는데 `original_dart_image` 다운로드 실패
- 원문에 `종속회사` 표가 있는데 `source_type=insufficient_data`
- 원문에 `계열회사 현황(상세)`가 있는데 `affiliate_companies`가 비어 있음

권장 이슈 코드:

```text
extraction_skipped_with_evidence_present
source_table_present_but_no_edges
original_image_candidate_not_downloaded
```

### G. 종합 신뢰도 점수

우선순위: mid

회사별 결과에 0~100 점수와 등급을 부여한다.

예시:

```text
confidence_score =
  source_type_base_score
  - missing_evidence_penalty
  - normalization_only_penalty
  - rate_mismatch_penalty
  - graph_anomaly_penalty
```

기본 점수 예:

```text
original_dart_image: 90
generated_ownership_graph: 85
generated_control_investment_graph: 75
generated_subsidiary_graph: 70
generated_numeric_subsidiary_graph: 70
generated_plain_subsidiary_graph: 65
generated_affiliate_directory: 55
insufficient_data: 20
```

주의:

source consistency 검증이 없는 상태에서 점수만 만들면 설득력이 약하다.
따라서 G는 정합성 검증 스크립트 이후 구현하는 것이 좋다.

### H. HTML/특수문자 잔재 검증

우선순위: low

회사명에 HTML entity 또는 제어문자가 남아 있는지 확인한다.

탐지 예:

```text
&nbsp;
&amp;
<br>
</p>
&#xAC00;
연속 공백 2개 이상
유니코드 control 문자
```

권장 이슈 코드:

```text
html_artifact_in_label
control_character_in_label
excessive_whitespace_in_label
```

### 보완 검증 구현 우선순위

```text
1. A + D
   시각화 품질에 바로 연결되고 구현 난이도가 낮다.

2. B + G
   수치 정합성과 UX 가치가 있지만 false positive와 설계 비용이 있다.

3. C + E + F + H
   장기 보완 항목으로 둔다.
```

## 다른 AI에게 요청할 다음 작업

다음 AI가 이어서 할 일은 `validate_affiliate_source_consistency.py`를 만드는 것이다.

작업 조건:

1. 기존 `validate_affiliate_graph_outputs.py`는 형식 검증으로 유지한다.
2. 새 스크립트는 DART 원문 정합성 검증만 담당한다.
3. 기존 생성 로직을 크게 바꾸지 말고, 먼저 검증 리포트부터 만든다.
4. 검증 실패를 무조건 오류로 보지 말고 `error`, `warning`, `manual_review`로 나눈다.
5. source_type별로 검증 기준을 다르게 적용한다.
6. 수동 검토 샘플 CSV를 반드시 생성한다.

추천 구현 순서:

```text
1. metadata와 extracted data 전체 로드
2. stock_code별 RAG JSONL 로드
3. source_chunk_id 인덱스 생성
4. edge/affiliate별 source chunk 존재 검증
5. 회사명 정규화 매칭 검증
6. 지분율 숫자 매칭 검증
7. source_type별 방향 검증
8. 계열회사 요약 수량 추출 및 비교
9. confidence_grade 부여
10. JSON/CSV/Markdown 리포트 저장
```

## 주의할 점

- `issues_total: 0`은 형식 품질 기준 통과이지, 원문 정합성 100% 보장을 의미하지 않는다.
- DART 표는 회사마다 형식이 다르므로 정합성 검증은 warning/manual review를 포함해야 한다.
- 정상 회사명 중 소문자로 시작하는 해외 법인이 있다. 예: `i-SENS USA, INC.`, `nepes US,Inc.`, `broadcom Inc`.
- 반대로 `up LLC`, `oup LLC`, `Co., Ltd.`처럼 잘린 조각도 있다. 검증기는 회사명 핵심 길이와 source evidence로 구분해야 한다.
- 원본 이미지가 있는 기업은 이미지 자체를 신뢰하고, 그래프 edge 정합성 검증 대상에서 제외한다.
- 구조도에 타법인출자 전체를 넣으면 목적과 다르게 단순투자까지 관계회사처럼 보일 수 있다.
