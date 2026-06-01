"""범용 추출 함수 (v4.8).

브리핑 생성용 사업보고서 텍스트 추출. 노트북에서 분리한 모듈이라
모듈 단독 실행 가능하도록 import 보강함.
"""
from __future__ import annotations
import re
import json
from typing import Optional


# ── 상수 ────────────────────────────────────────────────────────────────────

REVENUE_KEYWORDS = [
    '매출액', '매출',
    '영업수익', '보험영업수익', '영업수입',
    '이자수익', '수수료수익', '수탁수수료',
    '수입보험료',
    # 금융업/지주사 특화 (v2.1)
    '신용판매수익', '금융수익', '운용수익',
    '총부문수익', '보험료수익',
]

REIT_REVENUE_KEYWORDS = [
    '임대수익', '임대료', '운용수익', '배당수익', '분배금', '부동산임대', '이자수익',
]

SKIP_ROW_KEYWORDS = ['합계', '합 계', '소계', '소 계', '총계', '총 계',
                     '---', '사업부문', '품목', '제품군']

CHANNEL_SUB_KEYWORDS = {'수출', '내수', '국내', '해외', '직수출', '간접수출', '수 출', '내 수'}

REVENUE_SECTION_TARGETS = [
    'II. 사업의 내용 > 1. 사업의 개요',            # KT형 복합 대기업: 사업부문별 영업수익 테이블 우선
    'II. 사업의 내용 > 2. 주요 제품 및 서비스',
    'II. 사업의 내용 > 2. 영업의 현황',
    'II. 사업의 내용 > 4. 매출 및 수주현황',
    'II. 사업의 내용 > 4. 매출 및 수주상황',
    'II. 사업의 내용 > 4. 영업 개황 및 사업 부문의 구분',
]

_SPAC_BIZ_TARGETS = ['II. 사업의 내용 > 1. 사업의 개요']
_REIT_BIZ_TARGETS = ['II. 사업의 내용 > 1. 사업의 개요', '위험관리 및 파생거래']
_STD_BIZ_TARGETS  = [
    'II. 사업의 내용 > 1. 사업의 개요',
    'II. 사업의 내용 > 2. 주요 제품 및 서비스',
    'II. 사업의 내용 > 7. 기타 참고사항',
]
_FIN_BIZ_TARGETS  = [
    'II. 사업의 내용 > 1. 사업의 개요',
    'II. 사업의 내용 > 2. 영업의 현황',
]

# ── 기업 유형 감지 ────────────────────────────────────────────────────────────

def detect_corp_type(corp_name: str, wics: str = '') -> str:
    if '스팩' in corp_name or 'SPAC' in corp_name.upper():
        return 'spac'
    if '리츠' in corp_name or '부동산' in wics:
        return 'reit'
    if '보험' in wics:
        return 'insurance'
    if ('캐피탈' in corp_name or '캐피탈' in wics
            or '여신' in wics or '소비자금융' in wics):
        return 'finance'
    return 'general'

# ── 섹션 매칭 헬퍼 ───────────────────────────────────────────────────────────

def _matches_section(section_path: str, target: str) -> bool:
    if section_path == target:
        return True
    if section_path.endswith(target):
        return True
    stripped = re.sub(r'\([^)]+\)', '', section_path).strip()
    stripped = re.sub(r'\s+', ' ', stripped)
    return stripped == target or stripped.endswith(target)

def _get_sector_label(section_path: str):
    m = re.search(r'\(([^)]+)\)', section_path)
    return m.group(1) if m else None

def _normalize(text: str) -> str:
    return re.sub(r'\s+', '', text)

def _find_unit_by_idx(chunks: list, idx: int) -> str:
    for c in reversed(chunks[max(0, idx - 5):idx]):
        if c.get('kind') != 'text':
            continue
        m = re.search(r'단위\s*[:：]\s*([^\n）)\(]{1,40})', c.get('text', ''))
        if m:
            return m.group(1).strip()
    return ''

# ── 테이블 파싱 헬퍼 ─────────────────────────────────────────────────────────

def _parse_table_rows(text: str) -> list:
    rows = []
    for line in text.split('\n'):
        cells = [c.strip() for c in line.split('|')]
        cells = [c for c in cells if c]
        if cells:
            rows.append(cells)
    return rows

