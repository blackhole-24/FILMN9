# -*- coding: utf-8 -*-
"""_repo_index_data.txt -> FILMN9_GitHub_전체파일_트리맵.html
   폴더 트리 구조로 각 파일의 핵심내용/목적/역할/효과를 표로 렌더링."""
import os, html

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "_repo_index_data.txt")
OUT = os.path.join(BASE, "FILMN9_GitHub_전체파일_트리맵.html")

# ---- 데이터 로드 ----
rows = []
with open(SRC, "r", encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|||")]
        if len(parts) < 5:
            continue
        rows.append(parts[:5])  # path, 핵심, 목적, 역할, 효과

# briefs_final 요약 행 추가
rows.append([
    "briefs_final/  (폴더 전체 ~2,529개 파일)",
    "한 종목당 1개 JSON 브리핑(2,526종목+요약/선택상세 보조)",
    "LLM(gpt-5-mini) 사업보고서 자동요약 브리핑 산출물",
    "stock_code·meta(wics/tier)·brief(개요/사업모델/고객/주가요인/근거/confidence) 스키마",
    "종목 상세화면 히스토리 브리핑 데이터 공급(Mongo 적재용)",
])

# ---- 트리 빌드 ----
# node = {"dirs": {name: node}, "files": [ (filename, row) ]}
def new_node():
    return {"dirs": {}, "files": []}

root = new_node()
for r in rows:
    path = r[0]
    # briefs_final 특수행
    if path.startswith("briefs_final/"):
        root["dirs"].setdefault("briefs_final", new_node())
        root["dirs"]["briefs_final"]["files"].append(("(폴더 전체 ~2,529개)", r))
        continue
    parts = path.split("/")
    if len(parts) == 1:
        root["files"].append((parts[0], r))
    else:
        cur = root
        for d in parts[:-1]:
            cur = cur["dirs"].setdefault(d, new_node())
        cur["files"].append((parts[-1], r))

total_files = len(rows)

def count_files(node):
    n = len(node["files"])
    for d in node["dirs"].values():
        n += count_files(d)
    return n

# ---- 렌더 ----
def esc(s):
    return html.escape(s, quote=True)

def ext_class(fn):
    low = fn.lower()
    if low.endswith(".py"): return "py"
    if low.endswith((".tsx", ".ts", ".mjs")): return "ts"
    if low.endswith((".md", ".txt")): return "doc"
    if low.endswith((".json", ".csv")): return "data"
    if low.endswith((".html",)): return "html"
    if low.endswith((".bat", ".ps1")): return "bat"
    if low.endswith((".xlsx", ".docx", ".png", ".svg", ".ico", ".excalidraw")): return "bin"
    return "etc"

def render_node(name, node, depth, path_prefix):
    parts = []
    fcount = count_files(node)
    full = (path_prefix + "/" + name) if path_prefix else name
    parts.append(f'<details class="folder" open>')
    parts.append(f'<summary class="dirsum" style="--d:{depth}">'
                 f'<span class="fic">📁</span> <span class="dname">{esc(name)}/</span>'
                 f' <span class="cnt">{fcount}개</span></summary>')
    parts.append('<div class="folder-body">')
    # 직속 파일 표
    if node["files"]:
        parts.append('<table class="ftab"><thead><tr>'
                     '<th class="cfile">파일</th><th>핵심 내용 한줄</th><th>목적</th>'
                     '<th>역할</th><th>효과</th></tr></thead><tbody>')
        for fn, r in node["files"]:
            cls = ext_class(fn)
            parts.append(
                f'<tr data-fn="{esc(fn.lower())}">'
                f'<td class="cfile"><span class="dot {cls}"></span>{esc(fn)}</td>'
                f'<td class="core">{esc(r[1])}</td>'
                f'<td>{esc(r[2])}</td>'
                f'<td>{esc(r[3])}</td>'
                f'<td>{esc(r[4])}</td></tr>')
        parts.append('</tbody></table>')
    # 하위 폴더
    for dn in sorted(node["dirs"].keys()):
        parts.append(render_node(dn, node["dirs"][dn], depth + 1, full))
    parts.append('</div></details>')
    return "".join(parts)

body = []
# 루트 직속 파일
if root["files"]:
    body.append('<details class="folder" open><summary class="dirsum" style="--d:0">'
                '<span class="fic">📦</span> <span class="dname">FILMN9/ (루트 파일)</span>'
                f' <span class="cnt">{len(root["files"])}개</span></summary>')
    body.append('<div class="folder-body">')
    body.append('<table class="ftab"><thead><tr>'
                '<th class="cfile">파일</th><th>핵심 내용 한줄</th><th>목적</th>'
                '<th>역할</th><th>효과</th></tr></thead><tbody>')
    for fn, r in root["files"]:
        cls = ext_class(fn)
        body.append(
            f'<tr data-fn="{esc(fn.lower())}">'
            f'<td class="cfile"><span class="dot {cls}"></span>{esc(fn)}</td>'
            f'<td class="core">{esc(r[1])}</td>'
            f'<td>{esc(r[2])}</td><td>{esc(r[3])}</td><td>{esc(r[4])}</td></tr>')
    body.append('</tbody></table></div></details>')

for dn in sorted(root["dirs"].keys()):
    body.append(render_node(dn, root["dirs"][dn], 0, ""))

body_html = "\n".join(body)
top_dirs = len(root["dirs"])

HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FILMN9 GitHub 전체 파일 트리맵</title>
<style>
 *{box-sizing:border-box;margin:0;padding:0}
 body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;background:#0f172a;color:#e2e8f0;padding:22px;line-height:1.45}
 h1{font-size:1.4rem;color:#fff;margin-bottom:4px}
 .sub{color:#94a3b8;font-size:.84rem;margin-bottom:16px}
 .bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px}
 .stat{background:#1e293b;border:1px solid #334155;border-radius:9px;padding:9px 16px;text-align:center}
 .stat b{display:block;font-size:1.4rem;color:#60a5fa}
 .stat span{font-size:.72rem;color:#94a3b8}
 #q{flex:1;min-width:220px;background:#1e293b;border:1px solid #334155;color:#e2e8f0;
    padding:10px 14px;border-radius:9px;font-size:.9rem}
 .ctrls{display:flex;gap:8px}
 .btn{background:#2563eb;color:#fff;border:none;padding:9px 14px;border-radius:8px;font-size:.8rem;cursor:pointer;font-weight:600}
 .btn.gray{background:#475569}
 .legend{display:flex;gap:12px;flex-wrap:wrap;font-size:.72rem;color:#94a3b8;margin-bottom:14px}
 .legend span{display:inline-flex;align-items:center;gap:5px}
 .dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none}
 .dot.py{background:#3b82f6}.dot.ts{background:#22d3ee}.dot.doc{background:#a78bfa}
 .dot.data{background:#f59e0b}.dot.html{background:#ec4899}.dot.bat{background:#10b981}
 .dot.bin{background:#64748b}.dot.etc{background:#94a3b8}
 details.folder{margin:3px 0}
 summary.dirsum{cursor:pointer;padding:7px 10px;border-radius:7px;background:#1e293b;
   border:1px solid #2d3b52;font-weight:700;color:#e2e8f0;margin-left:calc(var(--d,0)*18px);
   list-style:none;display:flex;align-items:center;gap:7px;font-size:.9rem}
 summary.dirsum::-webkit-details-marker{display:none}
 summary.dirsum:hover{background:#243049}
 .dname{color:#fbbf24}
 .cnt{margin-left:auto;font-size:.7rem;color:#94a3b8;font-weight:600;background:#0f172a;
   padding:2px 8px;border-radius:20px}
 .folder-body{margin-left:calc((var(--d,0))*0px)}
 table.ftab{width:100%;border-collapse:collapse;margin:6px 0 10px;background:#111c33;
   border:1px solid #1e293b;border-radius:8px;overflow:hidden;font-size:.78rem}
 .ftab thead tr{background:#1d2b45}
 .ftab th{text-align:left;padding:7px 10px;color:#cbd5e1;font-weight:600;white-space:nowrap}
 .ftab td{padding:6px 10px;border-top:1px solid #1e293b;vertical-align:top;color:#cbd5e1}
 .ftab tr:hover td{background:#16233d}
 td.cfile{white-space:nowrap;font-family:Consolas,monospace;color:#e2e8f0;font-size:.76rem}
 td.core{color:#fff;font-weight:600;min-width:200px}
 .ftab th:nth-child(2),.ftab td:nth-child(2){min-width:210px}
 mark{background:#fde047;color:#000;padding:0 1px}
 .hidden{display:none}
 footer{margin-top:20px;color:#64748b;font-size:.72rem}
</style></head><body>
<h1>📂 FILMN9 — GitHub 전체 파일 트리맵</h1>
<div class="sub">github.com/blackhole-24/FILMN9 · 각 파일의 핵심내용·목적·역할·효과 / 폴더 구조 그대로 · 생성 2026-06-02</div>
<div class="bar">
 <div class="stat"><b>__TOTAL__</b><span>분석 파일</span></div>
 <div class="stat"><b>__DIRS__</b><span>최상위 폴더</span></div>
 <div class="stat"><b>~2,529</b><span>briefs_final(요약)</span></div>
 <input id="q" placeholder="🔍 파일명·내용 검색 (예: dcf, sankey, retriever)">
 <div class="ctrls"><button class="btn" onclick="setAll(true)">전체 펼치기</button>
 <button class="btn gray" onclick="setAll(false)">전체 접기</button></div>
</div>
<div class="legend">
 <span><i class="dot py"></i>.py</span><span><i class="dot ts"></i>.tsx/.ts</span>
 <span><i class="dot doc"></i>.md/.txt</span><span><i class="dot data"></i>.json/.csv</span>
 <span><i class="dot html"></i>.html</span><span><i class="dot bat"></i>.bat/.ps1</span>
 <span><i class="dot bin"></i>바이너리/에셋</span>
</div>
__BODY__
<footer>FILMN9 GitHub repo 전체 파일 인덱스 · 핵심내용/목적/역할/효과 4열 · briefs_final 2,529개는 동일 스키마라 1행 요약</footer>
<script>
function setAll(o){document.querySelectorAll('details.folder').forEach(d=>d.open=o);}
const q=document.getElementById('q');
q.addEventListener('input',()=>{
  const t=q.value.trim().toLowerCase();
  const rows=document.querySelectorAll('tr[data-fn]');
  if(!t){rows.forEach(r=>{r.classList.remove('hidden');r.querySelectorAll('td').forEach(td=>{td.innerHTML=td.innerHTML.replace(/<\\/?mark>/g,'');});});
    document.querySelectorAll('details.folder').forEach(d=>d.open=true);return;}
  rows.forEach(r=>{
    const txt=r.textContent.toLowerCase();
    if(txt.includes(t)){r.classList.remove('hidden');}else{r.classList.add('hidden');}
  });
  // 매칭 행 있는 폴더만 열기
  document.querySelectorAll('details.folder').forEach(d=>{
    const vis=d.querySelectorAll('tr[data-fn]:not(.hidden)').length;
    d.open=vis>0;
  });
});
</script>
</body></html>"""

HTML = (HTML.replace("__TOTAL__", str(total_files))
            .replace("__DIRS__", str(top_dirs))
            .replace("__BODY__", body_html))

with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"[OK] 생성: {OUT}")
print(f"   분석 파일 행수: {total_files}, 최상위 폴더: {top_dirs}")
