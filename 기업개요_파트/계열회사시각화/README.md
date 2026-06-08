# 계열회사 시각화

DART 사업보고서 JSONL 데이터를 기반으로 기업의 계열회사 정보를 시각화하는 모듈입니다.
공시 원문에 이미 제공된 소유지분도 이미지가 있으면 원본 이미지를 저장하고, 이미지가 없으면 JSONL의 표 데이터를 이용해 SVG 구조도를 생성합니다.

## 처리 방식

1. `RAG/*.jsonl`에서 계열회사, 종속기업, 구조성 타법인출자, 소유지분도 관련 섹션을 탐색합니다.
2. DART 원문 뷰어에서 소유지분도 이미지를 찾을 수 있으면 `original_dart_image`로 저장합니다.
3. 원본 이미지가 없으면 데이터 수준에 따라 SVG를 생성합니다.
4. 생성 결과와 메타데이터를 `output/affiliate_visualization/`에 저장합니다.
5. `_manifest.csv`, `_manifest.json`을 만들어 프론트엔드나 MongoDB 적재에서 사용할 수 있게 합니다.

## source_type 기준

- `original_dart_image`: DART 원문에서 가져온 실제 소유지분도 이미지
- `generated_ownership_graph`: 지분율이 있는 출자계통도 표 기반 SVG
- `generated_control_investment_graph`: 타법인출자 중 경영참여/계열회사 또는 20% 이상 등 구조 근거가 있는 관계 기반 SVG
- `generated_investment_note_graph`: 재무제표 주석 종속기업투자주식 블록 기반 SVG
- `generated_subsidiary_graph`: 연결대상 종속회사 현황 표 기반 SVG
- `generated_numeric_subsidiary_graph`: 재무제표 주석의 숫자형 종속기업 현황 기반 SVG
- `generated_plain_subsidiary_graph`: 재무제표 주석의 줄글형 종속기업 상세목록 기반 SVG
- `generated_affiliate_directory`: 지분율 없이 계열회사 목록만 있는 경우의 그룹 목록 SVG
- `insufficient_data`: 시각화에 쓸 수 있는 구조 데이터가 부족한 경우

## 데이터 사용 기준

메인 구조도는 KT 소유지분도처럼 계열회사와 지배/관계 구조를 설명하는 것을 목표로 합니다.
따라서 단순 보유성 `타법인출자 현황(상세)` 전체를 구조도에 사용하지 않습니다.

구조도에 사용하는 데이터 우선순위는 다음과 같습니다.

1. DART 원문 소유지분도/출자계통도 이미지 또는 표
2. 계열회사 출자계통도 표
3. 구조 근거가 있는 타법인출자
4. 연결대상 종속회사/종속기업 현황
5. 지분율이 없는 계열회사 목록

타법인출자는 다음 기준을 통과한 경우에만 메인 구조도에 표시합니다.

- `경영참여` 또는 `계열회사` 목적
- 목적이 일반/단순투자가 아니고 지분율이 20% 이상인 경우

다음 항목은 메인 구조도에서 제외하고, 메타데이터의 보조 정보로만 남깁니다.

- `일반투자`
- `단순투자`
- 20% 미만 소액 지분
- 투자조합, 펀드, 단순 보유성 투자

## 폴더 구조

```text
계열회사시각화/
  README.md
  scripts/
    build_affiliate_visualization.py
    build_affiliate_structure_diagrams.py
    build_affiliate_visual_manifest.py
    classify_affiliate_visual_sources.py
    refresh_affiliate_original_image_candidates.py
    sync_affiliate_visualizations_to_mongo.py
    validate_affiliate_graph_outputs.py
  notebooks/
    05_affiliate_visualization_probe.py
  docs/
    affiliate_visualization_storage.md
  samples/
    manifest_sample.csv
    affiliate_visual_classification_summary.json
    030200_케이티보통주/
    005930_삼성전자보통주/
    000070_삼양홀딩스보통주/
    000040_KR모터스보통주/
  samples_graphviz_style/
    000070_삼양홀딩스_graphviz_style.svg
    005930_삼성전자_graphviz_style.svg
    ...
  samples_structure_diagrams/
    005930_samsung_electronics/
    028260_samsung_ct/
    000070_samyang_holdings/
    096770_sk_innovation/
    005490_posco_holdings/
```

## 실행 방법

프로젝트 루트에 `RAG/` 폴더가 있는 상태에서 실행합니다. 이 폴더를 하위 기능 폴더로 올려도 스크립트가 상위 폴더의 `RAG/`를 자동으로 찾습니다.

전체 종목을 JSONL 기반 SVG 중심으로 재생성할 때는 다음 순서로 실행합니다.

