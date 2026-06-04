# 계열회사 시각화 저장/연동 메모

## 처리 흐름

```text
종목코드 입력
→ RAG JSONL 확인
→ DART 원본 이미지 확인(선택)
→ 원본 이미지가 있으면 jpg/png 저장
→ 없으면 JSONL 표/목록 기반 SVG 생성
→ metadata/data/manifest 저장
→ 프론트는 manifest 또는 MongoDB 문서를 조회해 이미지/SVG 표시
```

## 결과 파일

기본 저장 위치:

```text
output/affiliate_visualization/
```

종목별 폴더:

```text
output/affiliate_visualization/{stock_code}_{corp_name}/
  affiliate_visual_metadata.json
  affiliate_visual_data.json
  original_affiliate_diagram.jpg      # 원본 이미지가 있는 경우
  affiliate_ownership_graph.svg       # 출자계통도 표 기반 생성
  affiliate_investment_graph.svg      # 구조성 타법인출자 표 기반 생성
  affiliate_directory.svg             # 계열회사 목록 기반 생성
```

전체 manifest:

```text
output/affiliate_visualization/_manifest.json
output/affiliate_visualization/_manifest.csv
output/affiliate_visualization/_original_image_candidates.csv
output/affiliate_visualization/_original_image_confirmed.csv
```

## MongoDB 권장 문서 구조

이미지/SVG 파일 자체는 DB에 넣지 않고, 파일 경로와 근거 데이터만 저장한다.
파일은 `output/affiliate_visualization/` 또는 운영 파일 저장소에 두고, MongoDB는 조회/필터링용 메타데이터와 필요 시 그래프 데이터를 가진다.

```json
{
  "stock_code": "005930",
  "corp_name": "삼성전자",
  "corp_code": "00126380",
  "report_kind": "2025-annual",
  "rcept_no": "202603...",
  "rcept_dt": "20260310",
  "source_type": "generated_control_investment_graph",
  "has_original_image": false,
  "has_ownership_rate": true,
  "visual_file_type": "svg",
  "visual_path": "output/affiliate_visualization/005930_삼성전자보통주/affiliate_investment_graph.svg",
  "visual_url": "/static/affiliate_visualization/005930_삼성전자보통주/affiliate_investment_graph.svg",
  "dart_image_url": "",
  "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=202603...",
  "nodes_count": 102,
  "edges_count": 101,
  "affiliate_companies_count": 201,
  "investment_edges_total": 125,
  "structural_investment_edges_total": 101,
  "excluded_investment_edges_total": 24,
  "visual_edges_total": 101,
  "metadata_path": "output/affiliate_visualization/005930_삼성전자보통주/affiliate_visual_metadata.json",
  "extracted_data_path": "output/affiliate_visualization/005930_삼성전자보통주/affiliate_visual_data.json",
  "image_check": {
    "candidate": true,
    "confirmed_original": false,
    "checked_at": "2026-06-04T10:34:12",
    "error": ""
  },
  "created_at": "2026-05-28T16:29:12"
}
```

상세 데이터가 필요하면 `affiliate_visual_data.json`의 `nodes`, `edges`, `affiliate_companies`를 별도 컬렉션이나 같은 문서의 하위 필드로 저장한다.

권장 컬렉션은 하나로 충분하다.

```text
affiliate_visualizations
```

권장 unique key:

```text
stock_code + report_kind + rcept_no
```

자주 조회할 인덱스:

```text
stock_code
source_type
has_original_image
report_kind
rcept_dt
```

원본 이미지 자동 확인은 `_original_image_candidates.csv` 기준으로 실행하고, 확인된 원본 이미지는 `_original_image_confirmed.csv`와 manifest의 `source_type == original_dart_image`로 구분한다.

## source_type 의미

```text
original_dart_image
  DART 원문 이미지가 확인되어 원본 jpg/png를 저장한 경우

generated_ownership_graph
  출자계통도 표에서 출자사 → 피출자사 지분관계를 생성한 경우

generated_control_investment_graph
  타법인출자 현황 중 경영참여/계열회사 또는 20% 이상 등 구조 근거가 있는 관계만 표시한 경우

generated_affiliate_directory
  지분율 없이 계열회사 목록만 있어 구성도 형태로 생성한 경우

insufficient_data
  시각화할 계열회사 근거가 부족한 경우
```

## 프론트 표시 규칙

```text
source_type == original_dart_image
  원본 공시 이미지로 표시

source_type startswith generated_
  생성 SVG로 표시. 생성 SVG는 위→아래 흐름을 기본 방향으로 한다.

source_type == insufficient_data
  "공시 내 계열회사 시각화 근거 부족" 상태 표시
```

화면에는 신뢰도 문구를 함께 보여주는 것이 좋다.

```text
원본 공시 이미지
공시 표 기반 생성
계열회사 목록 기반 생성
지분율 미확인
```

## 실행 명령

전체 JSONL 기반 1차 생성:

```powershell
python scripts/build_affiliate_visualization.py --all --no-dart
```

원본 DART 이미지까지 확인해서 특정 종목 갱신:

```powershell
python scripts/build_affiliate_visualization.py 030200 --refresh
```

manifest 재생성:

```powershell
python scripts/build_affiliate_visual_manifest.py
```
