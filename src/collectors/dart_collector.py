"""
FILMN9 VEDA — DART 데이터 수집 모듈
수집 항목: 시가총액 기초 / IBD / NOA / LTM EBIT /
           FCFF (NWC·CAPEX) / EBITDA / EV 구성요소
"""

import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
DART_KEY = os.getenv("DART_API_KEY")
BASE_URL  = "https://opendart.fss.or.kr/api"


def _get(endpoint: str, params: dict) -> dict:
    """DART API GET 요청 공통 함수"""
    params["crtfc_key"] = DART_KEY
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") not in ("000", "013"):
        raise ValueError(f"DART API 오류: {data.get('status')} — {data.get('message')}")
    return data


def get_corp_code(company_name: str) -> str:
    """기업명 → DART corp_code 변환"""
    data = _get("company.json", {"corp_name": company_name})
    items = data.get("list", [])
    if not items:
        raise ValueError(f"'{company_name}'에 해당하는 기업을 찾을 수 없습니다.")
    for item in items:
        if item["corp_name"] == company_name:
            return item["corp_code"]
    return items[0]["corp_code"]


def _to_num(val) -> float:
    """문자열 금액 → float 변환"""
    if val is None or val == "":
        return 0.0
    return float(str(val).replace(",", "").replace(" ", ""))


def get_financial_statements(corp_code: str,
                              bsns_year: str,
                              reprt_code: str = "11011",
                              fs_div: str = "CFS") -> pd.DataFrame:
    """
    재무제표 전체 수집
    reprt_code: 11011=사업보고서, 11012=반기
    fs_div: CFS=연결, OFS=별도
    """
    data = _get("fnlttSinglAcntAll.json", {
        "corp_code"  : corp_code,
        "bsns_year"  : bsns_year,
        "reprt_code" : reprt_code,
        "fs_div"     : fs_div,
    })
    items = data.get("list", [])
    if not items:
        if fs_div == "CFS":
            return get_financial_statements(corp_code, bsns_year, reprt_code, "OFS")
        return pd.DataFrame()
    df = pd.DataFrame(items)
    for col in ["thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount"]:
        if col in df.columns:
            df[col] = df[col].apply(_to_num)
    return df


def find_account(df: pd.DataFrame, keywords: list) -> float:
    """키워드로 계정 검색 → 당기 금액 반환"""
    for kw in keywords:
        matched = df[df["account_nm"].str.contains(kw, na=False)]
        if not matched.empty:
            return float(matched.iloc[0]["thstrm_amount"])
    return 0.0


def get_shares_outstanding(corp_code: str,
                            bsns_year: str,
                            reprt_code: str = "11011") -> dict:
    """발행주식수 수집"""
    data = _get("stockTotqySttus.json", {
        "corp_code"  : corp_code,
        "bsns_year"  : bsns_year,
        "reprt_code" : reprt_code,
    })
    items = data.get("list", [])
    if not items:
        return {"total": 0, "common": 0}
    total = sum(int(str(r.get("stock_co", 0)).replace(",","")) for r in items)
    return {"total": total}


def collect_ibd(df_bs: pd.DataFrame) -> dict:
    """
    IBD (이자부부채) 수집
    포함: 단기차입금, 유동성장기부채, 장기차입금, 사채, 금융리스부채
    """
    items = {
        "단기차입금"    : find_account(df_bs, ["단기차입금", "단기차입"]),
        "유동성장기부채" : find_account(df_bs, ["유동성장기", "유동성장기부채"]),
        "장기차입금"    : find_account(df_bs, ["장기차입금", "장기차입"]),
        "사채"         : find_account(df_bs, ["사채"]),
        "금융리스부채"  : find_account(df_bs, ["리스부채", "금융리스"]),
    }
    uncertain = []
    for kw in ["상환전환우선주", "RCPS", "전환우선주", "상환우선주"]:
        matched = df_bs[df_bs["account_nm"].str.contains(kw, na=False)]
        if not matched.empty:
            uncertain.append({
                "account": kw,
                "amount" : float(matched.iloc[0]["thstrm_amount"]),
                "flag"   : "RCPS 감지 — 자본/부채 처리 사용자 확인 필요"
            })
    return {
        "ibd_total" : sum(items.values()),
        "detail"    : items,
        "uncertain" : uncertain,
    }


