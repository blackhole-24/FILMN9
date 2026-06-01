"""FastAPI 백엔드 — 기업가치 평가 + 현재가 적절성 진단 대시보드.

엔드포인트:
  GET  /                       → HTML 대시보드 (static/index.html)
  GET  /api/evaluate?ticker=   → 평가 실행(캐시 우선, force=1 시 재평가) → 통합 JSON
  GET  /api/result/{ticker}    → 저장된 최신 결과 JSON
  GET  /api/recent             → 최근 평가 종목 목록

실행:
  PYTHONIOENCODING=utf-8 python -m uvicorn valuation_engine.api:app --port 8000
  (또는 python -m valuation_engine.api)

주의: run_for_ticker 는 config.TARGET/PEERS 를 전역 swap 하므로 동시 요청에 안전하지
      않다. 데모(단일 사용자)용 — 동시성 필요 시 워커 1 + 큐로 직렬화 권장.
"""
from __future__ import annotations

import glob
import json
import math
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

_DIR = Path(__file__).resolve().parent
_VAR_ROOT = _DIR.parent
sys.path.insert(0, str(_VAR_ROOT))

RESULTS_DIR = _DIR / "results"
STATIC_DIR = _DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="기업가치 평가 — 현재가 적절성 진단")

# ── 비동기 평가 작업 인프라 ────────────────────────────────────────
# run_for_ticker 는 config.TARGET/PEERS 를 전역 swap 하므로 동시 실행 불가.
# → max_workers=1 단일 워커로 직렬화(큐). 첫 평가(수 분)가 uvicorn 워커를
#   블로킹하지 않도록 백그라운드 스레드에서 실행하고, 프론트는 폴링한다.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eval")
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_JOB_TTL = 2 * 3600          # 완료/실패 작업 보관 2시간
# 첫 평가 예상 소요(초) — 진행률 바 추정용(실측 평균 ~11분). 정확치 아님.
_EXPECTED_SEC = 660.0


@app.on_event("startup")
def _warmup() -> None:
    """속도 최적화 #2 — 서버 기동 시 BGE-M3 모델 + DB 를 백그라운드로 예열.

    첫 평가가 BGE-M3(2.3GB) 적재 지연을 떠안지 않도록 미리 로드. 별도 스레드라
    서버 기동을 막지 않는다(예열 중에도 캐시 종목 조회는 즉시 가능)."""
    def _do():
        try:
            from valuation_engine import db
            db.store._ensure_init()
        except Exception:
            pass
        try:
            sys.path.insert(0, str(_VAR_ROOT))
            from embedding.embedder import _load_model
            _load_model()   # 토크나이저+모델 GPU 적재 (FP16)
            print("[warmup] BGE-M3 예열 완료", flush=True)
        except Exception as e:
            print(f"[warmup] 임베딩 예열 스킵: {str(e)[:120]}", flush=True)
        try:
            # 회사명→코드 인덱스 예열 — 첫 '회사명/별칭' 캐시 조회를 즉시 처리
            from valuation_engine.ticker_lookup import lookup
            lookup("삼성전자")
            print("[warmup] ticker_lookup 인덱스 예열 완료", flush=True)
        except Exception as e:
            print(f"[warmup] ticker_lookup 예열 스킵: {str(e)[:120]}", flush=True)
    threading.Thread(target=_do, name="warmup", daemon=True).start()


def _prune_jobs() -> None:
    now = time.time()
    dead = [jid for jid, j in _jobs.items()
            if j.get("finished_at") and (now - j["finished_at"]) > _JOB_TTL]
    for jid in dead:
        _jobs.pop(jid, None)


