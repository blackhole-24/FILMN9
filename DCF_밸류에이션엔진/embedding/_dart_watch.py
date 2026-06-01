# -*- coding: utf-8 -*-
"""OpenDART 복구 감시: 5분마다 corpCode.xml 단발 시도. 성공 시 캐시 저장 후 종료."""
import io, time, zipfile, sys
from pathlib import Path
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VAR_ROOT = Path(r"C:\Users\Admin\Desktop\VAR")
CACHE = VAR_ROOT / "embedding" / "corpcode.xml"
key = None
for ln in (VAR_ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if ln.startswith("DART_API_KEY"):
        key = ln.split("=", 1)[1].strip()

URL = "https://opendart.fss.or.kr/api/corpCode.xml"
MAX_ATTEMPTS = 48          # 5분 × 48 = 최대 4시간 감시
INTERVAL = 300

for attempt in range(1, MAX_ATTEMPTS + 1):
    try:
        r = requests.get(URL, params={"crtfc_key": key}, timeout=60)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xmlb = z.read(z.namelist()[0])
        if len(xmlb) < 100000:
            raise RuntimeError(f"의심스런 작은 응답 {len(xmlb)}B: {xmlb[:200]!r}")
        CACHE.write_bytes(xmlb)
        print(f"RECOVERED at attempt {attempt} ({time.strftime('%H:%M:%S')}) "
              f"- corpcode.xml cached OK ({len(xmlb)} bytes)", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] attempt {attempt}/{MAX_ATTEMPTS} "
              f"still down - {type(e).__name__}", flush=True)
        if attempt < MAX_ATTEMPTS:
            time.sleep(INTERVAL)

print("WATCH ENDED - no recovery within window. restart needed.", flush=True)
sys.exit(1)