```powershell
cd <프로젝트_루트>

python 계열회사시각화\scripts\classify_affiliate_visual_sources.py
python 계열회사시각화\scripts\build_affiliate_visualization.py --all --refresh --no-dart
python 계열회사시각화\scripts\build_affiliate_structure_diagrams.py --all
python 계열회사시각화\scripts\build_affiliate_visual_manifest.py
```

DART 원본 이미지까지 확인해야 하는 단건은 `--no-dart` 없이 실행합니다.

```powershell
python 계열회사시각화\scripts\build_affiliate_visualization.py 030200 --refresh
python 계열회사시각화\scripts\build_affiliate_visualization.py 005930 --refresh
python 계열회사시각화\scripts\build_affiliate_visual_manifest.py
```

DART 원본 이미지 후보를 일괄 갱신할 때는 다음 명령을 사용합니다.

```powershell
python 계열회사시각화\scripts\refresh_affiliate_original_image_candidates.py --sleep 0.25 --progress-every 50
python 계열회사시각화\scripts\build_affiliate_visual_manifest.py
```

후보 CSV에 잡히지 않은 기업까지 원본 이미지 누락을 더 줄이려면 manifest 전체에서 아직 원본 이미지가 아닌 기업을 대상으로 확인합니다.
연 1회 운영 배치에서는 이 방식을 권장합니다.

```powershell
python 계열회사시각화\scripts\refresh_affiliate_original_image_candidates.py --source manifest --sleep 0.25 --progress-every 50
python 계열회사시각화\scripts\build_affiliate_visual_manifest.py
```

MongoDB 저장까지 진행할 때는 manifest 생성 이후 다음 순서로 실행합니다.

```powershell
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py --dry-run
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py
```

단건 저장/검증은 다음처럼 실행합니다.

```powershell
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py --dry-run --stock-code 030200
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py --stock-code 030200
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py --find --stock-code 030200
```

그래프 품질 검증은 다음 명령으로 실행합니다.

```powershell
python 계열회사시각화\scripts\validate_affiliate_graph_outputs.py --stock-code 000590 --strict
python 계열회사시각화\scripts\validate_affiliate_graph_outputs.py
```

검증 스크립트는 다음 문제를 자동으로 찾습니다.

- `산`, `스`, `재`처럼 한 글자로 잘린 회사명
- `CO.,LTD`, `Ltd.`처럼 법인격 접미사만 남은 회사명
- `본문으로 이동`, `합계`, `수량`, `금액` 같은 표/문서 노이즈
- metadata/data/SVG 파일 누락
- edge 수와 메타데이터 count 불일치

검증 결과는 기본적으로 다음 파일에 저장됩니다.

```text
output/affiliate_validation_report.json
output/affiliate_validation_issues.csv
```

계열회사 구조도 배치만 다시 만들 때는 다음 명령을 사용합니다.

```powershell
python 계열회사시각화\scripts\build_affiliate_structure_diagrams.py --all
```

일부 종목만 검증할 때는 다음처럼 실행합니다.

```powershell
python 계열회사시각화\scripts\build_affiliate_structure_diagrams.py --code 028260
python 계열회사시각화\scripts\build_affiliate_structure_diagrams.py --code 0007J0 --code 462020
```

## 산출물

시각화 원천 결과는 `output/affiliate_visualization/`에 저장됩니다.

```text
output/affiliate_visualization/
  _manifest.csv
  _manifest.json
  _original_image_candidates.csv
  _original_image_confirmed.csv
  <종목코드_회사명>/
    affiliate_visual_metadata.json
    affiliate_visual_data.json
    affiliate_*.svg 또는 original_affiliate_diagram.*
```

계열회사 구조도 배치 결과는 `output/affiliate_structure_batch/`에 저장됩니다.

```text
output/affiliate_structure_batch/
  _summary.json
  <종목코드_회사명>/
    *_affiliate_structure.svg
    *_visual_data.json
```

`_manifest.csv`와 `_manifest.json`은 프론트엔드 조회나 MongoDB 적재용 요약 데이터입니다.
타법인출자 필터링 결과를 확인할 수 있도록 다음 컬럼을 포함합니다.

- `investment_edges_total`: 공시에서 추출된 타법인출자 edge 수
- `structural_investment_edges_total`: 메인 구조도에 사용할 수 있는 구조성 타법인출자 edge 수
- `excluded_investment_edges_total`: 일반/단순투자 등으로 구조도에서 제외된 타법인출자 edge 수
- `visual_edges_total`: 실제 시각화에 사용된 edge 수

`_original_image_candidates.csv`는 KT처럼 DART 원문에 소유지분도/계통도 이미지가 있을 가능성이 있는 기업 후보 목록입니다.
원본 이미지 후보 갱신 전에는 후보가 752개였고, `refresh_affiliate_original_image_candidates.py` 실행 후에는 원본 이미지 345개를 확정 저장했으며 fallback 후보 407개가 남았습니다.
단, 후보 CSV는 분류 로직상 보수적으로 잡히므로 KT처럼 생성 SVG로 남은 기업까지 다시 검사하려면 `--source manifest` 옵션을 사용합니다.

