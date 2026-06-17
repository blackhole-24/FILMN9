"""DART API 로 기존 shares 캐시를 권위 데이터로 재조회·교정(backfill).

RAG/LLM 추출로 단위·자릿수 오류가 섞인 기존 data/rag_cache/shares_*.json 을 DART
stockTotqySttus(주식의 총수 현황) 값으로 일괄 교정한다. (현대로템 109,142천주→109,142,
두산 16,193,835→167,000,000 등.)

특징
  · 재실행 가능(resumable): source 가 'DART API' 인 캐시는 건너뜀 → 레이트리밋으로
    중단돼도 다시 실행하면 이어서 처리한다. (--force 로 전체 재조회)
  · 안전(gentle): 순차 + 짧은 지연. DART 가 연결을 끊는 throttle 시 연속 실패가
    임계치를 넘으면 중단하고(쿼터/throttle 회복 후 재실행) 처리분은 보존한다.
  · 교정분(>1% 변동) 리포트 + (옵션) 해당 종목 valuation 결과 무효화 → 다음 접근 시
    올바른 주식수로 재평가.

사용
  python -m valuation_engine.backfill_shares_api            # 적용(+변동종목 결과 무효화)
  python -m valuation_engine.backfill_shares_api --dry      # 비교만(쓰기 없음)
  python -m valuation_engine.backfill_shares_api --force    # API 소스 캐시도 재조회
  python -m valuation_engine.backfill_shares_api --keep-results   # 결과 무효화 안 함
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from valuation_engine import compute_equity as ce
from valuation_engine import db

_CACHE_DIR = _VAR_ROOT / "data" / "rag_cache"
_CACHE_RE = re.compile(r"shares_(\d{6})_(\d{4})\.json$")

# throttle 판정 — 연속 실패가 이 수를 넘으면 DART throttle 로 보고 중단(처리분 보존).
_MAX_CONSECUTIVE_FAIL = 25
# 호출 간 지연(초) — DART 남용방지(연결 끊김) 회피. 순차 + 0.3s ≈ 3 req/s (버스트 회피).
_INTER_CALL_DELAY = 0.3


def _invalidate_results(ticker: str) -> int:
    """변동 종목의 캐시된 valuation 결과 무효화 → 다음 접근 시 올바른 주식수로 재평가.

    mongo_docs(valuation_results) + valuation_runs + equity_results 에서 해당 종목 제거.
    온디스크 결과/equity 파일도 정리. 반환: 삭제한 DB 행 수.
    """
    tk = str(ticker).zfill(6)
    n = 0
    try:
        conn = db.store.connect()
        try:
            n += conn.execute("DELETE FROM mongo_docs WHERE collection='valuation_results' "
                              "AND doc_id LIKE ?", (f"{tk}_%",)).rowcount
            n += conn.execute("DELETE FROM valuation_runs WHERE stock_code=?", (tk,)).rowcount
            n += conn.execute("DELETE FROM equity_results WHERE stock_code=?", (tk,)).rowcount
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    # 온디스크 파일
    for pat in (_VAR_ROOT / "valuation_engine" / "results",
                _VAR_ROOT / "valuation_engine" / "data" / "equity"):
        try:
            for p in pat.glob(f"*_{tk}_*.json"):
                p.unlink()
            for p in pat.glob(f"valuation_{tk}_*.json"):
                p.unlink()
            for p in pat.glob(f"peers_equity_{tk}_*.json"):
                p.unlink()
        except Exception:
            pass
    return n


def backfill(*, apply: bool = True, force: bool = False,
             invalidate_results: bool = True, limit: int | None = None) -> dict:
    files = sorted(p for p in _CACHE_DIR.glob("shares_*_*.json")
                   if _CACHE_RE.search(p.name))
    if limit:
        files = files[:limit]

    stats = {"total": len(files), "skipped_api": 0, "same": 0, "changed": 0,
             "nocc": 0, "apifail": 0, "aborted": False}
    changes = []
    consecutive_fail = 0

    print(f"[백필] 대상 {len(files)}개  apply={apply} force={force} "
          f"invalidate_results={invalidate_results}")

    for i, p in enumerate(files, 1):
        m = _CACHE_RE.search(p.name)
        ticker, year = m.group(1), int(m.group(2))
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            old = {}
        old_issued = int(old.get("common_issued") or 0)
        # 이미 API 소스면 skip (resumable). --force 시 무시.
        if not force and str(old.get("source", "")).startswith("DART API"):
            stats["skipped_api"] += 1
            consecutive_fail = 0
            continue

        corp_code = ce._resolve_corp_code(ticker)
        if not corp_code:
            stats["nocc"] += 1
            continue

        r = None
        try:
            r = ce.fetch_shares_via_api(corp_code, year)
        except Exception:
            r = None
        time.sleep(_INTER_CALL_DELAY)

        if r is None:
            stats["apifail"] += 1
            consecutive_fail += 1
            if consecutive_fail >= _MAX_CONSECUTIVE_FAIL:
                stats["aborted"] = True
                print(f"[백필] 연속 실패 {consecutive_fail}건 → DART throttle/한도 추정. 중단."
                      f" (처리분 보존; 쿼터 회복 후 재실행하면 이어서 진행)")
                break
            continue
        consecutive_fail = 0

        new_issued = int(r.get("common_issued") or 0)
        ratio = (new_issued / old_issued) if old_issued else 0.0
        materially_changed = (not old_issued) or abs(ratio - 1) > 0.01

        if apply:
            try:
                p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            ce._mirror_shares_to_db(ticker, year, r)

        if materially_changed:
            stats["changed"] += 1
            nm = (db.get_company(ticker) or {}).get("corp_name") or ""
            inv = _invalidate_results(ticker) if (apply and invalidate_results) else 0
            changes.append((ticker, nm, old_issued, new_issued, ratio, inv))
            print(f"  [교정] {ticker} {nm[:12]:<12} {old_issued:>14,} → {new_issued:>14,} "
                  f"(×{ratio:.3g}){'  결과무효화' if inv else ''}")
        else:
            stats["same"] += 1

        if i % 200 == 0:
            print(f"  ... {i}/{len(files)} 처리 (교정 {stats['changed']}, "
                  f"동일 {stats['same']}, API실패 {stats['apifail']})")

    print("\n[백필 요약]")
    for k, v in stats.items():
        print(f"  {k:14s} {v}")
    print(f"  교정 종목 {len(changes)}개")
    return {"stats": stats, "changes": changes}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    args = set(sys.argv[1:])
    backfill(
        apply=("--dry" not in args),
        force=("--force" in args),
        invalidate_results=("--keep-results" not in args),
        limit=None,
    )
