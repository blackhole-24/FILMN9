# 계열회사 시각화 산출물 검토 메모

작성 기준: 2026-06-05

이 문서는 현재 생성된 계열회사 시각화 산출물을 팀 공유/발표 자료로 사용하기 전에 무엇을 확인했고, 어떤 리스크가 남아 있는지 정리한 검토 메모입니다.

## 결론

현재 산출물은 **화면 품질 검증 기준으로 통과**했고, DART 접속 실패로 기존 원본 이미지 metadata가 생성 SVG로 덮이는 문제도 보완했다.

```text
visual_records_checked: 2599
structure_records_checked: 2221
issues_total: 0
original_dart_image: 367
structure_summary_records: 2599
```

즉, 그래프 노드/엣지/SVG 텍스트에 `본문으로 이동`, `기준일`, `합계`, 잘린 회사명, 한 글자 라벨 같은 명백한 오류는 검증 기준상 남아 있지 않다.

또한 DART 원본 이미지를 이미 내려받은 기업은 DART에 다시 접속하지 않아도 기존 `original_affiliate_diagram.*` 파일을 우선 재사용하도록 수정했다. 따라서 DART 접속이 일시적으로 끊겨도 원본 이미지 보유 기업의 metadata가 fallback SVG로 덮이지 않는다.

주의할 점은 남아 있다. 현재 검증은 “화면에 이상한 라벨이 들어가지 않았는지”와 “산출물 파일 구조가 깨지지 않았는지”를 보는 품질 검증이다. DART 원문과 모든 지분 관계가 100% 일치한다는 의미의 원문 정합성 검증은 별도 단계로 봐야 한다.

## 검토한 산출물

```text
output/affiliate_visualization/
output/affiliate_structure_batch/
output/affiliate_validation_report.json
output/affiliate_validation_issues.csv
```

검증 리포트:

```text
output/affiliate_validation_report.json
```

현재 결과:

```json
{
  "visual_records_checked": 2599,
  "structure_records_checked": 2221,
  "issues_total": 0
}
```

## source_type 분포

최신 `affiliate_visual_metadata.json` 기준 source_type 분포는 다음과 같다.

```text
generated_affiliate_directory:        941
generated_control_investment_graph:   888
original_dart_image:                  367
generated_plain_subsidiary_graph:     277
generated_subsidiary_graph:            40
insufficient_data:                     33
generated_numeric_subsidiary_graph:    29
generated_ownership_graph:             24
```

해석:

- 대부분은 DART 표/본문 기반으로 생성한 SVG다.
- `generated_affiliate_directory`와 `generated_control_investment_graph` 비중이 크다.
- DART 원본 이미지를 확인해 저장한 기업은 `original_dart_image` 367개다.
- 직접적인 출자계통도 표 기반인 `generated_ownership_graph`는 24개로 제한적이다.

## 주요 발견사항

### Finding 1. DART 접속 실패 시 원본 이미지 metadata가 fallback SVG로 덮일 수 있었음

검토 당시 `output/affiliate_visualization` 아래에는 원본 이미지 파일이 367개 존재했지만, 마지막 전체 `--refresh` 중 DART 접속이 끊기면서 metadata가 생성 SVG로 덮인 사례가 있었다.

```text
actual original_affiliate_diagram* files: 367
latest original_dart_image metadata count: 367
```

원인 추정:

- 전체 `--refresh` 실행 중 DART 원본 이미지 확인 요청이 일부 `RemoteDisconnected`로 실패했다.
- 실패 시 fallback SVG 생성 결과가 metadata를 덮었다.
- 기존에 내려받은 `original_affiliate_diagram.jpg` 파일은 폴더에 남아 있지만 metadata의 `source_type`, `visual_path`는 생성 SVG를 가리킨다.

영향:

- DART가 일시적으로 끊긴 날에는 원본 이미지 보유 기업도 생성 SVG로 바뀐 것처럼 보일 수 있었다.
- README/발표에서 “그림 있는 기업은 원본 이미지를 우선 사용한다”고 말하려면 이 흐름을 반드시 막아야 했다.

수정 완료:

