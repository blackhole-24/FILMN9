"""저장 추상화 레이어.

지금은 로컬 디스크만 지원. 향후 S3 등 다른 백엔드 추가 시
이 모듈만 확장하면 다른 코드는 변경 불필요.

기본 API:
    save_bytes(data, key)       # 바이트 저장
    save_text(text, key)        # 텍스트 저장
    save_json(obj, key)         # JSON 저장
    load_text(key) -> str       # 텍스트 로드
    load_json(key) -> dict      # JSON 로드
    exists(key) -> bool         # 존재 여부
    list_keys(prefix) -> list   # prefix 매칭 목록

key 는 상대 경로 형태:
    "rag/005930_삼성전자.jsonl"
    "briefs/005930_삼성전자.json"
    "eval/005930.json"
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Union

from . import config


# ═══════════════════════════════════════════════════════════════════════════
# 로컬 백엔드
# ═══════════════════════════════════════════════════════════════════════════
class LocalStorage:
    """로컬 파일시스템 저장소."""

    def __init__(self, root_dir: Path):
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _full_path(self, key: str) -> Path:
        return self.root / key

    def save_bytes(self, data: bytes, key: str) -> str:
        p = self._full_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return str(p)

    def save_text(self, text: str, key: str) -> str:
        p = self._full_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return str(p)

    def save_json(self, obj, key: str, indent: int = 2) -> str:
        return self.save_text(json.dumps(obj, ensure_ascii=False, indent=indent), key)

    def load_text(self, key: str) -> str:
        return self._full_path(key).read_text(encoding="utf-8")

    def load_json(self, key: str):
        return json.loads(self.load_text(key))

    def exists(self, key: str) -> bool:
        return self._full_path(key).exists()

    def list_keys(self, prefix: str = "") -> list[str]:
        base = self._full_path(prefix) if prefix else self.root
        if not base.exists():
            return []
        if base.is_file():
            return [prefix]
        return [
            str(f.relative_to(self.root)).replace("\\", "/")
            for f in base.rglob("*") if f.is_file()
        ]

    def delete(self, key: str) -> bool:
        p = self._full_path(key)
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════════
# S3 백엔드 (To-be — 현재 미구현)
# ═══════════════════════════════════════════════════════════════════════════
class S3Storage:
    """AWS S3 저장소. 향후 구현 예정."""

    def __init__(self, bucket: str, prefix: str = ""):
        raise NotImplementedError(
            "S3 저장 모드는 현재 미구현입니다 (To-be). "
            "STORAGE_MODE=local 로 설정해주세요."
        )


# ═══════════════════════════════════════════════════════════════════════════
# 팩토리 — 설정에 따라 자동 선택
# ═══════════════════════════════════════════════════════════════════════════
def get_storage() -> LocalStorage:
    """현재 설정에 맞는 저장 백엔드 반환."""
    if config.STORAGE_MODE == "s3":
        # 향후 활성화
        return S3Storage(bucket="filmn9-data")
    # 기본: local
    return LocalStorage(config.LOCAL_DATA_DIR)


# 모듈 로드 시 단일 인스턴스
storage = get_storage()
