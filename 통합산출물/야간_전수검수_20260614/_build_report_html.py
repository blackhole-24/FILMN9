# -*- coding: utf-8 -*-
"""야간 1번-b(v2): 분석가능 종목(재무+주가) 기준 신뢰성 리포트.
기준: company_info 3,965 = 실제상장(~2,600)보다 많음(우선주·스팩·코넥스·상폐 섞임).
→ '분석가능 종목' = 재무하이라이트 O AND 주가 O. 이 안에서 각 모듈 커버리지를 봄(=진짜 검수)."""
import csv, re
from pathlib import Path
from datetime import datetime

OUT = Path(r"C:\Users\Admin\FILMN9\통합산출물\야간_전수검수_20260614")
rows = list(csv.DictReader(open(OUT / "검수_매트릭스.csv", encoding="utf-8-sig")))
# 분석가능 기준 모듈
BASE = ["재무하이라이트", "주가"]
# 분석가능 종목 안에서 점검할 모듈
CHECK = ["재무제표1년+", "재무제표3년", "손익흐름도", "주주구성", "경영인", "히스토리브리핑", "밸류에이션"]

analyzable = [r for r in rows if all(r[b] == "O" for b in BASE)]
A = len(analyzable) or 1
nonanal = [r for r in rows if r not in analyzable]

def label_non(r):
    nm = (r["회사명"] or "").strip()
    if "스팩" in nm: return "스팩(SPAC)"
    if re.search(r"우[0-9B]*$", nm): return "우선주"
    if r["시장"] == "기타": return "코넥스/기타시장"
    if r["주가"] == "X" and r["재무하이라이트"] == "X": return "데이터없음(상폐/신규/거래정지 추정)"
    if r["재무하이라이트"] == "X": return "재무없음"
    return "주가없음"
nseg = {}
for r in nonanal: nseg.setdefault(label_non(r), []).append(r)

def cov(m): return sum(1 for r in analyzable if r[m] == "O")
covc = {m: cov(m) for m in CHECK}
# 분석가능인데 핵심(재무제표·손익흐름도·주주·경영인) 누락 = 진짜 점검 대상
CORE_IN = ["재무제표1년+", "손익흐름도", "주주구성", "경영인"]
prob = [r for r in analyzable if any(r[m] == "X" for m in CORE_IN)]
prob.sort(key=lambda r: -sum(1 for m in CORE_IN if r[m] == "X"))

NOW = datetime.now().strftime("%Y-%m-%d %H:%M")
def bar(pct, c):
    return f'<div style="background:#e2e8f0;border-radius:5px;height:9px;width:150px;display:inline-block;vertical-align:middle"><div style="background:{c};height:9px;border-radius:5px;width:{pct}%"></div></div>'
def modrow(m):
    n = covc[m]; pct = n * 100 // A; c = "#22c55e" if pct >= 90 else "#f59e0b" if pct >= 60 else "#ef4444"
    part = " <span style='font-size:11px;color:#94a3b8'>(설계상 일부만)</span>" if m in ("밸류에이션", "히스토리브리핑", "재무제표3년") else ""
    return f"<tr><td><b>{m}</b>{part}</td><td>{n:,} / {A:,}</td><td>{bar(pct,c)} <b style='color:{c}'>{pct}%</b></td></tr>"
check_rows = "".join(modrow(m) for m in CHECK)
nseg_rows = "".join(f"<tr><td>{k}</td><td style='text-align:right'>{len(v):,}</td></tr>" for k, v in sorted(nseg.items(), key=lambda x: -len(x[1])))
prob_rows = "".join(
    f"<tr><td>{r['종목코드']}</td><td>{r['회사명']}</td><td>{r['업종'][:16]}</td><td style='color:#ef4444'>{', '.join(m for m in CORE_IN if r[m]=='X')}</td></tr>"
    for r in prob[:200])