후보 CSV에는 다음 정보가 들어갑니다.

- `stock_code`: 종목코드
- `corp_name`: 회사명
- `source_type`: 현재 JSONL 기반으로 생성된 fallback 결과 유형
- `classification`: 원본 이미지 확인이 필요한 이유
- `rcept_no`: 공시 접수번호
- `source_url`: DART 원문 URL

예를 들어 KT 외에도 `경방`, `삼양홀딩스`, `하이트진로`, `CJ대한통운`, `기아`, `한화손해보험` 등이 원본 이미지 확인 후보 또는 확정 원본 이미지 목록에 포함될 수 있습니다.

원본 이미지 자동 확인/다운로드 흐름은 다음과 같습니다.

```powershell
python 계열회사시각화\scripts\refresh_affiliate_original_image_candidates.py --source manifest --sleep 0.25 --progress-every 50
python 계열회사시각화\scripts\build_affiliate_visual_manifest.py
```

첫 번째 명령은 후보 기업만 순회하면서 DART 원본 이미지를 확인하고, 이미지가 있으면 `original_affiliate_diagram.*`로 저장합니다.
두 번째 명령은 결과를 다시 집계해서 `_manifest.csv`, `_manifest.json`, `_original_image_candidates.csv`, `_original_image_confirmed.csv`를 갱신합니다.
`_original_image_confirmed.csv`는 실제 이미지 다운로드가 확인된 기업만 따로 모은 목록입니다.

## MongoDB 저장

서비스 조회용으로는 MongoDB 저장을 권장합니다.
이미지/SVG 파일 자체는 DB에 넣지 않고 `output/affiliate_visualization/` 또는 운영 파일 저장소에 두며, MongoDB에는 조회와 캐싱에 필요한 메타데이터만 저장합니다.

기본 컬렉션은 다음과 같습니다.

```text
DB: filmn9
Collection: affiliate_visualizations
Unique key: stock_code + report_kind + rcept_no
```

MongoDB 연결 정보는 코드에 직접 넣지 않고 `.env`에 저장합니다.

```text
MONGO_URI=mongodb+srv://...
MONGO_DB=filmn9
AFFILIATE_VISUAL_COLLECTION=affiliate_visualizations
```

실제 적재 전에는 항상 `--dry-run`으로 manifest가 정상 로드되는지 확인합니다.

```powershell
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py --dry-run
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py
```

스크립트는 `_manifest.json`의 각 record를 다음 기준으로 upsert합니다.

- `stock_code`
- `report_kind`
- `rcept_no`

주요 저장 필드는 다음과 같습니다.

- `stock_code`, `corp_name`, `corp_code`
- `report_year`, `report_kind`, `rcept_no`, `rcept_dt`
- `source_type`, `asset_kind`, `status`
- `has_original_image`, `has_ownership_rate`, `has_visual`
- `visual_path`, `visual_url`, `dart_image_url`, `source_url`
- `nodes_count`, `edges_count`, `affiliate_companies_count`
- `investment_edges_total`, `structural_investment_edges_total`, `excluded_investment_edges_total`, `visual_edges_total`
- `metadata_path`, `extracted_data_path`
- `manifest_generated_at`, `synced_at`

프론트엔드는 사용자가 종목을 검색하면 MongoDB에서 최신 `stock_code` 결과를 조회하고, `source_type == original_dart_image`이면 원본 이미지를, `source_type`이 `generated_`로 시작하면 생성 SVG를 보여주면 됩니다.
상세 인터랙션이 필요해지면 `affiliate_visual_data.json`의 `nodes`, `edges`, `affiliate_companies`를 별도 컬렉션이나 같은 문서 하위 필드로 추가 적재합니다.

## 운영 주기

계열회사 구조는 주가처럼 매일 변하는 데이터가 아니므로, 기본 운영은 연 1회 전체 배치가 적합합니다.
사업보고서가 나온 뒤 전체 재생성, 원본 이미지 후보 갱신, manifest 생성, MongoDB upsert 순서로 실행합니다.

```powershell
cd <프로젝트_루트>

python 계열회사시각화\scripts\build_affiliate_visualization.py --all --refresh --no-dart
python 계열회사시각화\scripts\build_affiliate_visual_manifest.py
python 계열회사시각화\scripts\refresh_affiliate_original_image_candidates.py --sleep 0.25 --progress-every 50
python 계열회사시각화\scripts\build_affiliate_visual_manifest.py
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py --dry-run
python 계열회사시각화\scripts\validate_affiliate_graph_outputs.py --strict
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py
```