```text
1. 원본 이미지 파일이 이미 있는 기업은 DART에 재접속하지 않고 기존 original_affiliate_diagram.*를 우선 사용한다.
2. --no-dart는 "원격 DART 호출 생략"으로만 동작하고, 로컬 원본 이미지는 계속 재사용한다.
3. DART 접속 실패가 발생해도 기존 원본 이미지 metadata를 generated SVG metadata로 덮지 않는다.
```

검증 결과:

```text
000180 성창기업지주보통주 단일 refresh 및 strict 검증 통과를 확인했다.
원본 이미지 보유 폴더 367개를 --refresh --no-dart로 재연동했다.
manifest 재생성 후 original_dart_image 367개를 확인했다.
```

관련 이슈명:

```text
original_image_file_exists_but_metadata_fallback: fixed
```

### Finding 2. structure batch summary가 단일 종목 실행 결과로 덮일 수 있었음

검토 당시 `output/affiliate_structure_batch/_summary.json`이 마지막 단일 종목 실행 결과로 덮인 적이 있었다. 검증 스크립트는 각 폴더의 `*_visual_data.json`을 직접 읽기 때문에 strict 검증에는 문제가 없었지만, 팀 공유/발표에서 `_summary.json`을 전체 배치 요약으로 사용하면 잘못된 자료가 될 수 있었다.

수정 완료:

```text
python 계열회사시각화\scripts\build_affiliate_structure_diagrams.py --all
```

현재 `_summary.json` 기준:

```text
generated_structure_diagram: 1999
original_image_reused:        367
skipped_insufficient_data:    222
excluded_security_type:        11
total:                       2599
```

권장 운영 방식:

```text
전체 자료를 공유하기 전에는 build_affiliate_structure_diagrams.py --all 실행 후 _summary.json을 갱신한다.
```

### Finding 3. strict 검증은 형식 품질 검증이다

`issues_total: 0`은 다음을 의미한다.

```text
명백히 잘못된 라벨이 화면에 들어가지 않는다.
metadata와 SVG 파일 구조가 깨지지 않았다.
```

하지만 다음을 보장하지 않는다.

```text
DART 원문과 모든 관계가 정확히 일치한다.
누락된 계열회사가 없다.
지분율과 엣지 방향이 모두 원문과 일치한다.
```

따라서 “정확도 검증 완료”라고 말하면 안 되고, “형식/라벨 품질 검증 완료”라고 표현해야 한다.

### Finding 4. 생성 그래프의 근거 수준이 source_type마다 다르다

신뢰도는 source_type마다 다르다.

권장 표현:

```text
높음:
  generated_ownership_graph
  출자사/피출자사/지분율 표 기반

중간:
  generated_control_investment_graph
  구조성 타법인출자 기준

중간:
  generated_subsidiary_graph
  generated_numeric_subsidiary_graph
  generated_plain_subsidiary_graph
  종속회사/재무제표 주석 기반

낮음:
  generated_affiliate_directory
  관계 방향/지분율 없이 목록만 표시

검토 필요:
  insufficient_data
```

발표나 README에서는 모든 SVG를 같은 정확도처럼 설명하지 않는 것이 좋다.

## 구조도 산출물 현황

`output/affiliate_structure_batch` 기준:

```text
records: 2599
generated_structure_diagram: 1999
original_image_reused:        367
skipped_insufficient_data:    222
excluded_security_type:        11
```

해석:

- 대부분의 구조도는 생성 완료됐고, 원본 이미지가 있는 367개는 생성 SVG 대신 원본 이미지를 재사용한다.
- 222개는 구조도 생성에 충분한 edge가 없어 스킵됐다.
- 11개는 우선주/스팩 등 제외 대상이다.
- 스킵은 오류가 아니라 데이터 부족 상태로 해석한다.

## 수동 검토 추천 샘플

수동 검토는 source_type별로 나눠서 해야 한다.

### generated_ownership_graph

출자계통도 표 기반이라 가장 중요한 검토 대상이다.

추천 샘플:

```text
067630 HLB생명과학
003580 에이치엘비글로벌보통주
004000 롯데정밀화학보통주
000070 삼양홀딩스보통주
000150 두산보통주
```

확인할 것:

- 출자사 -> 피출자사 방향이 맞는지
- 지분율이 원문 표와 같은지
- 자기참조/합계 행이 빠졌는지

### generated_control_investment_graph

구조성 타법인출자 기반이다.

