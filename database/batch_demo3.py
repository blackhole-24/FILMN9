"""
db/batch_demo3.py
=================
데모 3종목 Tab1 데이터 풀자동 적재 (재실행 안전).

흐름
----
For each of DEMO_3:
  1) build_overview.py {code}    → company_info + financials
  2) build_ohlcv.py {code}       → ohlcv
  3) load_to_db.py --code {code} → SQLite 적재 (company/fin/ohlcv)
  4) build_extras.py {code}      → shareholders/executives/disclosures/financial_detail
  5) load_extras.py --code {code}→ SQLite 적재

사용법
------
cd C:/Users/Admin/FILMN9
python db/batch_demo3.py             # 풀 실행
python db/batch_demo3.py --skip-fetch # JSON 이미 있으면 DB 적재만
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
PY   = sys.executable
FIN  = ROOT / "part_company_overview" / "재무정보"
DB   = ROOT / "db"

DEMO_3 = [
    ("090430", "아모레퍼시픽"),
    ("009150", "삼성전기"),
    ("035420", "NAVER"),
]


def _run(cmd: list[str], cwd: Path = ROOT, timeout: int = 180) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="ignore", timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out[-200:]
    except subprocess.TimeoutExpired:
        return False, "[TIMEOUT]"
    except Exception as e:
        return False, f"[ERR] {e}"


def steps_for(code: str, skip_fetch: bool) -> dict:
    res = {}
    if not skip_fetch:
        print(f"    1) build_overview ...", end="", flush=True)
        ok, msg = _run([PY, str(FIN / "build_overview.py"), code], cwd=FIN)
        res["overview"] = ok
        print(" OK" if ok else f" FAIL ({msg[-80:]})")

        print(f"    2) build_ohlcv    ...", end="", flush=True)
        ok, msg = _run([PY, str(FIN / "build_ohlcv.py"), code], cwd=FIN)
        res["ohlcv"] = ok
        print(" OK" if ok else f" FAIL ({msg[-80:]})")

    print(f"    3) load_to_db     ...", end="", flush=True)
    ok, msg = _run([PY, str(DB / "load_to_db.py"), "--code", code], cwd=ROOT)
    res["load_base"] = ok
    print(" OK" if ok else f" FAIL ({msg[-80:]})")

    if not skip_fetch:
        print(f"    4) build_extras   ...", end="", flush=True)
        ok, msg = _run([PY, str(FIN / "build_extras.py"), code], cwd=ROOT, timeout=300)
        res["extras"] = ok
        print(" OK" if ok else f" FAIL ({msg[-80:]})")

    print(f"    5) load_extras    ...", end="", flush=True)
    ok, msg = _run([PY, str(DB / "load_extras.py"), "--code", code], cwd=ROOT)
    res["load_extras"] = ok
    print(" OK" if ok else f" FAIL ({msg[-80:]})")

    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--skip-fetch", action="store_true",
                   help="JSON 수집 건너뛰고 DB 적재만")
    args = p.parse_args()

    t0 = time.time()
    print(f"\n{'='*60}")
    print(f"  batch_demo3.py 시작  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  대상: {len(DEMO_3)}종목  모드: {'적재만' if args.skip_fetch else '수집+적재'}")
    print(f"{'='*60}")

    results = []
    for i, (code, name) in enumerate(DEMO_3, 1):
        print(f"\n  [{i}/{len(DEMO_3)}]  {code}  {name}")
        results.append((code, name, steps_for(code, args.skip_fetch)))

    print(f"\n{'='*60}")
    print(f"  완료  ({time.time()-t0:.0f}초)")
    print(f"{'='*60}")
    for code, name, res in results:
        all_ok = all(res.values())
        mark = "OK" if all_ok else "FAIL"
        print(f"  [{mark}] {code}  {name}  {res}")


if __name__ == "__main__":
    main()
