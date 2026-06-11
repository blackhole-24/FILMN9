# -*- coding: utf-8 -*-
"""밸류 전수취합: 이미 계산된 results(합본) → 6파일 변환 → data/valuation_results 배치.
OpenAI 호출 없음(무료). 백엔드 인식 폴더명 = {code}_{corp_name}."""
import sys, sqlite3, re, shutil, time
from pathlib import Path
sys.path.insert(0, r"C:\Users\Admin\FILMN9\DCF_밸류에이션엔진")
from valuation_engine.export_poc import export_one, _find_latest_integrated, _RESULTS_DIR

ROOT = Path(r"C:\Users\Admin\FILMN9")
DEST = ROOT / "data" / "valuation_results"
TEMP = ROOT / "data" / "_val_export_tmp"
DEST.mkdir(parents=True, exist_ok=True)
TEMP.mkdir(parents=True, exist_ok=True)

# code → corp_name (filmn9.db)
conn = sqlite3.connect(str(ROOT / "data" / "filmn9.db"))
name_map = dict(conn.execute("SELECT stock_code, corp_name FROM company_info").fetchall())
conn.close()

# results 의 고유 종목코드
codes = sorted({m.group(1) for f in _RESULTS_DIR.glob("valuation_*.json")
                if (m := re.match(r"valuation_(\d{6})_", f.name))})
print(f"대상 종목: {len(codes)}개\n")

ok = 0
fail = []
t0 = time.time()
for i, code in enumerate(codes, 1):
    try:
        p = _find_latest_integrated(code)
        if not p:
            fail.append((code, "통합 JSON 없음"))
            continue
        export_one(p, TEMP, verbose=False)          # TEMP/{code}/ 6파일
        nm = re.sub(r'[\\/:*?"<>|]', '', (name_map.get(code) or '')).strip() or "NA"
        dest = DEST / f"{code}_{nm}"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(TEMP / code), str(dest))
        ok += 1
    except Exception as e:
        fail.append((code, str(e)[:60]))
    if i % 200 == 0:
        print(f"  {i}/{len(codes)} ... 배치 {ok} / 실패 {len(fail)} ({time.time()-t0:.0f}s)")

# 정리
try:
    shutil.rmtree(TEMP)
except Exception:
    pass

print(f"\n=== 완료: {ok}종 배치 / 실패 {len(fail)}종 / {time.time()-t0:.0f}s ===")
if fail:
    print("실패 샘플(최대 20):")
    for c, e in fail[:20]:
        print(f"  {c}: {e}")
total = len(list(DEST.glob("*")))
print(f"data/valuation_results 총 폴더: {total}개")
