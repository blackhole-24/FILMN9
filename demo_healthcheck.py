# -*- coding: utf-8 -*-
"""
demo_healthcheck.py
===================
데모 3종목(090430·009150·035420)에 대해 16개 API 응답 자동 검증

사용:
  python demo_healthcheck.py                    # 기본 (localhost:8000)
  python demo_healthcheck.py --base https://...  # AWS 환경
  python demo_healthcheck.py --strict            # 엄격 모드 (필수 필드 누락 시 FAIL)

리포트 저장:
  handover/headcheck_YYYYMMDD_HHMM.md
"""
from __future__ import annotations
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DEMO_CODES = ["090430", "009150", "035420"]
DEMO_NAMES = {"090430": "아모레퍼시픽", "009150": "삼성전기", "035420": "NAVER"}

ENDPOINTS = [
    ("overview",         "/api/overview/{code}",                    ["company", "price"]),
    ("financial_BS",     "/api/financial_detail/{code}/BS?scope=연결", ["years", "items"]),
    ("financial_IS",     "/api/financial_detail/{code}/IS?scope=연결", ["years", "items"]),
    ("ohlcv",            "/api/ohlcv/{code}",                       ["data"]),
    ("shareholders",     "/api/shareholders/{code}",                ["items"]),
    ("executives",       "/api/executives/{code}",                  ["items"]),
    ("disclosures",      "/api/disclosures/{code}?limit=5",         ["items"]),
    ("supply_contracts", "/api/supply_contracts/{code}?years=5",    ["items"]),
    ("dart_disclosures", "/api/dart_disclosures/{code}?period=1m",  ["items", "total_count"]),
    ("health",           "/api/health/{code}",                      ["metrics"]),
    ("valuation",        "/api/valuation/{code}",                   None),   # MOCK 가능
    ("news",             "/api/news/{code}?limit=3",                ["items"]),
    ("realtime",         "/api/realtime/{code}",                    ["close"]),
    ("sankey",           "/sankey/{code}",                          None),    # HTML 응답
]


def http_get(url: str, timeout: int = 10):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            status = r.status
            ctype = r.headers.get("Content-Type", "")
            body = r.read()
        return {
            "status": status, "ctype": ctype, "body": body,
            "ms": int((time.time() - t0) * 1000),
            "error": None,
        }
    except urllib.error.HTTPError as e:
        return {"status": e.code, "ctype": "", "body": b"",
                "ms": int((time.time() - t0) * 1000), "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"status": 0, "ctype": "", "body": b"",
                "ms": int((time.time() - t0) * 1000), "error": str(e)[:120]}


def check_endpoint(base: str, code: str, name: str, path: str, required: list | None, strict: bool):
    raw_path = path.format(code=code)
    # 한글 등 비ASCII 문자 URL 인코딩 (쿼리·경로 둘 다)
    if "?" in raw_path:
        p, q = raw_path.split("?", 1)
        # 쿼리 값만 인코딩
        parts = []
        for kv in q.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                parts.append(f"{k}={urllib.parse.quote(v, safe='')}")
            else:
                parts.append(kv)
        url = base.rstrip("/") + p + "?" + "&".join(parts)
    else:
        url = base.rstrip("/") + raw_path
    r = http_get(url)
    res = {
        "name": name, "url": url, "status": r["status"],
        "ms": r["ms"], "ok": False, "note": "",
    }
    if r["error"]:
        res["note"] = r["error"]
        return res
    if r["status"] != 200:
        res["note"] = f"status={r['status']}"
        return res
    # 응답 타입별 검증
    if "json" in r["ctype"]:
        try:
            data = json.loads(r["body"].decode("utf-8"))
        except Exception as e:
            res["note"] = f"JSON parse failed: {e}"
            return res
        if required:
            missing = [k for k in required if k not in data]
            if missing and strict:
                res["note"] = f"필드 누락: {missing}"
                return res
            if missing:
                res["note"] = f"필드 누락(경고): {missing}"
        # items 길이 표시
        if isinstance(data, dict) and "items" in data:
            res["note"] = f"items={len(data['items'])}"
        elif isinstance(data, dict) and "data" in data:
            res["note"] = f"data={len(data['data'])}"
    elif "html" in r["ctype"]:
        # Sankey HTML이면 크기로 sanity 체크
        size_kb = len(r["body"]) // 1024
        if size_kb < 5:
            res["note"] = f"HTML 너무 작음 ({size_kb}KB)"
            return res
        res["note"] = f"HTML {size_kb}KB"
    res["ok"] = True
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    ts = datetime.now()
    out_lines = []
    out_lines.append(f"# 데모 3종목 헬스체크 리포트")
    out_lines.append(f"")
    out_lines.append(f"- 실행: {ts.strftime('%Y-%m-%d %H:%M:%S')}")
    out_lines.append(f"- BASE: `{args.base}`")
    out_lines.append(f"- 엄격모드: {args.strict}")
    out_lines.append(f"")

    overall_pass = 0
    overall_fail = 0
    for code in DEMO_CODES:
        name = DEMO_NAMES[code]
        out_lines.append(f"## {code} {name}")
        out_lines.append(f"")
        out_lines.append(f"| API | 상태 | 응답시간 | 비고 |")
        out_lines.append(f"|---|:-:|:-:|---|")
        for ep_name, path, required in ENDPOINTS:
            r = check_endpoint(args.base, code, ep_name, path, required, args.strict)
            mark = "✅" if r["ok"] else "❌"
            out_lines.append(f"| `{r['name']}` | {mark} {r['status']} | {r['ms']}ms | {r['note']} |")
            if r["ok"]:
                overall_pass += 1
            else:
                overall_fail += 1
        out_lines.append(f"")

    out_lines.append(f"## 종합")
    total = overall_pass + overall_fail
    pct = (overall_pass / total * 100) if total else 0
    out_lines.append(f"")
    out_lines.append(f"- 통과: **{overall_pass} / {total}** ({pct:.1f}%)")
    out_lines.append(f"- 실패: {overall_fail}")

    # 저장
    out_dir = Path(r"C:\Users\Admin\FILMN9\handover")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"healthcheck_{ts.strftime('%Y%m%d_%H%M')}.md"
    out_path.write_text("\n".join(out_lines), encoding="utf-8")

    print(f"[OK] {out_path}")
    print(f"통과 {overall_pass}/{total} ({pct:.1f}%)")
    return overall_fail


if __name__ == "__main__":
    raise SystemExit(main())
