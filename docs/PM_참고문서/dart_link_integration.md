# DART 공시 원문 연결 가이드

> 네이버증권처럼 종목별 공시 목록 → DART 원문 링크 연결하는 방법

---

## 핵심 구조

```
stock_code (우리 DB)
  → corp_code (ticker_universe.csv에 이미 있음)
  → OpenDART list.json API로 공시 목록 조회
  → rcept_no 추출
  → https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}
```

---

## 1. corp_code는 이미 있음

`ticker_universe.csv`에 `corp_code` 컬럼 포함되어 있음.
별도 매핑 작업 불필요.

| stock_code | corp_code | corp_name |
|------------|-----------|-----------|
| 005930     | 00126380  | 삼성전자  |
| 035420     | 00266961  | NAVER     |

---

## 2. 백엔드: 공시 목록 API 호출

**엔드포인트**: `https://opendart.fss.or.kr/api/list.json`

```python
import requests

def get_disclosures(corp_code: str, api_key: str, years: int = 1) -> list:
    """
    종목의 공시 목록 반환
    반환 항목: report_nm, rcept_no, rcept_dt, dart_url
    """
    from datetime import datetime, timedelta

    end_de = datetime.today().strftime('%Y%m%d')
    bgn_de = (datetime.today() - timedelta(days=365 * years)).strftime('%Y%m%d')

    res = requests.get("https://opendart.fss.or.kr/api/list.json", params={
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "page_count": 100,
        "sort": "date",
        "sort_mth": "desc",
    })
    res.raise_for_status()

    items = res.json().get("list", [])
    return [
        {
            "report_nm": item["report_nm"],
            "rcept_no":  item["rcept_no"],
            "rcept_dt":  item["rcept_dt"],
            "dart_url":  f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item['rcept_no']}",
        }
        for item in items
    ]
```

**공시 유형 필터** (필요 시 파라미터 추가):

| 파라미터                    | 값    | 의미       |
|-----------------------------|-------|------------|
| `pblntf_detail_ty=A001`     | A001  | 사업보고서 |
| `pblntf_detail_ty=A002`     | A002  | 반기보고서 |
| `pblntf_detail_ty=A003`     | A003  | 분기보고서 |

사업보고서만 조회 시:
```python
params["pblntf_detail_ty"] = "A001"
```

---

## 3. 프론트엔드: DART 원문 링크

백엔드에서 `dart_url`을 내려주면 그대로 연결.

```jsx
// React 예시
{disclosures.map((item) => (
  <div key={item.rcept_no}>
    <span>{item.rcept_dt}</span>
    <a
      href={item.dart_url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {item.report_nm}
    </a>
  </div>
))}
```

```html
<!-- 바닐라 HTML -->
<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240312000736"
   target="_blank">
  사업보고서 보기
</a>
```

---

## 4. API 응답 예시

```json
{
  "status": "000",
  "message": "정상",
  "list": [
    {
      "corp_code": "00126380",
      "corp_name": "삼성전자",
      "stock_code": "005930",
      "report_nm": "사업보고서",
      "rcept_no": "20240312000736",
      "rcept_dt": "20240312"
    }
  ]
}
```

---

## 5. 주의사항

- OpenDART API 키는 [https://opendart.fss.or.kr](https://opendart.fss.or.kr) 에서 발급
- 일일 호출 한도: 20,000건 (무료)
- `dart_url`은 백엔드에서 조합해서 내려주는 게 깔끔 (프론트에서 rcept_no만 받아 조합해도 무방)
- DART 뷰어는 PC 브라우저 최적화 — 모바일 UX 주의
