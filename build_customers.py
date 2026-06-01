# -*- coding: utf-8 -*-
"""
build_customers.py  (v2 — 통합 표기)
====================================
고객사 추출 — 사업보고서 JSONL 기반 ($0)

분류 (우선순위):
  1) B2B 기업명 추출 (자사·자회사·동일그룹 제외) → 유효기업 ≥1
  2) B2C 신호: 최종/일반소비자·불특정 다수·개인고객·"10% 외부고객 없음"·소비재 업종·채널
  3) 둘 다 → MIXED

표기:
  customer_type: B2B / B2C / MIXED
  customers    : 기업명 / "일반 소비자(개인)" / 기업명+소비자 병기
  channels     : 판매채널(빈도순) + 지역(내수/수출)
"""
import csv
import json
import re
import glob
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
CSV  = ROOT / "data" / "ticker_universe.csv"
RAG  = ROOT / "data" / "RAG"

SECTION_HINT = ["매출 및 수주", "사업의 내용", "매출", "고객", "판매", "영업의 개황"]
CUSTOMER_KW  = ["주요 매출처", "주요매출처", "주요 고객", "주요고객", "주요 거래처", "주요거래처", "납품처"]

MAJOR_CUSTOMERS = [
    "삼성전자", "삼성전기", "삼성디스플레이", "삼성SDI", "LG전자", "LG디스플레이",
    "LG에너지솔루션", "LG화학", "SK하이닉스", "SK이노베이션", "현대자동차", "기아",
    "현대모비스", "포스코", "한화", "두산", "애플", "Apple", "테슬라", "Tesla",
    "엔비디아", "NVIDIA", "구글", "Google", "아마존", "Amazon", "마이크로소프트",
    "Microsoft", "인텔", "Intel", "퀄컴", "Qualcomm", "AMD", "TSMC", "소니", "Sony",
    "화웨이", "Huawei", "샤오미", "Xiaomi", "메타", "Meta", "BMW", "벤츠", "Benz",
    "폭스바겐", "도요타", "Toyota", "보쉬", "Bosch", "쿠팡", "네이버", "카카오",
]

# 판매채널 (빈도순 — 리서치 결과 반영)
CHANNEL_ORDER = ["대리점", "가맹점", "백화점", "할인점", "마트", "온라인", "이커머스",
                 "편의점", "면세점", "직판", "유통", "약국", "병원", "의원",
                 "도매상", "양판점", "소매점"]
REGION_KW = ["내수", "수출"]

# B2C 소비자 표현
CONSUMER_KW = ["최종소비자", "최종 소비자", "최종고객", "최종 고객",
               "일반소비자", "일반 소비자", "불특정", "개인고객", "개인 고객",
               "개인 소비자", "end user", "end-user"]
# 소비재·B2C 성향 WICS 업종 키워드
CONSUMER_SECTOR = ["화장품", "의류", "섬유", "호텔", "레저", "음식료", "식료품", "음료",
                   "유통", "백화점", "미디어", "교육", "게임", "엔터", "여행", "항공",
                   "가정", "담배", "소매", "외식", "제약", "건강", "화장", "패션", "출판"]


def _core(name):
    n = re.sub(r"[\s\(\)（）㈜]|주식회사|보통주", "", name or "")
    n = re.sub(r"(홀딩스|지주회사|지주|그룹|Holdings|홀딩|네트워크|인터내셔널|코퍼레이션)$", "", n)
    return n