def _find_pct_col_idx(rows: list, text: str) -> int:
    if not rows:
        return -1
    def _count_pct_like(col):
        cnt = 0
        for r in rows[2:]:
            if col >= len(r): continue
            v = r[col].replace(',', '').strip().rstrip('%')
            try:
                f = float(v)
                if 0 < f <= 100: cnt += 1
            except: pass
        return cnt
    for row in rows[:3]:
        for i, cell in enumerate(row):
            if any(k in cell for k in ['비율', '구성비', '비중', '비 중']) or cell.strip() == '%':
                if _count_pct_like(i) >= 2:    return i
                elif _count_pct_like(i+1) >= 2: return i + 1
                # i·i+1 모두 유효 pct 없으면 다음 키워드 셀 계속 탐색 (NHN형 2행 헤더 대응)
    for row in rows:
        if any(('합계' in c or '합 계' in c) for c in row):
            for i, cell in enumerate(row):
                v = cell.replace(',', '').strip().rstrip('%')
                try:
                    if abs(float(v) - 100.0) < 1.0: return i
                except: pass
    # 셀에 '%' 기호가 직접 포함된 경우 (LG디스플레이형: 18.6%, 36.8% 등)
    if '%' in text:
        pct_votes: dict = {}
        for row in rows[1:]:
            for i, cell in enumerate(row):
                if '%' in cell and cell.strip() not in ('%', '비율(%)'):
                    v = cell.rstrip('%').replace(',', '').strip()
                    try:
                        f = float(v)
                        if 0 < f <= 100:
                            pct_votes[i] = pct_votes.get(i, 0) + 1
                    except: pass
        if pct_votes:
            best = max(pct_votes, key=pct_votes.get)
            if pct_votes[best] >= 2:
                return best
        # 마지막 컬럼 fallback
        col_len = len(rows[1]) if rows[1:] else 0
        cnt2 = 0
        for row in rows[1:]:
            if not row: continue
            v = row[-1].replace(',','').strip().rstrip('%')
            try:
                f = float(v)
                if 0 < f <= 100: cnt2 += 1
            except: pass
        if cnt2 >= 2 and col_len > 0: return col_len - 1
    return -1

def _find_name_col(rows: list, amt_col: int) -> int:
    best_col, best_score = 0, -1
    for col in range(min(amt_col, 5)):
        score = 0
        for row in rows[1:]:
            if col >= len(row): continue
            v = row[col].strip()
            if not v or '/' in v: continue
            if v in CHANNEL_SUB_KEYWORDS or v in ('합계', '합 계', '-', '구분', '항목'): continue
            try: float(v.replace(',', '')); continue  # 숫자는 segment명 아님
            except: pass
            score += 1
        if score > best_score:
            best_score, best_col = score, col
    return best_col

def _find_amount_col_idx(rows: list, pct_col: int) -> int:
    for offset in [1, 2]:
        candidate = pct_col - offset
        if candidate < 0: break
        for row in rows[1:]:
            if candidate < len(row):
                v = row[candidate].replace(',', '').strip().lstrip('(').rstrip(')')
                try:
                    if int(float(v)) > 100: return candidate
                except: pass
    return pct_col - 1 if pct_col > 0 else -1

