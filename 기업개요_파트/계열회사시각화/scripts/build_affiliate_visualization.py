from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "RAG").exists():
            return path
    return start


ROOT = find_project_root(Path(__file__).resolve().parents[1])
RAG_DIR = ROOT / "RAG"
DEFAULT_OUT_DIR = ROOT / "output" / "affiliate_visualization"
DART_BASE_URL = "https://dart.fss.or.kr"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

SECTION_KEYWORDS = ("계열회사 등에 관한 사항", "계열회사")
IMAGE_KEYWORDS = ("소유지분도", "소유 지분도", "계통도", "게통도", "출자", "지배구조", "그룹")
PURPOSE_WORDS = ("경영참여", "일반투자", "단순투자", "계열회사", "기타")
STRUCTURAL_INVESTMENT_RATE_THRESHOLD = 20.0


@dataclass
class TocItem:
    text: str
    rcp_no: str
    dcm_no: str
    ele_id: str
    offset: str
    length: str
    dtd: str


class ImgParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        self.images.append({key.lower(): value or "" for key, value in attrs})


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def safe_name(value: str, max_len: int = 80) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return value[:max_len] or "unknown"


def display_company_name(value: str) -> str:
    value = clean_cell(value)
    return re.sub(r"(보통주|우선주)$", "", value).strip() or value


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def clean_cell(value: str) -> str:
    value = unescape(strip_tags(value))
    value = value.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).strip()


def request_bytes(url: str, referer: str | None = None, timeout: int = 25) -> tuple[bytes, dict[str, str], str]:
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as response:
        raw_headers = {key: value for key, value in response.headers.items()}
        return response.read(), raw_headers, response.geturl()


def request_text(url: str, referer: str | None = None, timeout: int = 25) -> str:
    body, headers, _ = request_bytes(url, referer=referer, timeout=timeout)
    content_type = headers.get("Content-Type", "")
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.I)
    encodings = [match.group(1)] if match else []
    encodings.extend(["utf-8", "cp949", "euc-kr"])
    for encoding in encodings:
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def find_rag_file(target: str) -> Path:
    target = target.strip()
    if not target:
        raise ValueError("대상 종목코드 또는 회사명을 입력해야 합니다.")

    if re.fullmatch(r"\d{6}", target):
        matches = sorted(RAG_DIR.glob(f"{target}_*_annual_chunks.jsonl"))
    else:
        matches = sorted(path for path in RAG_DIR.glob("*_annual_chunks.jsonl") if target in path.name)

    if not matches:
        raise FileNotFoundError(f"JSONL 파일을 찾지 못했습니다: {target}")
    return matches[0]