def load_universe():
    names, name_map, self_info = set(), {}, {}
    with open(CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = (r.get("stock_code") or "").strip()
            nm = (r.get("corp_name") or "").strip()
            wics = (r.get("wics") or "").strip()
            if code:
                self_info[code] = {"name": nm, "wics": wics, "core": _core(nm)}
            if (r.get("is_preferred") or "").lower() == "true":
                continue
            if re.search(r"우[B]?$", nm) and "보통주" not in nm:
                continue
            if len(nm) >= 2:
                norm = re.sub(r"[\s\(\)（）㈜]|주식회사|보통주", "", nm)
                if len(norm) >= 2:
                    names.add(norm)
                    name_map.setdefault(norm, re.sub(r"보통주$", "", nm).strip())
    return names, name_map, self_info


def find_chunks(jsonl_path):
    texts = []
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                sec = d.get("section_path_str", "") or ""
                txt = d.get("text", "") or ""
                if any(h in sec for h in SECTION_HINT):
                    texts.append(txt)
    except Exception:
        pass
    return texts


def customer_sentence(texts):
    for txt in texts:
        for kw in CUSTOMER_KW:
            idx = txt.find(kw)
            if idx >= 0:
                seg = txt[idx: idx + 250]
                m = re.search(r"[.。]", seg[len(kw):])
                if m:
                    seg = seg[: len(kw) + m.end() + 1]
                return seg.strip()
    return None


def detect_companies(sentence, known, name_map, self_core):
    found = []
    if not sentence:
        return found
    s = re.sub(r"\s", "", sentence)
    for mc in MAJOR_CUSTOMERS:
        if re.sub(r"\s", "", mc) in s and mc not in found:
            found.append(mc)
    for norm in known:
        if len(norm) >= 3 and norm in s:
            found.append(name_map.get(norm, norm))
    # 자사·자회사·동일그룹 제외
    out = []
    for c in found:
        cc = _core(c)
        if not cc or len(cc) < 2:
            continue
        if self_core and (cc == self_core or self_core in cc or cc in self_core):
            continue  # 자기 자신/자회사/모회사
        if any(c != o and c in o for o in found):
            continue  # 더 긴 정식명 우선
        if c not in out:
            out.append(c)
    return out[:5]


def extract_channels(blob):
    chans = [ch for ch in CHANNEL_ORDER if ch in blob]   # 이미 빈도순 정렬
    region = [r for r in REGION_KW if r in blob]
    return chans[:6], region


def main():
    known, name_map, self_info = load_universe()
    print(f"상장사 사전 {len(known)} / 종목정보 {len(self_info)}")

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.executescript("""
        DROP TABLE IF EXISTS company_customers;
        CREATE TABLE company_customers (
            stock_code     TEXT PRIMARY KEY,
            customer_type  TEXT,    -- B2B / B2C / MIXED
            customers      TEXT,    -- 기업명 / '일반 소비자(개인)' / 병기
            channels       TEXT,    -- 판매채널(빈도순) + 지역
            source_grade   TEXT,    -- B(매출처) / C(소비자) / M(혼합)
            source_text    TEXT,
            loaded_at      TEXT
        );
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    files = glob.glob(str(RAG / "*_annual_chunks.jsonl"))
    print(f"JSONL {len(files)}개")

    stat = {"B2B": 0, "B2C": 0, "MIXED": 0, "none": 0}
    for i, fp in enumerate(files, 1):
        m = re.match(r"(\w{6})_", Path(fp).name)
        if not m:
            continue
        code = m.group(1)
        info = self_info.get(code, {})
        texts = find_chunks(fp)
        if not texts:
            stat["none"] += 1
            continue
        blob = " ".join(texts)
        sentence = customer_sentence(texts)
        companies = detect_companies(sentence, known, name_map, info.get("core", ""))

        # B2C 신호
        has_consumer = any(k in blob for k in CONSUMER_KW)
        sector_b2c = any(k in info.get("wics", "") for k in CONSUMER_SECTOR)
        dispersed = ("10%" in blob or "10 %" in blob) and any(
            x in blob for x in ["외부고객", "고객은 없", "거래처는 없", "고객이 없"])
        chans, region = extract_channels(blob)
        strong_b2c = has_consumer or sector_b2c          # 진짜 개인소비자 신호
        weak = dispersed or bool(chans)                  # 분산/채널만 (B2B 성향일 수 있음)

        # 분류
        if companies and strong_b2c:
            ctype, grade = "MIXED", "M"
            custs = ", ".join(companies) + ", 일반 소비자(개인)"
        elif companies:
            ctype, grade = "B2B", "B"
            custs = ", ".join(companies)
        elif strong_b2c:
            ctype, grade = "B2C", "C"
            custs = "일반 소비자(개인)"
        elif weak:
            # 기업명 없음 + 강한 소비자신호 없음 → 분산 거래처(B2B 성향)
            ctype, grade = "B2B", "B"
            custs = "불특정 다수 거래처"
        else:
            stat["none"] += 1
            continue

        ch_str = ", ".join(chans)
        if region:
            ch_str = (ch_str + " · " if ch_str else "") + "/".join(region)
        conn.execute("""INSERT OR REPLACE INTO company_customers
            (stock_code,customer_type,customers,channels,source_grade,source_text,loaded_at)
            VALUES (?,?,?,?,?,?,?)""",
            (code, ctype, custs, ch_str, grade, (sentence or blob[:200])[:300], now))
        stat[ctype] += 1
        if i % 500 == 0:
            print(f"  [{i}/{len(files)}] {dict(stat)}")

    conn.commit()
    print(f"\n적재: {dict(stat)}")
    print("샘플:")
    for code in ["080160", "090430", "139480", "009150", "000660"]:
        r = conn.execute("SELECT customer_type,customers,channels FROM company_customers WHERE stock_code=?", (code,)).fetchone()
        print(f"  {code}: {r}")
    conn.close()


if __name__ == "__main__":
    main()
