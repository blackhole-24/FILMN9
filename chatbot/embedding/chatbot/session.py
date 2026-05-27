"""멀티턴 대화 세션 (인메모리).

후속 질문("그럼 영업이익은?")에서 회사명이 생략돼도 직전 컨텍스트를
이어가도록 ticker/year 와 대화 이력을 세션 단위로 보관한다.

* 단일 프로세스 인메모리 — 다중 워커/재시작 시 휘발. 운영 시 Redis 등으로 교체.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Optional

from .config import SESSION_MAX_TURNS


class Session:
    def __init__(self, session_id: str):
        self.id = session_id
        self.created_at = time.time()
        self.history: list[dict] = []        # OpenAI chat messages (user/assistant)
        self.last_ticker: Optional[str] = None
        self.last_corp_name: Optional[str] = None
        self.last_year: Optional[int] = None

    def add_turn(self, question: str, answer: str) -> None:
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer})
        # 최근 SESSION_MAX_TURNS 턴만 유지 (메시지 2개 = 1턴)
        max_msgs = SESSION_MAX_TURNS * 2
        if len(self.history) > max_msgs:
            self.history = self.history[-max_msgs:]

    def update_context(self, ticker: Optional[str], corp_name: Optional[str],
                       year: Optional[int]) -> None:
        if ticker:
            self.last_ticker = ticker
            self.last_corp_name = corp_name
        if year is not None:
            self.last_year = year


class _SessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: Optional[str]) -> Session:
        with self._lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            sid = session_id or uuid.uuid4().hex
            s = Session(sid)
            self._sessions[sid] = s
            return s

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


STORE = _SessionStore()
