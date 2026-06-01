# DART 공급계약 공시 연결 가이드

> 기업별 "단일판매·공급계약 체결/해지" 공시를 뽑아서 화면에 보여주는 방법

---

## 핵심 구조

```
stock_code (우리 DB)
  → corp_code (ticker_universe.csv에 이미 있음)
  → OpenDART list.json API (거래소공시 I / 수시공시 I001)
  → report_nm에서 "단일판매공급계약체결/해지" 필터링
  → https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}
```

> OpenDART에 계약공시 전용 구조화 API는 없음.  
> 공시 목록 API + `report_nm` 필터링이 현실적인 방법.

---

## 1. 백엔드: 공급계약 공시 목록 조회

```python
import requests
from datetime import datetime

def get_supply_contract_disclosures(corp_code: str, api_key: str, years: int = 3) -> list:
    """
    단일판매·공급계약 체결/해지 공시 목록 반환
    반환 항목: corp_name, report_nm, event_type, rcept_dt, dart_url
    """
    end_de = datetime.today().strftime("%Y%m%d")
    bgn_de = str(int(end_de[:4]) - years) + end_de[4:]

    res = requests.get("https://opendart.fss.or.kr/api/list.json", params={
        "crtfc_key":          api_key,
        "corp_code":          corp_code,
        "bgn_de":             bgn_de,
        "end_de":             end_de,
        "pblntf_ty":          "I",      # 거래소공시
        "pblntf_detail_ty":   "I001",   # 수시공시
        "page_count":         100,
        "sort":               "date",
        "sort_mth":           "desc",
    })
    res.raise_for_status()

    results = []
    for item in res.json().get("list", []):
        # 특수문자·공백 제거 후 판단 (정정, 자율공시 등 변형 대응)
        normalized = (
            item.get("report_nm", "")
            .replace("ㆍ", "").replace("·", "").replace(" ", "")
        )
        if "단일판매공급계약체결" in normalized:
            event_type = "계약체결"
        elif "단일판매공급계약해지" in normalized:
            event_type = "계약해지"
        else:
            continue

        rcept_no = item["rcept_no"]
        results.append({
            "corp_name":  item.get("corp_name"),
            "stock_code": item.get("stock_code"),
            "report_nm":  item.get("report_nm"),
            "event_type": event_type,
            "rcept_dt":   item.get("rcept_dt"),   # "20260520"
            "rcept_no":   rcept_no,
            "dart_url":   f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        })
    return results
```

**`report_nm` 변형 예시** (위 코드로 모두 잡힘):

| 실제 report_nm | 분류 |
|----------------|------|
| 단일판매ㆍ공급계약체결 | 계약체결 |
| [정정]단일판매ㆍ공급계약체결 | 계약체결 |
| 단일판매ㆍ공급계약체결(자율공시) | 계약체결 |
| 단일판매ㆍ공급계약해지 | 계약해지 |
| 단일판매ㆍ공급계약해지(자회사의 주요경영사항) | 계약해지 |

---

## 2. 프론트엔드: 계약 공시 카드

```jsx
// React 예시
function SupplyContractSection({ disclosures }) {
  if (!disclosures.length) return null;

  return (
    <section>
      <h3>주요 계약 공시</h3>
      <table>
        <thead>
          <tr>
            <th>공시일</th>
            <th>유형</th>
            <th>공시명</th>
            <th>원문</th>
          </tr>
        </thead>
        <tbody>
          {disclosures.map((item) => (
            <tr key={item.rcept_no}>
              <td>{item.rcept_dt}</td>
              <td>{item.event_type}</td>  {/* 계약체결 / 계약해지 */}
              <td>{item.report_nm}</td>
              <td>
                <a href={item.dart_url} target="_blank" rel="noopener noreferrer">
                  DART 원문
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

화면 예시:
```
[주요 계약 공시]
공시일       유형      공시명                    원문
2026-05-20  계약체결  단일판매ㆍ공급계약체결     DART 원문 →
2025-05-08  계약해지  단일판매ㆍ공급계약해지     DART 원문 →
```

---

## 3. DB 테이블 (MVP 기준)

1차 구현은 목록 정보만 저장해도 충분함.

```sql
CREATE TABLE supply_contract_disclosures (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    corp_code   VARCHAR(8)   NOT NULL,
    stock_code  VARCHAR(6),
    corp_name   VARCHAR(100),
    rcept_no    VARCHAR(14)  NOT NULL UNIQUE,
    rcept_dt    DATE,
    report_nm   VARCHAR(255),
    event_type  VARCHAR(20),   -- '계약체결' / '계약해지'
    dart_url    TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

2차 고도화 시 아래 컬럼 추가 (원문 파싱 필요):

```sql
ALTER TABLE supply_contract_disclosures ADD COLUMN contract_amount  BIGINT NULL;
ALTER TABLE supply_contract_disclosures ADD COLUMN sales_ratio      DECIMAL(10,2) NULL;
ALTER TABLE supply_contract_disclosures ADD COLUMN counterparty     VARCHAR(255) NULL;
ALTER TABLE supply_contract_disclosures ADD COLUMN contract_start   DATE NULL;
ALTER TABLE supply_contract_disclosures ADD COLUMN contract_end     DATE NULL;
ALTER TABLE supply_contract_disclosures ADD COLUMN termination_reason TEXT NULL;
```

---

## 4. 단계별 구현 로드맵

```
1차 (MVP)
  OpenDART list.json → report_nm 필터링 → DART 링크 제공
  → "최근 주요 계약 공시" 목록만 보여줘도 투자자에게 유용

2차 (고도화)
  document.xml API → 원문 파싱
  → 계약금액, 매출액 대비 비율, 계약상대, 계약기간, 해지사유 추출

3차 (분석)
  계약 체결/해지일 전후 주가 변동, 매출 기여 가능성까지 연결
```

---

## 5. 주의사항

- `[정정]` 공시는 이전 체결 공시의 내용 수정 → 화면에서 묶어서 표시 권장
- `pblntf_ty=I` + `pblntf_detail_ty=I001` 조합으로 거래소 수시공시만 조회
- 일일 API 호출 한도: 20,000건 (무료)
- `corp_code`는 `ticker_universe.csv`에서 가져오면 됨 (별도 매핑 불필요)
