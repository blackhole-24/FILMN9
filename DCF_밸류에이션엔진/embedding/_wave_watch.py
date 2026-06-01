# -*- coding: utf-8 -*-
"""재시작(01:03) 이후 첫 최적화 웨이브들을 감지해 처리율을 측정/보고."""
import glob, os, time, json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VAR = Path(r"C:\Users\Admin\Desktop\VAR")
CUTOFF = time.mktime(time.strptime("2026-05-28 01:03", "%Y-%m-%d %H:%M"))  # 커널 재시작
POLL = 90
MAX_MIN = 120
OLD_RATE = 28.0  # 기존 처리율(청크/초) 참고치


def scan():
    """재시작 이후 새 q1 jsonl → 웨이브(mtime 군집)별 (끝시각, 건수, 청크수)."""
    files = glob.glob(str(VAR / "KOSPI" / "*_2026_q1_chunks.jsonl")) + \
            glob.glob(str(VAR / "KOSDAQ" / "*_2026_q1_chunks.jsonl"))
    new = [(os.path.getmtime(f), f) for f in files if os.path.getmtime(f) > CUTOFF]
    new.sort()
    if not new:
        return []
    waves = []
    cur = [new[0]]
    for t, f in new[1:]:
        if t - cur[-1][0] > 30:
            waves.append(cur); cur = [(t, f)]
        else:
            cur.append((t, f))
    waves.append(cur)
    out = []
    for w in waves:
        end = max(t for t, _ in w)
        chunks = 0
        for _, f in w:
            try:
                with open(f, encoding="utf-8") as fh:
                    chunks += sum(1 for _ in fh)
            except Exception:
                pass
        out.append({"end": end, "reports": len(w), "chunks": chunks})
    return out


start = time.time()
print(f"[watch] 시작 {time.strftime('%H:%M:%S')} — 재시작 이후 새 웨이브 대기...", flush=True)
reported = 0
while (time.time() - start) / 60 < MAX_MIN:
    waves = scan()
    if len(waves) > reported:
        for i in range(reported, len(waves)):
            w = waves[i]
            ts = time.strftime("%H:%M:%S", time.localtime(w["end"]))
            if i == 0:
                dur = w["end"] - CUTOFF  # 첫 웨이브는 discovery+모델로드 포함(참고용)
                note = "(discovery+로드 포함)"
            else:
                dur = w["end"] - waves[i - 1]["end"]  # 순수 웨이브 소요
                note = "(순수 웨이브)"
            rate = w["chunks"] / dur if dur > 0 else 0
            speedup = rate / OLD_RATE if OLD_RATE else 0
            print(f"[watch] 웨이브 #{i+1} 완료 {ts} | {w['reports']}건 "
                  f"{w['chunks']:,}청크 | {dur/60:.1f}분 | {rate:.0f}청크/초 "
                  f"{note} → 기존대비 {speedup:.2f}x", flush=True)
        reported = len(waves)
    # 순수 웨이브(2번째) 측정되면 종료
    if reported >= 2:
        print("[watch] 새 웨이브 2개 측정 완료 — 종료.", flush=True)
        sys.exit(0)
    time.sleep(POLL)

print("[watch] 시간초과 종료.", flush=True)