def _parse_amount_table_segments(rows: list) -> list:
    # % 컬럼 없는 테이블에서 합계/소계 행 기반으로 세그먼트별 비율 산출
    # 루닛(합 계 행), 아이진(소 계 행) 등 처리
    if len(rows) < 3:
        return []
    ALL_CHANNEL = CHANNEL_SUB_KEYWORDS | {'합계', '합 계', '소계', '소 계'}
    TOTAL_KW    = {'합계', '합 계', '소계', '소 계'}

    # 채널 컬럼 탐지: 수출/내수/합계 등이 3번 이상 등장하는 컬럼
    channel_col = -1
    sample_len  = len(rows[1]) if len(rows) > 1 else 0
    for col in range(min(sample_len, 6)):
        if sum(1 for r in rows[1:] if col < len(r) and r[col].strip() in ALL_CHANNEL) >= 3:
            channel_col = col
            break
    if channel_col < 0:
        return []

    # 이름 컬럼: 계층형 테이블에서 대분류는 항상 가장 왼쪽 컬럼 → 최소 인덱스 우선
    name_col = 0
    for col in range(min(channel_col, 5)):
        if any(col < len(r) and r[col].strip()
               and r[col].strip() not in ('구분', '항목', '-', '---')
               and r[col].strip() not in CHANNEL_SUB_KEYWORDS
               for r in rows[1:]):
            name_col = col
            break

    # 금액 컬럼: channel_col 이후 마지막 유효 숫자 컬럼 (최신연도 기준)
    ncols   = max((len(r) for r in rows[1:]), default=0)
    amt_col = -1
    for col in range(ncols - 1, channel_col, -1):
        valid = 0
        for r in rows[1:]:
            if col >= len(r): continue
            v = r[col].replace(',', '').strip().lstrip('(').rstrip(')')
            if v in ('', '-'): continue
            try:
                if int(float(v)) > 100: valid += 1
            except: pass
        if valid >= 2:
            amt_col = col
            break
    if amt_col < 0:
        return []

    # 세그먼트 집계
    seg_dict    = {}
    seg_order   = []
    grand_total = 0
    last_major  = ''
    in_grand_total = False
    for row in rows[1:]:
        if not row or channel_col >= len(row): continue
        raw_name = row[name_col].strip() if name_col < len(row) else ''
        channel  = row[channel_col].strip()
        # 그랜드 합계 시작 감지: '합 계' 행 + 다음 컬럼이 채널 키워드 (수출/내수 등)
        if not in_grand_total and raw_name in ('합계', '합 계'):
            col_next = row[name_col + 1].strip() if name_col + 1 < len(row) else ''
            if col_next in CHANNEL_SUB_KEYWORDS:
                in_grand_total = True
        # last_major: 채널/합계 값은 무시하고 실제 분류명만 업데이트
        if raw_name and raw_name not in ALL_CHANNEL:
            last_major = raw_name
        if channel not in TOTAL_KW:
            continue
        if amt_col >= len(row): continue
        v = row[amt_col].replace(',', '').strip().lstrip('(').rstrip(')')
        if v in ('', '-'): continue
        try:
            amount = int(float(v))
            if amount <= 0: continue
        except: continue
        if in_grand_total:
            grand_total = max(grand_total, amount)
        else:
            is_total_row = (not last_major
                            or any(kw in last_major for kw in SKIP_ROW_KEYWORDS))
            if is_total_row:
                grand_total = max(grand_total, amount)
            else:
                if last_major in seg_dict:
                    seg_dict[last_major] += amount
                else:
                    seg_dict[last_major] = amount
                    seg_order.append(last_major)

    if not grand_total:
        grand_total = sum(seg_dict.values())
    if not grand_total:
        return []
    return [(n, str(seg_dict[n]), round(seg_dict[n] / grand_total * 100, 1))
            for n in seg_order if seg_dict[n] > 0]

def _text_pct_fallback(text: str) -> str:
    matches = re.findall(r'[^\n。.]{0,30}[\d]+\.?\d*%[^\n。.]{0,30}', text)
    if not matches: return ""
    seen, results = set(), []
    for m in matches:
        m = m.strip()
        if m not in seen:
            seen.add(m); results.append(f"  • {m}")
        if len(results) >= 5: break
    return "■ 수익 구성 (텍스트 언급)\n" + "\n".join(results) if results else ""

# ── 본문 텍스트 추출 ─────────────────────────────────────────────────────────

