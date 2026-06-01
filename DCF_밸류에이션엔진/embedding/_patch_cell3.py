# -*- coding: utf-8 -*-
"""노트북 cell 3(build_corpcode_map)을 견고화 버전으로 교체: 세션+재시도+디스크캐시."""
import json
from pathlib import Path

NB = Path(r"C:\Users\Admin\Desktop\VAR\embedding\collect_embed_new_reports.ipynb")

new_src = r'''# ── 3) corp_code 매핑 (corpCode.xml — 세션+재시도+로컬캐시) ───────────
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except Exception:
    Retry = None
CORPCODE_CACHE = VAR_ROOT / "embedding" / "corpcode.xml"   # 1회 받으면 재사용(재실행시 재다운로드X)

def build_corpcode_map():
    if CORPCODE_CACHE.exists() and CORPCODE_CACHE.stat().st_size > 100000:
        xmlb = CORPCODE_CACHE.read_bytes()
    else:
        s = requests.Session()
        if Retry:
            s.mount("https://", HTTPAdapter(max_retries=Retry(
                total=6, backoff_factor=1.5,
                status_forcelist=[429,500,502,503,504], allowed_methods=["GET"])))
        last = None
        for attempt in range(6):
            try:
                r = s.get("https://opendart.fss.or.kr/api/corpCode.xml",
                          params={"crtfc_key": DART_KEY}, timeout=300)
                r.raise_for_status()
                z = zipfile.ZipFile(io.BytesIO(r.content))
                xmlb = z.read(z.namelist()[0])
                CORPCODE_CACHE.write_bytes(xmlb)   # 캐시 저장
                break
            except Exception as e:
                last = e
                print(f"  corpCode 재시도 {attempt+1}/6 — {str(e)[:80]}")
                time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"corpCode.xml 다운로드 실패(재시도 소진): {last}")
    root = ET.fromstring(xmlb)
    m = {}
    for el in root.iter("list"):
        sc=(el.findtext("stock_code") or "").strip(); cc=(el.findtext("corp_code") or "").strip()
        cn=(el.findtext("corp_name") or "").strip()
        if sc and cc: m[sc.zfill(6)] = {"corp_code": cc.zfill(8), "corp_name": cn}
    return m

CORP = build_corpcode_map()
print("corp_code 매핑:", len(CORP), "| 캐시:", CORPCODE_CACHE)
'''

nb = json.load(open(NB, encoding="utf-8"))
patched = 0
for c in nb["cells"]:
    if c["cell_type"] == "code" and any("build_corpcode_map" in ln for ln in c["source"]):
        c["source"] = new_src.splitlines(keepends=True)
        patched += 1
json.dump(nb, open(NB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("cell 3 패치:", patched, "곳")

# 문법 검증
import ast
for c in nb["cells"]:
    if c["cell_type"] == "code":
        ast.parse("".join(c["source"]))
print("전체 코드셀 문법 OK")
