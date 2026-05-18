"""
generate_report.py
───────────────────
FILMN9 POC — 기업 리포트 HTML 생성기.

사용법
──────
# 아모레퍼시픽 (기본)
python generate_report.py

# 특정 종목
python generate_report.py 000720   (현대건설)
python generate_report.py 006800   (미래에셋증권)
python generate_report.py 240810   (원익IPS)
python generate_report.py 090430   (아모레퍼시픽)

출력
────
outputs/{stock_code}_{corp_name}_report.html
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.processors.data_aggregator import aggregate
from src.components.html_builder    import build_html

# POC 4개 기업 corp_code 매핑
CORP_MAP = {
    "090430": "00583424",   # 아모레퍼시픽
    "000720": "00102266",   # 현대건설
    "006800": "00215821",   # 미래에셋증권
    "240810": "01011831",   # 원익IPS
}

OUTPUT_DIR = _ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


def generate(stock_code: str = "090430") -> Path:
    corp_code = CORP_MAP.get(stock_code)
    if not corp_code:
        # JSONL에서 corp_code 자동 탐색
        from src.collectors.jsonl_loader import load_all
        from src.app_config import RAG_DIR
        import json, glob
        matches = list(RAG_DIR.glob(f"{stock_code}_*_annual_chunks.jsonl"))
        if matches:
            with open(matches[0], encoding="utf-8") as f:
                first = json.loads(f.readline())
                corp_code = first.get("corp_code", "")
        if not corp_code:
            print(f"[오류] {stock_code} corp_code 를 찾을 수 없습니다.")
            sys.exit(1)

    ticker_yf = f"{stock_code}.KS"

    # 데이터 수집 + 통합
    data = aggregate(
        stock_code = stock_code,
        corp_code  = corp_code,
        ticker_yf  = ticker_yf,
    )

    # HTML 생성
    html = build_html(data)

    # 파일 저장
    corp_name = data["meta"]["name"].replace("(주)","").replace("/","_").strip()
    out_path  = OUTPUT_DIR / f"{stock_code}_{corp_name}_report.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"\n[OK] 리포트 생성 완료!")
    print(f"   파일: {out_path}")
    print(f"   브라우저에서 열기: {out_path.as_uri()}")
    return out_path


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "090430"
    generate(code)
