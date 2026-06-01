"""
build_ohlcv.py
==============
종목코드 또는 기업명 → pykrx로 OHLCV 수집 → ohlcv.json 저장.

출력
----
  data/parsed/{stock_code}/ohlcv.json

사용법
------
  cd C:/Users/Admin/FILMN9/part_company_overview/재무정보

  python build_ohlcv.py 090430          # 아모레퍼시픽 (종목코드)
  python build_ohlcv.py 삼성전자        # 기업명 검색
  python build_ohlcv.py                 # 기본값 090430

  # 날짜 범위 지정 (선택)
  python build_ohlcv.py 090430 --from 20200101
  python build_ohlcv.py 090430 --from 20200101 --to 20231231

  # 증분 업데이트 (기존 ohlcv.json에 최신 데이터만 추가)
  python build_ohlcv.py 090430 --update

ohlcv.json 스키마
-----------------
{
  "stock_code"   : "090430",
  "corp_name"    : "아모레퍼시픽",
  "from_date"    : "20060601",
  "to_date"      : "20260519",
  "count"        : 4987,
  "data": [
    {
      "date"  : "2006-06-01",   # Lightweight Charts 호환 (YYYY-MM-DD)
      "open"  : 123000,
      "high"  : 125000,
      "low"   : 121000,
      "close" : 124000,
      "volume": 12345
    }, ...
  ],
  "_source"      : "pykrx",
  "_generated_at": "2026-05-19 12:00"
}

주의
----
- pykrx는 KRX 장 영업일 기준으로만 데이터를 반환함 (주말·공휴일 없음)
- 상장일 이전 날짜를 from_date로 지정하면 pykrx가 자동으로 최초 영업일부터 반환
- 수치는 Python 계산만, LLM 환각 금지
- 값은 전부 JSON 경유, 코드 하드코딩 금지
"""

from __future__ import annotations

import sys
import json
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent   # 재무정보/
_ROOT = _HERE.parent.parent               # FILMN9/
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from build_overview import resolve_company  # corp_code_map 기반 종목 조회

# ─── pykrx ───────────────────────────────────────────────────────────────────
try:
    from pykrx import stock as krx
except ImportError:
    print("[ERROR] pykrx 미설치. pip install pykrx")
    sys.exit(1)


# =============================================================================
# 날짜 유틸
# =============================================================================

def _today() -> str:
    return datetime.today().strftime("%Y%m%d")


def _fmt_display(yyyymmdd: str) -> str:
    """'20260519' → '2026-05-19'  (Lightweight Charts time 필드)"""
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


_PYKRX_MIN_DATE = "20140101"   # pykrx(KRX) 데이터 제공 시작일

def _listing_date(stock_code: str) -> str:
    """
    company_info.json의 listing_date 파싱.
    pykrx는 2014년 이전 데이터를 제공하지 않으므로
    20140101 이전이면 20140101로 클램핑.
    """
    ci_path = _ROOT / "data" / "parsed" / stock_code / "company_info.json"
    if ci_path.exists():
        try:
            ci = json.loads(ci_path.read_text(encoding="utf-8"))
            raw = ci.get("listing_date", "")
            # 형식: "2006년 06월 01일" 또는 "20060601" 또는 "2006-06-01"
            digits = "".join(c for c in raw if c.isdigit())
            if len(digits) >= 8:
                date_str = digits[:8]
                # pykrx 데이터 제공 시작일 이전이면 클램핑
                return max(date_str, _PYKRX_MIN_DATE)
        except Exception:
            pass
    return _PYKRX_MIN_DATE


def _last_saved_date(ohlcv_path: Path) -> str | None:
    """기존 ohlcv.json에서 마지막 저장 날짜 추출."""
    if not ohlcv_path.exists():
        return None
    try:
        data = json.loads(ohlcv_path.read_text(encoding="utf-8"))
        return data.get("to_date")
    except Exception:
        return None


# =============================================================================
# pykrx OHLCV 수집
# =============================================================================

