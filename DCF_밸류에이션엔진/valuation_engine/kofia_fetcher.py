"""KOFIA 채권정보센터 hidden API 자동 수집 — 채권시가평가기준수익률.

배경:
  기존에는 KOFIA 채권정보센터에서 '채권시가평가기준수익률'을 수동 다운로드해
  VAR/채권시가평가기준수익률_<YYYYMMDD>.csv 로 저장 → kd_loader 가 파싱했다.
  본 모듈은 그 수동 단계를 KOFIA WebSquare/proframe hidden API 호출로 자동화한다.

API (F12 네트워크 분석으로 확보):
  URL    : https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/
  Method : POST
  C-Type : application/x-www-form-urlencoded; charset=UTF-8  (본문은 raw XML)
  세션   : 불필요 (쿠키 없이 응답)
  서비스 : pfmSvcName=BISBndSrtPrcSrchSO, pfmFnName=selectDay(데이터)/getHeadList(만기헤더)
  파라미터: standardDt=YYYYMMDD, reportCompCd=A20000(평가사 평균), applyGbCd=C00

응답 구조 (BISBndSrtPrcDayDTO 반복):
  종류=largeCategoryMrk, 종류명=typeNmMrk, 신용등급=creditRnkMrk,
  고시기관=koreanShotNm, val1~val16 = [3월,6월,9월,1년,1년6월,2년,2년6월,3년,
  4년,5년,7년,10년,15년,20년,30년,50년]  → val10 = 5년물 (Kd 산정용)

저장:
  VAR/채권시가평가기준수익률_<YYYYMMDD>.csv  (기존 kd_loader 가 읽는 형식과 동일)
  → kd_loader 무수정 연동.
"""
from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests

_VAR_ROOT = Path(__file__).resolve().parent.parent

_URL = "https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/"
_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Origin": "https://www.kofiabond.or.kr",
    "Referer": "https://www.kofiabond.or.kr/websquare/websquare.html"
               "?w2xPath=/xml/startest/BISBndSrtPrcDay.xml",
}

# CSV 헤더 (kd_loader 가 기대하는 기존 형식과 동일)
_MATURITY_COLS = ["3월", "6월", "9월", "1년", "1년6월", "2년", "2년6월", "3년",
                  "4년", "5년", "7년", "10년", "15년", "20년", "30년", "50년"]
_CSV_HEADER = ["종류", "종류명", "신용등급", "고시기관"] + _MATURITY_COLS


def _payload(fn: str, standard_dt: str, apply_gb: str = "C00") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<message><proframeHeader>'
        '<pfmAppName>BIS-KOFIABOND</pfmAppName>'
        '<pfmSvcName>BISBndSrtPrcSrchSO</pfmSvcName>'
        f'<pfmFnName>{fn}</pfmFnName>'
        '</proframeHeader><systemHeader></systemHeader>'
        '<BISBndSrtPrcDayDTO>'
        f'<standardDt>{standard_dt}</standardDt>'
        '<reportCompCd>A20000</reportCompCd>'
        f'<applyGbCd>{apply_gb}</applyGbCd>'
        '<val1>A10002</val1><val2>A10003</val2><val3>A10004</val3>'
        '<val4>A10005</val4><val5>A10006</val5>'
        '</BISBndSrtPrcDayDTO></message>'
    )


