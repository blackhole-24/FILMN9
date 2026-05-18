"""
processors/financial_parser.py
────────────────────────────────
jsonl_loader 가 병합한 마크다운 표 텍스트 → pandas DataFrame 변환.

제공 함수 (UI 컴포넌트별)
──────────────────────────
[컴포넌트 ②] get_financial_highlight(stock_code)
    → 매출액·영업이익·당기순이익 3개년 + YoY%  (재무 하이라이트 카드용)

[컴포넌트 ③] get_financial_detail(stock_code)
    → 포괄손익·재무상태표·현금흐름표 × 연결·별도  (상세 탭용)

내부 유틸
─────────
parse_markdown_to_df(merged_text)   마크다운 표 → DataFrame (범용)
clean_number(val)                   "2,003,730" / "(87,525)" → 숫자
clean_label(val)                    "[유  동  자  산]" → "유동자산"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.collectors.jsonl_loader import get_section

# ─────────────────────────────────────────────────────────────────────────────
# 1) 셀 값 정제 유틸
# ─────────────────────────────────────────────────────────────────────────────

_BRACKET_RE = re.compile(r"[\[\]]")
_MULTI_SP   = re.compile(r"\s{2,}")


def clean_label(val: str) -> str:
    """
    "[유  동  자  산]" → "유동자산"
    공백 정규화 + 대괄호 제거
    """
    val = _BRACKET_RE.sub("", val)
    val = _MULTI_SP.sub(" ", val)
    return val.strip()


def clean_number(val: str) -> float | None:
    """
    "2,003,730"  →  2003730.0
    "(87,525)"   →  -87525.0   (괄호 = 음수)
    "-"          →  None
    ""           →  None
    """
    val = val.strip()
    if not val or val in ("-", "–", "—", "△"):
        return None
    negative = val.startswith("(") and val.endswith(")")
    val = val.replace("(", "").replace(")", "").replace(",", "").strip()
    try:
        num = float(val)
        return -num if negative else num
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 2) 범용 마크다운 표 파서
# ─────────────────────────────────────────────────────────────────────────────

def _split_md_row(line: str) -> list[str]:
    """'| a | b | c |' → ['a', 'b', 'c']"""
    parts = line.split("|")
    # 앞뒤 빈 파트 제거 (| 로 시작/끝나는 경우)
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def parse_markdown_to_df(
    merged_text: str,
    number_cols: list[int] | None = None,
) -> pd.DataFrame:
    """
    병합된 마크다운 표 텍스트 → DataFrame.

    Parameters
    ----------
    merged_text  : merge_table_chunks() 결과의 merged_text
    number_cols  : 숫자로 변환할 컬럼 인덱스 (None이면 자동 감지)

    Returns
    -------
    pd.DataFrame  (첫 번째 | ... | 행을 컬럼으로 사용)
    """
    lines = [l.strip() for l in merged_text.splitlines() if l.strip()]
    md_lines = [l for l in lines if l.startswith("|")]

    if not md_lines:
        return pd.DataFrame()

    # 첫 행 = 헤더
    header_row = _split_md_row(md_lines[0])

    data_rows: list[list[str]] = []
    for line in md_lines[1:]:
        # 구분선(| --- |) 스킵
        if re.match(r"^\|\s*[-:]+", line):
            continue
        cells = _split_md_row(line)
        # 헤더와 동일한 행 스킵 (중복 헤더)
        if cells == header_row:
            continue
        # 컬럼 수가 맞지 않으면 패딩 또는 자르기
        if len(cells) < len(header_row):
            cells += [""] * (len(header_row) - len(cells))
        else:
            cells = cells[: len(header_row)]
        data_rows.append(cells)

    df = pd.DataFrame(data_rows, columns=header_row)

    # 숫자 컬럼 변환 (자동: 2번째 컬럼 이후)
    if number_cols is None:
        number_cols = list(range(1, len(header_row)))

    for idx in number_cols:
        if idx < len(df.columns):
            col = df.columns[idx]
            df[col] = df[col].apply(clean_number)

    # 첫 번째 컬럼(구분) 라벨 정제
    if len(df.columns) > 0:
        df[df.columns[0]] = df[df.columns[0]].apply(clean_label)

    return df.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# 3) 요약재무정보 파서 — 두 섹션 분리
#    (재무상태표 상단 + 포괄손익 하단이 한 표에 혼재)
# ─────────────────────────────────────────────────────────────────────────────

def _split_요약재무정보(merged_text: str) -> tuple[list[str], list[str]]:
    """
    요약재무정보 merged_text 를 두 섹션으로 분리.

    반환
    ----
    (balance_lines, income_lines)
    balance : 재무상태표 마크다운 행
    income  : 포괄손익 마크다운 행
    """
    lines = [l.strip() for l in merged_text.splitlines() if l.strip()]
    md_lines = [l for l in lines if l.startswith("|")]

    # 헤더 행 감지: 날짜 패턴을 포함하면 포괄손익 섹션 헤더
    # 예) |  | 2025년 1월 1일~2025년 12월 31일 | ...
    # 재무상태표 헤더: | 2025년 말 | 2024년 말 | ...

    balance_lines: list[str] = []
    income_lines: list[str] = []
    section = "balance"
    header_row = None

    for line in md_lines:
        if re.match(r"^\|\s*[-:]+", line):   # 구분선
            if section == "balance":
                balance_lines.append(line)
            else:
                income_lines.append(line)
            continue

        cells = _split_md_row(line)

        # 포괄손익 섹션 헤더 감지 ("1월 1일" 패턴)
        row_text = " ".join(cells)
        if "1월 1일" in row_text and section == "balance":
            section = "income"
            income_lines.append(line)
            continue

        if section == "balance":
            balance_lines.append(line)
        else:
            income_lines.append(line)

    return balance_lines, income_lines


def parse_요약재무정보(
    stock_code: str = "090430",
    kind: str = "연결",          # "연결" | "별도"
) -> dict[str, pd.DataFrame]:
    """
    요약재무정보 → {"재무상태표": df, "포괄손익": df}

    반환 DataFrame 구조
    ───────────────────
    재무상태표: index=구분, columns=[2025년 말, 2024년 말, 2023년 말]
    포괄손익  : index=구분, columns=[2025 회계연도, 2024 회계연도, 2023 회계연도]
    단위: 백만원 (요약재무정보는 원래 백만 단위)
    """
    tables = get_section(stock_code, "요약재무정보")

    # 연결 = 1-1, 별도 = 1-2
    prefix = "1-1" if kind == "연결" else "1-2"
    target = next((t for t in tables if t["title"].startswith(prefix)), None)
    if target is None:
        raise ValueError(f"요약재무정보에서 '{prefix}' 테이블을 찾을 수 없음")

    balance_lines, income_lines = _split_요약재무정보(target["merged_text"])

    result = {}

    # ── 재무상태표 ──
    if balance_lines:
        df_bs = parse_markdown_to_df("\n".join(balance_lines))
        # 컬럼명 단순화: "2025년 말" → "2025"
        col_map = {}
        for c in df_bs.columns[1:]:
            m = re.search(r"(\d{4})년", c)
            if m:
                col_map[c] = m.group(1)
        df_bs = df_bs.rename(columns=col_map)
        df_bs = df_bs.rename(columns={df_bs.columns[0]: "구분"})
        result["재무상태표"] = df_bs

    # ── 포괄손익 ──
    if income_lines:
        df_pl = parse_markdown_to_df("\n".join(income_lines))
        # 컬럼명: "2025년 1월 1일~2025년 12월 31일" → "2025"
        col_map = {}
        for c in df_pl.columns[1:]:
            m = re.search(r"(\d{4})년 1월 1일", c)
            if m:
                col_map[c] = m.group(1)
        df_pl = df_pl.rename(columns=col_map)
        df_pl = df_pl.rename(columns={df_pl.columns[0]: "구분"})
        result["포괄손익"] = df_pl

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4) 재무 하이라이트용 — 매출·영업이익·순이익 추출
# ─────────────────────────────────────────────────────────────────────────────

# 찾을 키워드 (부분 일치)
_HIGHLIGHT_KEYS = {
    "매출액"    : ["매출액"],
    "영업이익"  : ["영업이익"],
    "당기순이익": ["연결 당기순이익", "당기순이익"],
}


def get_financial_highlight(stock_code: str = "090430") -> dict[str, pd.DataFrame]:
    """
    컴포넌트 ② 재무 하이라이트 카드용.

    Returns
    -------
    {
      "연결": DataFrame(구분, 2025, 2024, 2023, yoy_pct),
      "별도": DataFrame(구분, 2025, 2024, 2023, yoy_pct),
    }
    단위: 백만원
    """
    result = {}
    for kind in ["연결", "별도"]:
        try:
            data = parse_요약재무정보(stock_code, kind)
        except (ValueError, KeyError):
            continue

        pl = data.get("포괄손익", pd.DataFrame())
        if pl.empty:
            continue

        year_cols = [c for c in pl.columns if re.match(r"\d{4}", str(c))]
        rows = []

        for label, keywords in _HIGHLIGHT_KEYS.items():
            # 키워드 중 하나가 구분 컬럼에 포함된 행 찾기
            matched = None
            for kw in keywords:
                mask = pl["구분"].str.contains(kw, na=False)
                if mask.any():
                    matched = pl[mask].iloc[0]
                    break

            if matched is None:
                continue

            row = {"구분": label}
            for y in year_cols:
                row[y] = matched.get(y)

            # YoY% (최신연도 vs 전년도)
            if len(year_cols) >= 2:
                latest = row.get(year_cols[0])
                prev   = row.get(year_cols[1])
                if latest is not None and prev and prev != 0:
                    row["yoy_pct"] = round((latest - prev) / abs(prev) * 100, 2)
                else:
                    row["yoy_pct"] = None

            rows.append(row)

        result[kind] = pd.DataFrame(rows)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 5) 재무정보 상세 탭용 — 연결재무제표 전체
# ─────────────────────────────────────────────────────────────────────────────

# 사업보고서 > III. 재무에 관한 사항 > 2. 연결재무제표
# 단일 셀 행이 섹션 구분자 역할을 함
_FS_SECTION_MARKERS: dict[str, str] = {
    "재무상태표"    : "재무상태표(연결)",
    "포괄손익계산서" : "포괄손익계산서(연결)",
    "현금흐름표"    : "현금흐름표(연결)",
    "자본변동표"    : "자본변동표(연결)",
}


def _build_period_year_map(lines: list[str]) -> dict[int, int]:
    """
    단일 셀 날짜 참조 행에서 기수→연도 매핑 추출.

    예) "| 제 20 기          2025.12.31 현재 |"
        → {20: 2025}
    """
    mapping: dict[int, int] = {}
    for line in lines:
        cells = _split_md_row(line)
        non_empty = [c for c in cells if c.strip()]
        if len(non_empty) != 1:
            continue
        cell = non_empty[0]
        m_p = re.search(r"제\s*(\d+)\s*기", cell)
        m_y = re.search(r"(\d{4})\.\d{2}\.\d{2}", cell)
        if m_p and m_y:
            mapping[int(m_p.group(1))] = int(m_y.group(1))
    return mapping


def _parse_detail_section(lines: list[str], unit_divisor: float = 1.0) -> pd.DataFrame:
    """
    연결재무제표 한 섹션의 마크다운 행 리스트 → DataFrame.

    Parameters
    ----------
    lines        : "| ... |" 형태의 행 리스트 (이미 필터된 것)
    unit_divisor : 원→백만원 변환 시 1_000_000

    Returns
    -------
    pd.DataFrame  컬럼=[구분, 2025, 2024, 2023, ...]
    """
    if not lines:
        return pd.DataFrame()

    # 기수→연도 매핑: "제 20 기  2025.12.31 현재" 단일 셀 행에서 추출
    period_to_year = _build_period_year_map(lines)

    # 헤더 찾기: "제 N 기" 패턴이 2개 이상 있는 다중 셀 행
    # (단일 셀 "제 20 기   2025.12.31 현재" 행은 제외)
    header_idx = 0
    header_cells = None
    for i, line in enumerate(lines):
        cells = _split_md_row(line)
        matching = [c for c in cells if re.search(r"제\s*\d+\s*기", c)]
        if len(matching) >= 2 and len(cells) >= 3:
            header_cells = cells
            header_idx = i
            break

    if header_cells is None:
        header_cells = _split_md_row(lines[0])
        header_idx = 0

    # 컬럼명: "제 N 기" → 연도 문자열
    # 1순위: period_to_year 매핑 (단일 셀 날짜 행에서 추출)
    # 2순위: 최대 기수 = 현재연도 방식 (fallback)
    from datetime import date as _date
    current_year = _date.today().year
    period_nums_in_header = []
    for c in header_cells:
        m = re.search(r"제\s*(\d+)\s*기", c)
        if m:
            period_nums_in_header.append(int(m.group(1)))
    max_period = max(period_nums_in_header) if period_nums_in_header else 0

    cleaned_cols = []
    for c in header_cells:
        m = re.search(r"제\s*(\d+)\s*기", c)
        if m:
            period_num = int(m.group(1))
            if period_num in period_to_year:
                year = period_to_year[period_num]
            else:
                # fallback: 최대기수→당해연도 차이로 계산
                if max_period and max_period in period_to_year:
                    year = period_to_year[max_period] - (max_period - period_num)
                else:
                    year = current_year - (max_period - period_num)
            cleaned_cols.append(str(year))
        else:
            cleaned_cols.append(c.strip() if c.strip() else "구분")

    data_rows: list[list] = []
    for line in lines[header_idx + 1:]:
        if re.match(r"^\|\s*[-:]+", line):
            continue
        cells = _split_md_row(line)
        if cells == header_cells:
            continue
        non_empty = [c for c in cells if c]
        if len(non_empty) == 1:
            continue  # 섹션 제목 행 스킵
        if len(cells) < len(cleaned_cols):
            cells += [""] * (len(cleaned_cols) - len(cells))
        else:
            cells = cells[: len(cleaned_cols)]
        data_rows.append(cells)

    if not data_rows:
        return pd.DataFrame()

    df = pd.DataFrame(data_rows, columns=cleaned_cols)
    first_col = df.columns[0]
    df[first_col] = df[first_col].apply(clean_label)

    year_cols = [c for c in df.columns if re.match(r"\d{4}", c)]
    for c in year_cols:
        df[c] = df[c].apply(clean_number)
        if unit_divisor != 1.0:
            df[c] = df[c].apply(
                lambda v: round(v / unit_divisor) if (v is not None and not pd.isna(v)) else None
            )

    return df.reset_index(drop=True)


def _split_연결재무제표(merged_text: str) -> dict[str, list[str]]:
    """
    연결재무제표 통합 마크다운 텍스트를 개별 재무제표별 행 리스트로 분리.

    단일 셀 행이 섹션 구분자:
      "연결 재무상태표"     → 재무상태표(연결) 섹션 시작
      "연결 포괄손익계산서"  → 포괄손익계산서(연결) 섹션 시작
      "연결 현금흐름표"     → 현금흐름표(연결) 섹션 시작
      "연결 자본변동표"     → 자본변동표(연결) 섹션 시작

    Returns
    -------
    {"재무상태표(연결)": [lines], "포괄손익계산서(연결)": [lines], ...}
    """
    md_lines = [l.strip() for l in merged_text.splitlines()
                if l.strip() and l.strip().startswith("|")]

    sections: dict[str, list[str]] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in md_lines:
        cells = _split_md_row(line)
        non_empty = [c for c in cells if c.strip()]

        if len(non_empty) == 1:
            cell_text = non_empty[0]
            matched_key = None
            for marker, key in _FS_SECTION_MARKERS.items():
                if marker in cell_text:
                    matched_key = key
                    break
            if matched_key:
                if current_key and current_lines:
                    sections[current_key] = current_lines
                current_key = matched_key
                current_lines = []
                continue   # 섹션 제목 행은 데이터에 포함하지 않음

        if current_key:
            current_lines.append(line)

    if current_key and current_lines:
        sections[current_key] = current_lines

    return sections


def get_financial_detail(stock_code: str = "090430") -> dict[str, pd.DataFrame]:
    """
    컴포넌트 ③ 재무정보 상세 탭용.

    출처 (JSONL 직접 파싱):
      사업보고서 > III. 재무에 관한 사항 > 2. 연결재무제표
      app_config.SECTION["연결재무제표"] 섹션 경로 사용

    Returns
    -------
    {
      "재무상태표(연결)"     : DataFrame,  단위=백만원
      "포괄손익계산서(연결)" : DataFrame,  단위=백만원
      "현금흐름표(연결)"     : DataFrame,  단위=백만원  (있을 경우)
    }

    Notes
    -----
    - JSONL 연결재무제표 원本 단위: 원(₩)
    - 반환 단위: 백만원  (÷ 1,000,000)
    - 컬럼명: "2025", "2024", "2023" (제N기 → 연도 자동 변환)
    """
    from src.collectors.jsonl_loader import get_section as _get_sec

    result: dict[str, pd.DataFrame] = {}
    try:
        tables = _get_sec(stock_code, "연결재무제표")
    except (ValueError, KeyError, FileNotFoundError):
        return result

    if not tables:
        return result

    # 연결재무제표 섹션은 모든 청크가 하나의 대형 테이블로 병합됨
    # (title=""인 단일 그룹)  →  내부 섹션별로 분리
    all_text_lines: list[str] = []
    for t in tables:
        all_text_lines.extend(
            l.strip() for l in t["merged_text"].splitlines()
            if l.strip() and l.strip().startswith("|")
        )

    full_merged = "\n".join(all_text_lines)
    sections = _split_연결재무제표(full_merged)

    for key, lines in sections.items():
        df = _parse_detail_section(lines, unit_divisor=1_000_000)
        if not df.empty:
            result[key] = df

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 6) 임원현황 파서
# ─────────────────────────────────────────────────────────────────────────────

def get_executive_table(stock_code: str = "090430") -> pd.DataFrame:
    """
    컴포넌트 ⑦ 경영인 테이블용.

    Returns
    -------
    DataFrame(성명, 직위, 담당업무, 주요경력, 재직기간)

    JSONL 실제 컬럼 구조 (위치 기반):
      0:성명 / 1:직위 / 2:담당업무 / 3:주요경력 /
      4:소유주식수(의결권) / 5:소유주식수(무의결권) /
      6:최대주주와의관계 / 7:재직기간 / 8~:기타
    """
    tables = get_section(stock_code, "임원현황")

    # header_hint 있는 테이블 (실제 임원 데이터)
    target = next((t for t in tables if t["header_hint"]), None)
    if target is None:
        return pd.DataFrame()

    # 위치 기반 컬럼명 (JSONL 청크 실제 순서 기준)
    ACTUAL_COLS = [
        "성명", "직위", "담당업무", "주요경력",
        "소유주식수_의결권", "소유주식수_무의결권",
        "최대주주와의관계", "재직기간", "임기만료일",
        "기타1", "기타2", "기타3",
    ]

    lines = [l.strip() for l in target["merged_text"].splitlines() if l.strip()]
    md_lines = [l for l in lines if l.startswith("|")]

    rows = []
    for line in md_lines:
        # 구분선 스킵
        if re.match(r"^\|\s*[-:]+", line):
            continue
        cells = _split_md_row(line)
        # 서브헤더 행 스킵 ("의결권있는 주식" 등)
        if cells and "의결권" in cells[0]:
            continue
        rows.append(cells)

    if not rows:
        return pd.DataFrame()

    n_cols = len(ACTUAL_COLS)
    clean_rows = []
    for cells in rows:
        if len(cells) < n_cols:
            cells += [""] * (n_cols - len(cells))
        clean_rows.append(cells[:n_cols])

    df = pd.DataFrame(clean_rows, columns=ACTUAL_COLS)

    # 빈 성명 행 제거
    df = df[df["성명"].str.strip().ne("")]
    df = df[df["성명"].str.strip().ne("-")]

    # UI에 필요한 컬럼만 반환
    keep = ["성명", "직위", "담당업무", "재직기간", "최대주주와의관계", "소유주식수_의결권"]
    df = df[keep].copy()

    # 주요경력이 담당업무 자리로 들어온 경우 정리
    # (담당업무 셀이 "- ..." 으로 시작하면 경력 텍스트임 → 별도 처리)
    df["담당업무"] = df["담당업무"].apply(
        lambda v: v if not str(v).startswith("-") else ""
    )

    df = df.reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 동작 확인
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    stock = "090430"
    print("=" * 60)
    print("FILMN9 financial_parser 검증 — 아모레퍼시픽(090430)")
    print("=" * 60)

    # ① 재무 하이라이트
    print("\n[컴포넌트 ②] 재무 하이라이트")
    highlight = get_financial_highlight(stock)
    for kind, df in highlight.items():
        print(f"\n  [{kind}]")
        print(df.to_string(index=False))

    # ② 재무 상세
    print("\n\n[컴포넌트 ③] 재무 상세 — 연결재무제표 앞 15행")
    detail = get_financial_detail(stock)
    for label, df in detail.items():
        yr_cols = [c for c in df.columns if str(c).isdigit()]
        print(f"\n  [{label}]  shape={df.shape}  단위=백만원")
        print(df.head(15).to_string(index=False))

    # ③ 임원현황
    print("\n\n[컴포넌트 ⑦] 경영인 테이블")
    exec_df = get_executive_table(stock)
    print(f"  임원 수: {len(exec_df)}명")
    if not exec_df.empty:
        print(exec_df[["성명", "직위", "담당업무", "재직기간"]].head(8).to_string(index=False))

    print("\n" + "=" * 60)
    print("✅ financial_parser 검증 완료")



