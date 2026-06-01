"""
db/batch_demo10.py
==================
시연 10종목 일괄 수집 + DB 적재 자동화.

작업 흐름
---------
For each of 10 demo stocks:
  1) build_overview.py {code}    → company_info.json + financials.json
  2) build_ohlcv.py {code}       → ohlcv.json
  3) load_to_db.py --code {code} → SQLite 적재

각 단계 실패해도 다음 종목 계속 진행 (예외 격리).

사용법
------
cd C:/Users/Admin/FILMN9
python db/batch_demo10.py             # 전체 실행
python db/batch_demo10.py --skip-fetch # 이미 JSON 있으면 DB 적재만
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
PY   = sys.executable
FIN  = ROOT / "기업개요_파트" / "재무정보"
DB   = ROOT / "db"

DEMO_10 = [
    # 휘주님 142개 history 중에서 선정 (10업종 다양성, KOSPI 대형주)
    ("002790", "아모레퍼시픽홀딩스"),
    ("003490", "대한항공"),
    ("009240", "한샘"),
    ("030200", "KT"),
    ("033780", "KT&G"),
    ("034220", "LG디스플레이"),
    ("071840", "롯데하이마트"),
    ("138930", "BNK금융지주"),
    ("267260", "HD현대일렉트릭"),
    ("373220", "LG에너지솔루션"),
]


def _run(cmd: list[str], cwd: Path = ROOT) -> tuple[bool, str]:
    """파이썬 스크립트 실행. 성공 여부 + 출력 일부 반환."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True,
            text=True, encoding="utf-8", errors="ignore",
            timeout=180,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out[-300:]
    except subprocess.TimeoutExpired:
        return False, "[TIMEOUT] 3분 초과"
    except Exception as e:
        return False, f"[ERR] {e}"


def step_overview(code: str) -> bool:
    """build_overview.py 실행."""
    print(f"    1) build_overview ...", end="", flush=True)
    ok, msg = _run([PY, str(FIN / "build_overview.py"), code], cwd=FIN)
    print(" ✅" if ok else f" ❌  ({msg[-100:]})")
    return ok


def step_ohlcv(code: str) -> bool:
    """build_ohlcv.py 실행."""
    print(f"    2) build_ohlcv    ...", end="", flush=True)
    ok, msg = _run([PY, str(FIN / "build_ohlcv.py"), code], cwd=FIN)
    print(" ✅" if ok else f" ❌  ({msg[-100:]})")
    return ok


def step_load(code: str) -> bool:
    """load_to_db.py --code 실행."""
    print(f"    3) load_to_db     ...", end="", flush=True)
    ok, msg = _run([PY, str(DB / "load_to_db.py"), "--code", code], cwd=ROOT)
    print(" ✅" if ok else f" ❌  ({msg[-100:]})")
    return ok


def main():
    p = argparse.ArgumentParser(description="시연 10종목 일괄 수집·적재")
    p.add_argument("--skip-fetch", action="store_true",
                   help="JSON 수집 단계 건너뛰고 DB 적재만 수행")
    args = p.parse_args()

    t0 = time.time()
    print(f"\n{'='*70}")
    print(f"  batch_demo10.py 시작 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  대상: {len(DEMO_10)} 종목")
    print(f"  모드: {'적재만' if args.skip_fetch else '수집+적재'}")
    print(f"{'='*70}\n")

    results = {"ok": [], "fail": []}

    for i, (code, name) in enumerate(DEMO_10, 1):
        print(f"\n  [{i}/{len(DEMO_10)}]  {code}  {name}")
        print(f"  {'-'*60}")

        ok_overview = True
        ok_ohlcv    = True

        if not args.skip_fetch:
            ok_overview = step_overview(code)
            ok_ohlcv    = step_ohlcv(code)

        ok_load = step_load(code)

        if ok_overview and ok_ohlcv and ok_load:
            results["ok"].append((code, name))
        else:
            results["fail"].append((code, name, {
                "overview": ok_overview, "ohlcv": ok_ohlcv, "load": ok_load
            }))

    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"  완료 요약 - {elapsed:.0f}초 소요")
    print(f"{'='*70}")
    print(f"  성공: {len(results['ok'])}/{len(DEMO_10)} 종목")
    for code, name in results["ok"]:
        print(f"    ✅ {code}  {name}")
    if results["fail"]:
        print(f"\n  실패: {len(results['fail'])} 종목")
        for code, name, status in results["fail"]:
            print(f"    ❌ {code}  {name}  ({status})")

    # 최종 DB 통계
    print(f"\n{'='*70}")
    print(f"  최종 DB 통계")
    print(f"{'='*70}")
    _run([PY, str(DB / "load_to_db.py"), "--stats"], cwd=ROOT)
    r = subprocess.run([PY, str(DB / "load_to_db.py"), "--stats"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    print(r.stdout)


if __name__ == "__main__":
    main()
