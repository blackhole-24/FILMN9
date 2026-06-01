# -*- coding: utf-8 -*-
"""
parse_jsonl_chunks_to_db.py
===========================
외감법인 422개 보충 — JSONL 청크에서 BS/IS/CIS 추출 → financial_detail 적재

원본 의사코드: handover/claude AI_외감법인422보충파이프라인_의사코드v2_2026-05-29.md
작성: 2026-05-29 (Claude Code 구현)

핵심 정책
- 신뢰도 ≥60 → source="JSONL_RAG_chunk" 정상 적재
- 신뢰도 <60 → source="JSONL_RAG_chunk_LOW_CONFIDENCE" 분리 적재
- 데모 3종목(090430, 009150, 035420) DEMO_LOCK — 건드리지 않음
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ════════════════════════════════════════════════════════════════════════
# 상수
# ════════════════════════════════════════════════════════════════════════
ROOT      = Path(r"C:\Users\Admin\FILMN9")
DB        = ROOT / "data" / "filmn9.db"
RAG_DIR   = ROOT / "data" / "RAG"
AUDIT_CSV = ROOT / "auto_reports" / "03_외감법인_보유현황.csv"
LOG_DIR   = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

DEMO_LOCK         = {"090430", "009150", "035420"}
CONF_THRESHOLD    = 60          # 0~100 점수에서 60점 미만은 LOW_CONFIDENCE
EPS_RATIO         = 0.001       # BS 항등식 허용오차 0.1%

# 계정명 정규화 + 표준 ID 매핑 (의사코드 v2 기준)
ACCOUNT_MAP = {
    # BS
    "자산총계":          ("ifrs-full_Assets", "BS"),
    "부채총계":          ("ifrs-full_Liabilities", "BS"),
    "자본총계":          ("ifrs-full_Equity", "BS"),
    "유동자산":          ("ifrs-full_CurrentAssets", "BS"),
    "비유동자산":        ("ifrs-full_NoncurrentAssets", "BS"),
    "유동부채":          ("ifrs-full_CurrentLiabilities", "BS"),
    "비유동부채":        ("ifrs-full_NoncurrentLiabilities", "BS"),
    "부채와자본총계":    ("ifrs-full_EquityAndLiabilities", "BS"),
    # IS
    "매출액":            ("ifrs-full_Revenue", "IS"),
    "수익매출액":        ("ifrs-full_Revenue", "IS"),
    "영업수익":          ("ifrs-full_Revenue", "IS"),
    "매출원가":          ("ifrs-full_CostOfSales", "IS"),
    "매출총이익":        ("ifrs-full_GrossProfit", "IS"),
    "판매비와관리비":    ("dart_SellingGeneralAdministrativeExpenses", "IS"),
    "영업이익":          ("dart_OperatingIncomeLoss", "IS"),
    "영업이익손실":      ("dart_OperatingIncomeLoss", "IS"),
    "당기순이익":        ("ifrs-full_ProfitLoss", "IS"),
    "당기순이익손실":    ("ifrs-full_ProfitLoss", "IS"),
    # CIS
    "총포괄손익":        ("ifrs-full_ComprehensiveIncome", "CIS"),
    "기타포괄손익":      ("ifrs-full_OtherComprehensiveIncome", "CIS"),
}

UNIT_MULT = {
    "원": 1, "천원": 1_000, "백만원": 1_000_000,
    "십억원": 1_000_000_000, "조원": 1_000_000_000_000,
    "백만": 1_000_000, "천": 1_000,
}

# 정규식
RE_UNIT     = re.compile(r"단위\s*[:：]?\s*\(?\s*([십백천억만원조\s]+)\)?")
RE_GI       = re.compile(r"제\s*(\d+)\s*기")
RE_YEAR     = re.compile(r"(20\d{2})")
RE_NUM      = re.compile(r"^\s*\(?\s*[△▲\-]?\s*[\d,]+(?:\.\d+)?\s*\)?\s*$")
RE_SEPLINE  = re.compile(r"^\|[\s\-:|]+\|?\s*$")

NULLS = {"", "-", "–", "—", "N/A", "해당없음", ".", "0"}

SEC_KW   = ["재무상태표", "손익계산서", "포괄손익계산서", "재무에 관한 사항"]
BS_KW    = ["재무상태표", "자산총계", "부채총계", "자본총계"]
IS_KW    = ["손익계산서", "포괄손익", "매출", "영업이익", "당기순이익"]


def setup_logging():
    log_file = LOG_DIR / f"jsonl_parse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_file


# ════════════════════════════════════════════════════════════════════════
# 유틸 — 정규화·파싱
# ════════════════════════════════════════════════════════════════════════
def norm_name(s: str) -> str:
    """'자 산 총 계 ' → '자산총계' / '당기순이익(손실)' → '당기순이익손실'"""
    if not s:
        return ""
    return re.sub(r"[\s\(\)（）:：·\.,]", "", s)


def parse_amount(raw: str, unit_mult: int = 1) -> tuple[float | None, float]:
    """'(1,234)' → -1234, '△1,234' → -1234, '1,234' → 1234, '-'/'' → None
    반환: (값, 파싱_신뢰도 0~1)
    """
    if raw is None:
        return None, 0.0
    s = str(raw).strip()
    if s in NULLS:
        return None, 0.0
    neg = False
    if s.startswith(("(", "（")) or s.endswith((")", "）")):
        neg = True
    if s[:1] in ("△", "▲", "-"):
        neg = True
    digits = re.sub(r"[^\d.]", "", s)
    if not digits:
        return None, 0.0
    try:
        val = float(digits) if "." in digits else int(digits)
    except ValueError:
        return None, 0.0
    val *= unit_mult
    if neg:
        val = -val
    # 신뢰도: 깔끔=1.0 / 부호·단위 보정=0.85 / 잔여 비숫자 多=0.6
    junk = len(re.sub(r"[\d,.\s△▲\-\(\)（）]", "", s))
    num_conf = 1.0 if junk == 0 and unit_mult == 1 else (0.85 if junk == 0 else 0.6)
    return val, num_conf


def detect_unit(text: str) -> tuple[int, bool]:
    """'(단위: 천원)' → (1000, True) / 미표기 → (1, False)"""
    head = text[:200]
    m = RE_UNIT.search(head)
    if not m:
        return 1, False
    key = re.sub(r"\s", "", m.group(1))
    return UNIT_MULT.get(key, 1), True


def detect_scope(section_path: str, text: str) -> tuple[str, bool]:
    """연결/별도 판정 — 섹션경로 우선, 외감법인 기본=별도"""
    if "연결" in section_path:
        return "연결", True
    if "별도" in section_path:
        return "별도", True
    head = text[:500]
    if "연결" in head:
        return "연결", False
    return "별도", False  # 외감법인 통상 별도


def detect_statement_type(section_path: str) -> str:
    """BS/IS/CIS 판정"""
    if "재무상태표" in section_path:
        return "BS"
    if "포괄손익" in section_path:
        return "CIS"
    if "손익계산서" in section_path or "손익" in section_path:
        return "IS"
    return "IS"  # 기본 IS


def detect_fiscal_year(header_cell: str, rcept_dt: str = "") -> tuple[int, float]:
    """'당기' → 2025, '전기' → 2024, '제97기' → rcept_dt 기반"""
    h = (header_cell or "").strip()
    if "전전기" in h:
        return 2023, 1.0
    if "전기" in h:
        return 2024, 1.0
    if "당기" in h or "금기" in h:
        return 2025, 1.0
    if RE_GI.search(h) and rcept_dt:
        base = int(rcept_dt[:4]) if rcept_dt[:4].isdigit() else 2026
        return base - 1, 0.9
    m = RE_YEAR.search(h)
    if m:
        return int(m.group(1)), 0.95
    return 2025, 0.5


def map_account(account_nm: str) -> tuple[str, str | None, float]:
    """계정명 → (표준 ID, 강제 statement_type or None, 매칭_신뢰도 0~1)
    매핑 성공 시 statement_type을 함께 반환해 섹션 기반 오류 보정.
    """
    if not account_nm:
        return "custom_unknown", None, 0.0
    key = norm_name(account_nm)
    if key in ACCOUNT_MAP:
        acc_id, stype = ACCOUNT_MAP[key]
        return acc_id, stype, 1.0
    # 부분일치 폴백
    for k, (acc_id, stype) in ACCOUNT_MAP.items():
        nk = norm_name(k)
        if nk and (nk in key or key in nk):
            return acc_id, stype, 0.7
    return "custom_" + account_nm.strip(), None, 0.4


# ════════════════════════════════════════════════════════════════════════
# 청크 처리
# ════════════════════════════════════════════════════════════════════════
def find_financial_table_chunks(jsonl_path: Path):
    """JSONL에서 재무표 청크만 필터"""
    out = []
    if not jsonl_path.exists():
        return out
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            try:
                ch = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ch.get("kind") != "table":
                continue
            sec = ch.get("section_path_str", "") or ""
            text = ch.get("text", "") or ""
            # 섹션경로 또는 본문에 재무표 키워드
            if any(k in sec for k in SEC_KW) or any(k in text[:300] for k in BS_KW + IS_KW):
                ch["_section"] = sec
                ch["_text"] = text
                out.append(ch)
    return out


def parse_md_table(text: str) -> tuple[list[str], list[list[str]]]:
    """마크다운 표 → (헤더 셀, 데이터 행들)"""
    lines = [l for l in text.splitlines() if l.strip().startswith("|")]
    lines = [l for l in lines if not RE_SEPLINE.match(l.strip())]
    if not lines:
        return [], []
    header = [c.strip() for c in lines[0].strip("| ").split("|")]
    rows = []
    for l in lines[1:]:
        cells = [c.strip() for c in l.strip("| ").split("|")]
        if len(cells) != len(header):
            continue  # 손상행 skip
        rows.append(cells)
    return header, rows


def pick_current_column(header: list[str]) -> int:
    """헤더에서 '당기'/'금기'/'제N기' 우선, 없으면 첫 숫자 컬럼"""
    for i, h in enumerate(header):
        if "당기" in h or "금기" in h:
            return i
    for i, h in enumerate(header):
        if RE_GI.search(h):
            return i
    # 디폴트: 마지막에서 두 번째 (보통 [계정, 당기, 전기])
    return 1 if len(header) >= 2 else 0


# ════════════════════════════════════════════════════════════════════════
# 메인 파이프라인
# ════════════════════════════════════════════════════════════════════════
def extract_rows_from_stock(stock_code: str, jsonl_path: Path,
                            rcept_dt: str = "20260331") -> list[dict]:
    """한 종목의 JSONL에서 후보 행들 추출 (중복 포함)"""
    if stock_code in DEMO_LOCK:
        return []  # 데모 보호

    chunks = find_financial_table_chunks(jsonl_path)
    candidates = []

    for ch in chunks:
        text = ch["_text"]
        section = ch["_section"]
        stype = detect_statement_type(section)
        scope, scope_explicit = detect_scope(section, text)
        unit_mult, unit_explicit = detect_unit(text)
        header, rows = parse_md_table(text)
        if not rows:
            continue

        cur_col = pick_current_column(header)
        fyear, year_conf = detect_fiscal_year(
            header[cur_col] if cur_col < len(header) else "", rcept_dt
        )

        # 매핑 성공률 (행 전체 기준)
        mapped = sum(1 for r in rows if map_account(r[0])[2] >= 0.7)
        map_rate = mapped / max(1, len(rows))

        for order, row in enumerate(rows):
            account_nm = row[0]
            account_id, forced_stype, name_conf = map_account(account_nm)
            if name_conf < 0.4:  # 매핑 완전 실패는 skip
                continue
            raw_val = row[cur_col] if cur_col < len(row) else ""
            amount, num_conf = parse_amount(raw_val, unit_mult)
            if amount is None:
                continue

            # 계정 매핑이 정확하면 statement_type 강제 (섹션 기반 오류 보정)
            final_stype = forced_stype if (forced_stype and name_conf >= 0.7) else stype

            # 신뢰도 (0~100)
            # 신뢰도 가중치 — C_단위강조 (2026-05-30 튜닝 결과 채택)
            # 30개 종목 실험: 60+ 비율 31% → 94% 개선
            # 이력: handover/외감422_가중치_튜닝_결과_20260530.json
            conf = round(100 * (
                0.30 * name_conf
                + 0.40 * num_conf       # 금액 파싱 강조 (단위·부호 깔끔도 비중↑)
                + 0.05 * map_rate       # 표 전체 매핑률 비중↓ (한 줄 실패가 모두 깎는 부당 감점 방지)
                + 0.15 * year_conf
                + 0.10 * (1.0 if scope_explicit else 0.6)
            ))

            candidates.append({
                "stock_code": stock_code,
                "fiscal_year": fyear,
                "statement_type": final_stype,
                "account_id": account_id,
                "statement_scope": scope,
                "account_nm": account_nm.strip(),
                "amount": int(amount),
                "unit": "원",
                "display_order": order,
                "_conf": conf,
            })
    return candidates


def pick_best_duplicates(rows: list[dict]) -> list[dict]:
    """동일 PK는 신뢰도 최고값만 채택"""
    best = {}
    for r in rows:
        key = (r["stock_code"], r["fiscal_year"], r["statement_type"],
               r["statement_scope"], r["account_id"])
        if key not in best or r["_conf"] > best[key]["_conf"]:
            best[key] = r
    return list(best.values())


def bs_identity_adjust(rows: list[dict]) -> list[dict]:
    """BS 항등식(자산=부채+자본) 통과 시 신뢰도 +10, 미통과 시 -20"""
    by_key = defaultdict(list)
    for r in rows:
        if r["statement_type"] != "BS":
            continue
        by_key[(r["stock_code"], r["fiscal_year"], r["statement_scope"])].append(r)

    for key, grp in by_key.items():
        amounts = {r["account_id"]: r["amount"] for r in grp}
        a = amounts.get("ifrs-full_Assets")
        l = amounts.get("ifrs-full_Liabilities")
        e = amounts.get("ifrs-full_Equity")
        if a is not None and l is not None and e is not None:
            if abs(a - (l + e)) <= max(1, EPS_RATIO * abs(a)):
                for r in grp:
                    r["_conf"] = min(100, r["_conf"] + 10)
            else:
                for r in grp:
                    r["_conf"] = max(0, r["_conf"] - 20)
    return rows


def finalize_rows(rows: list[dict]) -> list[dict]:
    """source / loaded_at 태깅"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        r["source"] = ("JSONL_RAG_chunk" if r["_conf"] >= CONF_THRESHOLD
                       else "JSONL_RAG_chunk_LOW_CONFIDENCE")
        r["loaded_at"] = now
    return rows


