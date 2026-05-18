"""
VEDA 데이터 수집 통합 테스트
실행: conda activate FILMN9_env
      cd C:\Users\Admin\FILMN9
      python notebooks/test_collection.py
"""

import sys
import json
sys.path.append(".")

from src.collectors.dart_collector import collect_all
from src.collectors.ecos_collector import get_all_rf
from src.calculators.beta_calculator import calc_all_betas
from src.calculators.wacc_constants import get_erp, get_srp
from datetime import datetime

# ============================================================
# 테스트 파라미터 (뷰노 — 실제 평가서 예시 기업)
# ============================================================
COMPANY     = "뷰노"
EVAL_DATE   = "2024-06-30"
TICKER      = "338220.KQ"    # 코스닥
BENCHMARK   = "^KQ11"        # 코스닥 지수
STOCK_PRICE = 11755           # 평가기준일 종가 (직접 입력)
SHARES      = 28_600_000      # 발행주식수 (직접 입력)

print("\n[1] DART 전체 수집")
result = collect_all(COMPANY, EVAL_DATE, STOCK_PRICE, SHARES)

print("\n[2] Rf 수집 (ECOS)")
rf_data = get_all_rf(EVAL_DATE)
for t, d in rf_data.items():
    if "error" not in d:
        print(f"  국고채 {t}: {d['rf_pct']:.2f}%")

print("\n[3] Beta 계산")
beta_result = calc_all_betas(
    ticker    = TICKER,
    benchmark = BENCHMARK,
    eval_date = datetime.strptime(EVAL_DATE, "%Y-%m-%d"),
    tc        = result["tax"]["tc"],
    ibd       = result["ibd"]["ibd_total"],
    mktcap    = result["mktcap"],
)
for p in ["5년월간", "2년주간"]:
    bd = beta_result.get(p, {})
    if bd.get("beta_raw"):
        print(f"  {p}: Raw={bd['beta_raw']:.4f} | Adj={bd.get('beta_adjusted','N/A')} | "
              f"β_U={bd.get('beta_u','N/A')} | R²={bd.get('r_squared','N/A'):.3f}")

print("\n[4] ERP / SRP")
erp = get_erp()
srp = get_srp(result["mktcap"])
print(f"  ERP = {erp['erp']*100:.1f}% | SRP = {srp['srp']*100:.2f}% ({srp['label']})")

print("\n" + "="*60)
print("최종 결과 요약")
print("="*60)
print(f"  기업명     : {result['meta']['company_name']}")
print(f"  시가총액   : {result['mktcap']/1e8:.0f}억원")
print(f"  IBD        : {result['ibd']['ibd_total']/1e8:.0f}억원")
print(f"  NOA        : {result['noa']['noa']/1e8:.0f}억원")
print(f"  LTM EBIT   : {result['ebit']['ltm_ebit']/1e8:.0f}억원")
print(f"  Tax Rate   : {result['tax']['tc']*100:.1f}% ({result['tax']['bracket']})")
print(f"  FCFF       : {result['fcff']['fcff']/1e8:.0f}억원")
print(f"  EV         : {result['multiples']['ev']/1e8:.0f}억원")
print(f"  EV/EBITDA  : {result['multiples']['multiples']['ev_ebitda']}배")
print(f"  P/E        : {result['multiples']['multiples']['per']}배")
print(f"  Rf (10Y)   : {rf_data.get('10Y', {}).get('rf_pct', 'N/A')}%")
print(f"  β_L (기본) : {beta_result.get('recommended_beta_l', 'N/A')}")
print(f"  β_U (기본) : {beta_result.get('recommended_beta_u', 'N/A')}")
print(f"  ERP        : {erp['erp']*100:.1f}%")
print(f"  SRP        : {srp['srp']*100:.2f}%")

with open("outputs/test_result.json", "w", encoding="utf-8") as f:
    json.dump(
        {"dart": result, "rf": rf_data, "beta": beta_result, "erp": erp, "srp": srp},
        f, ensure_ascii=False, indent=2, default=str
    )
print("\n  outputs/test_result.json 저장 완료 ✅")
