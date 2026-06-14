# -*- coding: utf-8 -*-
"""FINSIGHT 정적 파일 → S3 업로드.
대상: outputs/sankey (손익흐름도 HTML) + data/valuation_results (밸류 JSON).
사용:
  pip install boto3
  aws configure   (액세스키 등록)
  set FINSIGHT_S3_BUCKET=finsight-static-xxxx
  python s3_upload_static.py
※ 키/비밀번호는 코드에 넣지 않음 — AWS CLI 자격증명(aws configure)만 사용.
"""
import os, mimetypes, sys
from pathlib import Path

try:
    import boto3
except ImportError:
    sys.exit("boto3 미설치 → 먼저:  pip install boto3")

ROOT = Path(r"C:\Users\Admin\FILMN9")
BUCKET = os.environ.get("FINSIGHT_S3_BUCKET")
if not BUCKET:
    sys.exit("환경변수 FINSIGHT_S3_BUCKET 를 먼저 설정하세요 (예: set FINSIGHT_S3_BUCKET=finsight-static-xxxx)")

# (로컬폴더, S3 prefix)
TARGETS = [
    (ROOT / "outputs" / "sankey",          "sankey"),
    (ROOT / "data" / "valuation_results",  "valuation_results"),
    # 계열사 이미지 폴더가 생기면 여기에 추가:
    # (ROOT / "기업개요_파트" / "계열회사시각화" / "output", "affiliate"),
]

s3 = boto3.client("s3")

def ctype(p: Path) -> str:
    t, _ = mimetypes.guess_type(str(p))
    return t or "application/octet-stream"

total = 0
for folder, prefix in TARGETS:
    if not folder.exists():
        print(f"  (건너뜀) 폴더 없음: {folder}")
        continue
    files = [f for f in folder.rglob("*") if f.is_file()]
    print(f"▶ {prefix}: {len(files):,}개 업로드 시작 ({folder})")
    for i, f in enumerate(files, 1):
        key = f"{prefix}/{f.relative_to(folder).as_posix()}"
        s3.upload_file(str(f), BUCKET, key, ExtraArgs={"ContentType": ctype(f)})
        total += 1
        if i % 500 == 0:
            print(f"    ... {i:,}/{len(files):,}")
    print(f"  완료: {prefix}")

print(f"\n=== 총 {total:,}개 파일을 s3://{BUCKET} 에 업로드 완료 ===")
print("확인:  aws s3 ls s3://%s/sankey/ | head" % BUCKET)
