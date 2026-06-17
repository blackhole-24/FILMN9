"""
api/routers/affiliate.py
========================
계열회사 시각화(소유지분도/구조도) 서빙.

데이터 소스
----------
  기업개요_파트/계열회사시각화/  (기업개요 파트 모듈, Git 추적 샘플)
    samples/{code}_*/original_affiliate_diagram.*   ← DART 원본 이미지(최우선)
    samples_structure_diagrams/{code}_*/*_affiliate_structure.svg
    samples_graphviz_style/{code}_*_graphviz_style.svg
    samples/{code}_*/affiliate_*.svg
  ※ 전체 산출물(output/affiliate_visualization, 2,599종목)은 Git 제외 → 현재는 샘플만.
  ※ 없으면 available:false → 프론트 "데이터 준비중"(NO-MOCK).

엔드포인트
----------
  GET /api/affiliate/{code}        메타(available·source_type·file_url)
  GET /api/affiliate/{code}/file   실제 SVG/이미지 바이트
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

router = APIRouter()

_ROOT = Path(__file__).resolve().parent.parent.parent
_BASE = _ROOT / "기업개요_파트" / "계열회사시각화"

# ─── S3 정적 파일 (환경변수로 켜짐). 설정 시 S3 우선, 실패 시 로컬 폴백. ───
_S3_BUCKET = os.getenv("S3_STATIC_BUCKET", "").strip()
_s3_client = None


def _s3():
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    return _s3_client


def _find_s3(code: str):
    """S3 affiliate/{code}_*/*_affiliate_structure.svg 키 탐색. 반환: key 또는 None."""
    if not _S3_BUCKET:
        return None
    try:
        resp = _s3().list_objects_v2(Bucket=_S3_BUCKET, Prefix=f"affiliate/{code.strip()}_")
        for o in resp.get("Contents", []):
            if o["Key"].endswith("_affiliate_structure.svg"):
                return o["Key"]
    except Exception:
        return None
    return None
# 전 종목 배치 산출물(2026-06-15 전수 생성). 샘플에 없으면 여기서 찾음.
_OUT_BATCH = _ROOT / "output" / "affiliate_structure_batch"        # 구조도 SVG (2단계)
_OUT_VIS = _ROOT / "output" / "affiliate_visualization"            # 투자관계 그래프 (1단계)

_MEDIA = {
    ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif",
}


def _find(code: str):
    """종목코드로 최적 시각화 파일 1개 탐색. (품질 우선순위: 원본이미지 > 구조도 > graphviz > 기본생성)
    반환: (Path, source_type) 또는 (None, None)."""
    code = code.strip()
    # ※ _BASE(기업개요_파트)가 없어도(예: EC2엔 미배포) 배치 폴더(output/*)는 확인해야 하므로 조기 종료하지 않음.

    # 1) DART 원본 이미지 (최우선)
    sdir = _BASE / "samples"
    if sdir.exists():
        for d in sorted(sdir.glob(f"{code}_*")):
            if d.is_dir():
                for img in sorted(d.glob("original_affiliate_diagram.*")):
                    return img, "original_dart_image"

    # 2) 계열회사 구조도(개선판) SVG — 샘플
    stdir = _BASE / "samples_structure_diagrams"
    if stdir.exists():
        for d in sorted(stdir.glob(f"{code}_*")):
            if d.is_dir():
                for svg in sorted(d.glob("*_affiliate_structure.svg")):
                    return svg, "structure_diagram"

    # 2b) 전 종목 배치 구조도 SVG (output/affiliate_structure_batch)
    if _OUT_BATCH.exists():
        for d in sorted(_OUT_BATCH.glob(f"{code}_*")):
            if d.is_dir():
                for svg in sorted(d.glob("*_affiliate_structure.svg")):
                    return svg, "structure_diagram"

    # 3) Graphviz 스타일 SVG
    gdir = _BASE / "samples_graphviz_style"
    if gdir.exists():
        for svg in sorted(gdir.glob(f"{code}_*_graphviz_style.svg")):
            return svg, "graphviz_style"

    # 4) 기본 생성 SVG (samples/*/affiliate_*.svg)
    if sdir.exists():
        for d in sorted(sdir.glob(f"{code}_*")):
            if d.is_dir():
                for svg in sorted(d.glob("affiliate_*.svg")):
                    return svg, "generated_svg"

    # 4b) 전 종목 1단계 투자관계 그래프 (output/affiliate_visualization)
    if _OUT_VIS.exists():
        for d in sorted(_OUT_VIS.glob(f"{code}_*")):
            if d.is_dir():
                for svg in sorted(d.glob("affiliate_investment_graph.svg")):
                    return svg, "generated_svg"

    return None, None


_LABEL = {
    "original_dart_image": "DART 원본 소유지분도",
    "structure_diagram":   "계열회사 구조도",
    "graphviz_style":      "계열회사 구조도",
    "generated_svg":       "계열회사 관계도",
}


@router.get("/affiliate/{code}")
def affiliate_meta(code: str):
    """계열회사 시각화 메타. 없으면 available:false. (S3 우선 → 로컬 폴백)"""
    code = code.strip()
    # ① S3 우선
    s3key = _find_s3(code)
    if s3key:
        return {
            "available":   True,
            "stock_code":  code,
            "source_type": "structure_diagram",
            "label":       _LABEL.get("structure_diagram", "계열회사 구조"),
            "kind":        "svg",
            "file_url":    f"/api/affiliate/{code}/file",
            "file_name":   s3key.split("/")[-1],
        }
    # ② 로컬 폴백
    path, stype = _find(code)
    if path is None:
        return {"available": False, "stock_code": code,
                "_note": "계열회사 시각화 데이터 없음 (현재 샘플 종목만 제공)"}
    is_image = path.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif")
    return {
        "available":   True,
        "stock_code":  code,
        "source_type": stype,
        "label":       _LABEL.get(stype, "계열회사 구조"),
        "kind":        "image" if is_image else "svg",
        "file_url":    f"/api/affiliate/{code}/file",
        "file_name":   path.name,
    }


@router.get("/affiliate/{code}/file")
def affiliate_file(code: str):
    """계열회사 시각화 실제 파일(SVG/이미지) 반환. (S3 우선 → 로컬 폴백)"""
    code = code.strip()
    # ① S3 우선
    s3key = _find_s3(code)
    if s3key:
        try:
            obj = _s3().get_object(Bucket=_S3_BUCKET, Key=s3key)
            return Response(content=obj["Body"].read(), media_type="image/svg+xml")
        except Exception:
            pass  # S3 오류 → 로컬 폴백
    # ② 로컬 폴백
    path, _ = _find(code)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail=f"{code} 계열회사 시각화 없음")
    media = _MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(path), media_type=media)
