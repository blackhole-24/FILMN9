"""외부 API 호출용 retry/backoff 유틸리티.

용도:
  DART / KRX / ECOS / KOFIA / OpenAI 등 외부 API 호출 시 일시적 네트워크 오류 또는
  rate limit (HTTP 429, 503) 대응. 데코레이터로 호출 가능 함수에 즉시 적용.

사용:
  from valuation_engine._retry import with_retry

  @with_retry(max_tries=3, backoff=1.5, retry_on=(ConnectionError, TimeoutError))
  def fetch_xxx(...):
      ...

설계:
  · 지수 backoff (1, 1.5, 2.25 초)
  · HTTP 429/503 인식 (requests.Response.status_code)
  · 모든 try 실패 시 마지막 예외 raise
  · graceful 차원에서 verbose=True 시 시도마다 print

운영:
  이 모듈은 의존성 0 (표준 라이브러리만). 모든 fetch 모듈에 안전하게 import 가능.
"""
from __future__ import annotations
import functools
import time
from typing import Callable, Iterable


def with_retry(max_tries: int = 3, backoff: float = 1.5,
               retry_on: Iterable = (Exception,),
               verbose: bool = False) -> Callable:
    """함수 호출 retry 데코레이터.

    Args:
        max_tries: 최대 시도 횟수 (기본 3)
        backoff:   기본 대기(초) — 매 시도마다 backoff × (2^(n-1)) 적용. 기본 1.5.
                   1번째 실패 후 1.5s, 2번째 실패 후 3.0s.
        retry_on:  catch 할 예외 클래스 튜플
        verbose:   재시도 시 print 출력

    예시:
        @with_retry(max_tries=3, retry_on=(ConnectionError, TimeoutError))
        def fetch(url): ...
    """
    retry_on = tuple(retry_on)

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_tries + 1):
                try:
                    result = fn(*args, **kwargs)
                    # HTTP 429/503 인식 (requests.Response 객체 반환 시)
                    if hasattr(result, "status_code") and result.status_code in (429, 503):
                        msg = f"HTTP {result.status_code}"
                        if attempt < max_tries:
                            wait = backoff * (2 ** (attempt - 1))
                            if verbose:
                                print(f"  [retry {attempt}/{max_tries}] {fn.__name__}: {msg} → {wait:.1f}s 대기")
                            time.sleep(wait)
                            continue
                    return result
                except retry_on as e:
                    last_exc = e
                    if attempt < max_tries:
                        wait = backoff * (2 ** (attempt - 1))
                        if verbose:
                            print(f"  [retry {attempt}/{max_tries}] {fn.__name__}: {type(e).__name__}({str(e)[:60]}) → {wait:.1f}s 대기")
                        time.sleep(wait)
                    else:
                        raise
            if last_exc:
                raise last_exc
            return None
        return wrapper
    return deco