def auto_build_business_text(chunks, max_chars=2500, corp_type='general'):
    # 섹션별 최대 할당 글자수 (label+target 조합당)
    # 합계 = max_chars(2500): 1200+800+500=2500
    _SECTION_LIMITS = {
        '사업의 개요':        1200,
        '주요 제품 및 서비스': 800,
        '영업의 현황':        800,
        '기타 참고사항':      500,
    }
    _DEFAULT_LIMIT = 600

    def _section_limit(target: str) -> int:
        for k, v in _SECTION_LIMITS.items():
            if k in target:
                return v
        return _DEFAULT_LIMIT

    def _extract(targets):
        section_chars = {}   # (label, target) → 누적 글자수
        seen_texts    = set()  # 앞 100자로 중복 방지
        collected     = []

        for target in targets:
            limit = _section_limit(target)
            for c in chunks:
                if not (_matches_section(c.get('section_path_str') or '', target)
                        and c.get('kind') == 'text'
                        and len(c.get('text','')) >= 150):
                    continue
                label   = _get_sector_label(c.get('section_path_str') or '')
                text    = c['text'].strip()
                text_id = text[:100]
                if text_id in seen_texts:
                    continue
                key = (label, target)
                if section_chars.get(key, 0) >= limit:
                    continue
                section_chars[key] = section_chars.get(key, 0) + len(text)
                seen_texts.add(text_id)
                collected.append((label, text))

        if not collected: return ""
        multi  = len({l for l,_ in collected if l}) > 1
        result = ""
        for label, text in collected:
            header = (f"[{label}]" + chr(10)) if (multi and label) else ""
            block  = header + text
            result += block + chr(10) + chr(10)
        return result.strip()
    if corp_type == 'spac':
        return _extract(_SPAC_BIZ_TARGETS)
    elif corp_type == 'reit':
        return _extract(_REIT_BIZ_TARGETS)
    elif corp_type == 'insurance':
        # 보험사: 사업의 개요(수입보험료·투자수익률·ROA/ROE) 우선
        return _extract(_FIN_BIZ_TARGETS)
    elif corp_type == 'finance':
        # 캐피탈사: 영업의 현황 우선, 내용 부족하면 사업의 개요 포함
        fin = _extract(['II. 사업의 내용 > 2. 영업의 현황'])
        if len(fin) >= 500:
            return fin
        return _extract(_FIN_BIZ_TARGETS)
    else:
        std = _extract(_STD_BIZ_TARGETS)
        if len(std) >= 500: return std
        fin = _extract(_FIN_BIZ_TARGETS)
        return fin if len(fin) > len(std) else std

# ── 매출 구성 표 추출 ────────────────────────────────────────────────────────