def _fetch_single(stock_code: str, from_date: str, to_date: str,
                  retry: int = 3) -> list[dict]:
    """단일 범위 pykrx 조회 (내부용). 최대 ~3000건 제한 있음."""
    for attempt in range(1, retry + 1):
        try:
            df = krx.get_market_ohlcv(from_date, to_date, stock_code)
            if df is None or df.empty:
                return []
            records = []
            for idx, row in df.iterrows():
                date_str = idx.strftime("%Y%m%d")
                records.append({
                    "date"  : _fmt_display(date_str),
                    "open"  : int(row.get("시가",  0) or 0),
                    "high"  : int(row.get("고가",  0) or 0),
                    "low"   : int(row.get("저가",  0) or 0),
                    "close" : int(row.get("종가",  0) or 0),
                    "volume": int(row.get("거래량", 0) or 0),
                })
            records.sort(key=lambda r: r["date"])
            return records
        except Exception as e:
            print(f"    [WARN] 시도 {attempt}/{retry} 실패: {e}")
            if attempt < retry:
                time.sleep(2)
    return []


def fetch_ohlcv(stock_code: str, from_date: str, to_date: str,
                retry: int = 3) -> list[dict]:
    """
    pykrx → OHLCV 리스트 반환.

    pykrx는 한 번 호출에 최대 ~3,000건(약 12년치) 제한이 있으므로
    연도별 청크로 분할 조회 후 병합한다.

    Returns list of:
      {"date": "2026-05-19", "open": int, "high": int, "low": int,
       "close": int, "volume": int}
    """
    from_year = int(from_date[:4])
    to_year   = int(to_date[:4])

    # 3년 이하 → 단일 조회
    if to_year - from_year <= 3:
        print(f"  pykrx 조회: {stock_code}  {from_date} ~ {to_date}")
        records = _fetch_single(stock_code, from_date, to_date, retry)
        print(f"  수집 완료: {len(records):,}건")
        return records

    # 3년 초과 → 연도별 청크 (3년 단위) 분할 조회
    all_records: list[dict] = []
    seen_dates: set[str]    = set()

    chunk_years = 3  # 한 번에 3년씩
    year = from_year
    while year <= to_year:
        chunk_from = f"{year}0101" if year != from_year else from_date
        chunk_to   = f"{min(year + chunk_years - 1, to_year)}1231"
        if year + chunk_years - 1 >= to_year:
            chunk_to = to_date

        print(f"  pykrx 조회: {stock_code}  {chunk_from} ~ {chunk_to}")
        chunk = _fetch_single(stock_code, chunk_from, chunk_to, retry)

        added = 0
        for r in chunk:
            if r["date"] not in seen_dates:
                all_records.append(r)
                seen_dates.add(r["date"])
                added += 1
        print(f"    └ {added:,}건 수집")

        year += chunk_years
        if year <= to_year:
            time.sleep(0.5)  # KRX 서버 부하 방지

    all_records.sort(key=lambda r: r["date"])
    print(f"  총 수집 완료: {len(all_records):,}건")
    return all_records


# =============================================================================
# 증분 업데이트 (--update 모드)
# =============================================================================

