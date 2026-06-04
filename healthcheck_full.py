# -*- coding: utf-8 -*-
"""
healthcheck_full.py
===================
전수(3,000종목) 데모 검수 — "아무 종목이나 검색해도 화면이 깨지지 않는지" 자동 검증.

demo_healthcheck.py(데모 3종목)의 확장판.
각 종목 × 핵심 API 를 호출해 결과를 3단계로 분류:
  OK    : 200 + 데이터 있음
  EMPTY : 200 인데 비어있음 / 404(예: Sankey 미생성) — 데이터 커버리지 갭(크래시 아님)
  FAIL  : 5xx · 타임아웃 · 연결오류 · JSON 파싱오류 — ★진짜 버그(데모 전 반드시 수정)

사용:
  # 핵심(DB) 엔드포인트 전수 (빠름, OpenAI/외부호출 없음)
  python healthcheck_full.py
  # 랜덤 300종목 + 외부 API(realtime/news 등)까지
  python healthcheck_full.py --sample 300 --slow
  # 특정 종목만
  python healthcheck_full.py --codes 005930,009150,035420 --slow
  # 회사 전체(company_info 3,965) 기준
  python healthcheck_full.py --universe company

옵션:
  --base   기본 http://localhost:8090
  --sample N      랜덤 N종목 (기본: 전체)
  --workers W     동시 실행 (기본 12)
  --slow          외부 API(realtime·news·dart_disclosures)도 검사
  --universe      ticker(기본·2,586 활성) | company(3,965)
리포트: auto_reports/healthcheck_full_YYYYMMDD_HHMM.md  +  실패목록 CSV
"""
from __future__ import annotations
import argparse, csv, json, random, sqlite3, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB   = ROOT / "data" / "filmn9.db"

# (이름, 경로, kind, group, 404처리)  group: core(DB·빠름) / slow(외부·느림)
ENDPOINTS = [
    ("overview",        "/api/overview/{code}",                       "json", "core", "fail"),
    ("financial_BS",    "/api/financial_detail/{code}/BS?scope=연결", "json", "core", "empty"),
    ("financial_IS",    "/api/financial_detail/{code}/IS?scope=연결", "json", "core", "empty"),
    ("ohlcv",           "/api/ohlcv/{code}",                          "json", "core", "empty"),
    ("shareholders",    "/api/shareholders/{code}",                   "json", "core", "empty"),
    ("executives",      "/api/executives/{code}",                     "json", "core", "empty"),
    ("disclosures",     "/api/disclosures/{code}?limit=5",            "json", "core", "empty"),
    ("health",          "/api/health/{code}",                         "json", "core", "empty"),
    ("peers",           "/api/peers/{code}",                          "json", "core", "empty"),
    ("valuation",       "/api/valuation/{code}",                      "json", "core", "empty"),
    ("sankey",          "/sankey/{code}",                             "html", "core", "empty"),
    ("realtime",        "/api/realtime/{code}",                       "json", "slow", "empty"),
    ("news",            "/api/news/{code}?limit=3",                   "json", "slow", "empty"),
    ("dart_disclosures","/api/dart_disclosures/{code}?period=1m",     "json", "slow", "empty"),
]