def process_stock(stock_code: str, dry_run: bool = False) -> dict:
    """한 종목 전체 파이프라인. 반환: 통계 dict"""
    if stock_code in DEMO_LOCK:
        return {"status": "skip_demo", "inserted": 0, "review": 0}

    # JSONL 경로 탐색 (회사명 포함이라 와일드카드)
    matches = list(RAG_DIR.glob(f"{stock_code}_*_2025_annual_chunks.jsonl"))
    if not matches:
        return {"status": "no_jsonl", "inserted": 0, "review": 0}
    jsonl_path = matches[0]

    candidates = extract_rows_from_stock(stock_code, jsonl_path)
    if not candidates:
        return {"status": "no_table", "inserted": 0, "review": 0}

    rows = pick_best_duplicates(candidates)
    rows = bs_identity_adjust(rows)
    rows = finalize_rows(rows)

    inserted = [r for r in rows if r["_conf"] >= CONF_THRESHOLD]
    review = [r for r in rows if r["_conf"] < CONF_THRESHOLD]

    if not dry_run:
        adapt_and_insert(inserted + review)

    return {
        "status": "ok" if inserted else "no_confident",
        "inserted": len(inserted),
        "review": len(review),
        "rows": rows,  # 검증용
    }


_SQLITE_INT_MAX = 9_000_000_000_000_000_000   # 64bit 안전 한계
# 한국 최대기업 자산총계도 ~1000조(1e15) 미만 → 1e16 초과는 단위 오류로 간주
_AMOUNT_SANITY_MAX = 10 ** 16