def load_chunks(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not chunks:
        raise ValueError(f"JSONL 청크가 비어 있습니다: {path}")
    return chunks


def parse_toc_items(main_html: str) -> list[TocItem]:
    pattern = re.compile(
        r"node\d\['text'\]\s*=\s*\"(?P<text>[^\"]+)\";\s*"
        r"node\d\['id'\]\s*=\s*\"[^\"]+\";\s*"
        r"node\d\['rcpNo'\]\s*=\s*\"(?P<rcp_no>[^\"]+)\";\s*"
        r"node\d\['dcmNo'\]\s*=\s*\"(?P<dcm_no>[^\"]+)\";\s*"
        r"node\d\['eleId'\]\s*=\s*\"(?P<ele_id>[^\"]+)\";\s*"
        r"node\d\['offset'\]\s*=\s*\"(?P<offset>[^\"]+)\";\s*"
        r"node\d\['length'\]\s*=\s*\"(?P<length>[^\"]+)\";\s*"
        r"node\d\['dtd'\]\s*=\s*\"(?P<dtd>[^\"]+)\";",
        flags=re.S,
    )
    return [TocItem(**match.groupdict()) for match in pattern.finditer(main_html)]


def find_affiliate_toc(items: list[TocItem]) -> TocItem | None:
    for keyword in SECTION_KEYWORDS:
        for item in items:
            if keyword in item.text:
                return item
    return None


def viewer_url(item: TocItem) -> str:
    return (
        f"{DART_BASE_URL}/report/viewer.do?"
        f"rcpNo={item.rcp_no}&dcmNo={item.dcm_no}&eleId={item.ele_id}"
        f"&offset={item.offset}&length={item.length}&dtd={item.dtd}"
    )


def image_extension(src: str, content_type: str) -> str:
    content_type = content_type.lower()
    if "png" in content_type:
        return ".png"
    if "gif" in content_type:
        return ".gif"
    if "webp" in content_type:
        return ".webp"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    parsed = unquote(urlparse(src).path).lower()
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        if parsed.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def select_best_image(images: list[dict[str, str]]) -> dict[str, str] | None:
    if not images:
        return None

    def score(image: dict[str, str]) -> int:
        haystack = unquote(" ".join([image.get("src", ""), image.get("alt", ""), image.get("title", "")]))
        return sum(3 for keyword in IMAGE_KEYWORDS if keyword in haystack)

    ranked = sorted(images, key=score, reverse=True)
    if score(ranked[0]) > 0:
        return ranked[0]
    return ranked[0]


def try_download_original_image(meta: dict[str, Any], out_dir: Path) -> dict[str, Any] | None:
    rcept_no = str(meta.get("rcept_no") or "")
    if not rcept_no:
        return None

    main_url = f"{DART_BASE_URL}/dsaf001/main.do?rcpNo={rcept_no}"
    main_html = request_text(main_url)
    toc_item = find_affiliate_toc(parse_toc_items(main_html))
    if not toc_item:
        return None

    section_url = viewer_url(toc_item)
    section_html = request_text(section_url, referer=main_url)
    parser = ImgParser()
    parser.feed(section_html)
    image = select_best_image(parser.images)
    if not image or not image.get("src"):
        return None

    image_url = urljoin(DART_BASE_URL, unescape(image["src"]))
    body, headers, final_url = request_bytes(image_url, referer=section_url)
    content_type = headers.get("Content-Type", "")
    if "image" not in content_type.lower() and len(body) < 100:
        return None

    ext = image_extension(image_url, content_type)
    image_path = out_dir / f"original_affiliate_diagram{ext}"
    image_path.write_bytes(body)

    return {
        "source_type": "original_dart_image",
        "visual_file_type": ext.lstrip("."),
        "visual_path": str(image_path),
        "has_original_image": True,
        "has_ownership_rate": None,
        "dart_main_url": main_url,
        "dart_section_url": section_url,
        "dart_image_url": final_url,
        "image_alt": clean_cell(image.get("alt", "")),
        "image_mime": content_type,
        "image_size_bytes": len(body),
        "nodes": [],
        "edges": [],
        "affiliate_companies": [],
    }


def find_existing_original_image(out_dir: Path) -> Path | None:
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        path = out_dir / f"original_affiliate_diagram{ext}"
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def reuse_existing_original_image(meta: dict[str, Any], out_dir: Path) -> dict[str, Any] | None:
    image_path = find_existing_original_image(out_dir)
    if image_path is None:
        return None

    previous: dict[str, Any] = {}
    metadata_path = out_dir / "affiliate_visual_metadata.json"
    if metadata_path.exists():
        try:
            with metadata_path.open("r", encoding="utf-8") as f:
                previous = json.load(f)
        except (OSError, json.JSONDecodeError):
            previous = {}

    rcept_no = str(meta.get("rcept_no") or "")
    return {
        "source_type": "original_dart_image",
        "visual_file_type": image_path.suffix.lstrip("."),
        "visual_path": str(image_path),
        "has_original_image": True,
        "has_ownership_rate": None,
        "dart_main_url": f"{DART_BASE_URL}/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else "",
        "dart_section_url": previous.get("dart_section_url", ""),
        "dart_image_url": previous.get("dart_image_url", ""),
        "image_alt": previous.get("image_alt", ""),
        "image_mime": previous.get("image_mime", ""),
        "image_size_bytes": image_path.stat().st_size,
        "cached_original_image": True,
        "nodes": [],
        "edges": [],
        "affiliate_companies": [],
    }


def parse_markdown_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "|" not in line[1:]:
            continue
        cells = [clean_cell(cell) for cell in line.strip("|").split("|")]
        if not cells or all(not cell or re.fullmatch(r"[-:\s]+", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def parse_percent(value: str) -> float | None:
    value = clean_cell(value).replace("%", "").replace(",", "")
    if value in {"", "-", "N/A"}:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if 0 <= number <= 100:
        return number
    return None


def normalize_purpose(value: str) -> str:
    return re.sub(r"\s+", "", clean_cell(value))


def company_core_text(value: str) -> str:
    value = clean_cell(value)
    value = re.sub(r"\(주\)|㈜|주식회사|유한회사|회사|법인", "", value, flags=re.I)
    value = re.sub(
        r"(?i)[\s.,]*(?:company|co|ltd|limited|inc|corp|corporation|llc|l\.l\.c|gmbh)\.?,?$",
        "",
        value,
    )
    return re.sub(r"[^가-힣A-Za-z0-9]", "", value)


def looks_like_company_name(value: str) -> bool:
    value = clean_cell(value)
    if not value:
        return False
    exact_bad_words = {
        "합 계",
        "합계",
        "계",
        "외",
        "상장",
        "비상장",
        "국내",
        "해외",
        "기타",
    }
    if value in exact_bad_words:
        return False
    contains_bad_words = (
        "합 계",
        "합계",
        "수량",
        "금액",
        "법인명",
        "회사명",
        "상장여부",
        "구분",
        "거래상대방 합계",
        "출자사",
        "피출자사",
        "지분율",
        "당사 지분율",
        "소유지분율",
        "기준일",
        "본문으로 이동",
        "금리 Reset",
        "국고채",
        "사채권자",
        "자기주식",
        "의결권 주식",
        "장부금액",
        "당기 중",
        "매입하였습니다",
    )
    if any(word in value for word in contains_bad_words):
        return False
    if re.search(r"\d{4}년|\d{1,2}월(?:\s+\d{1,2}일)?|\d+(?:\.\d+)?\s*%", value):
        return False
    if re.fullmatch(r"[-\d.,()%\s]+", value):
        return False
    if re.fullmatch(
        r"(?:Co\.?|Co\.?,?\s*Ltd\.?|Ltd\.?|Limited|Inc\.?|Corp\.?|Corporation|Company|LLC\.?|L\.L\.C|GmbH)",
        value,
        flags=re.I,
    ):
        return False
    if len(company_core_text(value)) <= 1:
        return False
    if re.fullmatch(r"[a-z]{1,3}\s*(?:LLC\.?|Co\.?|Co\.?,?\s*Ltd\.?|Inc\.?|Corp\.?|GmbH)", value, flags=re.I):
        return False
    return bool(re.search(r"[가-힣A-Za-z㈜]", value))


def normalize_company_name(value: str) -> str:
    value = clean_cell(value)
    value = re.sub(r"\(\*[0-9]+\)", "", value)
    value = re.sub(r"\(주[0-9]+\)", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_affiliate_list(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    companies: list[dict[str, Any]] = []
    seen: set[str] = set()
    current_listing: str | None = None

    for chunk in chunks:
        path = str(chunk.get("section_path_str") or "")
        text = str(chunk.get("text") or "")
        if "계열회사 현황(상세)" not in path and "상장여부" not in text:
            continue
        for cells in parse_markdown_rows(text):
            if not cells:
                continue
            first = clean_cell(cells[0])
            if first in {"상장", "비상장"}:
                current_listing = first
                company = normalize_company_name(cells[2] if len(cells) >= 3 else "")
            else:
                company = normalize_company_name(first)
            if not looks_like_company_name(company):
                continue
            key = company.lower()
            if key in seen:
                continue
            seen.add(key)
            companies.append(
                {
                    "name": company,
                    "listing": current_listing or "미분류",
                    "source_chunk_id": chunk.get("id", ""),
                }
            )
    return companies


def parse_direct_matrix_edges(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()

    def add_edge(investor: str, investee: str, rate: float | None, chunk: dict[str, Any]) -> None:
        if rate is None or rate <= 0:
            return
        if not looks_like_company_name(investor) or not looks_like_company_name(investee):
            return
        if investor.lower() == investee.lower():
            return
        key = (investor.lower(), investee.lower(), rate)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "from": investor,
                "to": investee,
                "ownership_rate": rate,
                "relation_type": "ownership",
                "source": "출자계통도",
                "source_chunk_id": chunk.get("id", ""),
            }
        )

    row_table_active = False
    current_row_investor: str | None = None

    for chunk in chunks:
        path = str(chunk.get("section_path_str") or "")
        text = str(chunk.get("text") or "")
        if "계열회사" not in path and "출자계통도" not in text:
            continue
        rows = parse_markdown_rows(text)
        investors: list[str] = []
        for cells in rows:
            if not cells:
                continue

            header_text = normalize_purpose(" ".join(cells[:4]))
            if "출자사" in header_text and "피출자사" in header_text and "지분율" in header_text:
                row_table_active = True
                investors = []
                current_row_investor = None
                continue

            if row_table_active:
                if len(cells) >= 4 and cells[1] in {"상장", "비상장"}:
                    current_row_investor = normalize_company_name(cells[0])
                    add_edge(
                        current_row_investor,
                        normalize_company_name(cells[2]),
                        parse_percent(cells[3]),
                        chunk,
                    )
                    continue
                if current_row_investor and len(cells) >= 2 and all(not clean_cell(cell) for cell in cells[2:]):
                    add_edge(
                        current_row_investor,
                        normalize_company_name(cells[0]),
                        parse_percent(cells[1]),
                        chunk,
                    )
                    continue

            if "피출자사" in cells[0]:
                investors = [
                    investor
                    for investor in (normalize_company_name(cell) for cell in cells[1:])
                    if looks_like_company_name(investor)
                ]
                continue
            if not investors:
                continue
            investee = normalize_company_name(cells[0])
            if not looks_like_company_name(investee):
                continue
            for investor, cell in zip(investors, cells[1:]):
                add_edge(investor, investee, parse_percent(cell), chunk)
    return edges


def infer_investment_rate(cells: list[str]) -> float | None:
    has_listing_column = len(cells) >= 4 and cells[1] in {"상장", "비상장"}
    preferred_indexes = [12, 6] if has_listing_column else [10, 4]
    for index in preferred_indexes:
        if index < len(cells):
            rate = parse_percent(cells[index])
            if rate is not None:
                return rate
    percent_candidates = [parse_percent(cell) for cell in cells if "%" in cell]
    percent_candidates = [rate for rate in percent_candidates if rate is not None]
    return percent_candidates[-1] if percent_candidates else None


def parse_investment_edges(chunks: list[dict[str, Any]], corp_name: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    for chunk in chunks:
        path = str(chunk.get("section_path_str") or "")
        text = str(chunk.get("text") or "")
        if "타법인출자 현황(상세)" not in path and "법인명 / 상장여부" not in text:
            continue
        for cells in parse_markdown_rows(text):
            if len(cells) < 5:
                continue
            company = normalize_company_name(cells[0])
            if not looks_like_company_name(company):
                continue
            purpose = normalize_purpose(cells[3] if len(cells) >= 4 and cells[1] in {"상장", "비상장"} else cells[1])
            if purpose and not any(word in purpose for word in PURPOSE_WORDS):
                continue
            rate = infer_investment_rate(cells)
            if rate is not None and rate <= 0:
                continue
            key = company.lower()
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "from": corp_name,
                    "to": company,
                    "ownership_rate": rate,
                    "relation_type": "investment",
                    "source": "타법인출자 현황(상세)",
                    "source_chunk_id": chunk.get("id", ""),
                    "listing": cells[1] if len(cells) >= 2 and cells[1] in {"상장", "비상장"} else None,
                    "purpose": purpose,
                }
            )

    record_anchor_pattern = re.compile(
        rf"(?P<company>{PLAIN_INVESTMENT_COMPANY_PATTERN})\s+(?P<listing>상장|비상장)\s+"
        r"\d{4}년\s+\d{2}월\s+\d{2}일\s+(?P<purpose>[가-힣A-Za-z/·ㆍ]+)\s+",
        flags=re.I,
    )
    rate_context_pattern = re.compile(r"(?:^|\s)(?:-|\d[\d,]*)\s+(?P<rate>[0-9]+(?:\.[0-9]+)?)\s+(?:-|\d[\d,]*)")
    for chunk in chunks:
        text = clean_cell(str(chunk.get("text") or ""))
        if "타법인출자 현황(상세)" not in text or "법인명 상장여부" not in text:
            continue
        anchors = list(record_anchor_pattern.finditer(text))
        for index, match in enumerate(anchors):
            body_start = match.end()
            body_end = anchors[index + 1].start() if index + 1 < len(anchors) else len(text)
            body = text[body_start:body_end]
            company = normalize_company_name(match.group("company"))
            purpose = normalize_purpose(match.group("purpose"))
            if not looks_like_company_name(company):
                continue
            if purpose and not any(word in purpose for word in PURPOSE_WORDS):
                continue
            rate_candidates = [
                parse_percent(rate_match.group("rate"))
                for rate_match in rate_context_pattern.finditer(body)
            ]
            rate_candidates = [rate for rate in rate_candidates if rate is not None]
            rate = rate_candidates[-1] if rate_candidates else None
            if rate is not None and rate <= 0:
                continue
            key = company.lower()
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "from": corp_name,
                    "to": company,
                    "ownership_rate": rate,
                    "relation_type": "investment",
                    "source": "타법인출자 현황(상세)",
                    "source_chunk_id": chunk.get("id", ""),
                    "listing": match.group("listing"),
                    "purpose": purpose,
                }
            )
    return edges


def parse_percent_from_text(value: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", clean_cell(value))
    if match:
        return parse_percent(match.group(1))
    return parse_percent(value)


def parse_percent_owner(value: str) -> tuple[float | None, str | None]:
    value = clean_cell(value)
    owner_match = re.search(r"%\s*\(([^)]+)\)", value)
    owner = normalize_company_name(owner_match.group(1)) if owner_match else None
    return parse_percent_from_text(value), owner


def looks_like_subsidiary_company_name(value: str) -> bool:
    value = clean_cell(value)
    if not looks_like_company_name(value):
        return False
    if re.fullmatch(r"(?:Co\.?|Co\.?,?\s*Ltd\.?|Ltd\.?|Limited|Inc\.?|Corp\.?|Corporation)", value, flags=re.I):
        return False
    if re.match(r"^[a-z]", value):
        return False
    if re.search(r"\d+(?:\.\d+)?\s*%|\d{1,2}월|지분율|자기주식|당기 중|매입하였습니다|의결권 주식", value):
        return False
    if len(company_core_text(value)) <= 1:
        return False
    if value in {"금융업", "비금융업", "상장", "비상장", "국내", "해외", "기타"}:
        return False
    if any(word in value for word in ("지분율", "소유지분율", "지배지분율", "장부가액")):
        return False
    if value.count(")") > value.count("("):
        return False
    if re.fullmatch(r"[A-Za-z]\s*(?:Co\.?|Ltd\.?|Inc\.?|Corp\.?),?", value, flags=re.I):
        return False
    if re.fullmatch(r"[A-Za-z]\)\s*(?:Co\.?|Ltd\.?|Inc\.?|Corp\.?),?", value, flags=re.I):
        return False
    return bool(
        re.search(
            r"\(주\)|㈜|주식회사|회사|법인|유한공사|공사|Company|Co\.?|Ltd\.?|Limited|Inc\.?|Corp\.?|Corporation|LLC\.?|L\.L\.C|B\.V\.|GmbH|S\.A\.S\.|S\.A\.?\s*DE\s*C\.?V\.?|A\.S\.|S\.R\.L\.|S\.L\.U\.|Sp\.?\s*Z\.?\s*o\.?\s*o\.?|Pty|Pte\.?|Sdn\.?|Bhd\.?|L\.P\.|AG|AB|LTDA|Partnership|Trust|Fund|증권|은행|보험|카드|캐피탈|투자|홀딩스|파트너스|조합|신탁|제[일이삼사오육칠팔구십\d]+차",
            value,
            flags=re.I,
        )
    )


PLAIN_DETAIL_COUNTRY_PATTERN = (
    r"대한민국|한국|미국|캐나다|멕시코|브라질|칠레|콜롬비아|베트남|중국|일본|싱가포르|싱가폴|"
    r"인도네시아|말레이시아|태국|필리핀|홍콩|대만|미얀마|파키스탄|방글라데시|스리랑카|"
    r"사우디아라비아|아랍에미리트|인도|호주|뉴질랜드|체코|독일|프랑스|네덜란드|스웨덴|러시아|"
    r"튀르키예|터키|우크라이나|이집트|영국|이탈리아|스페인|폴란드|스위스|헝가리|벨기에|"
    r"오스트리아|덴마크|노르웨이|루마니아|슬로바키아|멕시코|브라질|남아프리카공화국|"
    r"카자흐스탄|케이만군도"
)

PLAIN_DETAIL_COMPANY_PATTERN = (
    r"(?:\(주\)\s*[가-힣A-Za-z][가-힣A-Za-z0-9\s().,&'’/\-·ㆍ]{1,80}?|"
    r"주식회사\s*[가-힣A-Za-z][가-힣A-Za-z0-9\s().,&'’/\-·ㆍ]{1,80}?|"
    r"[가-힣A-Za-z][가-힣A-Za-z0-9\s().,&'’/\-·ㆍ]{0,120}?"
    r"(?:\(주\)|㈜|주식회사|유한회사|회사|법인|Company(?: Limited)?|Co\.?,?\s*(?:Ltd\.?|LTD\.?)?|"
    r"Ltd\.?|Limited|Inc\.?|Corp\.?|Corporation|LLC\.?|L\.L\.C|B\.V\.|GmbH\.?|S\.A\.S\.|S\.A\.?\s*DE\s*C\.?V\.?|A\.S\.|"
    r"S\.R\.L\.|S\.L\.U\.|Sp\.?\s*Z\.?\s*o\.?\s*o\.?|Pty(?: Limited)?|Pte\.?(?: Ltd\.?)?|Sdn\.?\s*Bhd\.?|L\.P\.|AG|AB|LTDA|"
    r"Partnership|Trust|Fund|유한공사|공사|조합|신탁\d*호?|제[일이삼사오육칠팔구십\d]+차\w*회사))"
)

PLAIN_INVESTMENT_COMPANY_PATTERN = (
    r"[가-힣A-Za-z㈜(]"
    r"(?:(?!경영참여|일반투자|단순투자|\d{4}년|지분율|장부가액|수량|금액|합 계)"
    r"[가-힣A-Za-z0-9\s().,&'’/\-·ㆍ㈜]){1,100}?"
)

NUMERIC_DETAIL_COMPANY_PATTERN = r"[가-힣A-Za-z㈜(][가-힣A-Za-z0-9\s().,&'’/\-·ㆍ㈜]{1,140}?"


def looks_like_numeric_subsidiary_company_name(value: str) -> bool:
    value = clean_cell(value)
    if not looks_like_company_name(value):
        return False
    if re.fullmatch(r"(?:Co\.?|Ltd\.?|Limited|Inc\.?|Corp\.?|Corporation|LLC\.?|GmbH\.?)", value, flags=re.I):
        return False
    if any(word in value for word in ("지분율", "소유지분율", "지배지분율", "장부가액", "요약재무정보")):
        return False
    if re.search(r"\d{1,2}월|제조|판매업|대행업|연구|재무현황", value) and re.search(r"\d", value):
        return False
    if value.count(")") > value.count("("):
        return False
    if len(company_core_text(value)) <= 1:
        return False
    return True


def parse_plain_subsidiary_detail_edges(chunks: list[dict[str, Any]], corp_name: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    segment_anchor_pattern = re.compile(rf"(?<![가-힣A-Za-z0-9])(?={PLAIN_DETAIL_COMPANY_PATTERN}\s+)", flags=re.I)
    line_pattern = re.compile(
        rf"(?P<company>{PLAIN_DETAIL_COMPANY_PATTERN})\s+.+?(?:{PLAIN_DETAIL_COUNTRY_PATTERN}|〃)\s+"
        r"(?:.+?\s+)?(?P<rate>[0-9]+(?:\.[0-9]+)?)\s*%(?P<tail>.*)$",
        flags=re.I,
    )
    owner_pattern = re.compile(r"(?P<owner>.+?)\s+(?P<rate>[0-9]+(?:\.[0-9]+)?)\s*%", flags=re.I)

    for chunk in chunks:
        path = str(chunk.get("section_path_str") or "")
        text = str(chunk.get("text") or "")
        if "재무제표 주석" not in path and "연결대상 종속회사" not in text and "종속기업" not in text:
            continue
        if text.count("%") < 3:
            continue

        last_owner: str | None = None
        for raw_line in text.splitlines():
            line = clean_cell(raw_line)
            if not line:
                continue
            anchors = list(segment_anchor_pattern.finditer(line))
            segments = [line]
            if len(anchors) > 1:
                segments = [
                    line[anchors[index].start() : anchors[index + 1].start()]
                    for index in range(len(anchors) - 1)
                ]
                segments.append(line[anchors[-1].start() :])

            for segment in segments:
                if "%" not in segment or clean_cell(segment).startswith("-"):
                    continue
                match = line_pattern.match(clean_cell(segment))
                if not match:
                    continue

                company = normalize_company_name(match.group("company"))
                rate = parse_percent(match.group("rate"))
                parent = corp_name
                tail = clean_cell(match.group("tail"))

                owner_match = owner_pattern.search(tail)
                if owner_match:
                    owner = normalize_company_name(owner_match.group("owner"))
                    owner_rate = parse_percent(owner_match.group("rate"))
                    if owner == "〃":
                        owner = last_owner or ""
                    if looks_like_subsidiary_company_name(owner) and len(owner) <= 80:
                        parent = owner
                        last_owner = owner
                        if owner_rate is not None:
                            rate = owner_rate
                elif tail.startswith("〃") and last_owner:
                    parent = last_owner

                if rate is None or rate <= 0 or not looks_like_subsidiary_company_name(company):
                    continue
                key = (parent.lower(), company.lower())
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    {
                        "from": parent,
                        "to": company,
                        "ownership_rate": rate,
                        "relation_type": "plain_subsidiary_detail",
                        "source": "재무제표 주석 종속기업 상세목록",
                        "source_chunk_id": chunk.get("id", ""),
                        "purpose": "종속기업 상세목록",
                    }
                )
    return edges


def parse_numeric_subsidiary_detail_edges(chunks: list[dict[str, Any]], corp_name: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    header_pattern = re.compile(
        r"(?:회\s*사\s*명|회사명|종속기업명|기업명).{0,100}(?:지배지분율|소유지분율|지분율)\s*\(%\)",
        flags=re.I,
    )
    note_pattern = r"(?:\s*\((?:\*|주|구\.)[^)]*\))*"
    month_day_pattern = r"\d{1,2}월(?:\s+\d{1,2}일)?"
    number_pattern = r"[0-9]+(?:\.[0-9]+)?"
    country_pattern = rf"(?:{PLAIN_DETAIL_COUNTRY_PATTERN})"
    current_then_country_pattern = re.compile(
        rf"^(?P<company>{NUMERIC_DETAIL_COMPANY_PATTERN}){note_pattern}\s+"
        rf"(?P<rate>{number_pattern})\s+(?:{number_pattern}|-)\s+"
        rf"{country_pattern}\s+{month_day_pattern}(?:\s|$)",
        flags=re.I,
    )
    country_then_current_pattern = re.compile(
        rf"^(?P<company>{NUMERIC_DETAIL_COMPANY_PATTERN}){note_pattern}\s+"
        rf"{country_pattern}\s+.+?\s+{month_day_pattern}\s+"
        rf"(?P<rate>{number_pattern})\s+(?:{number_pattern}|-)(?:\s|$)",
        flags=re.I,
    )
    country_month_then_current_pattern = re.compile(
        rf"^(?P<company>{NUMERIC_DETAIL_COMPANY_PATTERN}){note_pattern}\s+"
        rf"{country_pattern}\s+{month_day_pattern}\s+.+?\s+"
        rf"(?P<rate>{number_pattern})\s+(?:{number_pattern}|-)(?:\s|$)",
        flags=re.I,
    )
    table_active = False

    for chunk in chunks:
        path = str(chunk.get("section_path_str") or "")
        text = str(chunk.get("text") or "")
        if "재무제표 주석" not in path and "연결대상 종속회사" not in text and "종속기업 현황" not in text:
            continue
        has_header = bool(header_pattern.search(text))
        if not has_header and not table_active:
            continue

        for raw_line in text.splitlines():
            line = clean_cell(raw_line)
            if not line:
                continue
            if header_pattern.search(line):
                table_active = True
                continue
            if has_header and not table_active:
                continue
            if re.match(r"^(관계기업|공동기업|공동영업|합\s*계|회사명\s+당기말|기업명\s+당기말)", line):
                table_active = False
                break
            if not table_active:
                continue
            if not line or line.startswith(("-", "주석", "회사명", "회 사 명", "당기말", "전기말", "종속기업")):
                continue
            match = (
                country_month_then_current_pattern.match(line)
                or country_then_current_pattern.match(line)
                or current_then_country_pattern.match(line)
            )
            if not match:
                continue

            company = normalize_company_name(match.group("company"))
            rate = parse_percent(match.group("rate"))
            if rate is None or rate <= 0 or not looks_like_numeric_subsidiary_company_name(company):
                continue

            key = company.lower()
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "from": corp_name,
                    "to": company,
                    "ownership_rate": rate,
                    "relation_type": "numeric_subsidiary_detail",
                    "source": "재무제표 주석 종속기업 현황",
                    "source_chunk_id": chunk.get("id", ""),
                    "purpose": "종속기업 현황",
                }
            )
    return edges


def parse_investment_note_edges(chunks: list[dict[str, Any]], corp_name: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    country_pattern = r"대한민국|미국|캐나다|베트남|중국|일본|싱가포르|인도네시아|말레이시아|태국|필리핀|홍콩|대만"

    for chunk in chunks:
        text = str(chunk.get("text") or "")
        if "종속기업" not in text or "12월 31일" not in text:
            continue
        in_subsidiary_block = False
        for raw_line in text.splitlines():
            line = clean_cell(raw_line)
            if not line:
                continue
            if line.startswith("종속기업"):
                in_subsidiary_block = True
                continue
            if line.startswith(("공동기업", "관계기업", "합 계")):
                in_subsidiary_block = False
                continue
            if not in_subsidiary_block:
                continue

            match = re.match(
                rf"(?P<company>.+?)\s+(?:{country_pattern})\s+.+?\s+12월\s+31일\s+(?P<rate>-|[0-9]+(?:\.[0-9]+)?)\s+",
                line,
            )
            if not match:
                continue
            company = normalize_company_name(match.group("company"))
            rate = parse_percent(match.group("rate"))
            if rate is None or rate <= 0 or not looks_like_company_name(company):
                continue
            key = company.lower()
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "from": corp_name,
                    "to": company,
                    "ownership_rate": rate,
                    "relation_type": "subsidiary_investment",
                    "source": "재무제표 주석 종속기업투자주식",
                    "source_chunk_id": chunk.get("id", ""),
                    "purpose": "종속기업투자주식",
                }
            )
    return edges


