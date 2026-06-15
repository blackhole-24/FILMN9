# -*- coding: utf-8 -*-
"""
daily_status_update.py
======================
하루 1회 실행 — 상장 상태 + 누락 데이터 자동 갱신 파이프라인.

순서:
  1) gap_analysis.py        : 현재 상장(KRX-DESC) 대비 주가/재무 누락분 재산출
  2) backfill_price.py      : 누락 주가 yfinance 백필
  3) backfill_financials.py : 누락 재무 DART 백필
  4) build_stock_status.py  : 상장폐지/거래정지/관리종목 상태 최종 갱신

Windows Task Scheduler 등록 예 (장 마감 후 18:30):
  schtasks /Create /TN "FILMN9_DailyStatus" /TR "python C:\\Users\\Admin\\FILMN9\\daily_status_update.py" /SC DAILY /ST 18:30
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
PY = sys.executable
STEPS = [
    ("누락 재산출",      "gap_analysis.py"),
    ("주가 백필",        "backfill_price.py"),
    ("재무 백필",        "backfill_financials.py"),
    ("DART 정지공시 증분", "dart_halt_scan.py", ["--days", "14"]),  # 거래정지/해제 14일 갱신
    ("상태 갱신",        "build_stock_status.py"),
]


def run(label, script, extra=None):
    print(f"\n{'='*60}\n[{datetime.now():%H:%M:%S}] {label} → {script}\n{'='*60}")
    cmd = [PY, str(ROOT / script)] + (extra or [])
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        print(f"  ⚠️ {script} 실패 (코드 {r.returncode}) — 다음 단계 계속")


def main():
    print(f"FILMN9 일일 상태/데이터 갱신 시작 — {datetime.now():%Y-%m-%d %H:%M:%S}")
    for step in STEPS:
        label, script = step[0], step[1]
        extra = step[2] if len(step) > 2 else None
        run(label, script, extra)
    print(f"\n[{datetime.now():%H:%M:%S}] 일일 갱신 전체 완료")


if __name__ == "__main__":
    main()
