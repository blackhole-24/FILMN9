"""팀원 공유 패키지 생성 — 프론트(UI) + 3종목 데이터 JSON.

산출물 (git_share/ui_share/):
  · index.html             — 실제 UI (백엔드 API 연동 버전)
  · index_standalone.html  — 백엔드 없이 더블클릭으로 검증 (3종목 샘플 데이터 내장)
  · data/<ticker>_<name>.json — 종목별 서비스 구현용 전체 데이터(ui_payload + 구조화)
  · README.md              — 검증 방법 + API 계약 + 데이터 스키마
그리고 git_share/ui_share.zip 로 압축.

실행:
    python -m valuation_engine.db.export_share
"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from .. import db as api
from . import store

_VAR_ROOT = Path(__file__).resolve().parent.parent.parent
_STATIC = _VAR_ROOT / "valuation_engine" / "static" / "index.html"
_OUT = _VAR_ROOT / "git_share" / "ui_share"
_DATA = _OUT / "data"

TARGETS = [("035420", "NAVER"), ("009150", "삼성전기"), ("090430", "아모레퍼시픽")]


def _latest_detail(table: str, tk: str):
    r = store.query_one(
        f"SELECT detail FROM {table} WHERE stock_code=? ORDER BY eval_date DESC LIMIT 1",
        (tk,))
    if r and r.get("detail"):
        try:
            return json.loads(r["detail"])
        except Exception:
            return r["detail"]
    return None


def build_ticker_json(tk: str, name: str) -> dict:
    """종목별 전체 데이터 번들 — ui_payload(프론트 입력) + structured_data(DB)."""
    ui = api.get_latest_result(tk) or {}
    # 5년 재무 (원본 {meta, financials})
    years = [r["fiscal_year"] for r in store.query(
        "SELECT fiscal_year FROM financials WHERE stock_code=? ORDER BY fiscal_year", (tk,))]
    financials = []
    for y in years:
        fin = api.get_financials(tk, y)
        if fin:
            financials.append({"fiscal_year": y, **fin})
    credit = api.get_credit_rating(tk, max(years) if years else 2025)
    beta = _latest_detail("beta_results", tk)
    return {
        "stock_code": tk,
        "corp_name": name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "note": "ui_payload = 프론트(/api/evaluate 의 result)가 그대로 소비하는 데이터. "
                "structured_data = DB(SQLite) 정형 데이터(팀원 컬럼명 기준).",
        # 프론트가 그대로 받는 통합 결과 (UI 표시에 필요한 전부)
        "ui_payload": ui,
        # 서비스/DB 구현용 구조화 데이터
        "structured_data": {
            "company":       api.get_company(tk),
            "financials":    financials,            # 5년 {meta, financials}
            "credit_rating": credit,
            "wacc":          _latest_detail("wacc_results", tk),
            "dcf":           _latest_detail("dcf_results", tk),
            "equity":        _latest_detail("equity_results", tk),
            "diagnostics":   _latest_detail("diagnostics_results", tk),
            "beta":          beta,
        },
    }


def _sanitize(o):
    import math
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_sanitize(v) for v in o]
    return o


def build_standalone(samples: dict) -> str:
    """index.html + 3종목 샘플 내장 → 백엔드 없이 열리는 standalone HTML."""
    base = _STATIC.read_text(encoding="utf-8")
    sample_js = json.dumps(samples, ensure_ascii=False)
    override = (
        "\n<script>\n"
        "/* ── 백엔드 없이 검증용: 3종목 샘플 내장 + go/loadRecent 오버라이드 ── */\n"
        f"const SAMPLE = {sample_js};\n"
        "loadRecent = async function(){\n"
        "  document.getElementById('recent').innerHTML = '샘플 종목: ' +\n"
        "    Object.values(SAMPLE).map(d=>`<a onclick=\"quick('${d.company.ticker}')\">${d.company.name}</a>`).join('');\n"
        "};\n"
        "go = async function(){\n"
        "  const t=document.getElementById('ticker').value.trim(); if(!t)return;\n"
        "  if(pollTimer){clearInterval(pollTimer);pollTimer=null;}\n"
        "  document.getElementById('hint').style.display='none';\n"
        "  let d = SAMPLE[t] || Object.values(SAMPLE).find(x=>x.company&&(x.company.ticker===t||(x.company.name||'').includes(t)));\n"
        "  finishLoad();\n"
        "  if(!d){ showErr('이 standalone 데모에는 035420(NAVER)·009150(삼성전기)·090430(아모레퍼시픽)만 들어 있어요.'); return; }\n"
        "  render(d);\n"
        "};\n"
        "/* Chart.js(CDN)가 오프라인이면 가격대 차트만 안내문으로 대체, 나머지는 정상 렌더 */\n"
        "const _origDrawRange = drawRange;\n"
        "drawRange = function(d){ try{ if(typeof Chart!=='undefined'){ _origDrawRange(d); } else {\n"
        "  const c=document.getElementById('cRange'); if(c){ c.outerHTML='<div class=\"footnote\">📊 막대 차트는 인터넷 연결(Chart.js CDN) 시 표시됩니다. 숫자·게이지·표는 그대로 보입니다.</div>'; } } }catch(e){} };\n"
        "loadRecent();\n"
        "</script>\n"
    )
    banner = ('<div style="background:#fef3c7;color:#92400e;text-align:center;'
              'padding:7px;font-size:12px;">🔌 백엔드 없이 동작하는 데모입니다 — '
              '내장된 3종목(NAVER·삼성전기·아모레퍼시픽)만 조회됩니다.</div>')
    base = base.replace("<body>", "<body>\n" + banner, 1)
    return base.replace("</body>", override + "</body>", 1)


README = """# 기업가치 평가 — 프론트엔드 검증 패키지