def parse_subsidiary_edges(chunks: list[dict[str, Any]], corp_name: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    group_labels = {"금융업", "비금융업", "상장", "비상장", "국내", "해외"}

    for chunk in chunks:
        path = str(chunk.get("section_path_str") or "")
        text = str(chunk.get("text") or "")
        has_subsidiary_title = "연결대상 종속회사" in path or "연결대상 종속회사" in text
        has_detail_table_shape = "회사명" in text and "지분율" in text and (
            "주요 사업" in text or "재무정보" in text or "자산총계" in text
        )
        has_share_count_table_shape = has_subsidiary_title and "투자주식수" in text and "지분율" in text
        has_top_header_ownership_shape = (
            "상위 헤더" in text
            and "종속기업" in text
            and "소유지분율" in text
            and "소재지" in text
        )
        if not (
            (has_subsidiary_title and "회사명" in text and "지분율" in text)
            or has_detail_table_shape
            or has_share_count_table_shape
            or has_top_header_ownership_shape
        ):
            continue
        for cells in parse_markdown_rows(text):
            if len(cells) < 2:
                continue
            if any(header in cells[0] for header in ("구분", "회사명", "자산총계", "합계")):
                continue

            company = ""
            rate: float | None = None
            owner: str | None = None
            if len(cells) >= 3 and parse_percent_from_text(cells[2]) is not None and cells[0] in group_labels:
                company = normalize_company_name(cells[1])
                rate, owner = parse_percent_owner(cells[2])
            elif (
                has_top_header_ownership_shape
                and len(cells) >= 3
                and parse_percent_from_text(cells[2]) is not None
                and looks_like_subsidiary_company_name(cells[0])
            ):
                company = normalize_company_name(cells[0])
                rate, owner = parse_percent_owner(cells[2])
            elif (
                has_share_count_table_shape
                and len(cells) >= 3
                and parse_percent_from_text(cells[2]) is not None
                and looks_like_subsidiary_company_name(cells[0])
            ):
                company = normalize_company_name(cells[0])
                rate, owner = parse_percent_owner(cells[2])
            elif parse_percent_from_text(cells[1]) is not None:
                company = normalize_company_name(cells[0])
                rate, owner = parse_percent_owner(cells[1])

            if not looks_like_subsidiary_company_name(company):
                continue
            parent = owner or corp_name
            key = (parent.lower(), company.lower())
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "from": parent,
                    "to": company,
                    "ownership_rate": rate,
                    "relation_type": "subsidiary",
                    "source": "연결대상 종속회사 현황",
                    "source_chunk_id": chunk.get("id", ""),
                    "purpose": "종속회사",
                }
            )
    return edges