def fetch_incremental(stock_code: str, existing: dict) -> dict:
    """
    기존 ohlcv.json에 누락된 최신 데이터만 추가.
    last_date 다음 영업일부터 오늘까지 수집 후 병합.
    """
    last_date = existing.get("to_date", "")
    if not last_date:
        print("  [WARN] 기존 to_date 없음 → 전체 재수집")
        return existing

    # 다음날부터 조회 (last_date 포함 안 함)
    last_dt  = datetime.strptime(last_date, "%Y%m%d")
    from_dt  = last_dt + timedelta(days=1)
    from_str = from_dt.strftime("%Y%m%d")
    to_str   = _today()

    if from_str > to_str:
        print(f"  이미 최신 상태 ({last_date}). 업데이트 불필요.")
        return existing

    new_records = fetch_ohlcv(stock_code, from_str, to_str)
    if not new_records:
        print("  신규 데이터 없음.")
        return existing

    # 병합 (중복 날짜 제거)
    existing_dates = {r["date"] for r in existing["data"]}
    added = [r for r in new_records if r["date"] not in existing_dates]
    existing["data"].extend(added)
    existing["data"].sort(key=lambda r: r["date"])

    existing["to_date"]      = existing["data"][-1]["date"].replace("-", "")
    existing["count"]        = len(existing["data"])
    existing["_generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"  증분 추가: {len(added):,}건  (총 {existing['count']:,}건)")
    return existing


# =============================================================================
# 메인
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="pykrx OHLCV 수집기")
    parser.add_argument("query",    nargs="?", default="090430",
                        help="종목코드 (6자리) 또는 기업명")
    parser.add_argument("--from",   dest="from_date", default=None,
                        help="시작일 YYYYMMDD (기본: 상장일)")
    parser.add_argument("--to",     dest="to_date",   default=None,
                        help="종료일 YYYYMMDD (기본: 오늘)")
    parser.add_argument("--update", action="store_true",
                        help="기존 ohlcv.json에 최신 데이터만 추가 (증분)")
    args = parser.parse_args()

    # ── 종목 조회 ─────────────────────────────────────────────────────────
    resolved = resolve_company(args.query)
    if resolved is None:
        sys.exit(1)

    stock_code, _corp_code, corp_name = resolved

    print(f"\n{'='*55}")
    print(f"  build_ohlcv  [{corp_name} / {stock_code}]")
    print(f"{'='*55}")

    out_dir    = _ROOT / "data" / "parsed" / stock_code
    out_dir.mkdir(parents=True, exist_ok=True)
    ohlcv_path = out_dir / "ohlcv.json"

    # ── 증분 업데이트 모드 ────────────────────────────────────────────────
    if args.update and ohlcv_path.exists():
        print("\n[증분 업데이트 모드]")
        try:
            existing = json.loads(ohlcv_path.read_text(encoding="utf-8"))
            updated  = fetch_incremental(stock_code, existing)
            ohlcv_path.write_text(
                json.dumps(updated, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"  저장: {ohlcv_path}")
            _print_summary(updated)
            return
        except Exception as e:
            print(f"  [ERROR] 증분 업데이트 실패: {e} → 전체 재수집으로 전환")

    # ── 전체 수집 모드 ────────────────────────────────────────────────────
    from_date = args.from_date or _listing_date(stock_code)
    to_date   = args.to_date   or _today()

    print(f"\n  수집 범위: {from_date} ~ {to_date}")
    print(f"  (상장일 기준: {_listing_date(stock_code)})\n")

    records = fetch_ohlcv(stock_code, from_date, to_date)

    # ── JSON 조립 ─────────────────────────────────────────────────────────
    actual_from = records[0]["date"].replace("-", "") if records else from_date
    actual_to   = records[-1]["date"].replace("-", "") if records else to_date

    ohlcv_json = {
        "stock_code"    : stock_code,
        "corp_name"     : corp_name,
        "from_date"     : actual_from,
        "to_date"       : actual_to,
        "count"         : len(records),
        "data"          : records,
        "_source"       : "pykrx",
        "_generated_at" : datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    ohlcv_path.write_text(
        json.dumps(ohlcv_json, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n  저장: {ohlcv_path}")
    _print_summary(ohlcv_json)


def _print_summary(data: dict) -> None:
    print(f"\n{'='*55}")
    print(f"  완료 요약")
    print(f"{'='*55}")
    print(f"  기업명   : {data['corp_name']}")
    print(f"  수집 기간: {data['from_date']} ~ {data['to_date']}")
    print(f"  총 거래일: {data['count']:,}일")

    records = data.get("data", [])
    if records:
        latest = records[-1]
        print(f"  최근 종가: {latest['close']:,}원  ({latest['date']})")
        print(f"  최근 거래량: {latest['volume']:,}주")

    print(f"\n  ohlcv.json : {data['count']:,}건")
    print(f"  생성 시각  : {data['_generated_at']}")


if __name__ == "__main__":
    main()
