# -*- coding: utf-8 -*-
"""
build_customers.py
==================
고객사 추출 — 사업보고서 JSONL 기반 (단계 2 + 4, 모두 $0)

단계 2 (매출처 기업명): "주요 매출처" 텍스트에서 상장사·대기업명 탐지
단계 4 (B2C 채널 서술): 기업명 없으면 판매경로·채널 서술형 추출

결과: company_customers 테이블
  - source_grade: B(매출처표) / D(채널서술)
"""
import csv
import json
import re
import glob
import sqlite3
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
CSV  = ROOT / "data" / "ticker_universe.csv"
RAG  = ROOT / "data" / "RAG"

# 매출처 정보가 담긴 섹션·키워드
SECTION_HINT = ["매출 및 수주", "사업의 내용"]
CUSTOMER_KW  = ["주요 매출처", "주요매출처", "주요 고객", "주요고객", "주요 거래처", "주요거래처", "납품처"]

# 대기업·글로벌 고객 후보 (상장사 외 자주 등장하는 큰 고객)
MAJOR_CUSTOMERS = [
    "삼성전자", "삼성전기", "삼성디스플레이", "삼성SDI", "LG전자", "LG디스플레이",
    "LG에너지솔루션", "LG화학", "SK하이닉스", "SK이노베이션", "현대자동차", "기아",
    "현대모비스", "포스코", "한화", "두산", "애플", "Apple", "테슬라", "Tesla",
    "엔비디아", "NVIDIA", "구글", "Google", "아마존", "Amazon", "마이크로소프트",
    "Microsoft", "인텔", "Intel", "퀄컴", "Qualcomm", "AMD", "TSMC", "소니", "Sony",
    "화웨이", "Huawei", "샤오미", "Xiaomi", "메타", "Meta", "BMW", "벤츠", "Benz",
    "폭스바겐", "도요타", "Toyota", "보쉬", "Bosch", "쿠팡", "네이버", "카카오",
]

# 채널 서술형 키워드 (B2C/B2G)
CHANNEL_KW = ["백화점", "면세점", "할인점", "양판점", "대리점", "온라인", "편의점",
              "마트", "약국", "도매상", "병원", "의원", "직판", "수출", "내수",
              "B2B", "B2C", "이커머스", "소매점", "유통"]