일반투자자용 가치평가 대시보드의 프론트엔드와, 3종목(NAVER·삼성전기·아모레퍼시픽)
데이터를 담았습니다.

## 파일
| 파일 | 설명 |
|---|---|
| `index_standalone.html` | **더블클릭으로 바로 열어 검증** (백엔드 불필요, 3종목 샘플 내장) |
| `index.html` | 실제 운영 UI (백엔드 API `/api/evaluate` 연동) |
| `data/<코드>_<이름>.json` | 종목별 **서비스 구현용 전체 데이터** (ui_payload + 구조화) |

## 검증 방법
### 1) 가장 빠름 — standalone
`index_standalone.html` 더블클릭 → 검색창에 `NAVER` / `삼성전기` / `아모레퍼시픽`
(또는 `035420`/`009150`/`090430`) 입력 → 전체 UI 확인.
(가격대 막대 차트만 Chart.js CDN 때문에 인터넷 필요. 나머지는 오프라인 OK)

### 2) 백엔드 연동 — index.html
저장소 루트에서:
```
PYTHONIOENCODING=utf-8 python -m uvicorn valuation_engine.api:app --port 8011
```
브라우저에서 http://localhost:8011

## API 계약 (운영 UI)
- `GET /api/evaluate?ticker=<코드|이름>&force=0`
  - 캐시 있음 → `{ "status":"done", "result": <ui_payload> }`
  - 신규/재평가 → `{ "status":"queued", "job_id":"...", "queue_ahead":N }`
- `GET /api/status/{job_id}` (폴링)
  - 진행 → `{ "status":"running", "elapsed":초, "progress":0~0.95 }`
  - 완료 → `{ "status":"done", "result": <ui_payload> }`
  - 실패 → `{ "status":"error", "error":"메시지" }`
- `GET /api/recent` → `[{ "ticker","name","as_of" }, ...]`

## ui_payload 핵심 스키마 (프론트가 소비)
```jsonc
{
  "company": { "name", "ticker", "market" },
  "as_of_date": "YYYY-MM-DD",
  "summary": { "current_price", "fair_price", "upside_pct", "wacc", "ke", "rf",
               "equity_value_won" },
  "valuation_diagnostics": {            // 현재가 적절성 진단 5종
    "valid", "headline", "epv_price", "growth_premium", "implied_growth",
    "implied_growth_verdict", "expectations_gap", "margin_of_safety",
    "gdp_growth_ref"
  },
  "scenarios": { "Bear":{"price"}, "Base":{"price"}, "Bull":{"price"} },
  "multiples": [ { "멀티플","피어 중위","역산가" }, ... ],
  "wacc_breakdown": [ ["항목","값","근거"], ... ],
  "peer_beta": [ { "회사","β_adj","R²","warn" }, ... ]
}
```
※ 데이터 식별자는 팀원 표준(`stock_code`, `corp_name`)에 맞춰 DB(SQLite)에 저장됩니다.
   `data/*.json` 의 `structured_data` 가 그 형식입니다.
"""


def run():
    if _OUT.exists():
        shutil.rmtree(_OUT)
    _DATA.mkdir(parents=True, exist_ok=True)

    samples = {}
    for tk, name in TARGETS:
        bundle = _sanitize(build_ticker_json(tk, name))
        (_DATA / f"{tk}_{name}.json").write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        samples[tk] = bundle["ui_payload"]
        print(f"  데이터 JSON: {tk}_{name}.json")

    # index.html (운영)
    shutil.copy(_STATIC, _OUT / "index.html")
    # standalone
    (_OUT / "index_standalone.html").write_text(
        build_standalone(samples), encoding="utf-8")
    (_OUT / "README.md").write_text(README, encoding="utf-8")
    print(f"  index.html / index_standalone.html / README.md 작성")

    # zip
    zip_path = _VAR_ROOT / "git_share" / "ui_share.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(_OUT.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(_OUT.parent))
    size_kb = zip_path.stat().st_size / 1024
    print(f"\n압축 완료: {zip_path}  ({size_kb:.0f} KB)")
    print(f"폴더:     {_OUT}")
    return zip_path


if __name__ == "__main__":
    run()