def is_structural_investment_edge(edge: dict[str, Any]) -> bool:
    purpose = normalize_purpose(str(edge.get("purpose") or ""))
    if "경영참여" in purpose or "계열회사" in purpose:
        return True
    if "일반투자" in purpose or "단순투자" in purpose:
        return False
    rate = edge.get("ownership_rate")
    return isinstance(rate, (int, float)) and rate >= STRUCTURAL_INVESTMENT_RATE_THRESHOLD


def nodes_from_edges(corp_name: str, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {corp_name.lower(): {"id": safe_name(corp_name), "name": corp_name, "role": "reporting_company"}}
    for edge in edges:
        for field in ("from", "to"):
            name = str(edge[field])
            nodes.setdefault(name.lower(), {"id": safe_name(name), "name": name, "role": "company"})
    return list(nodes.values())


def pct_label(rate: float | None) -> str:
    if rate is None:
        return "지분율 미확인"
    if rate == int(rate):
        return f"{int(rate)}%"
    return f"{rate:.2f}".rstrip("0").rstrip(".") + "%"


def wrap_label(value: str, max_chars: int = 16, max_lines: int = 2) -> list[str]:
    value = clean_cell(value)
    if len(value) <= max_chars:
        return [value]

    words = value.split(" ")
    lines: list[str] = []
    current = ""
    if len(words) > 1:
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    else:
        lines = [value[index : index + max_chars] for index in range(0, len(value), max_chars)]

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(1, max_chars - 1)] + "..."
    return lines


def svg_text_lines(x: float, y: float, lines: list[str], class_name: str, anchor: str = "middle", line_height: int = 16) -> str:
    parts = [f"<text x='{x}' y='{y}' text-anchor='{anchor}' class='{class_name}'>"]
    for index, line in enumerate(lines):
        dy = 0 if index == 0 else line_height
        parts.append(f"<tspan x='{x}' dy='{dy}'>{html_escape(line)}</tspan>")
    parts.append("</text>")
    return "".join(parts)


def svg_card(x: float, y: float, w: float, h: float, text: str, fill: str, stroke: str, subtext: str | None = None) -> str:
    title_lines = wrap_label(text, max_chars=18 if w >= 220 else 14, max_lines=2)
    parts = [
        f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='6' fill='{fill}' stroke='{stroke}' stroke-width='1.5'/>",
        svg_text_lines(x + w / 2, y + 22, title_lines, "node-title"),
    ]
    if subtext:
        sub = html_escape(subtext)
        parts.append(f"<text x='{x + w / 2}' y='{y + h - 12}' text-anchor='middle' class='node-sub'>{sub}</text>")
    return "\n".join(parts)


