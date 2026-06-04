# %%
"""
계열회사 시각화 검증용 노트북 스타일 스크립트.

VS Code/Jupyter에서 셀 단위로 실행하거나, 일반 Python 파일처럼 실행해도 됩니다.
최종 반복 실행은 scripts/build_affiliate_visualization.py를 사용합니다.
"""

from pathlib import Path
import sys


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "RAG").exists():
            return path
    return start


ROOT = find_project_root(Path(__file__).resolve().parents[1])
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if not SCRIPTS.exists():
    SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_affiliate_visualization import build_for_target  # noqa: E402


OUT_DIR = ROOT / "output" / "affiliate_visualization_probe"


# %%
# 1. KT: 원본 DART 이미지가 있는 대표 케이스
kt_result = build_for_target("030200", out_base_dir=OUT_DIR, try_dart_image=True, refresh=True)
kt_result


# %%
# 2. 삼성전자: 원본 이미지가 없거나 실패하면 JSONL 기반 fallback 확인
samsung_result = build_for_target("005930", out_base_dir=OUT_DIR, try_dart_image=False, refresh=True)
samsung_result


# %%
# 3. 삼양홀딩스: 출자계통도 표 기반 edge 추출 확인
samyang_result = build_for_target("000070", out_base_dir=OUT_DIR, try_dart_image=False, refresh=True)
samyang_result


# %%
# 4. 주요 결과만 보기
for result in [kt_result, samsung_result, samyang_result]:
    print(f"[{result['stock_code']}] {result['corp_name']}")
    print(f"  source_type: {result['source_type']}")
    print(f"  visual_path: {result['visual_path']}")
    print(f"  nodes: {len(result.get('nodes', []))}")
    print(f"  edges: {len(result.get('edges', []))}")
    print(f"  affiliates: {len(result.get('affiliate_companies', []))}")
    print()