def load_known_companies():
    """ticker_universe corp_name → 정규화 집합 (상장사 탐지용)"""
    names = set()
    name_map = {}  # 정규화명 → 원본명
    with open(CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            nm = (r.get("corp_name") or "").strip()
            # 우선주 제외 (is_preferred 또는 이름이 우/우B로 끝남)
            if (r.get("is_preferred") or "").lower() == "true":
                continue
            if re.search(r"우[B]?$", nm) and "보통주" not in nm:
                continue
            if len(nm) >= 2:
                norm = re.sub(r"[\s\(\)（）㈜]|주식회사|보통주", "", nm)
                if len(norm) >= 2:
                    names.add(norm)
                    # 보통주/짧은 정식명 우선 (이미 있으면 덮어쓰지 않음)
                    if norm not in name_map:
                        name_map[norm] = re.sub(r"보통주$", "", nm).strip()
    return names, name_map


def find_customer_chunks(jsonl_path):
    """매출처/고객 관련 청크 텍스트 모으기"""
    texts = []
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("kind") != "text" and d.get("kind") != "table":
                    pass
                sec = d.get("section_path_str", "") or ""
                txt = d.get("text", "") or ""
                if any(h in sec for h in SECTION_HINT):
                    if any(k in txt for k in CUSTOMER_KW + CHANNEL_KW):
                        texts.append(txt)
    except Exception:
        pass
    return texts


def extract_customer_sentence(texts):
    """'주요 매출처' 가 포함된 문장 추출"""
    for txt in texts:
        for kw in CUSTOMER_KW:
            idx = txt.find(kw)
            if idx >= 0:
                # 키워드 주변 문장 추출 (200자)
                seg = txt[idx: idx + 250]
                # 문장 끝(마침표)까지
                m = re.search(r"[.。]", seg[len(kw):])
                if m:
                    seg = seg[: len(kw) + m.end() + 1]
                return seg.strip()
    return None


def detect_companies(sentence, known_names, name_map):
    """문장에서 상장사·대기업명 탐지"""
    found = []
    if not sentence:
        return found
    s_norm = re.sub(r"\s", "", sentence)
    # 대기업 후보 먼저
    for mc in MAJOR_CUSTOMERS:
        mc_norm = re.sub(r"\s", "", mc)
        if mc_norm in s_norm and mc not in found:
            found.append(mc)
    # 상장사명 (3자 이상만, 오탐 방지)
    for norm in known_names:
        if len(norm) >= 3 and norm in s_norm:
            orig = name_map.get(norm, norm)
            if orig not in found:
                found.append(orig)
    # 정리: 우선주("우"/"우B"로 끝나는 중복) 제거 + 다른 이름의 부분집합 제거
    cleaned = []
    for c in found:
        c_base = re.sub(r"우[B]?$", "", c)
        # 이미 본문(base)이 들어있으면 우선주 변형 skip
        if c != c_base and any(re.sub(r"우[B]?$", "", x) == c_base for x in cleaned):
            continue
        # 다른 항목의 부분문자열이면 skip (더 긴 정식명 우선)
        if any(c != o and c in o for o in found):
            continue
        cleaned.append(c)
    return cleaned[:5]


def extract_channels(texts):
    """채널 서술형 추출 (B2C/B2G)"""
    channels = []
    blob = " ".join(texts)
    for ch in CHANNEL_KW:
        if ch in blob and ch not in channels:
            channels.append(ch)
    return channels[:8]


def main():
    known_names, name_map = load_known_companies()
    print(f"상장사명 사전: {len(known_names)}개")

    conn = sqlite3.connect(DB)
    conn.executescript("""
        DROP TABLE IF EXISTS company_customers;
        CREATE TABLE company_customers (
            stock_code     TEXT PRIMARY KEY,
            customer_type  TEXT,          -- 'B2B'(기업명) / 'CHANNEL'(채널서술)
            customers      TEXT,          -- 기업명 콤마구분 또는 채널 콤마구분
            source_grade   TEXT,          -- B(매출처표) / D(채널서술)
            source_text    TEXT,          -- 원문 발췌
            loaded_at      TEXT
        );
    """)

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    files = glob.glob(str(RAG / "*_annual_chunks.jsonl"))
    print(f"JSONL 파일: {len(files)}개")

    stat = {"B2B": 0, "CHANNEL": 0, "none": 0}
    for i, fp in enumerate(files, 1):
        m = re.match(r"(\w{6})_", Path(fp).name)
        if not m:
            continue
        code = m.group(1)
        texts = find_customer_chunks(fp)
        if not texts:
            stat["none"] += 1
            continue

        sentence = extract_customer_sentence(texts)
        companies = detect_companies(sentence, known_names, name_map)

        if companies:
            conn.execute("""INSERT OR REPLACE INTO company_customers
                VALUES (?, 'B2B', ?, 'B', ?, ?)""",
                (code, ", ".join(companies), (sentence or "")[:300], now))
            stat["B2B"] += 1
        else:
            channels = extract_channels(texts)
            if channels:
                conn.execute("""INSERT OR REPLACE INTO company_customers
                    VALUES (?, 'CHANNEL', ?, 'D', ?, ?)""",
                    (code, ", ".join(channels), (sentence or texts[0][:200] if texts else "")[:300], now))
                stat["CHANNEL"] += 1
            else:
                stat["none"] += 1

        if i % 500 == 0:
            print(f"  [{i}/{len(files)}] B2B={stat['B2B']} CHANNEL={stat['CHANNEL']} none={stat['none']}")

    conn.commit()

    print(f"\n적재 결과: B2B(기업명)={stat['B2B']} / CHANNEL(채널서술)={stat['CHANNEL']} / 없음={stat['none']}")
    covered = stat["B2B"] + stat["CHANNEL"]
    print(f"커버리지: {covered}개 종목")

    print("\n샘플 검증:")
    for code in ["009150", "000660", "090430", "005930", "000020"]:
        r = conn.execute("SELECT customer_type, customers, source_grade FROM company_customers WHERE stock_code=?", (code,)).fetchone()
        if r:
            print(f"  {code} [{r[0]}·{r[2]}] → {r[1][:80]}")
        else:
            print(f"  {code} → (데이터 없음)")

    conn.close()
    print(f"\n[OK] company_customers 테이블 완료")


if __name__ == "__main__":
    main()