정정공시, 신규상장, 누락 기업이 있으면 전체 배치 대신 해당 종목만 refresh 후 MongoDB에 단건 upsert합니다.

```powershell
python 계열회사시각화\scripts\build_affiliate_visualization.py 030200 --refresh
python 계열회사시각화\scripts\build_affiliate_visual_manifest.py
python 계열회사시각화\scripts\sync_affiliate_visualizations_to_mongo.py --stock-code 030200
```

## 샘플

- 원본 이미지 예시: `samples/030200_케이티보통주/original_affiliate_diagram.jpg`
- 삼성전자: `samples/005930_삼성전자보통주/affiliate_investment_graph.svg`
- 삼양홀딩스: `samples/000070_삼양홀딩스보통주/affiliate_ownership_graph.svg`
- KR모터스: `samples/000040_KR모터스보통주/affiliate_directory.svg`
- Graphviz 스타일 개선안: `samples_graphviz_style/`
- 계열회사 구조도 재시각화: `samples_structure_diagrams/`

Graphviz 스타일 개선안은 원본 이미지가 없는 기업의 SVG 품질을 높이기 위한 비교 샘플입니다.
현재 PC에는 Graphviz `dot.exe`가 없어 실제 Graphviz 렌더링 대신 같은 Top-to-Bottom 규칙을 적용한 fallback SVG/PNG를 생성했습니다.
`dot.exe`가 설치된 환경에서는 함께 저장된 `.dot` 파일을 Graphviz로 렌더링할 수 있습니다.

계열회사 구조도 재시각화는 `build_affiliate_structure_diagrams.py`로 생성합니다.
각 기업별로 다음 파일을 함께 저장합니다.

- `*_affiliate_structure.svg`, `*_affiliate_structure.png`: 계열회사 구조도 메인 산출물
- `*_graphviz.dot`: Graphviz 렌더링용 DOT 파일
- `*_networkx.png`: NetworkX/Matplotlib 비교안
- `*_sankey.html`: Plotly Sankey 비교안
- `*_visual_data.json`: 사용 edge와 생성 메타데이터

삼성전자와 삼성물산은 단일 보고서만 쓰지 않고 삼성전자, 삼성물산, 삼성전기, 삼성SDI, 삼성SDS, 삼성생명, 삼성화재 등 삼성 주요 계열 보고서 데이터를 병합해 삼성그룹 공통 구조도로 생성합니다.

## 현재 검증 결과

전체 2,599개 기업을 생성하고 원본 이미지 후보 752개를 자동 확인한 뒤 source_type 분포는 다음과 같습니다.

```text
generated_control_investment_graph  881
generated_affiliate_directory       875
generated_plain_subsidiary_graph    353
original_dart_image                 345
generated_subsidiary_graph           41
generated_ownership_graph            37
generated_numeric_subsidiary_graph   34
insufficient_data                    32
generated_investment_note_graph       1
```

원본 이미지 후보 갱신 결과는 `success=752`, `original_image=345`, `fallback=407`, `failed=0`입니다.
즉, 원본 이미지가 확인된 기업은 `original_dart_image`로 저장했고, 이미지가 없거나 확정되지 않은 기업은 JSONL 기반 생성 SVG로 fallback 처리했습니다.

원본 이미지와 생성 SVG는 Git에 전체 업로드하지 않고, 운영에서는 `output/affiliate_visualization/` 또는 별도 파일 저장소에 저장한 뒤 MongoDB에는 파일 경로, source_type, 생성 시각, 원천 공시 정보, 노드/엣지 수 같은 메타데이터를 저장하는 방식을 권장합니다.

계열회사 구조도 전 종목 배치 결과는 `generated_structure_diagram` 2,370개, `no_affiliates` 185개, `skipped_insufficient_data` 33개, `excluded_security_type` 11개, 오류 0개입니다. 이번 배치는 `--no-dart` 결과 기준이므로 `original_image_reused`는 별도 집계하지 않았습니다. 우선주/스팩은 기본 배치에서 제외하고, DART 내부 링크 문구인 `본문으로 이동`류 텍스트는 계열회사명에서 필터링합니다.

## 계열회사 구조도 status 기준

- `generated_structure_diagram`: 원본 이미지가 없어 계열회사 구조도 SVG를 새로 생성
- `original_image_reused`: DART 원본 이미지가 있어 원본 이미지 경로를 재사용
- `no_affiliates`: 계열회사가 없어 구조도 생성 생략
- `skipped_insufficient_data`: 원천/파싱 데이터가 부족해 구조도 생성 생략
- `excluded_security_type`: 우선주/스팩 제외
- `error`: 실행 오류

## 제외한 것

`.env`, API 키, 전체 `output/affiliate_visualization/`, 전체 `RAG/` 원천 데이터는 이 업로드 폴더에 포함하지 않았습니다.