추천 샘플:

```text
005930 삼성전자보통주
028260 삼성물산보통주
096770 SK이노베이션 보통주
005490 POSCO홀딩스
066570 LG전자보통주
```

확인할 것:

- 단순투자/일반투자가 메인 구조도에 과하게 들어가지 않았는지
- 20% 이상 또는 경영참여 기준이 맞는지
- 복잡한 그룹사에서 그래프가 읽을 수 있는지

### generated_affiliate_directory

지분율 없이 목록만 보여주는 경우다.

추천 샘플:

```text
000040 KR모터스보통주
000400 롯데손해보험
000440 중앙에너비스
000540 흥국화재해상보험보통주
041910 폴라리스에이아이파마
```

확인할 것:

- 계열회사 목록에 기준일/합계/주석 문장이 들어가지 않았는지
- 계열회사가 없거나 적은 기업에서 억지로 노드가 만들어지지 않았는지

### generated_subsidiary 계열

추천 샘플:

```text
005380 현대자동차보통주
051910 LG화학보통주
004250 NPC보통주
006060 화승인더스트리보통주
181710 NHN
```

확인할 것:

- 종속회사 표에서 회사명만 깔끔하게 추출됐는지
- 사업내용/결산월/재무수치가 회사명에 섞이지 않았는지

### insufficient_data

추천 샘플:

```text
002450 삼익악기보통주
003470 유안타증권보통주
003850 보령보통주
004960 한신공영보통주
011280 태림포장
```

확인할 것:

- 실제로 계열회사 정보가 없는지
- 원문에는 있는데 파서가 놓친 것은 아닌지

## 발표/팀 공유 시 권장 문구

권장 표현:

```text
DART 사업보고서 JSONL을 기반으로 계열회사 관련 표와 주석을 탐색해 기업별 관계회사 시각화를 생성했다.
명백한 표 헤더/기준일/합계/잘린 회사명이 그래프에 들어가지 않도록 형식 검증을 수행했고, 현재 strict 검증 기준 issues_total 0건을 확인했다.
다만 원문과의 완전 정합성, 누락 여부, 지분율 방향 검증은 후속 source consistency 검증으로 분리한다.
```

피해야 할 표현:

```text
모든 계열회사 관계를 정확히 검증했다.
모든 DART 원본 이미지를 자동으로 사용했다.
지분율과 방향이 원문과 100% 일치한다.
```

## 후속 조치 우선순위

### 1순위. 원본 이미지 metadata 전체 반영

기존 원본 이미지 재사용 로직은 코드에 반영됐다.
다만 전체 metadata에 반영하려면 원본 이미지 보유 종목을 다시 실행해야 한다.

목표:

```text
original_affiliate_diagram.*가 존재하는 기업은 source_type=original_dart_image로 복구
visual_path는 원본 이미지 파일을 가리키도록 수정
```

이 작업을 해야 “이미지 있는 기업은 원본 이미지 사용”이라고 설명할 수 있다.

### 2순위. 전체 structure summary 재생성

현재 `_summary.json`은 전체 summary가 아니다.

목표:

```text
2588개 구조도 기준 전체 summary 생성
```

### 3순위. source consistency 검증

다음 항목을 자동 검증한다.

```text
source_chunk_id 존재 여부
회사명 원문 근거 존재 여부
지분율 숫자 근거 존재 여부
엣지 방향 검증
계열회사 수량 비교
source_type별 confidence grade
```

### 4순위. A+D 보완 검증

문서에 남겨둔 보완 항목 중 먼저 구현할 만한 것은 다음이다.

```text
A. 그래프 위상 검증
D. 회사명 중복 노드 검증
```

단, 순환출자는 한국 기업집단에서 실제로 존재할 수 있으므로 error가 아니라 warning/manual_review로 둔다.

## 최종 판단

현재 산출물은 다음 목적으로 사용 가능하다.

```text
생성 SVG 품질 확인
화면 표시용 프로토타입
팀 공유용 기능 데모
형식 검증 통과 사례
```

다음 목적으로 사용하려면 추가 정리가 필요하다.

```text
DART 원본 이미지 우선 사용 최종본
원문 정합성 검증 완료본
DB 적재용 confidence 포함 최종 데이터
발표에서 정확도까지 주장하는 자료
```
