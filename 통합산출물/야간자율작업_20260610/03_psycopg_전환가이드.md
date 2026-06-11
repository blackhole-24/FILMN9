# 백엔드 SQLite → PostgreSQL(psycopg) 전환 가이드 (초안)

> 작성: 2026-06-10 야간 자율작업 · 대상: backend/routers 7개(sqlite3) + overview.py(pymongo)
> 핵심 권고: **psycopg3(`psycopg`)** 사용 → `conn.execute()`가 그대로 지원돼 수정량 최소화.
> ⚠️ 이 문서는 초안. 실제 코드 수정·검증은 Supabase 연결 확보 후 낮에 함께.

## 0. 왜 psycopg3 인가
| | sqlite3 | psycopg2 | **psycopg3 (권장)** |
|---|---|---|---|
| `conn.execute(sql)` 직접 호출 | ✅ | ❌ (cursor 필요) | ✅ |
| dict 행 반환 | `row_factory=sqlite3.Row` | RealDictCursor | `row_factory=dict_row` |
| placeholder | `?` | `%s` | `%s` |
현재 코드가 전부 `conn.execute(...)` 패턴이라, **psycopg2면 모든 호출을 cursor로 고쳐야** 하지만 **psycopg3면 placeholder(`?`→`%s`)와 연결부만** 바꾸면 됨.

## 1. 공통 DB 헬퍼 신설 — `backend/db.py`
지금은 각 라우터가 `sqlite3.connect(_DB_PATH)`를 직접 호출. **연결을 한 곳으로 모아** 환경변수로 SQLite↔Postgres 전환하게 만든다.

```python
# backend/db.py  (신규)
import os
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite")  # "sqlite" | "postgres"

if DB_BACKEND == "postgres":
    import psycopg
    from psycopg.rows import dict_row
    _DSN = os.getenv("DATABASE_URL")  # Supabase 연결 문자열(.env, 절대 하드코딩 금지)
    def connect():
        # autocommit=False, dict 행 반환 → sqlite3.Row 와 동일하게 행["컬럼"] 접근 가능
        return psycopg.connect(_DSN, row_factory=dict_row)
else:
    import sqlite3
    _DB_PATH = os.getenv("FILMN9_DB", r"C:\Users\Admin\FILMN9\data\filmn9.db")
    def connect():
        c = sqlite3.connect(_DB_PATH)
        c.row_factory = sqlite3.Row
        return c
```
각 라우터는 `from backend.db import connect` 후 `conn = connect()` 만 쓰면 됨. (DSN/경로는 `.env` 에서만, 코드/Git 금지 — 보안 원칙)

## 2. 쿼리 치환 규칙 (전수 적용)
| SQLite | PostgreSQL | 비고 |
|---|---|---|
| `?` placeholder | `%s` | ★전수 치환. `WHERE x=?` → `WHERE x=%s` |
| `INSERT OR REPLACE INTO t ...` | `INSERT INTO t ... ON CONFLICT (pk) DO UPDATE SET ...` | upsert |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` | |
| `strftime('%Y',date)` | `to_char(date::date,'YYYY')` 또는 문자열 slice | date가 TEXT라 `substr` 도 가능 |
| `||` (문자열 연결) | `||` | 동일 — 수정 불필요 |
| `LIMIT n` / `LIMIT n OFFSET m` | 동일 | 수정 불필요 |
| `IFNULL(a,b)` | `COALESCE(a,b)` | |
| `INTEGER` 자동증가 rowid | 없음(자연키라 무관) | 본 스키마 영향 없음 |
| 대소문자 비교 | PG는 기본 대소문자 구분 | `ILIKE` 검토(검색 라우터) |

## 3. 라우터별 영향도
| 파일 | sqlite3 사용 | 주요 작업 | 난이도 |
|---|:--:|---|:--:|
| `ohlcv.py` | ✅ | `?`→`%s`, connect 교체 | 하 |
| `company.py` | ✅ | 〃 | 하 |
| `valuation_summary.py` | ✅ | 〃 + JSON 컬럼은 JSONB | 중 |
| `sectors.py` | ✅ | 〃 + 검색 `LIKE`→`ILIKE` 검토 | 중 |
| `extras.py` | ✅ | 〃 | 하 |
| `admin.py` | ✅ | 〃 + `_scale_match` 등 집계쿼리 점검 | 중 |
| `overview.py` | ✅+pymongo | sqlite 부분 동일 / **Mongo는 DB이관② 별도** | 중 |

> `overview.py`의 MongoDB(pymongo)는 [DB이관②]에서 처리: histories를 Supabase JSONB로 옮기거나 Atlas 유지(하이브리드).

## 4. 전환 절차 (권장 순서)
1. `backend/db.py` 신설 + 7개 라우터의 `sqlite3.connect(...)` → `connect()` 교체.
2. 각 라우터 SQL의 `?` → `%s` 전수 치환 (정규식 `\?`→`%s`, 단 문자열 리터럴 내 `?` 주의).
3. `INSERT OR REPLACE` 사용처 → `ON CONFLICT` 로 수정 (적재 스크립트 쪽 多).
4. `valuations.forecast_*`·`data_sources` 는 JSONB → `json.loads/dumps` 대신 psycopg가 dict 자동 변환.
5. `.env` 에 `DB_BACKEND=postgres` + `DATABASE_URL=...`(Supabase) 설정 → 로컬에서 먼저 검증.
6. healthcheck_full.py 로 전 종목·전 화면 회귀검증 ([DB이관⑤]).

## 5. 데이터 적재 (스키마와 별개)
- 소·중 테이블: `pgloader sqlite://filmn9.db postgresql://...` (자동) 또는 테이블별 CSV `\copy`.
- **ohlcv 1,067만행**: 반드시 `\copy ohlcv FROM 'ohlcv.csv' CSV HEADER;` (INSERT 루프 금지).
- ⚠️ Supabase 무료티어 500MB → ohlcv가 초과 가능. **Pro 전환 또는 ohlcv 기간 축소** 사전 결정([DB이관 선행]).

## 6. 리스크 / 체크포인트
- raw SQL이라 자동도구(pgloader)는 **데이터만** 옮김 → 애플리케이션 쿼리 호환은 위 2번 수작업 필수.
- 날짜가 TEXT("YYYY-MM-DD")로 저장돼 있어 정렬·비교는 문자열로도 동작하나, 범위쿼리 많으면 `DATE` 타입 전환 검토.
- 전환 후 **NO-MOCK 회귀검증**: 숫자 1개도 안 틀리게 SQLite 결과와 대조.
