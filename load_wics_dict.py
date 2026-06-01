# -*- coding: utf-8 -*-
"""WICS 78업종 유사어 사전 → SQLite 적재
   handover/claude AI_WICS78업종유사어사전_2026-05-29.md 파일에서
   JSON 사전 부분을 추출해 wics_keywords 테이블에 저장
"""
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
MD   = ROOT / "handover" / "claude AI_WICS78업종유사어사전_2026-05-29.md"


def extract_json_dict(md_text: str) -> dict:
    """마크다운에서 ```json ... ``` 블록 추출 후 파싱"""
    m = re.search(r"```json\s*(\{.*?\})\s*```", md_text, re.DOTALL)
    if not m:
        raise ValueError("JSON 블록을 찾을 수 없음")
    raw = m.group(1)
    return json.loads(raw)


def main():
    text = MD.read_text(encoding="utf-8")
    wics_dict = extract_json_dict(text)
    print(f"WICS 사전 파싱: {len(wics_dict)}개 업종")

    conn = sqlite3.connect(DB)
    # 스키마 생성
    conn.executescript("""
        DROP TABLE IF EXISTS wics_keywords;
        CREATE TABLE wics_keywords (
            wics_name   TEXT NOT NULL,
            keyword     TEXT NOT NULL,
            keyword_norm TEXT NOT NULL,   -- 공백·대소문자 정규화
            PRIMARY KEY (wics_name, keyword)
        );
        CREATE INDEX idx_wics_kw_norm ON wics_keywords(keyword_norm);
    """)

    total = 0
    for wics_name, keywords in wics_dict.items():
        for kw in keywords:
            kw_norm = re.sub(r"\s+", "", kw).lower()
            conn.execute(
                "INSERT OR REPLACE INTO wics_keywords (wics_name, keyword, keyword_norm) VALUES (?, ?, ?)",
                (wics_name, kw, kw_norm)
            )
            total += 1

    # 정규명 자체도 키워드로 (예: "반도체와반도체장비" 검색 시도)
    for wics_name in wics_dict.keys():
        norm = re.sub(r"\s+", "", wics_name).lower()
        conn.execute(
            "INSERT OR REPLACE INTO wics_keywords (wics_name, keyword, keyword_norm) VALUES (?, ?, ?)",
            (wics_name, wics_name, norm)
        )
        total += 1

    conn.commit()

    # 검증
    n_wics = conn.execute("SELECT COUNT(DISTINCT wics_name) FROM wics_keywords").fetchone()[0]
    n_kw = conn.execute("SELECT COUNT(*) FROM wics_keywords").fetchone()[0]
    print(f"적재 완료: {n_wics}개 업종 / {n_kw}개 키워드")

    # 샘플 조회 테스트
    samples = ["방산", "식음료", "엔터", "반도체", "5G"]
    print("\n샘플 검색 테스트:")
    for q in samples:
        q_norm = re.sub(r"\s+", "", q).lower()
        rows = conn.execute("""
            SELECT DISTINCT wics_name FROM wics_keywords
            WHERE keyword_norm LIKE '%' || ? || '%'
        """, (q_norm,)).fetchall()
        wics_list = [r[0] for r in rows]
        print(f"  '{q}' → {wics_list}")

    conn.close()
    print(f"\n[OK] data/filmn9.db wics_keywords 테이블 적재 완료")


if __name__ == "__main__":
    main()