def auto_extract_revenue_context(chunks, corp_type='general'):
    if corp_type == 'spac':
        return ''
    if corp_type == 'reit':
        use_keywords = REIT_REVENUE_KEYWORDS + REVENUE_KEYWORDS
        use_sections = ['II. 사업의 내용 > 1. 사업의 개요', '위험관리 및 파생거래']
    else:
        use_keywords = REVENUE_KEYWORDS
        use_sections = REVENUE_SECTION_TARGETS

    sector_chunks, sector_cands = {}, {}
    raw_table_chunks, raw_table_cands, sector_texts, unit_hints = {}, {}, {}, {}

    for target in use_sections:
        for idx, c in enumerate(chunks):
            if not _matches_section(c.get('section_path_str') or '', target): continue
            text      = c.get('text', '')
            text_norm = _normalize(text)
            label     = _get_sector_label(c.get('section_path_str') or '') or '전사'

            if c.get('kind') == 'table':
                has_rev = any(kw in text_norm for kw in use_keywords)
                has_pct = ('%' in text
                           or '비율' in text_norm
                           or '비중' in text_norm
                           or '구성비' in text_norm)
                has_composition = '구성비' in text_norm
                if has_rev or has_composition:
                    if '시장점유율' in text:  # 경쟁사 점유율 테이블 제외
                        continue
                    unit = _find_unit_by_idx(chunks, idx)
                    if label not in raw_table_chunks:
                        raw_table_chunks[label] = text
                        unit_hints[label] = unit
                    raw_table_cands.setdefault(label, [])
                    if text not in raw_table_cands[label]:
                        raw_table_cands[label].append(text)
                    if has_pct:
                        # sector_cands: 모든 후보 수집 (클리오형 빈 청크 → 다음 후보 시도)
                        sector_cands.setdefault(label, [])
                        if c not in sector_cands[label]:
                            sector_cands[label].append(c)
                        if label not in sector_chunks:
                            sector_chunks[label] = c
                            unit_hints.setdefault(label, unit)
            elif c.get('kind') == 'text' and label not in sector_texts:
                if any(kw in text_norm for kw in use_keywords) and len(text) >= 100:
                    sector_texts[label] = text

    if not sector_chunks and not raw_table_chunks and not sector_texts:
        return ""

    all_labels    = set(list(sector_chunks) + list(raw_table_chunks) + list(sector_texts))
    multi         = len(all_labels) > 1
    all_lines     = []
    parsed_labels = set()

    for label in list(sector_chunks.keys()):
        # Fix F: sector_cands의 모든 후보 순차 시도 (첫 후보가 빈 청크면 다음 후보)
        cands_to_try = sector_cands.get(label, [sector_chunks[label]])
        segments_out = None
        for chunk in cands_to_try:
            text    = chunk['text']
            rows    = _parse_table_rows(text)
            pct_col = _find_pct_col_idx(rows, text)
            if pct_col < 0: continue
            amt_col  = _find_amount_col_idx(rows, pct_col)
            name_col = _find_name_col(rows, amt_col)
            ch_col   = name_col + 1
            is_channel_table = any(
                ch_col < len(r) and r[ch_col].strip() in CHANNEL_SUB_KEYWORDS
                for r in rows[1:] if r
            )
            seg_dict  = {}   # name → [amt_str, pct_sum]
            seg_order = []
            last_name = ''
            # pre-scan: full row(col1=text) 수 카운트 → 1개면 동양생명형(단일 부모, sub-item 추출)
            _HDR_NORMS = {'금액','비율','구분','항목','비중','매출액','합계','소계','매출'}
            _full_row_cnt = 0
            for _r in rows[1:]:
                if not _r or name_col >= len(_r): continue
                _rn = _r[name_col].strip()
                _nx = _r[name_col + 1].strip() if name_col + 1 < len(_r) else ''
                _rn_norm = re.sub(r'\s+', '', _rn)
                if (_rn and not _rn.startswith('[') and not _rn.startswith('(')
                        and _rn_norm not in _HDR_NORMS
                        and not any(kw in _rn for kw in SKIP_ROW_KEYWORDS)
                        and _nx not in ('', '-', '---') and _nx not in CHANNEL_SUB_KEYWORDS):
                    try: float(_nx.replace(',', ''))
                    except: _full_row_cnt += 1
            is_sub_item_table = (not is_channel_table) and (_full_row_cnt == 1)
            for row in rows:
                if not row: continue
                name = row[name_col].strip() if name_col < len(row) else ''
                if is_channel_table:
                    if name:
                        last_name = name
                    else:
                        name = last_name
                else:
                    if name:
                        if not any(kw in name for kw in SKIP_ROW_KEYWORDS):
                            col_next = row[name_col + 1].strip() if name_col + 1 < len(row) else ''
                            # Fix D: 괄호형 음수 (33,238) → 숫자로 인식
                            try:
                                float(col_next.replace(',', '').lstrip('(').rstrip(')'))
                                col_next_numeric = True
                            except:
                                col_next_numeric = False
                            if not col_next_numeric and col_next not in CHANNEL_SUB_KEYWORDS:
                                if is_sub_item_table and col_next:
                                    name = col_next
                                    last_name = ''
                                else:
                                    # Fix A: pct 없는 행(제목행)은 last_name 갱신 안 함
                                    if pct_col < len(row):
                                        last_name = name
                                    else:
                                        name = last_name
                            elif last_name and (col_next_numeric or not col_next):
                                name = last_name
                        else:
                            last_name = ''  # Fix B: SKIP 행 만나면 last_name 초기화
                    elif not name:
                        continue
                name_norm = re.sub(r'\s+', ' ', name)
                # Fix B+C: SKIP 키워드 및 '계' 단독 → last_name 초기화 후 skip
                if (any(kw in name_norm for kw in SKIP_ROW_KEYWORDS)
                        or name_norm.strip() == '계'):
                    last_name = ''
                    continue
                if name in ('','구분','항목','---') or re.match(r'^[-=]+$', name): continue
                if pct_col >= len(row): continue
                pct_raw = row[pct_col].strip().rstrip('%') if pct_col < len(row) else ''
                # pct_col이 금액을 가리킬 경우(full row 추가 열로 인한 오프셋) → pct_col+1 시도
                actual_pct_col = pct_col
                pct_val = -1.0
                try:
                    pct_val = float(pct_raw.replace(',',''))
                    if pct_val > 100 and pct_col + 1 < len(row):
                        pct_raw2 = row[pct_col + 1].strip().rstrip('%')
                        try:
                            pct_val2 = float(pct_raw2.replace(',', ''))
                            if 0 < pct_val2 <= 100:
                                pct_val = pct_val2
                                actual_pct_col = pct_col + 1
                            else:
                                pct_val = -1.0
                        except:
                            pct_val = -1.0
                    elif pct_val <= 0:
                        pct_val = -1.0
                except:
                    pct_val = -1.0
                # pct 미확정: 행 전체 inline-% 스캔 (LG디스플레이 TV형 — merged cell로 인한 열 이동)
                if pct_val < 0:
                    for ci, cv in enumerate(row):
                        if '%' in cv and cv.strip() not in ('%', '비율(%)'):
                            v2 = cv.rstrip('%').replace(',', '').strip()
                            try:
                                f2 = float(v2)
                                if 0 < f2 <= 100:
                                    pct_val = f2; actual_pct_col = ci; break
                            except: pass
                if pct_val <= 0: continue
                actual_amt_col = actual_pct_col - 1
                amt_str = ''
                if 0 <= actual_amt_col < len(row):
                    v = row[actual_amt_col].replace(',','').strip()
                    try: int(float(v)); amt_str = v
                    except: pass
                if name in seg_dict:
                    seg_dict[name][1] += pct_val
                else:
                    seg_dict[name] = [amt_str, pct_val]; seg_order.append(name)
            segments = [(n, seg_dict[n][0], seg_dict[n][1]) for n in seg_order]
            if segments:
                segments_out = segments
                break  # 유효 세그먼트 찾았으면 이후 후보 시도 불필요
        if not segments_out:
            continue
        parsed_labels.add(label)
        segments  = segments_out
        # 품질 검사: % 합계 이상하거나 단일 세그먼트 >100% → 이름만 표시
        pct_sum     = sum(p for _, _, p in segments)
        bad_quality = pct_sum > 115 or any(p > 100 for _, _, p in segments)
        unit_str  = unit_hints.get(label, '')
        unit_part = f", {unit_str}" if unit_str else ""
        if bad_quality:
            hdr = (f"■ [{label}] 주요 사업부문 (비율 불명확{unit_part})" if multi
                   else f"■ 주요 사업부문 (비율 불명확{unit_part})")
            all_lines.append(hdr)
            for name, _, _ in segments:
                all_lines.append(f"  - {name}")
        else:
            hdr = (f"■ [{label}] 영업수익 구성 (FY2025{unit_part})" if multi
                   else f"■ 사업부문별 영업수익 구성 (FY2025{unit_part})")
            all_lines.append(hdr)
            for name, amt, pct in segments:
                amt_part = f": {int(float(amt)):,}" if amt else ""
                all_lines.append(f"  - {name}{amt_part} ({pct:.1f}%)")
        all_lines.append("")

    for label, raw_text in raw_table_chunks.items():
        if label in parsed_labels: continue
        unit_str  = unit_hints.get(label, '')
        # 모든 후보 테이블을 순차 시도 (첫 번째가 파이프라인 설명 테이블일 경우 다음 후보 사용)
        _segs = []
        for cand_text in raw_table_cands.get(label, [raw_text]):
            _rows = _parse_table_rows(cand_text)
            _segs = _parse_amount_table_segments(_rows) if _rows else []
            if _segs:
                break
        if _segs:
            parsed_labels.add(label)
            unit_part = f", {unit_str}" if unit_str else ""
            hdr = (f"■ [{label}] 매출 구성 (FY최신{unit_part})" if multi
                   else f"■ 매출 구성 (FY최신{unit_part})")
            all_lines.append(hdr)
            for name, amt, pct in _segs:
                amt_part = f": {int(float(amt)):,}" if amt else ""
                all_lines.append(f"  - {name}{amt_part} ({pct:.1f}%)")
            all_lines.append("")
        else:
            unit_part = f" (단위: {unit_str})" if unit_str else ""
            hdr = (f"■ [{label}] 사업부문별 매출{unit_part} (원문 테이블)\n" if multi
                   else f"■ 사업부문별 매출{unit_part} (원문 테이블)\n")
            all_lines.append(hdr + raw_text[:800])
            all_lines.append("")

    for label, text in sector_texts.items():
        if label in parsed_labels or label in raw_table_chunks: continue
        fb = _text_pct_fallback(text)
        if fb:
            all_lines.append((f"■ [{label}] " + fb.lstrip('■ ')) if multi else fb)
            all_lines.append("")

    return "\n".join(all_lines).strip()