html = f"""<!DOCTYPE html><html lang=ko><head><meta charset=UTF-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>FINSIGHT 전수 검수 리포트</title><style>
body{{font-family:'Segoe UI','Malgun Gothic',sans-serif;background:#f5f7fb;color:#1e293b;padding:26px 18px;line-height:1.5}}
.wrap{{max-width:1080px;margin:0 auto}} h1{{font-size:26px;font-weight:800}} h2{{font-size:17px;margin:26px 0 10px;font-weight:800}}
.sub{{color:#64748b;font-size:13px;margin-top:4px}} .card{{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:18px 20px;margin-top:12px;box-shadow:0 1px 3px rgba(15,23,42,.04)}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:7px 10px;border-bottom:1px solid #eef2f7;text-align:left}} th{{background:#f8fafc;font-size:12px;color:#64748b}}
.kpi{{display:flex;gap:14px;flex-wrap:wrap;margin-top:12px}} .kpi div{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:14px 20px;flex:1;min-width:150px}}
.kpi b{{font-size:24px;color:#6366f1}} .kpi span{{font-size:12px;color:#64748b;display:block}}
.note{{background:#ecfdf5;border:1px solid #bbf7d0;border-radius:10px;padding:10px 14px;font-size:13px;margin-top:12px;color:#166534}}</style></head><body><div class=wrap>
<h1>🩺 FINSIGHT 전수 검수 리포트</h1><p class=sub>기능 모듈별 데이터 전수 실측 · 로컬 SQLite/파일/Mongo · {NOW} · NO-MOCK</p>
<div class=kpi>
<div><span>company_info 전체</span><b>{len(rows):,}</b>종</div>
<div><span>✅ 분석가능(재무+주가)</span><b style="color:#16a34a">{A:,}</b>종</div>
<div><span>분석불가(우선주·스팩·상폐 등)</span><b style="color:#94a3b8">{len(nonanal):,}</b>종</div>
<div><span>분석가능 中 핵심모듈 누락</span><b style="color:#ef4444">{len(prob):,}</b>종</div>
</div>
<div class=note>📌 <b>분석가능 종목 = 재무 하이라이트 + 주가가 둘 다 있는 종목</b>(서비스가 실제 분석 가능한 모집단, ≈ 실제 상장사 수). 이 안에서 각 기능 모듈이 얼마나 채워졌는지가 진짜 검수입니다. company_info엔 우선주·스팩·코넥스·상폐 엔트리가 섞여 전체수가 큽니다(아래 분리).</div>

<h2>✅ 분석가능 종목 내 기능 모듈 커버리지</h2><div class=card><table><tr><th>기능 모듈</th><th>보유</th><th>커버리지</th></tr>{check_rows}</table>
<p class=sub style="margin-top:8px">밸류에이션(2,224)·히스토리브리핑·재무제표3년은 설계상 전 종목 대상이 아님 → 낮은 %는 "오류"가 아니라 "미산출".</p></div>

<h2>🗂 분석불가 종목 분류 ({len(nonanal):,}종)</h2><div class=card><table><tr><th>분류</th><th style='text-align:right'>종목수</th></tr>{nseg_rows}</table>
<p class=sub style="margin-top:8px">우선주는 본주 데이터 공유·스팩/코넥스/상폐는 분석대상 아님 → 정상. "데이터없음"이 많으면 신규상장/거래정지 가능.</p></div>

<h2>⚠️ 분석가능인데 핵심 모듈 누락 (상위 200 · 내일 직접 검토)</h2><div class=card><table><tr><th>코드</th><th>회사명</th><th>업종</th><th style='color:#ef4444'>누락(재무제표·손익흐름도·주주·경영인)</th></tr>{prob_rows}</table>
<p class=sub style="margin-top:8px">전체는 <b>검수_매트릭스.csv</b> (핵심누락수 정렬). 이게 진짜 손봐야 할 후보들.</p></div>

<p style="text-align:center;color:#94a3b8;font-size:11px;margin-top:40px;letter-spacing:.2em">FILMN9 Inc. · 야간 자율 검수</p>
</div></body></html>"""
(OUT / "검수_리포트.html").write_text(html, encoding="utf-8")
print(f"분석가능 {A}종 / 핵심누락 {len(prob)}종")
for m in CHECK: print(f"  {m}: {covc[m]}/{A} ({covc[m]*100//A}%)")
print("분석불가 분류:", {k: len(v) for k, v in nseg.items()})
print("저장:", OUT / "검수_리포트.html")