def collect_noa(df_bs: pd.DataFrame) -> dict:
    """NOA (순영업자산) 수집"""
    current_assets   = find_account(df_bs, ["유동자산"])
    cash             = find_account(df_bs, ["현금및현금성자산", "현금"])
    short_fin_assets = find_account(df_bs, ["단기금융자산", "단기투자자산"])
    current_liab     = find_account(df_bs, ["유동부채"])
    st_borrowings    = find_account(df_bs, ["단기차입금"])
    current_ltd      = find_account(df_bs, ["유동성장기"])
    operating_assets = current_assets - cash - short_fin_assets
    operating_liab   = current_liab - st_borrowings - current_ltd
    return {
        "noa"             : operating_assets - operating_liab,
        "operating_assets": operating_assets,
        "operating_liab"  : operating_liab,
    }


def collect_ltm_ebit(corp_code: str, eval_date: str, bsns_year: str) -> dict:
    """LTM EBIT 계산 (최근 12개월 영업이익)"""
    df_annual   = get_financial_statements(corp_code, bsns_year, "11011")
    ebit_annual = find_account(df_annual, ["영업이익", "영업손익"])
    eval_dt = datetime.strptime(eval_date, "%Y-%m-%d")
    if eval_dt.month == 12:
        return {"ltm_ebit": ebit_annual, "method": "연간 사업보고서 직접 사용"}
    try:
        df_h1_curr   = get_financial_statements(corp_code, bsns_year, "11012")
        ebit_h1_curr = find_account(df_h1_curr, ["영업이익", "영업손익"])
    except:
        ebit_h1_curr = 0.0
    prev_year = str(int(bsns_year) - 1)
    try:
        df_h1_prev   = get_financial_statements(corp_code, prev_year, "11012")
        ebit_h1_prev = find_account(df_h1_prev, ["영업이익", "영업손익"])
    except:
        ebit_h1_prev = 0.0
    ltm_ebit = ebit_annual + ebit_h1_curr - ebit_h1_prev
    return {"ltm_ebit": ltm_ebit, "method": "연간 + 상반기 - 전년 상반기"}


def get_tax_rate(ebit: float) -> dict:
    """한국 법인세 한계세율 (지방세 포함) — Python 확정 로직"""
    ebit_bil = ebit / 1e8
    if ebit_bil <= 2:
        return {"tc": 0.099, "bracket": "2억 이하"}
    elif ebit_bil <= 200:
        return {"tc": 0.209, "bracket": "2억~200억"}
    elif ebit_bil <= 3000:
        return {"tc": 0.231, "bracket": "200억~3000억"}
    else:
        return {"tc": 0.264, "bracket": "3000억 초과"}


def collect_fcff_inputs(df_bs_curr, df_bs_prev, df_cf, df_is) -> dict:
    """FCFF 계산 재료 수집 (D&A, CAPEX, ΔNWC)"""
    da = find_account(df_cf, ["감가상각비", "감가상각", "상각비"])
    if da == 0.0:
        da = find_account(df_is, ["감가상각비"])
    capex = (abs(find_account(df_cf, ["유형자산의 취득", "유형자산취득"])) +
             abs(find_account(df_cf, ["무형자산의 취득", "무형자산취득"])))
    def _nwc(df):
        return ((find_account(df, ["유동자산"]) - find_account(df, ["현금및현금성자산"])) -
                (find_account(df, ["유동부채"]) - find_account(df, ["단기차입금"])))
    delta_nwc = _nwc(df_bs_curr) - _nwc(df_bs_prev)
    return {"da": da, "capex": capex, "delta_nwc": delta_nwc}


