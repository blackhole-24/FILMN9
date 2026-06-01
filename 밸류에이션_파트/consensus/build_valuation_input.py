"""
FILMN9 - 3단계: A2 통합 (DCF 입력값 생성)
===========================================
한경(적정가 분포) + 네이버(미래 추정치)를 종목별로 병합하여
valuation_input/{code}.json 생성.

실행:
  python 밸류에이션_파트/build_valuation_input.py
"""

import json
from pathlib import Path
from datetime import datetime

# ── 경로 설정 ──────────────────────────────────────────────────────
HK_DIR  = Path("C:/Users/Admin/FILMN9/data/hankyung/by_stock_code")
NV_DIR  = Path("C:/Users/Admin/FILMN9/data/naver_consensus/by_stock_code")
OUT_DIR = Path("C:/Users/Admin/FILMN9/data/valuation_input/by_stock_code")


def data_quality(hk: dict | None, nv: dict | None) -> str:
    """
    green  : 한경 + 네이버 모두 있고 매출 추정치 1개 이상
    yellow : 둘 중 하나만 있거나 추정치 없음
    red    : 둘 다 없음
    """
    has_hk = hk is not None and hk.get("report_count", 0) > 0
    has_nv_data = (
        nv is not None
        and nv.get("status") != "fetch_failed"
        and nv.get("revenue")
        and any(v is not None for v in nv.get("revenue", []))
    )
    if has_hk and has_nv_data:
        return "green"
    if has_hk or has_nv_data:
        return "yellow"
    return "red"


def extract_forecast(nv: dict | None) -> dict:
    """네이버 데이터에서 3개년 추정치 추출 (E 연도만)"""
    if not nv or nv.get("status") == "fetch_failed":
        return {"revenue": {}, "op_income": {}, "net_income": {}}

    years      = nv.get("fiscal_years", [])
    is_est     = nv.get("is_estimate", [False]*len(years))
    revenue    = nv.get("revenue", [])
    op_income  = nv.get("op_income", [])
    net_income = nv.get("net_income", [])

    rev_d, op_d, net_d = {}, {}, {}
    for i, (yr, est) in enumerate(zip(years, is_est)):
        if est:
            rev_d[str(yr)]  = revenue[i]    if revenue    and i < len(revenue)    else None
            op_d[str(yr)]   = op_income[i]  if op_income  and i < len(op_income)  else None
            net_d[str(yr)]  = net_income[i] if net_income and i < len(net_income) else None

    return {"revenue": rev_d, "op_income": op_d, "net_income": net_d}


def extract_multiples(nv: dict | None) -> dict:
    if not nv or nv.get("status") == "fetch_failed":
        return {"per_estimate": [], "pbr_estimate": [], "roe_estimate": []}

    years  = nv.get("fiscal_years", [])
    is_est = nv.get("is_estimate", [False]*len(years))

    def est_vals(key):
        vals = nv.get(key, [])
        return [vals[i] for i, est in enumerate(is_est) if est and vals and i < len(vals)]

    return {
        "per_estimate": est_vals("per"),
        "pbr_estimate": est_vals("pbr"),
        "roe_estimate": est_vals("roe"),
    }


def build_consensus(hk: dict | None, nv: dict | None) -> dict:
    hk_tp = hk.get("target_price", {}) if hk else {}
    nv_tp = nv.get("target_price") if nv else None

    # 한경 적정가 없으면 네이버 목표가로 보완
    avg_tp = hk_tp.get("avg") or nv_tp

    return {
        "target_price_avg"  : avg_tp,
        "target_price_range": (
            [hk_tp.get("min"), hk_tp.get("max")] if hk_tp.get("min") else None
        ),
        "analyst_count"     : hk.get("report_count") if hk else None,
        "opinion_majority"  : (
            max(hk["opinion_distribution"], key=hk["opinion_distribution"].get)
            if hk and hk.get("opinion_distribution")
            else None
        ),
    }


def main():
    print(f"{'='*60}")
    print(f"  FILMN9 A2 통합 빌더")
    print(f"{'='*60}")

    if not HK_DIR.exists():
        print(f"❌ 한경 데이터 없음: {HK_DIR}")
        print("   collect_hankyung.py를 먼저 실행하세요.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    hk_codes = {p.stem for p in HK_DIR.glob("*.json")}
    nv_codes = {p.stem for p in NV_DIR.glob("*.json")} if NV_DIR.exists() else set()
    all_codes = hk_codes | nv_codes

    print(f"  한경 커버: {len(hk_codes)}종목")
    print(f"  네이버 커버: {len(nv_codes)}종목")
    print(f"  통합 대상: {len(all_codes)}종목")

    stats = {"green": 0, "yellow": 0, "red": 0}

    for code in sorted(all_codes):
        hk_path = HK_DIR / f"{code}.json"
        nv_path = NV_DIR / f"{code}.json" if NV_DIR.exists() else None

        hk = json.loads(hk_path.read_text(encoding='utf-8')) if hk_path.exists() else None
        nv = json.loads(nv_path.read_text(encoding='utf-8')) if (nv_path and nv_path.exists()) else None

        stock_name = (hk or nv or {}).get("stock_name", "")
        quality = data_quality(hk, nv)
        stats[quality] += 1

        sources = []
        if hk: sources.append("hankyung")
        if nv and nv.get("status") != "fetch_failed": sources.append("naver")

        merged = {
            "stock_code"          : code,
            "stock_name"          : stock_name,
            "built_at"            : datetime.now().strftime('%Y-%m-%d %H:%M'),
            "data_quality"        : quality,
            "data_sources"        : sources,
            "consensus"           : build_consensus(hk, nv),
            "forecast"            : extract_forecast(nv),
            "valuation_multiples" : extract_multiples(nv),
        }

        out_path = OUT_DIR / f"{code}.json"
        out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n  [품질 분포]")
    print(f"    🟢 green  (한경+네이버): {stats['green']}개")
    print(f"    🟡 yellow (부분 데이터): {stats['yellow']}개")
    print(f"    🔴 red    (데이터 없음): {stats['red']}개")
    print(f"\n  저장 위치: {OUT_DIR}")

    # 샘플 출력
    greens = [p for p in OUT_DIR.glob("*.json")
              if json.loads(p.read_text('utf-8')).get("data_quality") == "green"]
    if greens:
        sample = json.loads(greens[0].read_text('utf-8'))
        print(f"\n  [green 샘플 - {sample['stock_code']} {sample['stock_name']}]")
        fc = sample.get("forecast", {})
        print(f"    매출 추정: {fc.get('revenue')}")
        print(f"    영업이익:  {fc.get('op_income')}")
        cs = sample.get("consensus", {})
        print(f"    적정가 평균: {cs.get('target_price_avg')}원")
        print(f"    애널리스트: {cs.get('analyst_count')}명")

    print(f"\n{'='*60}")
    print(f"  완료! valuation.py에서 아래와 같이 사용:")
    print(f"")
    print(f"    from pathlib import Path")
    print(f"    import json")
    print(f"    def load_valuation_input(code: str) -> dict:")
    print(f"        p = Path('data/valuation_input/by_stock_code') / f'{{code}}.json'")
    print(f"        return json.loads(p.read_text('utf-8')) if p.exists() else {{}}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
