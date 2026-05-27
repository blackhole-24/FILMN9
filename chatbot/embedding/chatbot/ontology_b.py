"""B안 정교 온톨로지 런타임 (chatbot 내장).

외부에서 설계·grounding된 B안 온톨로지(ontology_b.json)를 로드해 질의 확장 +
커버리지 체크리스트를 제공한다. 구조:
  - scope(broad/narrow) + relations.has_part → 광의 개념은 하위 components 합집합 커버
  - triggers + user_phrasings (+ llm_tags) 매칭 → 트리거 경직성 완화
  - components → 답변 커버리지 체크리스트(누락 방지)

pipeline 은 analyze(text) 한 함수만 쓰면 된다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).resolve().parent / "ontology_b.json"


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


class Ontology:
    def __init__(self, concepts: list[dict]):
        self.concepts = concepts
        self.by_name = {c["name"]: c for c in concepts}

    @classmethod
    def load(cls, path: Path = _DATA_PATH) -> Optional["Ontology"]:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(data["concepts"])
        except Exception:
            return None

    def match(self, query: str, llm_tags: Optional[list[str]] = None) -> list[dict]:
        q = _norm(query)
        hit: dict[str, dict] = {}
        for c in self.concepts:
            if any(_norm(t) in q for t in c.get("triggers", [])):
                hit[c["name"]] = c
                continue
            if any(_norm(p) in q for p in c.get("user_phrasings", [])):
                hit[c["name"]] = c
        if llm_tags:
            for name in llm_tags:
                if name in self.by_name:
                    hit[name] = self.by_name[name]
        return list(hit.values())

    def _checklist(self, concept: dict) -> list[str]:
        items = list(concept.get("components", []))
        if concept.get("scope") == "broad":
            for child in concept.get("relations", {}).get("has_part", []):
                cc = self.by_name.get(child)
                if cc:
                    items += cc.get("components", [])
        return list(dict.fromkeys(items))

    def expand(self, query: str, llm_tags: Optional[list[str]] = None) -> dict:
        matched = self.match(query, llm_tags=llm_tags)
        terms: list[str] = []
        sections: list[str] = []
        checklist: list[str] = []
        for c in matched:
            rel = c.get("relations", {})
            # 검색 확장어: components(핵심) + 동의어 + 연관개념 + 섹션앵커
            terms += c.get("components", [])
            terms += rel.get("synonyms", [])
            terms += rel.get("related_to", [])
            sections += c.get("section_real", [])
            checklist += self._checklist(c)
        return {
            "matched": [c["name"] for c in matched],
            "expanded_terms": list(dict.fromkeys(t for t in terms if t)),
            "sections": list(dict.fromkeys(sections)),
            "checklist": list(dict.fromkeys(checklist)),
        }


# 전역 1회 로드 (없으면 None → pipeline 이 폴백)
_ONT: Optional[Ontology] = Ontology.load()


def reload() -> int:
    global _ONT
    _ONT = Ontology.load()
    return len(_ONT.concepts) if _ONT else 0


def available() -> bool:
    return _ONT is not None


def analyze(text: str, max_expand: int = 8, max_checklist: int = 16) -> dict:
    """pipeline 용 단일 진입점.

    Returns: {concepts, expand_terms, sections, checklist}
      - expand_terms: 검색 질의 확장용(상한 max_expand)
      - checklist:    답변 커버리지 체크리스트(상한 max_checklist) — 누락 방지
    """
    if _ONT is None:
        return {"concepts": [], "expand_terms": [], "sections": [], "checklist": []}
    r = _ONT.expand(text)
    return {
        "concepts": r["matched"],
        "expand_terms": r["expanded_terms"][:max_expand],
        "sections": r["sections"],
        "checklist": r["checklist"][:max_checklist],
    }