# ── 경쟁환경 텍스트 추출 ─────────────────────────────────────────────────────

def auto_build_price_context(chunks, max_chars=1000):
    KEYWORDS = ['경쟁', '시장점유', '리스크', '환율', '수출', '채널', '규제']
    PRICE_TARGETS = [
        'II. 사업의 내용 > 7. 기타 참고사항',
        'II. 사업의 내용 > 4. 영업 개황 및 사업 부문의 구분',
        'II. 사업의 내용 > 2. 주요 제품 및 서비스',
        'II. 사업의 내용 > 2. 영업의 현황',
    ]
    for target in PRICE_TARGETS:
        matched = [
            c for c in chunks
            if _matches_section(c.get('section_path_str') or '', target)
            and c.get('kind') == 'text'
            and len(c.get('text','')) >= 200
            and any(kw in c.get('text','') for kw in KEYWORDS)
        ]
        if matched:
            for c in matched:
                if '경쟁' in c['text'] or '시장점유' in c['text']:
                    return c['text'][:max_chars]
            return matched[0]['text'][:max_chars]
    return ""

# ── MD&A 텍스트 추출 ─────────────────────────────────────────────────────────

def build_mda_text(chunks, max_chars=2000):
    MDA_TARGETS = [
        'IV. 이사의 경영진단 및 분석의견 > 2. 개요',
        'IV. 이사의 경영진단 및 분석의견 > 3. 재무상태 및 영업실적',
    ]
    result = ""
    for target in MDA_TARGETS:
        for c in chunks:
            if (_matches_section(c.get('section_path_str') or '', target)
                    and c.get('kind') == 'text'
                    and len(c.get('text','')) >= 200):
                text = c['text'].strip()
                if len(result) + len(text) + 2 > max_chars:
                    return result.strip()
                result += text + "\n\n"
    return result.strip()


