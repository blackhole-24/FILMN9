"""RAG 챗봇 설정.

검색 강화(reranking·query transformation)와 LLM 생성 파라미터를 한 곳에서 관리.
임베딩/DB 설정은 상위 패키지(embedding/config.py)를 재사용한다.
"""
from __future__ import annotations

import os
from pathlib import Path

CHATBOT_DIR = Path(__file__).resolve().parent

# ─────────────────────────────────────────────────────────────
# OpenAI (질문 분석 + 쿼리 변환 + 답변 생성)
# ─────────────────────────────────────────────────────────────
# 단순 one-shot RAG: 생성·분석 모두 최신 mini (표·한국어 독해 + 별칭 세계지식↑).
# 분석기는 nano 도 가능하나 별칭 품질(회사 해석 정확도)이 떨어져 mini 권장(추가비용 ~1원/질의).
# 비용 ≈ 질의당 10~30원. (gpt-4o-mini 로 되돌리려면 환경변수로 덮어쓰기)
OPENAI_MODEL          = os.getenv("CHATBOT_OPENAI_MODEL", "gpt-5.4-mini")
OPENAI_ANALYZER_MODEL = os.getenv("CHATBOT_ANALYZER_MODEL", "gpt-5.4-mini")
OPENAI_TIMEOUT_S      = 60
OPENAI_TEMPERATURE    = 0.1   # 사실 기반 답변 → 낮게 (미지원 모델은 자동 폴백)

# ─────────────────────────────────────────────────────────────
# 검색 (Retrieval) 파라미터
# ─────────────────────────────────────────────────────────────
# 1단계 recall: 각 변형 쿼리마다 넓게 가져옴 (속도/정확도 균형: 12)
RECALL_TOP_K   = 12
# RRF 융합 후 reranker 에 넘길 후보 상한 (작을수록 재랭킹 빠름)
RERANK_POOL    = 16
# 2단계 precision: 최종 LLM 컨텍스트에 넣을 청크 수 (구체성 위해 12)
FINAL_TOP_K    = 12
# RRF 상수 (작을수록 상위 랭크 가중 ↑)
RRF_K          = 60

# ─────────────────────────────────────────────────────────────
# Query Transformation
# ─────────────────────────────────────────────────────────────
ENABLE_MULTI_QUERY = True
N_QUERY_VARIANTS   = 2      # 원본 + (N-1) 변형 (속도 위해 2; 정확도 우선 시 3~4)
ENABLE_HYDE        = True   # 가상답변(HyDE) 1개를 추가 쿼리로 사용

# 온톨로지 기반 질의 확장 (우발부채 → 약정·지급보증·담보 등 도메인 용어로 확장)
ENABLE_ONTOLOGY     = True
ONTOLOGY_MAX_TERMS  = 6      # 온톨로지가 추가할 확장 검색어 상한
MAX_TOTAL_QUERIES   = 9      # 전체 검색 질의 수 상한(임베딩/Chroma 부하 관리)

# ─────────────────────────────────────────────────────────────
# Reranking (cross-encoder)
# ─────────────────────────────────────────────────────────────
ENABLE_RERANK   = True
RERANKER_MODEL  = "BAAI/bge-reranker-v2-m3"   # 임베딩과 동일 패밀리(한국어 우수)
RERANKER_MAX_LEN = 1024
# 확장 인지 재랭킹: 원본 질문 + 온톨로지 확장 개념어로 각각 채점 후 청크별 max.
# 단어중심 질문(예: "우발부채")이 끌어온 동의 청크(지급보증·담보)가 재랭킹에서 살아남게 함.
ENABLE_EXPANSION_RERANK = True
RERANK_MAX_QUERIES      = 3     # 재랭킹에 쓸 질의 수 상한(원본 1 + 확장 2). 속도 위해 5→3
# 빈 stub 테이블(키워드만 있고 값 없는 헤더/라벨) 강등 — 값 있는 표가 위로 오게.
# '짧으면서(헤더 수준) 숫자가 거의 없는' 표만 강등(값 있는 짧은 표·긴 정성표는 보존).
ENABLE_STUB_DEMOTE   = True
STUB_TABLE_MAX_CHARS = 80      # 이보다 짧은 table 청크만 stub 후보
STUB_MIN_DIGITS      = 3       # 숫자가 이보다 적으면 데이터 없는 라벨/헤더로 간주
STUB_PENALTY         = 5.0     # 재랭킹 점수 강등폭
# 최초 실행 시 미캐시면 HuggingFace 에서 다운로드 필요 (~2.2GB).
RERANKER_LOCAL_ONLY = os.getenv("CHATBOT_RERANKER_LOCAL_ONLY", "0") == "1"

# ─────────────────────────────────────────────────────────────
# LLM 컨텍스트 예산
# ─────────────────────────────────────────────────────────────
MAX_CONTEXT_CHARS = 16000   # format_chunks_for_llm 에 전달 (구체성 위해 확대)

# ─────────────────────────────────────────────────────────────
# 회사 인덱스 캐시
# ─────────────────────────────────────────────────────────────
COMPANY_INDEX_PATH = CHATBOT_DIR / "companies.json"
# 퍼지 매칭 최소 점수 (0~100). 이보다 낮으면 "회사 못 찾음"으로 처리.
FUZZY_MIN_SCORE = 70
# 사용자에게 되물을 후보 최대 개수
MAX_CANDIDATES  = 5

# ─────────────────────────────────────────────────────────────
# 세션
# ─────────────────────────────────────────────────────────────
SESSION_MAX_TURNS = 12   # 보관할 최대 대화 턴 수

# ─────────────────────────────────────────────────────────────
# DART 섹션 deep-link
# ─────────────────────────────────────────────────────────────
# 출처 클릭 시 DART 뷰어의 해당 섹션으로 바로 점프.
# 보고서 목차(TOC) 트리를 1회 가져와 파싱(보고서당 캐싱) 후 섹션 매칭.
# 실패/비활성 시 보고서 첫 화면 URL 로 폴백.
ENABLE_DART_DEEPLINK = True
DART_FETCH_TIMEOUT   = 4          # DART 페이지 fetch 타임아웃(초)
DART_TOC_CACHE_PATH  = CHATBOT_DIR / "dart_toc_cache.json"