def _call(fn: str, standard_dt: str, apply_gb: str = "C00", timeout: int = 30) -> str:
    r = requests.post(_URL, data=_payload(fn, standard_dt, apply_gb).encode("utf-8"),
                      headers=_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text


def _parse_rows(xml_text: str) -> list[list[str]]:
    """selectDay 응답 XML → CSV 행 리스트 (헤더 제외). 데이터 0건이면 빈 리스트."""
    root = ET.fromstring(xml_text)
    rows = []
    for dto in root.iter("BISBndSrtPrcDayDTO"):
        g = lambda t: (dto.findtext(t) or "").strip()
        kind = g("largeCategoryMrk")
        if not kind:                      # 헤더/빈 행 skip
            continue
        vals = [g(f"val{i}") or "-" for i in range(1, 17)]
        rows.append([kind, g("typeNmMrk"), g("creditRnkMrk"), g("koreanShotNm")] + vals)
    return rows


def _persist_yields_to_db(dt_str: str, rows: list[list[str]]) -> None:
    """write-through: kofia_bond_yields (만기별 언피벗 → DB 기록). guarded.

    읽기(Kd)는 kd_loader 가 CSV 사용 → 불변. DB 는 회사채금리 이력·쿼리용.
    """
    try:
        from valuation_engine import db as _db
        _iso = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
        _dbrows = []
        for _r in rows:
            _rating = f"{_r[1]}/{_r[2]}"   # 종류명/신용등급 (PK 충돌 방지)
            for _mat, _v in zip(_MATURITY_COLS, _r[4:4 + len(_MATURITY_COLS)]):
                if _v and _v != "-":
                    try:
                        _yp = float(_v)
                    except (ValueError, TypeError):
                        continue
                    _dbrows.append({"yield_date": _iso, "rating": _rating,
                                    "maturity": _mat, "yield_pct": _yp})
        if _dbrows:
            _db.save_kofia_yields(_dbrows)
    except Exception:
        pass


def _read_csv_rows(path: Path) -> list[list[str]]:
    """저장된 CSV → 데이터 행 리스트 (헤더 제외). 실패 시 빈 리스트."""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rdr = csv.reader(f)
            all_rows = list(rdr)
        return all_rows[1:] if len(all_rows) > 1 else []
    except Exception:
        return []


def fetch_and_save(eval_date: Optional[date] = None,
                   max_lookback: int = 7,
                   force: bool = False,
                   verbose: bool = True) -> Path:
    """KOFIA API 호출 → 채권시가평가기준수익률 CSV 저장 (kd_loader 형식).

    - eval_date 기준 직전 영업일부터 역산하며 데이터가 있는 첫 날을 사용.
    - 해당 날짜 CSV 가 이미 있으면(force=False) 재호출 없이 그 경로 반환 (캐시).

    Returns: 저장된 CSV 경로.
    Raises:  RuntimeError — max_lookback 일 내 데이터를 못 찾으면 (임의값 금지 정책).
    """
    base = eval_date or date.today()
    if isinstance(base, str):
        from datetime import datetime as _dt
        base = _dt.fromisoformat(base).date()

    for back in range(max_lookback + 1):
        d = base - timedelta(days=back)
        dt_str = d.strftime("%Y%m%d")
        out = _VAR_ROOT / f"채권시가평가기준수익률_{dt_str}.csv"
        if out.exists() and not force:
            if verbose:
                print(f"  [KOFIA] 캐시 hit: {out.name}")
            # write-through: 캐시 hit 에도 DB 적재 (DB 초기화 후 CSV만 남은 경우 대비).
            _persist_yields_to_db(dt_str, _read_csv_rows(out))
            return out
        try:
            rows = _parse_rows(_call("selectDay", dt_str))
        except Exception as e:
            if verbose:
                print(f"  [KOFIA] {dt_str} 호출 실패: {str(e)[:80]}")
            continue
        if not rows:
            if verbose:
                print(f"  [KOFIA] {dt_str} 데이터 0건 (비영업일 추정) → 직전일 재시도")
            continue
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(_CSV_HEADER)
            w.writerows(rows)
        # ── write-through: kofia_bond_yields (만기별 언피벗 → DB 기록) ──
        #   읽기(Kd)는 kd_loader 가 CSV 사용 → 불변. DB 는 회사채금리 이력·쿼리용.
        try:
            from valuation_engine import db as _db
            _iso = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
            _dbrows = []
            for _r in rows:
                _rating = f"{_r[1]}/{_r[2]}"   # 종류명/신용등급 (PK 충돌 방지)
                for _mat, _v in zip(_MATURITY_COLS, _r[4:4 + len(_MATURITY_COLS)]):
                    if _v and _v != "-":
                        try:
                            _yp = float(_v)
                        except (ValueError, TypeError):
                            continue
                        _dbrows.append({"yield_date": _iso, "rating": _rating,
                                        "maturity": _mat, "yield_pct": _yp})
            if _dbrows:
                _db.save_kofia_yields(_dbrows)
        except Exception:
            pass
        if verbose:
            n_corp = sum(1 for r in rows if "회사채" in r[0] and "무보증" in r[1])
            print(f"  [KOFIA] {out.name} 저장 ({len(rows)}행, 회사채무보증 {n_corp}등급)")
        return out

    raise RuntimeError(
        f"KOFIA 채권시가평가수익률을 {max_lookback}일 내 찾지 못함 "
        f"(기준 {base}). API 변경 또는 네트워크 점검 필요.")


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else None
    p = fetch_and_save(eval_date=d, force=True, verbose=True)
    print("저장 완료:", p)