print("v4.8 정의 완료:")
print("  detect_corp_type() : spac / reit / insurance / finance / general")
print("  SPAC      → revenue_ctx='' / biz_text=사업의 개요만")
print("  REIT      → 임대수익 키워드 + 사업의 개요·위험관리 섹션")
print("  insurance → biz_text=사업의 개요(수입보험료·투자수익률·ROA) 우선")
print("  finance   → biz_text=영업의 현황 우선, 부족시 사업의 개요 fallback")
print("  general   → 기존 로직 유지")

# ── 사업분야 4단계 폴백 게이트 (아이디어 1 — v2 추가) ────────────────────────

SEGMENT_HINT_KEYWORDS = ['사업부문', '부문', '사업분야', '사업의 종류',
                         '주요 제품', '주요제품', '제품군', '서비스 부문',
                         '영업 부문', '영업부문', '사업 영역', '사업영역']

def _has_valid_pct(ctx: str) -> bool:
    """auto_extract_revenue_context 결과에 0<x<=100 형태 % 가 2개 이상 있는지"""
    if not ctx:
        return False
    nums = re.findall(r'(\d{1,3}(?:\.\d+)?)\s*%', ctx)
    valid = [float(n) for n in nums if 0 < float(n) <= 100]
    return len(valid) >= 2

def _mentions_segments(text: str) -> bool:
    """본문에 사업부문 힌트 키워드가 있고 부문 관련 단어가 3회 이상 등장하는가"""
    if not text:
        return False
    if not any(k in text for k in SEGMENT_HINT_KEYWORDS):
        return False
    return (text.count('부문') + text.count('사업')) >= 3