def load_codes(universe: str) -> list[tuple[str, str]]:
    """(code, name) 목록."""
    if universe == "company":
        con = sqlite3.connect(DB)
        rows = con.execute("SELECT stock_code, corp_name FROM company_info ORDER BY stock_code").fetchall()
        con.close()
        return [(r[0], r[1] or "") for r in rows]
    # 기본: ticker_universe 활성(SPAC·우선주 제외)
    out = []
    with open(ROOT / "ticker_universe.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            t = lambda v: str(v).strip().lower() in ("true", "1", "y", "yes")
            if t(r.get("is_spac")) or t(r.get("is_preferred")):
                continue
            out.append(((r.get("stock_code") or "").strip(), (r.get("corp_name") or "").strip()))
    return out


def build_url(base: str, path: str, code: str) -> str:
    raw = path.format(code=code)
    if "?" in raw:
        p, q = raw.split("?", 1)
        parts = []
        for kv in q.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                parts.append(f"{k}={urllib.parse.quote(v, safe='')}")
            else:
                parts.append(kv)
        return base.rstrip("/") + p + "?" + "&".join(parts)
    return base.rstrip("/") + raw


def classify(base, code, ep, timeout=15) -> dict:
    name, path, kind, group, missing = ep
    url = build_url(base, path, code)
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            status, ctype, body = r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        # 404 → 커버리지 갭(empty) 또는 fail
        cat = "EMPTY" if (e.code == 404 and missing == "empty") else "FAIL"
        return {"code": code, "ep": name, "cat": cat, "status": e.code,
                "ms": int((time.time()-t0)*1000), "note": f"HTTP {e.code}"}
    except Exception as e:
        return {"code": code, "ep": name, "cat": "FAIL", "status": 0,
                "ms": int((time.time()-t0)*1000), "note": str(e)[:80]}

    ms = int((time.time()-t0)*1000)
    if kind == "html":
        kb = len(body)//1024
        if kb < 5:
            return {"code": code, "ep": name, "cat": "EMPTY", "status": status, "ms": ms, "note": f"HTML {kb}KB"}
        return {"code": code, "ep": name, "cat": "OK", "status": status, "ms": ms, "note": f"{kb}KB"}

    # JSON
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as e:
        return {"code": code, "ep": name, "cat": "FAIL", "status": status, "ms": ms, "note": f"JSON parse: {e}"[:80]}

    # 비어있음 판정
    note = ""
    empty = False
    if isinstance(data, dict):
        if data.get("is_mock") is True:
            note = "mock"; empty = (name == "valuation")  # 밸류는 mock=데이터없음 취급
        elif "items" in data and isinstance(data["items"], list):
            note = f"items={len(data['items'])}"; empty = len(data["items"]) == 0
        elif "data" in data and isinstance(data["data"], list):
            note = f"data={len(data['data'])}"; empty = len(data["data"]) == 0
        elif len(data) == 0:
            empty = True
        # overview는 핵심 → 비면 FAIL(missing=fail)
    if empty:
        cat = "FAIL" if missing == "fail" else "EMPTY"
        return {"code": code, "ep": name, "cat": cat, "status": status, "ms": ms, "note": note or "empty"}
    return {"code": code, "ep": name, "cat": "OK", "status": status, "ms": ms, "note": note}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8090")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--slow", action="store_true")
    ap.add_argument("--universe", default="ticker", choices=["ticker", "company"])
    ap.add_argument("--codes", default="")
    args = ap.parse_args()

    if args.codes:
        names = {c: c for c in args.codes.split(",")}
        codes = [(c.strip(), c.strip()) for c in args.codes.split(",") if c.strip()]
    else:
        codes = load_codes(args.universe)
        if args.sample and args.sample < len(codes):
            random.seed(42)
            codes = random.sample(codes, args.sample)
    name_map = {c: n for c, n in codes}

    eps = [e for e in ENDPOINTS if args.slow or e[3] == "core"]
    tasks = [(c, e) for c, _ in codes for e in eps]
    print(f"[검수] 종목 {len(codes)} × API {len(eps)} = {len(tasks)} 요청 | base={args.base} | workers={args.workers}")
    if args.slow and len(codes) > 400:
        print("  ⚠ --slow + 다수 종목: 외부 API(yfinance/DART) 레이트리밋·지연 주의. --sample 권장.")

    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(classify, args.base, c, e): (c, e[0]) for c, e in tasks}
        done = 0
        for fu in as_completed(futs):
            results.append(fu.result())
            done += 1
            if done % 500 == 0:
                print(f"  …{done}/{len(tasks)}")
    elapsed = time.time() - t0

    # 집계
    by_ep = {}
    for r in results:
        d = by_ep.setdefault(r["ep"], {"OK": 0, "EMPTY": 0, "FAIL": 0})
        d[r["cat"]] += 1
    fails = [r for r in results if r["cat"] == "FAIL"]

    ts = datetime.now()
    L = []
    L.append("# 전수 검수 리포트 (healthcheck_full)\n")
    L.append(f"- 실행: {ts:%Y-%m-%d %H:%M:%S} | base: `{args.base}` | universe: {args.universe}")
    L.append(f"- 종목 {len(codes)} × API {len(eps)} = {len(results)} 검사 | {elapsed:.0f}s")
    L.append(f"- ★ FAIL(진짜 버그): **{len(fails)}건**\n")
    L.append("## 엔드포인트별 결과\n")
    L.append("| API | ✅OK | ⚪EMPTY(갭) | ❌FAIL(버그) | OK% |")
    L.append("|---|--:|--:|--:|--:|")
    for ep in [e[0] for e in eps]:
        d = by_ep.get(ep, {"OK":0,"EMPTY":0,"FAIL":0})
        tot = d["OK"]+d["EMPTY"]+d["FAIL"]
        pct = d["OK"]/tot*100 if tot else 0
        L.append(f"| `{ep}` | {d['OK']} | {d['EMPTY']} | {d['FAIL']} | {pct:.1f}% |")
    L.append("\n## ❌ FAIL 목록 (수정 대상, 최대 100건)\n")
    if fails:
        L.append("| 종목 | API | status | 비고 |")
        L.append("|---|---|--:|---|")
        for r in fails[:100]:
            L.append(f"| {r['code']} {name_map.get(r['code'],'')} | `{r['ep']}` | {r['status']} | {r['note']} |")
    else:
        L.append("FAIL 0건 — 크래시 없음 ✅")

    out_dir = ROOT / "auto_reports"; out_dir.mkdir(exist_ok=True)
    md = out_dir / f"healthcheck_full_{ts:%Y%m%d_%H%M}.md"
    md.write_text("\n".join(L), encoding="utf-8")
    # 실패 CSV
    if fails:
        csvp = out_dir / f"healthcheck_full_FAILS_{ts:%Y%m%d_%H%M}.csv"
        with open(csvp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["code","name","ep","status","note"])
            for r in fails:
                w.writerow([r["code"], name_map.get(r["code"],""), r["ep"], r["status"], r["note"]])

    print(f"\n[완료] {elapsed:.0f}s | FAIL {len(fails)}건")
    for ep in [e[0] for e in eps]:
        d = by_ep.get(ep, {"OK":0,"EMPTY":0,"FAIL":0})
        print(f"  {ep:18s} OK {d['OK']:4d} | EMPTY {d['EMPTY']:4d} | FAIL {d['FAIL']:4d}")
    print(f"리포트: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
