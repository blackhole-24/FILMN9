"""사용자 ticker 입력 → 자동 피어 산정 → DCF 통합 진입점.

기존 run_valuation.py 는 config.TARGET/PEERS 하드코딩 (현대건설 + 건설 3사).
본 모듈은 사용자가 임의의 종목을 입력해도 자동으로 전체 흐름 실행.

실행:
    conda activate dart-rag
    cd C:\\Users\\Admin\\Desktop\\VAR
    python -m valuation_engine.run_valuation_auto --ticker 000720
    python -m valuation_engine.run_valuation_auto --ticker 현대건설
    python -m valuation_engine.run_valuation_auto --ticker 삼양식품

흐름:
  Step 1. 입력 정규화          (ticker_lookup)
  Step 2. 자동 피어 산정        (peer_selector — KRX 캐시 + XBRL + RAG)
  Step 3. config 동적 교체      (TARGET/PEERS in-place update)
  Step 4. 기존 run_valuation    (XBRL → WACC → DCF → 멀티플 → 시나리오)
  Step 5. 결과 출력 + JSON 저장

설계 노트 — config in-place update:
  config.TARGET / PEERS / ALL_COMPANIES 는 mutable list/dict.
  다른 모듈이 `from .config import TARGET` 한 객체와 동일 참조 유지하면서
  내부 값만 갱신 (clear + update/extend) → 모든 모듈에 새 값 반영.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# ── Phase 0(2026-05-28): config TARGET/PEERS 동시 호출 경합 차단 ──
# 본 모듈은 config.TARGET/PEERS 를 in-place mutate 하므로 동시 호출 시 race 위험.
# api.py 의 ThreadPoolExecutor(max_workers=1) 가 직렬화하지만, 외부 스크립트가
# run_for_ticker 를 직접 호출하는 경로(pytest·배치 등)에서는 보호 필요.
# 근본 해결(ValuationContext 객체 전달) 은 잔여작업 — 본 RLock 으로 동시성 위험만 차단.
_VALUATION_LOCK = threading.RLock()

# ★ Windows cp949 콘솔에서도 한글·이모지·유니코드 대시 출력 가능하게
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from . import config
from .ticker_lookup import lookup
from .peer_selector import select_peers_for_target
from .peer_universe_data import get_company_info


# ─────────────────────────────────────────────────────────────
# config 동적 교체 (in-place update)
# ─────────────────────────────────────────────────────────────
def _swap_target_and_peers(target: dict, peers: list[dict]) -> None:
    """config 모듈의 TARGET/PEERS/ALL_COMPANIES 를 in-place 로 교체.

    다른 모듈이 `from .config import TARGET` 한 객체와 동일 참조 유지
    → 모든 모듈에 자동 반영.
    """
    # TARGET dict 교체
    config.TARGET.clear()
    config.TARGET.update(target)

    # PEERS list 교체
    config.PEERS.clear()
    config.PEERS.extend(peers)

    # ALL_COMPANIES 재구성
    config.ALL_COMPANIES.clear()
    config.ALL_COMPANIES.append(config.TARGET)
    config.ALL_COMPANIES.extend(config.PEERS)


def _resolve_market_from_krx_cache(ticker: str) -> Optional[str]:
    """KRX 전종목 일별시세 캐시에서 ticker 의 실제 시장(KOSPI/KOSDAQ) 판별.

    ticker_lookup 이 krx_desc.csv 매칭 시 market='(unknown)' 을 반환하는 경우 보정용.
    (krx_desc 에 시장 컬럼이 없어 청크 파일명 매칭 실패 종목은 모두 '(unknown)' 이 됨)
    API 무호출 — 이미 받아둔 캐시 파일만 조회. 미발견 시 None.
    """
    import json as _json
    try:
        from peer_beta.config import RAW_DIR as _RAW
    except Exception:
        return None
    tk = str(ticker).zfill(6)
    for market in ("KOSPI", "KOSDAQ"):
        files = sorted(_RAW.glob(f"stock_{market}_*.json"))
        if not files:
            continue
        try:
            with files[-1].open(encoding="utf-8") as f:
                data = _json.load(f)
        except Exception:
            continue
        for row in data.get("OutBlock_1", []):
            code = (row.get("ISU_SRT_CD") or row.get("ISU_CD") or "")
            if len(code) == 12 and code.upper().startswith("KR"):
                code = code[3:9]
            if code.zfill(6) == tk:
                return market
    return None


def _normalize_market(ticker: str, market: str) -> str:
    """market 이 '(unknown)'·빈값·비정상이면 KRX 캐시로 보정. 실패 시 KOSPI 폴백.

    베타 단계(fetch_index_weekly)는 market 으로 ENDPOINTS 를 조회하므로
    '(unknown)' 이 흘러들면 KeyError 로 평가가 통째로 실패한다 → 진입 직후 정규화.
    """
    if market in ("KOSPI", "KOSDAQ"):
        return market
    return _resolve_market_from_krx_cache(ticker) or "KOSPI"


def _build_target_dict(ticker: str, market: str = "KOSPI",
                       name: str | None = None) -> dict:
    """ticker → config.TARGET 호환 dict 구성.

    name: ticker_lookup 이 해석한 정식 회사명(권위 소스). 이게 있으면 우선 사용 →
          get_company_info 가 None 을 줘서 TARGET['name']=ticker 로 폴백되던 문제 해소.
          (TARGET['name']=ticker 이면 load_cached/_find_cached_json 등 '이름 키' 조회가
           실제 corp_name 으로 저장된 캐시를 못 찾아 자본구조 등이 깨짐 → 근본 수정.)
    """
    info = get_company_info(ticker) or {}
    return {
        "name":      name or info.get("name") or ticker,
        "ticker":    ticker,
        "corp_code": "",         # XBRL 호출 시 자동 lookup
        "market":    _normalize_market(ticker, market),
    }


def _build_peers_list(peers_selector_result: list[dict]) -> list[dict]:
    """select_peers_for_target 결과 → config.PEERS 호환 list."""
    out = []
    for p in peers_selector_result:
        out.append({
            "name":      p["name"],
            "ticker":    p["ticker"],
            "corp_code": "",
            "market":    _normalize_market(p["ticker"], p.get("market", "KOSPI")),
            "score":     p.get("total_score"),   # peer_selector 반환 키=total_score [0,1] (βU 가중용)
        })
    return out


# ─────────────────────────────────────────────────────────────
# peer_beta config 도 동적 교체
# ─────────────────────────────────────────────────────────────
def _swap_peer_beta_config(target: dict, peers: list[dict]) -> None:
    """peer_beta/config.py 의 DEFAULT_PEERS 도 동기화."""
    try:
        from peer_beta import config as pb_config
        # peer_beta 도 mutable list 가정 — in-place
        new_companies = [
            {"name": target["name"], "ticker": target["ticker"],
             "market": target["market"], "role": "target"},
        ]
        for p in peers:
            new_companies.append({
                "name": p["name"], "ticker": p["ticker"],
                "market": p["market"], "role": "peer"
            })
        if hasattr(pb_config, "DEFAULT_PEERS"):
            pb_config.DEFAULT_PEERS.clear()
            pb_config.DEFAULT_PEERS.extend(new_companies)
    except Exception as e:
        print(f"  [WARN] peer_beta config 동기화 실패: {e}")


# ─────────────────────────────────────────────────────────────
# 메인 진입점
# ─────────────────────────────────────────────────────────────
def run_for_ticker(user_input: str,
                   eval_date: Optional[date] = None,
                   top_n_peers: int = 3,
                   use_rag: bool = True,
                   progress_cb=None,
                   verbose: bool = True) -> dict:
    """사용자 입력 → 자동 피어 → DCF 통합 흐름.

    실데이터만 사용 (임의값 금지). 데이터 부재 시 RuntimeError.

    Args:
        user_input:  사용자 입력 (티커 또는 회사명)
        eval_date:   평가기준일 (기본 today)
        top_n_peers: 피어 개수
        use_rag:     사업보고서 RAG 유사도 사용 (피어 산정 단계)
        progress_cb: 진행상황 콜백 (UI 표시용). callable(msg: str) 형태
        verbose:     진행상황 출력

    Returns:
        run_valuation 의 통합 JSON (streamlit 입력 호환)
    """
    # Phase 0: 전체 평가를 _VALUATION_LOCK 안에서 수행 — config in-place mutation 보호.
    with _VALUATION_LOCK:
        return _run_for_ticker_locked(user_input, eval_date, top_n_peers,
                                      use_rag, progress_cb, verbose)


# 명확한 금융업만 — 제조업 DCF/피어 모델이 구조적으로 안 맞아 피어 산정이 0개가 되는 업종.
#   '기타 금융업'·'금융 지원 서비스업'은 지주회사(에코프로 등)·전자결제가 섞여 있어 제외
#   (이들은 피어 산정 후 DCF 단계 graceful 또는 피어 0개 안전망에서 처리).
_CLEAR_FINANCE_KW = ("은행", "보험", "증권", "신탁", "신용카드", "할부금융", "여신")


def _is_clear_financial(ticker: str) -> tuple[bool, str]:
    """명확한 금융업 여부 (KRX Industry 키워드). Returns (여부, industry)."""
    try:
        from .industry_classifier import _load_desc
        ind = _load_desc().get(str(ticker).zfill(6), {}).get("Industry", "") or ""
        return any(kw in ind for kw in _CLEAR_FINANCE_KW), ind
    except Exception:
        return False, ""


def _unsupported_payload(ticker, name, market, eval_d, kind, reason):
    """DCF/피어 모델 대상 외(금융 등) — 크래시 대신 graceful 안내 결과.

    제조업 DCF·피어 비교 모델이 구조적으로 안 맞는 업종(금융=이자수익이 본업)에 대해
    RuntimeError 로 평가를 중단시키는 대신 status='unsupported' 결과를 돌려준다.
    소비자(UI/배치)는 status 로 분기해 '미지원 + 권장 모형(DDM/RIM)' 을 안내한다.
    """
    try:
        from .config import MODEL_VERSION as _MV
    except Exception:
        _MV = None
    _ed = eval_d.isoformat() if hasattr(eval_d, "isoformat") else str(eval_d)
    return {
        "as_of_date": _ed,
        "company": {"name": name, "ticker": ticker, "market": market},
        "status": "unsupported",
        "unsupported_kind": kind,
        "unsupported_reason": reason,
        "summary": {"fair_price": None, "dcf_valid": False,
                    "peer_confidence_grade": None, "peer_confidence_score": None},
        "model_version": _MV,
    }


def _run_for_ticker_locked(user_input, eval_date, top_n_peers,
                            use_rag, progress_cb, verbose):
    """run_for_ticker 의 락 보호 내부 — 기존 로직 그대로."""
    eval_d = eval_date or date.today()
    if isinstance(eval_d, str):
        eval_d = datetime.fromisoformat(eval_d).date()

    t0 = time.time()
    print("=" * 70)
    print(f"  자동 피어 산정 + 가치평가 - {user_input}  (T={eval_d})")
    print("=" * 70)

    # ── Step 1. 입력 정규화 ──────────────────────────────────
    print(f"\n[Step 1] 입력 정규화")
    look = lookup(user_input)
    if look["status"] == "not_found":
        raise ValueError(f"입력 '{user_input}' 매칭 실패: {look.get('note')}")
    if look["status"] == "ambiguous":
        print(f"  [WARN] 모호 - 후보 {len(look['suggestions'])}개:")
        for s in look["suggestions"][:5]:
            print(f"    - {s['ticker']}  {s['corp_name']}  ({s['market']})")
        raise ValueError(f"입력 '{user_input}' 모호. 구체적인 티커 또는 정확한 회사명 입력 필요.")
    target_match = look["match"]
    target_ticker = target_match["ticker"]
    target_name   = target_match["corp_name"]
    target_market = target_match["market"]
    print(f"  [OK] 매칭: {target_ticker}  {target_name}  ({target_market})")

    # ── 명확 금융업 사전 차단 — 은행·보험·증권·신탁·카드·여신은 제조업 DCF/피어 모델
    #   대상 외. Step 2 피어 산정 0개로 RuntimeError 나기 전에 graceful 안내 반환.
    #   ※ '기타 금융업'·'금융 지원 서비스업'은 지주회사(에코프로)·전자결제가 섞여 있어
    #     여기서 차단하지 않는다 → 피어 산정 후 DCF graceful 또는 아래 피어 0개 안전망 처리.
    _fin, _fin_ind = _is_clear_financial(target_ticker)
    if _fin:
        _reason = (f"금융업({_fin_ind.strip()}) — 이자수익이 본업이라 일반 현금흐름 평가"
                   f"(DCF)가 안 맞습니다. 배당·자본 기반 평가(DDM·RIM) 권장")
        print(f"\n[중단] {_reason}")
        return _unsupported_payload(target_ticker, target_name, target_market,
                                    eval_d, kind="financial", reason=_reason)

    # ── Step 2. 자동 피어 산정 ──────────────────────────────
    print(f"\n[Step 2] 자동 피어 산정 (Top {top_n_peers})")
    peers = select_peers_for_target(
        target_ticker, target_data=None, top_n=top_n_peers,
        use_rag=use_rag, verbose=verbose)
    if not peers:
        # 피어 0개 — 명확 금융 외(기타금융 지주·금융지원·WICS 매핑부재 등)에서도 후보가
        #   없으면 크래시 대신 graceful. 제조업 피어·지표 기반이라 일부 업종은 구조적 부재.
        #   (디버깅 단서는 로그/콘솔로 남기되 평가 흐름은 중단시키지 않음)
        print(f"\n[중단] 동종 피어 0개 — 비교가치 평가 불가 ({target_ticker})\n"
              f"  점검: WICS 매핑 / KRX 캐시 / XBRL raw")
        return _unsupported_payload(
            target_ticker, target_name, target_market, eval_d, kind="no_peers",
            reason="동종 피어를 충분히 찾지 못해 평가가 어렵습니다 "
                   "(업종 특성상 상장 피어 부족 또는 데이터 미비).")

    # ── Step 3. config 동적 교체 ────────────────────────────
    print(f"\n[Step 3] config TARGET/PEERS 동적 교체")
    new_target = _build_target_dict(target_ticker, market=target_market, name=target_name)
    new_peers  = _build_peers_list(peers)
    _swap_target_and_peers(new_target, new_peers)
    _swap_peer_beta_config(new_target, new_peers)
    print(f"  [OK] TARGET = {new_target['name']} ({new_target['ticker']})")
    print(f"  [OK] PEERS  = {', '.join(p['name'] for p in new_peers)}")
    if len(new_peers) < 3:
        print(f"  ⚠ [경고] 피어 {len(new_peers)}사 — 중위값 통계 신뢰도 낮음 "
              f"(섹터 내 가용 피어 부족). 결과 해석 시 주의.")

    # ── Step 3.5 제거(속도 #3): XBRL 수집은 Step 4(run_valuation Phase 1-B)의
    #    fetch_all 가 단일·병렬(#4)·피어 깊이 차등(#5)으로 수행한다. 과거에는
    #    여기서 collect_one_company_5yr(3초 sleep×N) 로 선수집 후 Phase 1-B 가
    #    재순회하는 이중 구조였음 → 중복 제거로 시간 단축.

    # ── Step 4. 기존 run_valuation 호출 ─────────────────────
    print(f"\n[Step 4] DCF 가치평가 실행 (기존 run_valuation 흐름)")
    # 주의: run_valuation 의 모듈 import 시점에 config 가져오므로
    # 본 모듈은 함수 안에서 lazy import 해야 갱신된 config 반영됨.
    from .run_valuation import run as run_dcf
    try:
        result = run_dcf(eval_date=eval_d, verbose=verbose)
    except Exception as e:
        raise RuntimeError(
            f"DCF 실행 실패: {e}\n"
            f"가능 원인:\n"
            f"  - PEERS XBRL 데이터 부재 → collect_xbrl_raw 로 자동 선정 피어 받기 필요\n"
            f"  - 사업보고서 청크 부재 → 사업보고서 RAG 미작동\n"
            f"  - KOFIA CSV 미존재 → Kd 산출 불가"
        ) from e

    # D-1: Phase 1 피어셋 신뢰도 — Fallback 첨부.
    #   주 첨부 지점은 run_valuation.run() 내부(파일/DB 동시반영).
    #   여기서는 호출자 반환값(result)에만 한 번 더 보존 — run() 가
    #   이미 채워 줬으면 no-op.
    try:
        if isinstance(result, dict) and not result.get("peer_confidence"):
            from .peer_selector import get_last_peer_confidence
            _conf = get_last_peer_confidence()
            if _conf:
                result["peer_confidence"] = _conf
                if "summary" in result and isinstance(result["summary"], dict):
                    result["summary"]["peer_confidence_grade"] = _conf.get("grade")
                    result["summary"]["peer_confidence_score"] = _conf.get("score")
    except Exception as _e:
        if verbose:
            print(f"  [WARN] peer_confidence 첨부 실패(fallback): {str(_e)[:100]}")

    elapsed = time.time() - t0
    print("\n" + "=" * 70)
    print(f"  완료 - 총 소요 {elapsed:.0f}초")
    _summary = result.get("summary", {}) if result else {}
    _fp = _summary.get("fair_price")
    _up = _summary.get("upside_pct")
    if _fp is not None:
        print(f"  적정주가: KRW {_fp:,.0f}/주")
        print(f"  상승여력: {_up:+.1f}%" if _up is not None else "  상승여력: -")
    else:
        print(f"  적정주가: - (DCF 산출 불가, dcf_valid=False)")
    print(f"  WACC: {_summary.get('wacc', 0)*100:.2f}%")
    print("=" * 70)
    print("\n다음: python -m uvicorn valuation_engine.api:app --port 8011")

    return result


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="사용자 ticker 입력 → 자동 피어 → DCF 가치평가",
    )
    parser.add_argument("--ticker", "-t", type=str, required=True,
                        help="타깃 종목코드 또는 회사명 (예: 000720, 현대건설, 삼양식품)")
    parser.add_argument("--date", "-d", type=str, default=None,
                        help="평가기준일 YYYY-MM-DD (기본 today)")
    parser.add_argument("--peers", "-n", type=int, default=3,
                        help="피어 개수 (기본 3)")
    parser.add_argument("--no-rag", action="store_true",
                        help="피어 산정 단계 RAG 임베딩 비활성화 (다른 RAG 호출은 유지)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="진행상황 출력 최소화")
    args = parser.parse_args(argv)

    eval_d = None
    if args.date:
        eval_d = datetime.strptime(args.date, "%Y-%m-%d").date()

    try:
        run_for_ticker(
            user_input=args.ticker,
            eval_date=eval_d,
            top_n_peers=args.peers,
            use_rag=not args.no_rag,
            verbose=not args.quiet,
        )
        return 0
    except (ValueError, RuntimeError) as e:
        print(f"\n[오류] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