def _collect_all_section_II(chunks: list, max_chars: int = 5000) -> str:
    """II. 사업의 내용 하위 전 섹션 텍스트를 순서대로 합본"""
    buf = []
    for c in chunks:
        sp = c.get('section_path_str') or ''
        if ('II. 사업의 내용' in sp or 'Ⅱ. 사업의 내용' in sp) and c.get('kind') == 'text':
            t = (c.get('text') or '').strip()
            if t:
                buf.append(t)
        if sum(len(x) for x in buf) > max_chars:
            break
    return '\n'.join(buf)[:max_chars]

def resolve_business_segments(chunks: list, corp_name: str,
                              corp_type: str) -> dict:
    """
    4단계 폴백 게이트. 위에서 성공하면 즉시 반환.
    반환: {'tier': int, 'mode': str, 'data': str}
    """
    # TIER 1 — 비율(%) 테이블 존재 (raw % 컬럼)
    # TIER 2 — 금액 테이블만 존재 (Python 비율 계산)
    # FY2025 헤더 = raw %(Tier1) / FY최신 헤더 = Python 계산(Tier2)
    pct_ctx = auto_extract_revenue_context(chunks, corp_type=corp_type)
    if pct_ctx and _has_valid_pct(pct_ctx):
        if 'FY2025' in pct_ctx:
            return {'tier': 1, 'mode': 'exact_pct', 'data': pct_ctx}
        return {'tier': 2, 'mode': 'calc_pct', 'data': pct_ctx}
    if pct_ctx and pct_ctx.strip():
        return {'tier': 2, 'mode': 'calc_pct', 'data': pct_ctx}

    # TIER 3 — 표 없음, 본문에 부문 서술 존재
    biz_text = auto_build_business_text(chunks, corp_type=corp_type)
    if biz_text and _mentions_segments(biz_text):
        return {'tier': 3, 'mode': 'narrative_segments', 'data': biz_text[:4000]}

    # TIER 4 — 부문 구분 불명확 → II장 전체로 best effort
    fallback_text = _collect_all_section_II(chunks)
    if not fallback_text:
        fallback_text = (biz_text or '')[:5000]
    return {'tier': 4, 'mode': 'best_effort_summary', 'data': fallback_text}

TIER_INSTRUCTION = {
    1: ("[사업부문별 매출 구성]에 비율(%)이 제공됩니다. "
        "각 부문의 %를 그대로 인용해 business_model에 수치로 명시하세요."),
    2: ("[사업부문별 매출 구성]에 각 부문의 비율(%)이 제공됩니다. "
        "그 %를 그대로 사용하고 새로 계산하지 마세요."),
    3: ("매출 비율 수치는 제공되지 않았습니다. 본문에 서술된 사업부문을 근거로 "
        "'○○은 A·B·C 사업을 영위하며 그중 □□가 주력으로 보입니다' "
        "형태로 1~3문장 정성 서술하세요. 추측 비율(%)을 절대 만들지 마세요."),
    4: ("사업부문이 명확히 구분되지 않는 기업입니다. 부문을 억지로 나누지 말고 "
        "'○○은 △△ 사업을 단일/주력으로 영위하며, 사업부문별 매출 구성은 "
        "사업보고서상 별도 제시되지 않습니다' 식으로 1~2문장 솔직하게 서술하세요. "
        "business_model을 비워두지 마세요."),
}

print("v2 추가: resolve_business_segments() / TIER_INSTRUCTION 정의 완료")
print("  TIER 1=exact_pct  2=calc_pct  3=narrative_segments  4=best_effort")



# -- 멀티섹터 청크 필터링 (v3: has_multi_sector=True 기업용) ----------------

FINANCIAL_SECTOR_LABELS = {'금융업', '보험업', '여신전문금융업'}

def filter_multisector_chunks(chunks: list) -> list:
    """
    (금융업)·(보험업) 등 금융 종속기업 청크 제거.
    has_multi_sector=True 기업에만 적용.
    (제조서비스업) 또는 섹터 라벨 없는 청크는 그대로 유지.
    """
    filtered = []
    for c in chunks:
        sp = c.get('section_path_str') or ''
        m = re.search(r'\(([^)]+)\)', sp)
        label = m.group(1) if m else None
        if label not in FINANCIAL_SECTOR_LABELS:
            filtered.append(c)
    return filtered

print('filter_multisector_chunks() 정의 완료 -- 금융업/보험업 청크 제거')