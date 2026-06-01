"""
db/check_demo10.py
==================
시연 10종목의 데이터 가용성 점검.
- corp_code_map.json 에서 corp_code, JSONL 보유 여부 확인
- data/parsed/{code}/ 이미 적재된 파일 확인
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
cmap_path  = ROOT / "data" / "corp_code_map.json"
parsed_dir = ROOT / "data" / "parsed"

cmap = json.loads(cmap_path.read_text(encoding="utf-8"))
by_sc = cmap["by_stock_code"]

DEMO_10 = [
    ("090430", "아모레퍼시픽"),
    ("240810", "원익IPS"),
    ("000720", "현대건설"),
    ("006800", "미래에셋증권"),
    ("035420", "NAVER"),
    ("005380", "현대차"),
    ("373220", "LG에너지솔루션"),
    ("207940", "삼성바이오로직스"),
    ("017670", "SK텔레콤"),
    ("097950", "CJ제일제당"),
]

print(f'{"code":<8} {"이름":<18} {"corp_code":<11} {"JSONL":<6} {"market":<8} {"이미적재":<8}')
print("-" * 72)

for code, name in DEMO_10:
    info = by_sc.get(code)
    if not info:
        print(f"{code:<8} {name:<18} ❌ corp_map 미포함")
        continue

    # 이미 적재된 JSON 파일 확인
    p_dir = parsed_dir / code
    files = []
    if p_dir.exists():
        if (p_dir / "company_info.json").exists(): files.append("ci")
        if (p_dir / "financials.json").exists():   files.append("fin")
        if (p_dir / "ohlcv.json").exists():        files.append("ohlcv")
    file_str = "/".join(files) if files else "없음"

    jsonl = "O" if info["has_jsonl"] else "X"
    print(f"{code:<8} {info['corp_name'][:16]:<18} {info['corp_code']:<11} {jsonl:<6} {info['market']:<8} {file_str}")