def _run_job(job_id: str, ticker: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["started_at"] = time.time()
    try:
        from valuation_engine.run_valuation_auto import run_for_ticker
        out = run_for_ticker(ticker, verbose=False)
        if not isinstance(out, dict):
            raise RuntimeError("평가 결과 형식 오류")
        out["_cache"] = False
        with _jobs_lock:
            j = _jobs.get(job_id)
            if j is not None:
                j.update(status="done", result=_sanitize(out), finished_at=time.time())
    except (ValueError, RuntimeError) as e:
        with _jobs_lock:
            j = _jobs.get(job_id)
            if j is not None:
                j.update(status="error", error=f"평가 불가: {str(e)[:300]}",
                         finished_at=time.time())
    except Exception as e:
        with _jobs_lock:
            j = _jobs.get(job_id)
            if j is not None:
                j.update(status="error", error=f"평가 실패: {str(e)[:300]}",
                         finished_at=time.time())


def _sanitize(obj: Any) -> Any:
    """NaN/Inf → None (표준 JSON 직렬화 안전)."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _resolve_ticker(user_input: str) -> str | None:
    """입력(회사명/별칭/부분명/사명변경)을 정규 종목코드로 정규화.

    6자리 숫자면 그대로(zfill). 그 외엔 ticker_lookup 으로 해석(matched 일 때만).
    모호/미발견 시 None (호출자는 원입력으로 진행 → run_for_ticker 가 적절히 처리).
    """
    s = str(user_input).strip()
    if s.isdigit():
        return s.zfill(6)
    try:
        from valuation_engine.ticker_lookup import lookup
        r = lookup(s)
        # ticker_lookup 성공 status 는 'exact'/'fuzzy' 등 — not_found/ambiguous 만 제외
        # (run_valuation_auto 와 동일 정책: 모호하면 추측하지 않고 캐시 미스로 둠)
        if r.get("status") not in ("not_found", "ambiguous") and r.get("match"):
            return r["match"].get("ticker")
    except Exception:
        pass
    return None


def _latest_result(ticker: str) -> dict | None:
    # DB 우선 — 입력을 먼저 정규 종목코드로 변환(naver→035420, SK하이닉스→000660) 후
    #   stock_code 로 조회해 항상 최신 평가 적중. 사명 표기 차이(SK하이닉스 vs
    #   에스케이하이닉스)로 corp_name 폴백이 옛 레코드를 잡아 stale 재평가되던 문제 방지.
    code = _resolve_ticker(ticker)
    try:
        from valuation_engine import db
        if code:
            r = db.get_latest_result(code)         # 정규 코드(stock_code) 우선
            if r is not None:
                return r
        # 코드 정규화 실패/미스 → 원본으로 (코드·사명 직접 일치 + corp_name 폴백)
        r = db.get_latest_result(ticker)
        if r is not None:
            return r
    except Exception:
        pass
    # 파일 폴백 — 정규 코드 우선, 없으면 원본
    for key in (code, str(ticker).strip()):
        if not key:
            continue
        files = sorted(glob.glob(str(RESULTS_DIR / f"valuation_{key}_*.json")))
        if files:
            with open(files[-1], encoding="utf-8") as f:
                return json.load(f)
    return None


def _cache_is_fresh(result: dict) -> bool:
    """캐시 결과가 '최신 영업일' 기준인지 — 매일 최신 자동보장.

    as_of_date >= 최신 영업일(주말이면 직전 금요일)이면 fresh(캐시 즉시 반환).
    오래되면 stale → 호출자(evaluate)가 자동 재평가(당일 주가·최신 분기 BS·TTM 반영).
    판정 실패 시 보수적으로 stale(재평가).
    """
    # C.2: 모델 버전 불일치 → 무조건 stale (코드·산식 개선이 즉시 재평가로 반영).
    #   구버전 캐시(model_version 없음/상이)는 자동 재평가 큐로 보낸다.
    try:
        from valuation_engine.config import MODEL_VERSION
        if (result or {}).get("model_version") != MODEL_VERSION:
            return False
    except Exception:
        pass
    try:
        from datetime import date as _date
        from peer_beta.calendar_utils import previous_business_day_candidates, parse_date
        aod = (result or {}).get("as_of_date")
        if not aod:
            return False
        cands = previous_business_day_candidates(_date.today())
        latest_bday = cands[0] if cands else _date.today()
        return parse_date(aod) >= latest_bday
    except Exception:
        return False


@app.get("/")
def index():
    idx = STATIC_DIR / "index.html"
    if not idx.exists():
        return JSONResponse({"error": "index.html 없음 — static/index.html 생성 필요"}, 404)
    return FileResponse(idx)


@app.get("/api/result/{ticker}")
def get_result(ticker: str):
    data = _latest_result(ticker)
    if data is None:
        raise HTTPException(404, f"{ticker} 결과 없음 — 먼저 평가 필요")
    return JSONResponse(_sanitize(data))


_TICKER_RE = __import__("re").compile(r"^[\dA-Za-z가-힣()·\s\-\.]{1,30}$")


def _validate_ticker(s: str) -> str:
    """ticker 입력 sanitize — 6자리 숫자 또는 한글/영문 회사명(1~30자).

    Raises HTTPException 400 if invalid.
    """
    s = (s or "").strip()
    if not s:
        raise HTTPException(400, "ticker 비어 있음")
    if not _TICKER_RE.match(s):
        raise HTTPException(400, "ticker 형식 오류 — 6자리 숫자 또는 회사명(특수문자 제한)")
    return s


@app.get("/api/evaluate")
def evaluate(ticker: str, force: int = 0):
    """평가 실행(비동기) — 캐시 우선(force=0), force=1 시 최신 코드로 재평가.

    반환:
      캐시 적중      → {"status":"done", "result": <통합 JSON>}
      신규/재평가    → {"status":"queued"|"running", "job_id": ...} → /api/status 폴링
    """
    ticker = _validate_ticker(ticker)
    if not force:
        cached = _latest_result(ticker)
        # 매일 최신 자동보장 — 캐시가 '최신 영업일' 기준일 때만 즉시 반환.
        # 오래된 캐시(어제 등)는 stale 처리 → 아래 재평가 큐로 (당일 데이터 반영).
        if cached is not None and _cache_is_fresh(cached):
            cached["_cache"] = True
            return JSONResponse({"status": "done", "result": _sanitize(cached)})

    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _prune_jobs()
        # 대기열: 이 작업보다 앞서 처리 중/대기 중인 건수
        ahead = sum(1 for j in _jobs.values() if j.get("status") in ("queued", "running"))
        _jobs[job_id] = {"status": "queued", "ticker": ticker,
                         "created_at": time.time()}
    _executor.submit(_run_job, job_id, ticker)
    return JSONResponse({"status": "queued", "job_id": job_id,
                         "ticker": ticker, "queue_ahead": ahead})


@app.get("/api/status/{job_id}")
def job_status(job_id: str):
    """비동기 평가 작업 폴링 — running 시 경과/예상진행률, done 시 result 포함."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "작업을 찾을 수 없음(만료되었거나 잘못된 ID)")
        job = dict(job)   # 락 밖에서 안전하게 사용할 사본
    resp: dict[str, Any] = {"status": job["status"], "ticker": job.get("ticker")}
    if job["status"] in ("queued", "running"):
        started = job.get("started_at")
        elapsed = round(time.time() - started, 1) if started else 0.0
        resp["elapsed"] = elapsed
        # 예상 진행률(추정) — 완료 전까지 95% 상한, 정확치 아님
        resp["progress"] = round(min(0.95, elapsed / _EXPECTED_SEC), 3) if started else 0.0
        resp["expected_sec"] = _EXPECTED_SEC
    elif job["status"] == "done":
        resp["result"] = job["result"]
    elif job["status"] == "error":
        resp["error"] = job.get("error", "알 수 없는 오류")
    return JSONResponse(resp)


@app.get("/api/recent")
def recent():
    # DB 우선
    try:
        from valuation_engine import db
        rows = db.list_recent_runs(30)
        if rows:
            return [{"ticker": r["stock_code"], "name": r.get("corp_name") or r["stock_code"],
                     "as_of": r.get("eval_date")} for r in rows]
    except Exception:
        pass
    # 파일 폴백
    out = []
    seen = set()
    for f in sorted(glob.glob(str(RESULTS_DIR / "valuation_*_*.json")), reverse=True):
        name = Path(f).stem  # valuation_<ticker>_<date>
        parts = name.split("_")
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        tk = parts[1]
        if tk in seen:
            continue
        seen.add(tk)
        try:
            with open(f, encoding="utf-8") as fp:
                d = json.load(fp)
            out.append({"ticker": tk, "name": d.get("company", {}).get("name", tk),
                        "as_of": d.get("as_of_date")})
        except Exception:
            continue
    return out[:30]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("valuation_engine.api:app", host="0.0.0.0", port=8000, reload=False)