def adapt_and_insert(rows: list[dict]):
    """SQLite financial_detail INSERT (비정상 금액 필터)"""
    if not rows:
        return
    safe_rows = []
    for r in rows:
        amt = r["amount"]
        if amt is None:
            continue
        # 단위 오검출로 폭증한 비정상 금액 제외 (1경 초과)
        if abs(amt) >= _AMOUNT_SANITY_MAX:
            continue
        if abs(amt) >= _SQLITE_INT_MAX:
            continue
        safe_rows.append(r)
    if not safe_rows:
        return
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO financial_detail
            (stock_code, fiscal_year, statement_type, account_id, statement_scope,
             account_nm, amount, unit, display_order, source, loaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [(
            r["stock_code"], r["fiscal_year"], r["statement_type"],
            r["account_id"], r["statement_scope"], r["account_nm"],
            int(r["amount"]), r["unit"], r["display_order"], r["source"], r["loaded_at"]
        ) for r in safe_rows])
        conn.commit()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════
# 명단·실행
# ════════════════════════════════════════════════════════════════════════
def load_audit_422() -> list[str]:
    """JSONL 보유한 외감법인만 반환"""
    codes = []
    with open(AUDIT_CSV, encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            if r.get("JSONL_보유") == "✅":
                codes.append(r["stock_code"])
    return codes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0,
                    help="무작위 N개만 처리 (0=전체 422개)")
    ap.add_argument("--dry-run", action="store_true",
                    help="DB 미적재, 통계만 출력")
    ap.add_argument("--codes", nargs="+", help="특정 종목코드만 처리")
    ap.add_argument("--seed", type=int, default=20260529)
    args = ap.parse_args()

    log_file = setup_logging()
    logging.info("=" * 70)
    logging.info("외감법인 422 보충 — JSONL 청크 파싱 시작")
    logging.info(f"log: {log_file}")
    logging.info(f"dry_run: {args.dry_run}, sample: {args.sample}")
    logging.info("=" * 70)

    if args.codes:
        targets = args.codes
    else:
        all_codes = load_audit_422()
        logging.info(f"외감법인 JSONL 보유: {len(all_codes)}개")
        if args.sample > 0:
            random.seed(args.seed)
            targets = random.sample(all_codes, min(args.sample, len(all_codes)))
            logging.info(f"무작위 {len(targets)}개 샘플 처리")
        else:
            targets = all_codes

    stats = defaultdict(int)
    conf_dist = defaultdict(int)
    results = []

    start = datetime.now()
    for i, code in enumerate(targets, 1):
        r = process_stock(code, dry_run=args.dry_run)
        stats[r["status"]] += 1
        stats["total_inserted"] += r["inserted"]
        stats["total_review"] += r["review"]
        for row in r.get("rows", []):
            bucket = (row["_conf"] // 10) * 10
            conf_dist[bucket] += 1
        results.append({"code": code, **{k: v for k, v in r.items() if k != "rows"}})
        if i % 20 == 0 or i == len(targets):
            logging.info(f"  [{i}/{len(targets)}] ok={stats['ok']} "
                         f"no_jsonl={stats['no_jsonl']} no_table={stats['no_table']} "
                         f"no_confident={stats['no_confident']}")

    elapsed = (datetime.now() - start).total_seconds()
    logging.info("=" * 70)
    logging.info(f"완료 — {elapsed:.1f}초")
    logging.info(f"상태별: ok={stats['ok']} / no_jsonl={stats['no_jsonl']} / "
                 f"no_table={stats['no_table']} / no_confident={stats['no_confident']} / "
                 f"skip_demo={stats['skip_demo']}")
    logging.info(f"적재: {stats['total_inserted']}건 정상 / {stats['total_review']}건 LOW_CONFIDENCE")
    logging.info("신뢰도 분포:")
    for b in sorted(conf_dist.keys()):
        logging.info(f"  {b:3d}~{b+9:3d}: {conf_dist[b]:>5d}건")

    # 결과 CSV
    out_csv = ROOT / "auto_reports" / f"외감422_파싱결과_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "status", "inserted", "review"])
        w.writeheader()
        w.writerows(results)
    logging.info(f"결과 CSV: {out_csv}")


if __name__ == "__main__":
    main()