def edge_rate(edge: dict[str, Any]) -> float:
    rate = edge.get("ownership_rate")
    return float(rate) if isinstance(rate, (int, float)) else -1.0


def edge_color(rate: float | None) -> str:
    if isinstance(rate, (int, float)) and rate >= 50:
        return "#2563eb"
    if isinstance(rate, (int, float)) and rate >= 20:
        return "#475569"
    return "#94a3b8"


def render_top_down_star_svg(
    corp_name: str,
    edges: list[dict[str, Any]],
    out_path: Path,
    title: str,
    source_note: str,
    max_edges: int = 48,
) -> None:
    visible_edges = sorted(edges, key=edge_rate, reverse=True)[:max_edges]
    hidden_count = max(0, len(edges) - len(visible_edges))
    cols = 4 if len(visible_edges) > 18 else 3
    card_w, card_h = 236, 62
    gap_x, gap_y = 50, 62
    width = max(1180, 90 + cols * card_w + (cols - 1) * gap_x)
    rows = max(1, (len(visible_edges) + cols - 1) // cols)
    height = 250 + rows * (card_h + gap_y) + 96
    root_w, root_h = 300, 68
    root_x, root_y = (width - root_w) / 2, 92
    grid_w = cols * card_w + (cols - 1) * gap_x
    start_x = (width - grid_w) / 2
    start_y = 242
    root_cx = root_x + root_w / 2
    root_bottom = root_y + root_h

    paths: list[str] = []
    cards: list[str] = []
    for index, edge in enumerate(visible_edges):
        col = index % cols
        row = index // cols
        x = start_x + col * (card_w + gap_x)
        y = start_y + row * (card_h + gap_y)
        child_cx = x + card_w / 2
        rate = edge.get("ownership_rate")
        stroke = edge_color(rate if isinstance(rate, (int, float)) else None)
        bus_y = y - 28
        paths.append(
            f"<path d='M {root_cx:.1f} {root_bottom:.1f} V {bus_y:.1f} H {child_cx:.1f} V {y:.1f}' "
            f"fill='none' stroke='{stroke}' stroke-width='1.5' marker-end='url(#arrow)'/>"
        )
        paths.append(
            f"<rect x='{child_cx - 36:.1f}' y='{y - 23:.1f}' width='72' height='24' rx='12' fill='#ffffff' stroke='{stroke}'/>"
        )
        paths.append(
            f"<text x='{child_cx:.1f}' y='{y - 6:.1f}' text-anchor='middle' class='edge-label' fill='{stroke}'>{html_escape(pct_label(rate if isinstance(rate, (int, float)) else None))}</text>"
        )
        subtext = str(edge.get("purpose") or edge.get("source") or "")
        cards.append(svg_card(x, y, card_w, card_h, str(edge["to"]), "#ffffff", stroke, subtext[:20] if subtext else None))

    if hidden_count:
        cards.append(
            f"<text x='{width / 2}' y='{height - 42}' text-anchor='middle' class='footer'>나머지 {hidden_count}개 관계는 JSON에 저장됨</text>"
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .title {{ font: 700 26px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .note {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #475569; }}
  .node-title {{ font: 700 14px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .node-sub {{ font: 400 11px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
  .edge-label {{ font: 700 12px 'Malgun Gothic', Arial, sans-serif; }}
  .footer {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
</style>
<defs>
  <marker id="arrow" markerWidth="10" markerHeight="10" refX="5" refY="5" orient="auto" markerUnits="strokeWidth">
    <path d="M0,0 L10,5 L0,10 z" fill="#64748b"/>
  </marker>
</defs>
<rect width="100%" height="100%" fill="#ffffff"/>
<text x="40" y="46" class="title">{html_escape(title)}</text>
<text x="40" y="70" class="note">{html_escape(source_note)}</text>
{svg_card(root_x, root_y, root_w, root_h, corp_name, "#eef6ff", "#2563eb", "보고회사")}
{"".join(paths)}
{"".join(cards)}
</svg>
"""
    out_path.write_text(svg, encoding="utf-8")


def compute_hierarchy(edges: list[dict[str, Any]], max_edges: int) -> tuple[list[dict[str, Any]], list[list[str]]]:
    selected_edges = sorted(edges, key=edge_rate, reverse=True)[:max_edges]
    nodes: set[str] = set()
    children: dict[str, list[str]] = {}
    indegree: dict[str, int] = {}
    outdegree: dict[str, int] = {}

    for edge in selected_edges:
        parent = str(edge["from"])
        child = str(edge["to"])
        nodes.update([parent, child])
        children.setdefault(parent, []).append(child)
        indegree[child] = indegree.get(child, 0) + 1
        indegree.setdefault(parent, indegree.get(parent, 0))
        outdegree[parent] = outdegree.get(parent, 0) + 1
        outdegree.setdefault(child, outdegree.get(child, 0))

    roots = sorted(
        [node for node in nodes if indegree.get(node, 0) == 0],
        key=lambda node: (-outdegree.get(node, 0), node),
    )
    if not roots and selected_edges:
        roots = [str(selected_edges[0]["from"])]

    level: dict[str, int] = {root: 0 for root in roots}
    changed = True
    guard = 0
    while changed and guard < len(nodes) + len(selected_edges) + 5:
        changed = False
        guard += 1
        for edge in selected_edges:
            parent = str(edge["from"])
            child = str(edge["to"])
            parent_level = level.get(parent, 0)
            next_level = parent_level + 1
            if child not in level or level[child] < next_level:
                level[child] = next_level
                changed = True

    for node in nodes:
        level.setdefault(node, 0)

    grouped: dict[int, list[str]] = {}
    for node, node_level in level.items():
        grouped.setdefault(node_level, []).append(node)

    levels: list[list[str]] = []
    for node_level in sorted(grouped):
        levels.append(sorted(grouped[node_level], key=lambda node: (-outdegree.get(node, 0), node)))
    return selected_edges, levels


def render_top_down_ownership_svg(
    corp_name: str,
    edges: list[dict[str, Any]],
    out_path: Path,
    title: str,
    source_note: str,
    max_edges: int = 72,
) -> None:
    visible_edges, levels = compute_hierarchy(edges, max_edges=max_edges)
    hidden_count = max(0, len(edges) - len(visible_edges))
    card_w, card_h = 230, 62
    gap_x, row_gap, level_gap = 48, 34, 92
    max_cols_per_level = 6
    max_cols = min(max((len(level_nodes) for level_nodes in levels), default=1), max_cols_per_level)
    width = max(1180, 100 + max_cols * card_w + (max_cols - 1) * gap_x)
    level_row_counts = [max(1, (len(level_nodes) + max_cols_per_level - 1) // max_cols_per_level) for level_nodes in levels]
    height = 150 + sum(row_count * card_h + (row_count - 1) * row_gap for row_count in level_row_counts)
    height += max(0, len(levels) - 1) * level_gap + 80
    start_y = 118

    positions: dict[str, tuple[float, float]] = {}
    current_y = start_y
    for level_index, level_nodes in enumerate(levels):
        rows = [level_nodes[index : index + max_cols_per_level] for index in range(0, len(level_nodes), max_cols_per_level)]
        for row_index, row_nodes in enumerate(rows):
            row_w = len(row_nodes) * card_w + max(0, len(row_nodes) - 1) * gap_x
            start_x = (width - row_w) / 2
            y = current_y + row_index * (card_h + row_gap)
            for index, node in enumerate(row_nodes):
                positions[node] = (start_x + index * (card_w + gap_x), y)
        current_y += len(rows) * card_h + max(0, len(rows) - 1) * row_gap + level_gap

    paths: list[str] = []
    for edge in visible_edges:
        parent = str(edge["from"])
        child = str(edge["to"])
        if parent not in positions or child not in positions:
            continue
        px, py = positions[parent]
        cx, cy = positions[child]
        parent_cx = px + card_w / 2
        child_cx = cx + card_w / 2
        parent_bottom = py + card_h
        mid_y = parent_bottom + (cy - parent_bottom) / 2
        rate = edge.get("ownership_rate")
        stroke = edge_color(rate if isinstance(rate, (int, float)) else None)
        paths.append(
            f"<path d='M {parent_cx:.1f} {parent_bottom:.1f} V {mid_y:.1f} H {child_cx:.1f} V {cy:.1f}' "
            f"fill='none' stroke='{stroke}' stroke-width='1.5' marker-end='url(#arrow)'/>"
        )
        label_x = (parent_cx + child_cx) / 2
        paths.append(
            f"<rect x='{label_x - 34:.1f}' y='{mid_y - 13:.1f}' width='68' height='23' rx='11.5' fill='#ffffff' stroke='{stroke}'/>"
        )
        paths.append(
            f"<text x='{label_x:.1f}' y='{mid_y + 3:.1f}' text-anchor='middle' class='edge-label' fill='{stroke}'>{html_escape(pct_label(rate if isinstance(rate, (int, float)) else None))}</text>"
        )

    cards: list[str] = []
    root_names = set(levels[0]) if levels else set()
    for node, (x, y) in positions.items():
        fill = "#eef6ff" if node in root_names else "#ffffff"
        stroke = "#2563eb" if node in root_names else "#64748b"
        subtext = "최상위 노드" if node in root_names else None
        cards.append(svg_card(x, y, card_w, card_h, node, fill, stroke, subtext))

    footer = ""
    if hidden_count:
        footer = f"<text x='{width / 2}' y='{height - 36}' text-anchor='middle' class='footer'>나머지 {hidden_count}개 관계는 JSON에 저장됨</text>"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .title {{ font: 700 26px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .note {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #475569; }}
  .node-title {{ font: 700 14px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .node-sub {{ font: 400 11px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
  .edge-label {{ font: 700 12px 'Malgun Gothic', Arial, sans-serif; }}
  .footer {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
</style>
<defs>
  <marker id="arrow" markerWidth="10" markerHeight="10" refX="5" refY="5" orient="auto" markerUnits="strokeWidth">
    <path d="M0,0 L10,5 L0,10 z" fill="#64748b"/>
  </marker>
</defs>
<rect width="100%" height="100%" fill="#ffffff"/>
<text x="40" y="46" class="title">{html_escape(title)}</text>
<text x="40" y="70" class="note">{html_escape(source_note)}</text>
{"".join(paths)}
{"".join(cards)}
{footer}
</svg>
"""
    out_path.write_text(svg, encoding="utf-8")


def split_edges_by_rate(edges: list[dict[str, Any]]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    buckets = [
        ("지배/종속", "50% 이상", []),
        ("주요 지분", "20% 이상 50% 미만", []),
        ("기타 확인 지분", "20% 미만", []),
    ]
    unknown: list[dict[str, Any]] = []
    for edge in sorted(
        edges,
        key=lambda item: (
            item.get("ownership_rate") is not None,
            float(item.get("ownership_rate") or -1),
        ),
        reverse=True,
    ):
        rate = edge.get("ownership_rate")
        if not isinstance(rate, (int, float)):
            unknown.append(edge)
        elif rate >= 50:
            buckets[0][2].append(edge)
        elif rate >= 20:
            buckets[1][2].append(edge)
        else:
            buckets[2][2].append(edge)
    if unknown:
        buckets.append(("지분율 미확인", "공시 표 내 수치 없음", unknown))
    return buckets


def render_investment_board_svg(
    corp_name: str,
    edges: list[dict[str, Any]],
    out_path: Path,
    title: str,
    source_note: str,
    max_items_per_bucket: int = 14,
) -> None:
    buckets = split_edges_by_rate(edges)
    width = 1220
    col_w = 354
    col_gap = 34
    visible_buckets = [bucket for bucket in buckets if bucket[2]]
    if not visible_buckets:
        visible_buckets = buckets[:3]
    max_rows = max((min(len(bucket[2]), max_items_per_bucket) for bucket in visible_buckets), default=1)
    height = 260 + max_rows * 68 + 92
    total_w = len(visible_buckets) * col_w + max(0, len(visible_buckets) - 1) * col_gap
    start_x = (width - total_w) / 2
    root_w, root_h = 300, 66
    root_x, root_y = (width - root_w) / 2, 96

    pieces = [
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .title {{ font: 700 26px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .note {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #475569; }}
  .chip {{ font: 700 12px 'Malgun Gothic', Arial, sans-serif; fill: #1e40af; }}
  .node-title {{ font: 700 14px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .node-sub {{ font: 400 11px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
  .bucket-title {{ font: 700 16px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .bucket-sub {{ font: 400 12px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
  .rate {{ font: 700 12px 'Malgun Gothic', Arial, sans-serif; fill: #ffffff; }}
  .footer {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
</style>
<rect width="100%" height="100%" fill="#ffffff"/>
<text x="40" y="46" class="title">{html_escape(title)}</text>
<text x="40" y="70" class="note">{html_escape(source_note)}</text>
<rect x="40" y="86" width="112" height="28" rx="14" fill="#dbeafe"/>
<text x="96" y="105" text-anchor="middle" class="chip">표 기반 생성</text>
<rect x="162" y="86" width="122" height="28" rx="14" fill="#dcfce7"/>
<text x="223" y="105" text-anchor="middle" class="chip">지분율 확인</text>
{svg_card(root_x, root_y, root_w, root_h, corp_name, "#eff6ff", "#2563eb", "보고회사")}
"""
    ]
    root_cx = root_x + root_w / 2
    for bucket_index, (bucket_title, bucket_sub, bucket_edges) in enumerate(visible_buckets):
        x = start_x + bucket_index * (col_w + col_gap)
        header_y = 210
        col_h = 74 + min(len(bucket_edges), max_items_per_bucket) * 68 + (24 if len(bucket_edges) > max_items_per_bucket else 0)
        col_cx = x + col_w / 2
        pieces.append(
            f"<path d='M {root_cx:.1f} {root_y + root_h:.1f} C {root_cx:.1f} 184, {col_cx:.1f} 184, {col_cx:.1f} {header_y:.1f}' "
            "fill='none' stroke='#cbd5e1' stroke-width='1.3'/>"
        )
        pieces.append(f"<rect x='{x}' y='{header_y}' width='{col_w}' height='{col_h}' rx='8' fill='#f8fafc' stroke='#cbd5e1'/>")
        pieces.append(f"<text x='{x + 18}' y='{header_y + 31}' class='bucket-title'>{html_escape(bucket_title)} ({len(bucket_edges)}개)</text>")
        pieces.append(f"<text x='{x + 18}' y='{header_y + 52}' class='bucket-sub'>{html_escape(bucket_sub)}</text>")
        for row_index, edge in enumerate(bucket_edges[:max_items_per_bucket]):
            y = header_y + 74 + row_index * 68
            rate = edge.get("ownership_rate")
            stroke = "#2563eb" if isinstance(rate, (int, float)) and rate >= 50 else "#64748b"
            pieces.append(f"<rect x='{x + 16}' y='{y}' width='{col_w - 32}' height='54' rx='6' fill='#ffffff' stroke='{stroke}'/>")
            pieces.append(svg_text_lines(x + 32, y + 22, wrap_label(str(edge["to"]), max_chars=20, max_lines=2), "node-title", anchor="start"))
            badge_w = 70
            pieces.append(f"<rect x='{x + col_w - 16 - badge_w}' y='{y + 15}' width='{badge_w}' height='25' rx='12.5' fill='{stroke}'/>")
            pieces.append(
                f"<text x='{x + col_w - 16 - badge_w / 2}' y='{y + 32}' text-anchor='middle' class='rate'>{html_escape(pct_label(rate if isinstance(rate, (int, float)) else None))}</text>"
            )
        if len(bucket_edges) > max_items_per_bucket:
            pieces.append(
                f"<text x='{x + 18}' y='{header_y + 74 + max_items_per_bucket * 68 + 14}' class='footer'>외 {len(bucket_edges) - max_items_per_bucket}개는 JSON에 저장됨</text>"
            )
    pieces.append("</svg>")
    out_path.write_text("".join(pieces), encoding="utf-8")


def render_graph_svg(
    corp_name: str,
    edges: list[dict[str, Any]],
    out_path: Path,
    title: str,
    source_note: str,
    max_edges: int = 36,
) -> None:
    visible_edges = sorted(
        edges,
        key=lambda edge: (
            edge.get("ownership_rate") is not None,
            float(edge.get("ownership_rate") or -1),
        ),
        reverse=True,
    )[:max_edges]
    hidden_count = max(0, len(edges) - len(visible_edges))
    cols = 4 if len(visible_edges) > 18 else 3
    card_w, card_h = 230, 60
    gap_x, gap_y = 42, 54
    width = 1120
    rows = max(1, (len(visible_edges) + cols - 1) // cols)
    height = 240 + rows * (card_h + gap_y) + 90
    root_w, root_h = 280, 66
    root_x, root_y = (width - root_w) / 2, 92
    grid_w = cols * card_w + (cols - 1) * gap_x
    start_x = (width - grid_w) / 2
    start_y = 230

    lines: list[str] = []
    cards: list[str] = []
    root_cx = root_x + root_w / 2
    root_bottom = root_y + root_h

    for index, edge in enumerate(visible_edges):
        col = index % cols
        row = index // cols
        x = start_x + col * (card_w + gap_x)
        y = start_y + row * (card_h + gap_y)
        child_cx = x + card_w / 2
        rate = edge.get("ownership_rate")
        stroke = "#2563eb" if isinstance(rate, (int, float)) and rate >= 50 else "#64748b"
        label = pct_label(rate if isinstance(rate, (int, float)) else None)
        dash = "" if isinstance(rate, (int, float)) else " stroke-dasharray='5 5'"
        mid_y = root_bottom + 24 + row * 4
        lines.append(
            f"<path d='M {root_cx:.1f} {root_bottom:.1f} C {root_cx:.1f} {mid_y:.1f}, {child_cx:.1f} {mid_y:.1f}, {child_cx:.1f} {y:.1f}' "
            f"fill='none' stroke='{stroke}' stroke-width='1.4'{dash}/>"
        )
        lines.append(
            f"<text x='{child_cx}' y='{y - 8}' text-anchor='middle' class='edge-label' fill='{stroke}'>{html_escape(label)}</text>"
        )
        subtext = str(edge.get("purpose") or edge.get("source") or "")
        cards.append(svg_card(x, y, card_w, card_h, str(edge["to"]), "#f8fafc", stroke, subtext[:22] if subtext else None))

    if hidden_count:
        cards.append(
            f"<text x='{width / 2}' y='{height - 42}' text-anchor='middle' class='footer'>나머지 {hidden_count}개 관계는 메타데이터 JSON에 저장됨</text>"
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .title {{ font: 700 26px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .note {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #475569; }}
  .node-title {{ font: 700 15px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .node-sub {{ font: 400 11px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
  .edge-label {{ font: 700 12px 'Malgun Gothic', Arial, sans-serif; }}
  .footer {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
</style>
<rect width="100%" height="100%" fill="#ffffff"/>
<text x="40" y="46" class="title">{html_escape(title)}</text>
<text x="40" y="70" class="note">{html_escape(source_note)}</text>
{svg_card(root_x, root_y, root_w, root_h, corp_name, "#eff6ff", "#2563eb", "보고회사")}
{"".join(lines)}
{"".join(cards)}
</svg>
"""
    out_path.write_text(svg, encoding="utf-8")


def render_edge_list_svg(
    corp_name: str,
    edges: list[dict[str, Any]],
    out_path: Path,
    title: str,
    source_note: str,
    max_edges: int = 42,
) -> None:
    visible_edges = sorted(
        edges,
        key=lambda edge: (
            edge.get("ownership_rate") is not None,
            float(edge.get("ownership_rate") or -1),
        ),
        reverse=True,
    )[:max_edges]
    hidden_count = max(0, len(edges) - len(visible_edges))
    width = 1180
    row_h = 82
    height = 130 + max(1, len(visible_edges)) * row_h + 70
    left_x, right_x = 70, 705
    card_w, card_h = 345, 54
    arrow_start = left_x + card_w + 18
    arrow_end = right_x - 18
    pieces = [
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .title {{ font: 700 26px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .note {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #475569; }}
  .node-title {{ font: 700 14px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .node-sub {{ font: 400 11px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
  .edge-label {{ font: 700 12px 'Malgun Gothic', Arial, sans-serif; }}
  .footer {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
</style>
<defs>
  <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
    <path d="M0,0 L0,6 L9,3 z" fill="#475569"/>
  </marker>
</defs>
<rect width="100%" height="100%" fill="#ffffff"/>
<text x="40" y="46" class="title">{html_escape(title)}</text>
<text x="40" y="70" class="note">{html_escape(source_note)}</text>
<text x="{left_x}" y="104" class="note">출자사</text>
<text x="{right_x}" y="104" class="note">피출자사</text>
"""
    ]
    for index, edge in enumerate(visible_edges):
        y = 125 + index * row_h
        rate = edge.get("ownership_rate")
        stroke = "#2563eb" if isinstance(rate, (int, float)) and rate >= 50 else "#64748b"
        label = pct_label(rate if isinstance(rate, (int, float)) else None)
        pieces.append(svg_card(left_x, y, card_w, card_h, str(edge["from"]), "#eff6ff", "#2563eb"))
        pieces.append(svg_card(right_x, y, card_w, card_h, str(edge["to"]), "#f8fafc", stroke))
        mid_y = y + card_h / 2
        pieces.append(
            f"<line x1='{arrow_start}' y1='{mid_y}' x2='{arrow_end}' y2='{mid_y}' stroke='{stroke}' stroke-width='1.6' marker-end='url(#arrow)'/>"
        )
        pieces.append(
            f"<rect x='{(arrow_start + arrow_end) / 2 - 38}' y='{mid_y - 17}' width='76' height='24' rx='12' fill='#ffffff' stroke='{stroke}'/>"
        )
        pieces.append(
            f"<text x='{(arrow_start + arrow_end) / 2}' y='{mid_y}' text-anchor='middle' dominant-baseline='central' class='edge-label' fill='{stroke}'>{html_escape(label)}</text>"
        )
    if hidden_count:
        pieces.append(
            f"<text x='{width / 2}' y='{height - 38}' text-anchor='middle' class='footer'>나머지 {hidden_count}개 관계는 메타데이터 JSON에 저장됨</text>"
        )
    pieces.append("</svg>")
    out_path.write_text("".join(pieces), encoding="utf-8")


def render_directory_svg(corp_name: str, companies: list[dict[str, Any]], out_path: Path, max_items_per_group: int = 34) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for company in companies:
        groups.setdefault(str(company.get("listing") or "미분류"), []).append(company)
    ordered_groups = [(name, groups[name]) for name in ("상장", "비상장", "미분류") if name in groups]
    width = 1120
    group_w = 320
    group_gap = 38
    max_visible = max((min(len(items), max_items_per_group) for _, items in ordered_groups), default=1)
    height = 260 + max_visible * 24 + 110
    root_w, root_h = 280, 66
    root_x, root_y = (width - root_w) / 2, 92
    total_group_w = len(ordered_groups) * group_w + max(0, len(ordered_groups) - 1) * group_gap
    start_x = (width - total_group_w) / 2
    start_y = 230

    pieces = [
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .title {{ font: 700 26px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .note {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #475569; }}
  .node-title {{ font: 700 15px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .node-sub {{ font: 400 11px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
  .group-title {{ font: 700 15px 'Malgun Gothic', Arial, sans-serif; fill: #0f172a; }}
  .item {{ font: 400 12px 'Malgun Gothic', Arial, sans-serif; fill: #334155; }}
  .footer {{ font: 400 13px 'Malgun Gothic', Arial, sans-serif; fill: #64748b; }}
</style>
<rect width="100%" height="100%" fill="#ffffff"/>
<text x="40" y="46" class="title">{html_escape(corp_name)} 계열회사 구성도</text>
<text x="40" y="70" class="note">계열회사 목록 기반 생성 - 지분율/소유관계는 공시 본문에서 확인된 범위가 아님</text>
{svg_card(root_x, root_y, root_w, root_h, corp_name, "#eff6ff", "#2563eb", "기업집단")}
"""
    ]
    root_cx = root_x + root_w / 2
    for index, (group_name, items) in enumerate(ordered_groups):
        x = start_x + index * (group_w + group_gap)
        y = start_y
        group_h = 74 + min(len(items), max_items_per_group) * 24 + (24 if len(items) > max_items_per_group else 0)
        group_cx = x + group_w / 2
        pieces.append(
            f"<path d='M {root_cx:.1f} {root_y + root_h:.1f} C {root_cx:.1f} 186, {group_cx:.1f} 186, {group_cx:.1f} {y:.1f}' "
            "fill='none' stroke='#94a3b8' stroke-width='1.3' stroke-dasharray='5 5'/>"
        )
        pieces.append(f"<rect x='{x}' y='{y}' width='{group_w}' height='{group_h}' rx='6' fill='#f8fafc' stroke='#cbd5e1'/>")
        pieces.append(
            f"<text x='{x + 18}' y='{y + 30}' class='group-title'>{html_escape(group_name)} 계열회사 ({len(items)}개)</text>"
        )
        for row_index, company in enumerate(items[:max_items_per_group]):
            pieces.append(
                f"<text x='{x + 18}' y='{y + 62 + row_index * 24}' class='item'>{html_escape(company['name'])}</text>"
            )
        if len(items) > max_items_per_group:
            pieces.append(
                f"<text x='{x + 18}' y='{y + 62 + max_items_per_group * 24}' class='footer'>외 {len(items) - max_items_per_group}개</text>"
            )
    pieces.append("</svg>")
    out_path.write_text("".join(pieces), encoding="utf-8")


def build_generated_visual(meta: dict[str, Any], chunks: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    corp_name = display_company_name(str(meta.get("corp_name") or meta.get("stock_code") or "회사"))
    direct_edges = parse_direct_matrix_edges(chunks)
    investment_edges = parse_investment_edges(chunks, corp_name)
    investment_note_edges = parse_investment_note_edges(chunks, corp_name)
    subsidiary_edges = parse_subsidiary_edges(chunks, corp_name)
    plain_subsidiary_edges = parse_plain_subsidiary_detail_edges(chunks, corp_name)
    numeric_subsidiary_edges = parse_numeric_subsidiary_detail_edges(chunks, corp_name)
    structural_investment_edges = [edge for edge in investment_edges if is_structural_investment_edge(edge)]
    affiliates = parse_affiliate_list(chunks)

    if direct_edges:
        visual_path = out_dir / "affiliate_ownership_graph.svg"
        render_top_down_ownership_svg(
            corp_name,
            direct_edges,
            visual_path,
            f"{corp_name} 출자계통도",
            "공시 내 출자계통도 표 기반 생성 - 각 행은 출자사에서 피출자사로 향하는 확인된 지분관계",
        )
        source_type = "generated_ownership_graph"
        edges = direct_edges
    elif structural_investment_edges:
        visual_path = out_dir / "affiliate_investment_graph.svg"
        render_top_down_star_svg(
            corp_name,
            structural_investment_edges,
            visual_path,
            f"{corp_name} 구조성 타법인출자",
            "타법인출자 현황(상세) 중 경영참여/계열회사 또는 20% 이상 지분처럼 구조 근거가 있는 관계만 표시",
        )
        source_type = "generated_control_investment_graph"
        edges = structural_investment_edges
    elif subsidiary_edges:
        visual_path = out_dir / "affiliate_subsidiary_graph.svg"
        render_top_down_star_svg(
            corp_name,
            subsidiary_edges,
            visual_path,
            f"{corp_name} 연결대상 종속회사 구조",
            "연결대상 종속회사 현황 표 기반 생성 - 지분율이 확인된 종속회사 관계를 표시",
        )
        source_type = "generated_subsidiary_graph"
        edges = subsidiary_edges
    elif numeric_subsidiary_edges:
        visual_path = out_dir / "affiliate_numeric_subsidiary_graph.svg"
        render_top_down_star_svg(
            corp_name,
            numeric_subsidiary_edges,
            visual_path,
            f"{corp_name} 종속기업 상세 구조",
            "재무제표 주석의 숫자형 종속기업 현황 기반 생성 - 지분율이 확인된 관계를 표시",
        )
        source_type = "generated_numeric_subsidiary_graph"
        edges = numeric_subsidiary_edges
    elif plain_subsidiary_edges:
        visual_path = out_dir / "affiliate_plain_subsidiary_graph.svg"
        render_top_down_star_svg(
            corp_name,
            plain_subsidiary_edges,
            visual_path,
            f"{corp_name} 종속기업 상세 구조",
            "재무제표 주석의 줄글형 종속기업 상세목록 기반 생성 - 지분율이 확인된 관계를 표시",
        )
        source_type = "generated_plain_subsidiary_graph"
        edges = plain_subsidiary_edges
    elif investment_note_edges:
        visual_path = out_dir / "affiliate_investment_note_graph.svg"
        render_top_down_star_svg(
            corp_name,
            investment_note_edges,
            visual_path,
            f"{corp_name} 종속기업투자 구조",
            "재무제표 주석 종속기업투자주식 블록 기반 생성 - 직접 보유한 종속기업 지분을 표시",
        )
        source_type = "generated_investment_note_graph"
        edges = investment_note_edges
    elif affiliates:
        visual_path = out_dir / "affiliate_directory.svg"
        render_directory_svg(corp_name, affiliates, visual_path)
        source_type = "generated_affiliate_directory"
        edges = []
    else:
        visual_path = None
        source_type = "insufficient_data"
        edges = []

    return {
        "source_type": source_type,
        "visual_file_type": "svg" if visual_path else None,
        "visual_path": str(visual_path) if visual_path else None,
        "has_original_image": False,
        "has_ownership_rate": any(edge.get("ownership_rate") is not None for edge in edges),
        "nodes": nodes_from_edges(corp_name, edges),
        "edges": edges,
        "supporting_investment_edges": [edge for edge in investment_edges if edge not in edges],
        "supporting_investment_note_edges": investment_note_edges if investment_note_edges != edges else [],
        "supporting_subsidiary_edges": subsidiary_edges if subsidiary_edges != edges else [],
        "supporting_numeric_subsidiary_edges": numeric_subsidiary_edges if numeric_subsidiary_edges != edges else [],
        "supporting_plain_subsidiary_edges": plain_subsidiary_edges if plain_subsidiary_edges != edges else [],
        "investment_edges_total": len(investment_edges),
        "structural_investment_edges_total": len(structural_investment_edges),
        "excluded_investment_edges_total": len(investment_edges) - len(structural_investment_edges),
        "investment_note_edges_total": len(investment_note_edges),
        "subsidiary_edges_total": len(subsidiary_edges),
        "numeric_subsidiary_edges_total": len(numeric_subsidiary_edges),
        "plain_subsidiary_edges_total": len(plain_subsidiary_edges),
        "visual_edges_total": len(edges),
        "affiliate_companies": affiliates,
    }


def build_for_rag_file(
    rag_file: Path,
    out_base_dir: Path = DEFAULT_OUT_DIR,
    try_dart_image: bool = True,
    refresh: bool = False,
) -> dict[str, Any]:
    chunks = load_chunks(rag_file)
    meta = chunks[0]
    stock_code = str(meta.get("stock_code") or rag_file.name.split("_", 1)[0])
    corp_name = str(meta.get("corp_name") or rag_file.stem)
    out_dir = out_base_dir / f"{stock_code}_{safe_name(corp_name)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = out_dir / "affiliate_visual_metadata.json"
    extracted_data_path = out_dir / "affiliate_visual_data.json"

    if metadata_path.exists() and not refresh:
        with metadata_path.open("r", encoding="utf-8") as f:
            cached = json.load(f)
        cached["cache_hit"] = True
        return cached

    result: dict[str, Any] | None = reuse_existing_original_image(meta, out_dir)
    errors: list[str] = []
    if try_dart_image and result is None:
        try:
            result = try_download_original_image(meta, out_dir)
        except Exception as exc:
            errors.append(f"DART 원본 이미지 확인 실패: {type(exc).__name__}: {exc}")

    if result is None:
        result = build_generated_visual(meta, chunks, out_dir)

    result.update(
        {
            "stock_code": stock_code,
            "corp_name": corp_name,
            "corp_code": meta.get("corp_code", ""),
            "display_corp_name": display_company_name(corp_name),
            "report_nm": meta.get("report_nm", ""),
            "report_kind": meta.get("report_kind", ""),
            "rcept_no": meta.get("rcept_no", ""),
            "rcept_dt": meta.get("rcept_dt", ""),
            "source_url": meta.get("source_url", ""),
            "rag_file": str(rag_file),
            "metadata_path": str(metadata_path),
            "extracted_data_path": str(extracted_data_path),
            "errors": errors,
            "created_at": now_iso(),
            "cache_hit": False,
        }
    )

    extracted_data = {
        "nodes": result.get("nodes", []),
        "edges": result.get("edges", []),
        "supporting_investment_edges": result.get("supporting_investment_edges", []),
        "supporting_investment_note_edges": result.get("supporting_investment_note_edges", []),
        "supporting_subsidiary_edges": result.get("supporting_subsidiary_edges", []),
        "supporting_numeric_subsidiary_edges": result.get("supporting_numeric_subsidiary_edges", []),
        "supporting_plain_subsidiary_edges": result.get("supporting_plain_subsidiary_edges", []),
        "affiliate_companies": result.get("affiliate_companies", []),
    }
    with extracted_data_path.open("w", encoding="utf-8") as f:
        json.dump(extracted_data, f, ensure_ascii=False, indent=2)
    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def build_for_target(target: str, out_base_dir: Path = DEFAULT_OUT_DIR, try_dart_image: bool = True, refresh: bool = False) -> dict[str, Any]:
    return build_for_rag_file(find_rag_file(target), out_base_dir=out_base_dir, try_dart_image=try_dart_image, refresh=refresh)


def iter_all_rag_files(limit: int | None = None) -> list[Path]:
    files = sorted(RAG_DIR.glob("*_annual_chunks.jsonl"))
    return files[:limit] if limit else files


def print_result(result: dict[str, Any]) -> None:
    visual_path = result.get("visual_path") or "-"
    print(f"[{result.get('stock_code')}] {result.get('corp_name')}")
    print(f"  source_type: {result.get('source_type')}")
    print(f"  visual: {visual_path}")
    print(f"  nodes/edges/affiliates: {len(result.get('nodes', []))}/{len(result.get('edges', []))}/{len(result.get('affiliate_companies', []))}")
    if result.get("errors"):
        print(f"  errors: {' | '.join(result['errors'])}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DART 계열회사 원본 이미지 추출 및 fallback 시각화 생성")
    parser.add_argument("target", nargs="?", help="종목코드 또는 회사명")
    parser.add_argument("--all", action="store_true", help="RAG 폴더의 전체 JSONL 실행")
    parser.add_argument("--limit", type=int, default=None, help="--all 실행 시 처리할 최대 파일 수")
    parser.add_argument("--no-dart", action="store_true", help="DART 원본 이미지 확인을 건너뛰고 JSONL 기반으로 생성")
    parser.add_argument("--refresh", action="store_true", help="기존 결과가 있어도 다시 생성")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR), help="결과 저장 폴더")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_base_dir = Path(args.output_dir)
    out_base_dir.mkdir(parents=True, exist_ok=True)

    if args.all:
        files = iter_all_rag_files(args.limit)
        print(f"실행 대상: {len(files)}개 JSONL")
        success = 0
        for index, path in enumerate(files, start=1):
            print(f"\n=== {index}/{len(files)} {path.name} ===")
            try:
                result = build_for_rag_file(path, out_base_dir=out_base_dir, try_dart_image=not args.no_dart, refresh=args.refresh)
                print_result(result)
                success += 1
            except Exception as exc:
                print(f"  실패: {type(exc).__name__}: {exc}")
        print(f"\n완료: {success}/{len(files)}")
        return 0 if success == len(files) else 1

    if not args.target:
        print("target 또는 --all 중 하나가 필요합니다.", file=sys.stderr)
        return 2

    result = build_for_target(args.target, out_base_dir=out_base_dir, try_dart_image=not args.no_dart, refresh=args.refresh)
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
