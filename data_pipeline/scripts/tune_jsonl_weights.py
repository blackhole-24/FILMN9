# -*- coding: utf-8 -*-
"""외감 422 보충 신뢰도 가중치 튜닝 실험
parse_jsonl_chunks_to_db.py 의 extract_rows_from_stock 일부 로직을 복사해
3가지 가중치 조합을 같은 샘플 30개에 돌려보고 60+/70+/80+ 비율 비교.
"""
import sys, random, json, re
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, r"C:\Users\Admin\FILMN9")
import parse_jsonl_chunks_to_db as M

# 3가지 가중치 조합
WEIGHT_SETS = {
    "A_현재(기준)":   dict(name=0.30, num=0.25, map_rate=0.20, year=0.15, scope=0.10),
    "B_매핑우대":     dict(name=0.45, num=0.25, map_rate=0.05, year=0.15, scope=0.10),
    "C_단위강조":     dict(name=0.30, num=0.40, map_rate=0.05, year=0.15, scope=0.10),
}

def evaluate_stock_with_weights(stock_code: str, weights: dict):
    """parse_jsonl_chunks_to_db.extract_rows_from_stock 로직 재현 + 가중치만 교체"""
    if stock_code in M.DEMO_LOCK:
        return []
    matches = list(M.RAG_DIR.glob(f"{stock_code}_*_2025_annual_chunks.jsonl"))
    if not matches:
        return []
    jsonl_path = matches[0]
    chunks = M.find_financial_table_chunks(jsonl_path)
    confs = []
    for ch in chunks:
        text = ch["_text"]
        section = ch["_section"]
        scope, scope_explicit = M.detect_scope(section, text)
        unit_mult, unit_explicit = M.detect_unit(text)
        header, rows = M.parse_md_table(text)
        if not rows:
            continue
        cur_col = M.pick_current_column(header)
        fyear, year_conf = M.detect_fiscal_year(
            header[cur_col] if cur_col < len(header) else "", "20260331"
        )
        mapped = sum(1 for r in rows if M.map_account(r[0])[2] >= 0.7)
        map_rate = mapped / max(1, len(rows))
        for row in rows:
            account_nm = row[0]
            account_id, forced_stype, name_conf = M.map_account(account_nm)
            if name_conf < 0.4:
                continue
            raw_val = row[cur_col] if cur_col < len(row) else ""
            amount, num_conf = M.parse_amount(raw_val, unit_mult)
            if amount is None:
                continue
            # 신뢰도 (0~100) — 가중치 적용
            conf = round(100 * (
                weights["name"] * name_conf
                + weights["num"] * num_conf
                + weights["map_rate"] * map_rate
                + weights["year"] * year_conf
                + weights["scope"] * (1.0 if scope_explicit else 0.6)
            ))
            confs.append(conf)
    return confs

def main():
    random.seed(20260530)
    codes = random.sample(M.load_audit_422(), 30)
    print(f"실험 샘플: 외감법인 30개 종목 (seed=20260530)\n")

    out = {}
    for label, w in WEIGHT_SETS.items():
        all_confs = []
        for code in codes:
            all_confs.extend(evaluate_stock_with_weights(code, w))
        n = len(all_confs)
        if n == 0:
            out[label] = None
            continue
        n60 = sum(1 for c in all_confs if c >= 60)
        n70 = sum(1 for c in all_confs if c >= 70)
        n80 = sum(1 for c in all_confs if c >= 80)
        avg = sum(all_confs) / n
        med = sorted(all_confs)[n // 2]
        out[label] = dict(weights=w, total=n, n60=n60, n70=n70, n80=n80,
                          p60=n60/n*100, p70=n70/n*100, p80=n80/n*100, avg=avg, med=med)

    print("=" * 90)
    print(f"{'조합':<16} {'총행수':>7} {'60+':>6} ({'%':>5}) {'70+':>6} ({'%':>5}) {'80+':>6} ({'%':>5}) {'평균':>6} {'중앙':>6}")
    print("=" * 90)
    for label, s in out.items():
        if s is None:
            print(f"{label:<16}  데이터 없음")
            continue
        print(f"{label:<16} {s['total']:>7} {s['n60']:>6} ({s['p60']:>5.1f}%) "
              f"{s['n70']:>6} ({s['p70']:>5.1f}%) {s['n80']:>6} ({s['p80']:>5.1f}%) "
              f"{s['avg']:>6.1f} {s['med']:>6}")
    print("=" * 90)

    # 최적 조합 추천
    best = max((k for k in out if out[k]), key=lambda k: out[k]['p60'])
    print(f"\n🏆 60점 이상 비율 최고: {best} ({out[best]['p60']:.1f}%)")
    print(f"   가중치: {out[best]['weights']}")

    # 결과 저장
    import json
    out_path = Path(r"C:\Users\Admin\FILMN9\handover\외감422_가중치_튜닝_결과_20260530.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in out.items()}, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")

if __name__ == "__main__":
    main()
