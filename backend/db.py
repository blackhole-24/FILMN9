"""DB 접근 단일 진입점 — SQLite ↔ PostgreSQL(Supabase) 전환 헬퍼.

환경변수 DB_BACKEND 로 백엔드를 고른다. 기본 'sqlite'(기존 동작 그대로).
  - DB_BACKEND=sqlite    : 로컬 SQLite (현행, 변경 없음)
  - DB_BACKEND=postgres  : Supabase/PostgreSQL (DATABASE_URL 필요, psycopg3)

라우터는 `from backend.db import connect` 후 `conn = connect()` 만 쓰면 된다.
반환 연결은 sqlite3.Row / psycopg dict_row 로 둘 다 row["컬럼"] 접근이 동일하게 동작.

⚠️ 보안: DATABASE_URL·키는 .env 에서만 읽는다. 코드/Git 에 절대 하드코딩 금지.
⚠️ placeholder: SQLite는 '?', PostgreSQL은 '%s'. postgres 모드에서는 SQL의 '?'를
   '%s' 로 변환해 실행한다(아래 _PgConn 래퍼). 라우터 SQL 수정 없이 점진 전환 가능.
"""
from __future__ import annotations

import os
from pathlib import Path

# .env 로드 (DATABASE_URL·DB_BACKEND 를 .env 에서만 읽음 — 코드 하드코딩 금지)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").lower()


# ─────────────────────────────────────────────────────────────
# SQLite (현행)
# ─────────────────────────────────────────────────────────────
if DB_BACKEND == "sqlite":
    import sqlite3

    _DB_PATH = os.getenv("FILMN9_DB", r"C:\Users\Admin\FILMN9\data\filmn9.db")

    def connect():
        c = sqlite3.connect(_DB_PATH, timeout=30.0)
        c.row_factory = sqlite3.Row
        return c

    PLACEHOLDER = "?"


# ─────────────────────────────────────────────────────────────
# PostgreSQL / Supabase (이관 대상) — psycopg3
# ─────────────────────────────────────────────────────────────
elif DB_BACKEND == "postgres":
    import psycopg

    _DSN = os.getenv("DATABASE_URL")  # .env 전용 (예: postgresql://user:pw@host:5432/db)
    if not _DSN:
        raise RuntimeError(
            "DB_BACKEND=postgres 인데 DATABASE_URL 이 없습니다. .env 에 설정하세요."
        )

    # sqlite3.Row 처럼 인덱스(r[0])와 키(r["col"]) 둘 다 지원 + dict(r) 변환 가능.
    # → 라우터의 row[0] / row["col"] / dict(r) 코드를 수정 없이 그대로 호환.
    class _HybridRow:
        __slots__ = ("_cols", "_vals", "_map")
        def __init__(self, cols, vals):
            self._cols, self._vals, self._map = cols, vals, None
        def _m(self):
            if self._map is None:
                self._map = dict(zip(self._cols, self._vals))
            return self._map
        def __getitem__(self, k):
            return self._vals[k] if isinstance(k, int) else self._m()[k]
        def get(self, k, default=None):
            return self._m().get(k, default)
        def keys(self):
            return self._cols
        def values(self):
            return self._vals
        def __iter__(self):
            return iter(self._vals)
        def __len__(self):
            return len(self._vals)

    def _hybrid_row(cursor):
        cols = [c.name for c in cursor.description] if cursor.description else []
        def maker(values):
            return _HybridRow(cols, list(values))
        return maker

    dict_row = _hybrid_row  # connect() 에서 사용

    class _PgConn:
        """sqlite3.Connection 과 유사한 최소 인터페이스 래퍼.

        - conn.execute(sql, params) 직접 호출 지원 (psycopg3 기본 제공)
        - SQL 내 '?' placeholder 를 '%s' 로 자동 변환 → 라우터 SQL 무수정 전환
        - 행은 dict_row 라 row["컬럼"] 접근이 sqlite3.Row 와 동일
        """

        def __init__(self, raw):
            self._raw = raw

        def execute(self, sql, params=()):
            # 리터럴 %(LIKE '%키워드%' 등)를 %% 로 이스케이프한 뒤 ? → %s 변환.
            # (psycopg3는 % 를 placeholder 로 해석 → LIKE 패턴이 500 에러 유발)
            sql2 = sql.replace("%", "%%").replace("?", "%s")
            return self._raw.execute(sql2, params)

        def cursor(self, *a, **k):
            return self._raw.cursor(*a, **k)

        def commit(self):
            return self._raw.commit()

        def rollback(self):
            return self._raw.rollback()

        def close(self):
            return self._raw.close()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def connect():
        raw = psycopg.connect(_DSN, row_factory=dict_row, autocommit=True)
        return _PgConn(raw)

    PLACEHOLDER = "%s"


else:
    raise RuntimeError(f"알 수 없는 DB_BACKEND: {DB_BACKEND} (sqlite|postgres)")
