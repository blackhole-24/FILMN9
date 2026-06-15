# -*- coding: utf-8 -*-
"""
rerank_competitors.py
=====================
경쟁사 정밀화 — 사업보고서 "사업의 내용" 텍스트 TF-IDF 유사도로 재정렬

목적: WICS 동종업계(peer_competitors)를 "사업의 결" 유사도 순으로 재정렬
  - 같은 WICS라도 사업 내용이 다르면(NAVER vs SOOP) 유사도 낮음 → 후순위/제외
  - 순수 파이썬 (모델·라이브러리 다운로드 X, $0)
  - 같은 WICS 그룹 내에서만 비교 → 가벼움

결과: peer_competitors 에 similarity 컬럼 추가 + 유사도 순 재정렬
      유사도 임계 미만은 제외 (개수 강제 안 함)
"""
import csv
import json
import glob
import math
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
CSV  = ROOT / "data" / "ticker_universe.csv"
RAG  = ROOT / "data" / "RAG"

SIM_THRESHOLD = 0.05   # 이 미만 유사도는 경쟁사에서 제외
MAX_PEERS = 5

# 사업 내용이 담긴 섹션
BIZ_SECTIONS = ["사업의 내용", "사업의 개요", "주요 제품", "사업의 현황"]
# 불용어 (사업보고서 공통 단어 — 변별력 없음)
STOPWORDS = {
    "당사", "회사", "사업", "제품", "매출", "시장", "고객", "기준", "경우", "관련",
    "통해", "위해", "대한", "있습니다", "합니다", "있으며", "등을", "또한", "그리고",
    "내용", "기재", "현황", "주요", "다양", "지속", "확대", "강화", "전략", "구분",
    "연결", "기말", "당기", "전기", "보고", "이상", "이하", "수준", "경쟁", "국내",
    "해외", "생산", "판매", "공급", "사용", "제공", "개발", "운영", "포함",
}


def tokenize(text):
    """한글 2글자+ 단어, 영문 2자+ 추출 (형태소분석 없이 경량)"""
    text = re.sub(r"[^가-힣A-Za-z0-9\s]", " ", text)
    tokens = []
    # 한글 연속 2~6글자
    for w in re.findall(r"[가-힣]{2,6}", text):
        if w not in STOPWORDS:
            tokens.append(w)
    # 영문 단어 2자+
    for w in re.findall(r"[A-Za-z]{2,}", text):
        tokens.append(w.lower())
    return tokens


def load_business_text(jsonl_path, max_chars=4000):
    """사업의 내용 섹션 텍스트 모으기 (앞부분 위주)"""
    parts = []
    total = 0
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                sec = d.get("section_path_str", "") or ""
                if any(s in sec for s in BIZ_SECTIONS):
                    t = d.get("text", "") or ""
                    parts.append(t)
                    total += len(t)
                    if total >= max_chars:
                        break
    except Exception:
        pass
    return " ".join(parts)[:max_chars]


def main():
    # 1. 종목별 사업 텍스트 로드
    print("사업 텍스트 로딩...")
    code_text = {}
    for fp in glob.glob(str(RAG / "*_annual_chunks.jsonl")):
        m = re.match(r"(\w{6})_", Path(fp).name)
        if not m:
            continue
        txt = load_business_text(fp)
        if txt:
            code_text[m.group(1)] = tokenize(txt)
    print(f"  사업 텍스트 보유: {len(code_text)}개 종목")

    # 2. IDF 계산 (전체 문서 기준)
    df = Counter()
    for toks in code_text.values():
        for t in set(toks):
            df[t] += 1
    N = len(code_text)
    idf = {t: math.log(N / (1 + c)) for t, c in df.items()}

    # 3. TF-IDF 벡터 (정규화)
    def tfidf_vec(toks):
        tf = Counter(toks)
        vec = {t: (1 + math.log(c)) * idf.get(t, 0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}, norm

    vecs = {code: tfidf_vec(toks)[0] for code, toks in code_text.items()}

    def cosine(a, b):
        # 작은 쪽 순회
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(t, 0) for t, v in a.items())

    # 4. peer_competitors 재정렬
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT DISTINCT stock_code FROM peer_competitors").fetchall()
    targets = [r["stock_code"] for r in rows]

    # similarity 컬럼 추가
    cols = [r[1] for r in conn.execute("PRAGMA table_info(peer_competitors)").fetchall()]
    if "similarity" not in cols:
        conn.execute("ALTER TABLE peer_competitors ADD COLUMN similarity REAL")

    reranked = 0
    dropped = 0
    no_text = 0
    for code in targets:
        if code not in vecs:
            no_text += 1
            continue
        comps = conn.execute(
            "SELECT competitor_code, competitor_name, wics, basis FROM peer_competitors WHERE stock_code=?",
            (code,)).fetchall()
        scored = []
        for c in comps:
            cc = c["competitor_code"]
            sim = cosine(vecs[code], vecs[cc]) if cc in vecs else 0.0
            scored.append((sim, c))
        # 유사도 순 정렬
        scored.sort(key=lambda x: -x[0])
        # "정확히 같은 결만" — 최고 유사도의 70% 이상 + 절대 하한 동시 충족
        top_sim = scored[0][0] if scored else 0.0
        rel_cut = top_sim * 0.70
        kept = [s for s in scored if s[0] >= max(SIM_THRESHOLD, rel_cut) and s[0] > 0]
        # 전부 0(텍스트 빈약)이면 1위만 유지
        if not kept and scored:
            kept = scored[:1]
        kept = kept[:MAX_PEERS]
        dropped += len(scored) - len(kept)

        # DB 갱신: 기존 삭제 후 재삽입
        conn.execute("DELETE FROM peer_competitors WHERE stock_code=?", (code,))
        for rank, (sim, c) in enumerate(kept, 1):
            conn.execute("""
                INSERT INTO peer_competitors
                (stock_code, rank, competitor_code, competitor_name, wics, basis, similarity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (code, rank, c["competitor_code"], c["competitor_name"],
                  c["wics"], "동종업계 + 사업유사도 정렬", round(sim, 3)))
        reranked += 1

    conn.commit()
    print(f"\n재정렬: {reranked}개 종목 / 사업텍스트 없어 유지: {no_text}개 / 저유사도 제외: {dropped}건")

    print("\n샘플 검증 (유사도 점수):")
    for code in ["035420", "009150", "090430", "005930", "068270"]:
        comps = conn.execute(
            "SELECT competitor_name, similarity FROM peer_competitors WHERE stock_code=? ORDER BY rank",
            (code,)).fetchall()
        nm = conn.execute("SELECT competitor_name FROM peer_competitors WHERE competitor_code=? LIMIT 1", (code,)).fetchone()
        s = " · ".join(f"{c['competitor_name']}({c['similarity']})" for c in comps)
        print(f"  {code}: {s}")

    conn.close()
    print("\n[OK] 경쟁사 사업유사도 재정렬 완료")


if __name__ == "__main__":
    main()
