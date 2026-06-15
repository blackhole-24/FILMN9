# FILMN9 — 프로젝트 진입점 (새 세션은 이 파일을 자동으로 읽습니다)

> **이 파일 하나가 인수인계의 단일 진입점입니다.** 새 대화/새 PC에서 시작해도
> 이 파일 + `MEMORY.md` + git 로그만 보면 진행 상황과 다음 할 일을 즉시 파악할 수 있습니다.
> 날짜별 `인수인계서_YYYYMMDD.txt`는 **더 만들지 않습니다.** 상태가 바뀌면 이 파일의 "현재 상태"만 갱신.

## 0. 프로젝트 한 줄 요약
KOSPI/KOSDAQ ~3,000개 기업 AI 분석 플랫폼 (KPMG AI Lab). **데모 6/5**. 내 파트 = 종목 상세화면(주가·재무·Sankey·건전성·주주·경영인·공시·뉴스) **3000개 전수 보장**.

## 1. 실행 방법 (수동 서버 기동)
```
cd C:\Users\Admin\FILMN9
# 백엔드 (FastAPI :8000) — conda env 필수
C:\Users\Admin\miniconda3\envs\FILMN9_env\python.exe -m uvicorn backend.main:app --port 8000
# 프론트 (Next.js :3000)
cd frontend && npm run dev
```
- DB: `data/filmn9.db` (SQLite) · MongoDB Atlas(histories) · Chroma
- 환경변수: `.env` (DART_API_KEY, OPENAI_API_KEY, MONGO_URI) — **git/채팅/캡처 금지**

## 2. 핵심 데이터 파이프라인 (재실행 가능 스크립트)
| 목적 | 스크립트 | 비고 |
|---|---|---|
| 재무 하이라이트·건전성 (DART 진실원천) | `build_financials_from_dart.py` | FY2024, /1e6 백만원 통일 |
| 손익 Sankey 흐름도 | `build_sankey_v3.py` | 매출=파랑/이익=초록/비용=빨강, 적자 노드도 (-)표시 |
| 고객사 B2B/B2C/MIXED | `build_customers.py` | |
| 종목명 KRX 기준 교정 | `update_display_names.py` | |
| 거래정지/상폐 일일갱신 | `daily_status_update.py` | Windows 작업 `FILMN9_DailyStatus` 18:30 |
| 재무 검증 | `validate_financials.py` (+`--dart`) | 내부 일관성 + DART 대조 |

## 3. 현재 상태 (← 작업 끝낼 때마다 여기만 갱신)
**업데이트: 2026-06-01**
- ✅ 재무 하이라이트/건전성: DART 재적재 완료 (2,607종목)
- ✅ 주가 장기차트: backfill 완료 (2,769종목 250봉+)
- ✅ RFHIC 등 KOSDAQ 주가오류: ticker_suffix 테이블로 수정
- ✅ Sankey 적자종목 전 노드 (-)표시: build_sankey_v3 (2,614 생성)
- 🔄 **진행중**: Sankey 디자인 보강 — (a)음수값 노드 노란색, (b)매출액 노드를 "{기업명} 총매출" 파란 띠로 길게. → `build_sankey_v3.py` 수정 중
- ⏸ 보류: OpenAI 키 교체(6/2, platform.openai.com 수동), 180종목(외감·DART미보유) 하이라이트 없음(불요)

## 4. 다음 할 일 (6/2~)
- Sankey 디자인 보강 마무리 → 3000개 재생성
- 메인 모닝루틴 위젯 / AI 챗봇 RAG / 산업별 대장주 / AWS 배포(6/4)

## 5. 지켜야 할 제약 (변경 금지)
- OpenAI API 사용 사전 승인 필수($50 팀 공유) · **키 삭제 금지**
- `MONGO_URI` GitHub 커밋·그룹채팅·캡처 금지
- Tab3 AI 챗봇: 80~100% 완성 전 삭제 금지 · LLM 5단계 보류

## 6. git / 환경
- remote: github.com/blackhole-24/FILMN9 (branch main)
- `.gitignore`: data/, *.jsonl, .env, node_modules, 인수인계서류 제외
- 더 깊은 환경구축(MongoDB 등)은 `기업개요 파트_MongoDB_환경구축_가이드.md` 참조
