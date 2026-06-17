"""사업보고서 RAG 챗봇 (OpenAI gpt-4o-mini + BGE-M3 검색 + reranking).

상위 embedding 패키지의 임베딩/검색 인프라 위에
질문분석·쿼리변환·재랭킹·생성 레이어를 얹는다.
"""
# VAR/.env 의 OPENAI_API_KEY 등을 패키지 import 시점에 환경변수로 로드.
# (CWD 와 무관하게 VAR 루트의 .env 를 명시 경로로 읽음)
from pathlib import Path as _Path

try:
    from dotenv import load_dotenv as _load_dotenv

    _VAR_ROOT = _Path(__file__).resolve().parent.parent.parent  # embedding/chatbot → VAR
    _load_dotenv(_VAR_ROOT / ".env")
except ImportError:
    # python-dotenv 미설치 시: 환경변수에 직접 설정돼 있으면 그대로 동작.
    pass
