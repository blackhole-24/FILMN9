# -*- coding: utf-8 -*-
"""상장중(DESC) 대비 주가/재무 누락 종목 규모 측정"""
import sqlite3
import FinanceDataReader as fdr

def pad(s): return str(s).zfill(6)

desc = fdr.StockListing("KRX-DESC")
desc_set = set(pad(c) for c in desc["Code"])
delist = fdr.StockListing("KRX-DELISTING")
delist_set = set(pad(s) for s in delist["Symbol"])
print(f"현재상장(DESC): {len(desc_set)}  상폐이력: {len(delist_set)}")

c = sqlite3.connect(r"C:\Users\Admin\FILMN9\data\filmn9.db")
market_latest = c.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0]
print(f"시장 최신 거래일(our ohlcv): {market_latest}")

# 종목별 최신 거래일
ohlcv_last = dict(c.execute("SELECT stock_code, MAX(date) FROM ohlcv GROUP BY stock_code").fetchall())
fin_codes = set(r[0] for r in c.execute("SELECT DISTINCT stock_code FROM financial_detail").fetchall())
ci_codes = set(r[0] for r in c.execute("SELECT stock_code FROM company_info").fetchall())
c.close()

# 상장중 종목 기준 누락
listed = desc_set
ohlcv_have = set(ohlcv_last.keys())
ohlcv_fresh = set(k for k, v in ohlcv_last.items() if v and v >= "2026-05-20")  # 최근 거래

gap_price = sorted(listed - ohlcv_fresh)       # 상장중인데 최근주가 없음
gap_fin = sorted(listed - fin_codes)           # 상장중인데 재무 없음
delisted_known = sorted((ci_codes | ohlcv_have) - listed)  # 우리가 아는데 상폐된 것

print(f"\n[상장중 {len(listed)}개 기준]")
print(f"  최근 주가 누락: {len(gap_price)}개")
print(f"  재무 누락     : {len(gap_fin)}개")
print(f"\n우리 DB에 있으나 현재 비상장(상폐 등): {len(delisted_known)}개")
print(f"  그중 상폐이력 확인됨: {len([x for x in delisted_known if x in delist_set])}개")

# 백필 대상 저장
import json
json.dump({"gap_price": gap_price, "gap_fin": gap_fin},
          open(r"C:\Users\Admin\FILMN9\data\backfill_targets.json", "w"), ensure_ascii=False)
print("\n→ data/backfill_targets.json 저장")