def calc_fcff(ebit, tc, da, capex, delta_nwc) -> dict:
    """FCFF 계산 — Python 확정 로직 (LLM 절대 사용 금지)"""
    nopat = ebit * (1 - tc)
    fcff  = nopat + da - capex - delta_nwc
    return {"fcff": fcff, "nopat": nopat, "ebit": ebit,
            "tc": tc, "da": da, "capex": capex, "delta_nwc": delta_nwc}


def collect_multiples_inputs(df_bs, df_is, df_cf, ebit, da, mktcap, ibd) -> dict:
    """멀티플 지표 수집"""
    ebitda       = ebit + da
    cash         = find_account(df_bs, ["현금및현금성자산", "현금"])
    ev           = mktcap + ibd - cash
    net_income   = find_account(df_is, ["당기순이익"])
    total_equity = find_account(df_bs, ["자본총계"])
    revenue      = find_account(df_is, ["매출액", "매출"])
    def safe_div(a, b): return round(a/b, 2) if b and b != 0 else None
    return {
        "ebitda": ebitda, "ev": ev, "cash": cash,
        "mktcap": mktcap, "ibd": ibd,
        "net_income": net_income, "total_equity": total_equity,
        "revenue": revenue,
        "multiples": {
            "ev_ebitda" : safe_div(ev, ebitda),
            "ev_revenue": safe_div(ev, revenue),
            "per"       : safe_div(mktcap, net_income),
            "pbr"       : safe_div(mktcap, total_equity),
            "psr"       : safe_div(mktcap, revenue),
        }
    }


def collect_all(company_name: str, eval_date: str,
                stock_price: float, shares: int) -> dict:
    """VEDA 전체 데이터 수집 통합 함수"""
    print(f"\n{'='*60}\nVEDA 수집 시작: {company_name} | {eval_date}\n{'='*60}")
    bsns_year = eval_date[:4]
    prev_year = str(int(bsns_year) - 1)
    corp_code = get_corp_code(company_name)
    mktcap    = stock_price * shares
    time.sleep(0.3)
    df_bs_curr = get_financial_statements(corp_code, bsns_year, "11011")
    time.sleep(0.3)
    df_bs_prev = get_financial_statements(corp_code, prev_year, "11011")
    time.sleep(0.3)
    df_is      = get_financial_statements(corp_code, bsns_year, "11011")
    df_cf      = df_is.copy()
    ibd_data   = collect_ibd(df_bs_curr)
    noa_data   = collect_noa(df_bs_curr)
    ebit_data  = collect_ltm_ebit(corp_code, eval_date, bsns_year)
    tax_data   = get_tax_rate(ebit_data["ltm_ebit"])
    fcff_in    = collect_fcff_inputs(df_bs_curr, df_bs_prev, df_cf, df_is)
    fcff_res   = calc_fcff(ebit_data["ltm_ebit"], tax_data["tc"],
                           fcff_in["da"], fcff_in["capex"], fcff_in["delta_nwc"])
    mult_data  = collect_multiples_inputs(df_bs_curr, df_is, df_cf,
                                          ebit_data["ltm_ebit"], fcff_in["da"],
                                          mktcap, ibd_data["ibd_total"])
    print(f"수집 완료 | 시총={mktcap/1e8:.0f}억 | IBD={ibd_data['ibd_total']/1e8:.0f}억 |"
          f" LTM EBIT={ebit_data['ltm_ebit']/1e8:.0f}억 | FCFF={fcff_res['fcff']/1e8:.0f}억")
    return {
        "meta"       : {"company_name": company_name, "corp_code": corp_code,
                        "eval_date": eval_date, "bsns_year": bsns_year},
        "mktcap"     : mktcap,
        "shares"     : shares,
        "stock_price": stock_price,
        "ibd"        : ibd_data,
        "noa"        : noa_data,
        "ebit"       : ebit_data,
        "tax"        : tax_data,
        "fcff_inputs": fcff_in,
        "fcff"       : fcff_res,
        "multiples"  : mult_data,
    }
