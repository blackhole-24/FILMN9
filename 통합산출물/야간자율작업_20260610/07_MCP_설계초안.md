# FINSIGHT MCP(Model Context Protocol) 설계 초안

> 작성: 2026-06-10 야간 자율작업 · 목적: FINSIGHT 데이터·기능을 LLM이 표준 프로토콜로 안전하게 활용
> 상태: 설계 초안 (아키텍처 보강용. 구현은 후순위 P2)

## 1. MCP란 & 왜 FINSIGHT에 쓰나
- **MCP** = LLM(클로드 등)이 외부 도구·데이터에 접근하는 **표준 프로토콜**. "LLM용 USB-C 포트".
- FINSIGHT 적용 가치:
  1. **챗봇 고도화**: 현재 RAG(사업보고서 임베딩)만 참조 → MCP로 **정형 DB(재무·주가·밸류)**까지 LLM이 직접 조회해 정확한 수치 답변.
  2. **외부 노출**: FINSIGHT를 "기업분석 MCP 서버"로 만들면, 클로드 데스크톱·다른 에이전트가 우리 데이터를 호출 가능(B2B 확장).
  3. **NO-MOCK 강화**: LLM이 추측 대신 MCP 도구로 실제 DB 값을 가져와 답함(할루시네이션 차단).

## 2. 아키텍처 (제안)
```
[LLM/클로드/챗봇]  ──MCP(stdio/HTTP)──▶  [FINSIGHT MCP 서버]
                                              │
                  ┌───────────────┬───────────┼───────────┬─────────────┐
                  ▼               ▼           ▼           ▼             ▼
            company_info     financials    ohlcv    valuation_*    ChromaDB
            (기업개요)        (재무)        (주가)    (밸류)         (사업보고서 RAG)
```
- MCP 서버 = 기존 FastAPI(8090) 위에 **얇은 MCP 어댑터** 신설 (`mcp_server.py`), 내부적으로 기존 라우터/DB 재사용.
- 전송: 로컬은 stdio, 배포는 HTTP/SSE.

## 3. 노출할 도구(Tools) — 읽기 전용 우선
| 도구명 | 입력 | 반환 | 매핑 |
|---|---|---|---|
| `get_company_overview` | stock_code | 기업개요(이름·업종·CEO·상장일…) | company_info |
| `get_financials` | stock_code, years | 재무요약(매출·영업익·순익·부채비율) | financials |
| `get_stock_price` | stock_code, range | OHLCV 일봉 | ohlcv |
| `get_valuation` | stock_code | DCF 적정가·WACC·등급·상승여력 | valuation_summary/full |
| `search_disclosures` | stock_code | 최근 공시 목록·DART 링크 | disclosures |
| `search_report_rag` | stock_code, query | 사업보고서 RAG 검색 청크+출처 | ChromaDB |
| `find_peers` | stock_code | 경쟁사·피어 | peer_competitors |
| `search_by_sector` | 업종명 | 업종별 종목 리스트 | WICS |

## 4. 리소스(Resources)
- `finsight://company/{code}` — 종목 종합 컨텍스트(개요+재무+밸류 묶음)
- `finsight://sector/{wics}` — 업종 컨텍스트
- (LLM이 대화 시작 시 종목 컨텍스트를 리소스로 로드)

## 5. 보안·거버넌스 (필수)
- **읽기 전용 우선** — 쓰기/삭제 도구는 노출 금지(데이터 보호).
- **.env 시크릿 분리** — DB 접속·API 키는 코드/Git 금지(기존 보안 원칙 동일).
- **레이트 리밋 + 스코프** — 종목조회 등 안전 도구만, 비용 유발(OpenAI) 도구는 별도 승인.
- **NO-MOCK** — 도구가 데이터 없으면 "데이터 없음" 반환(임의값 금지).
- **감사 로그** — MCP 호출 기록(관리자 페이지 연계).

## 6. 단계별 구현 로드맵
1. (P2) 로컬 stdio MCP 서버 + 읽기 도구 4종(개요·재무·주가·밸류) PoC.
2. RAG 도구(`search_report_rag`) 연결 → 챗봇이 정형+비정형 동시 활용.
3. 리소스(종목 컨텍스트) 추가.
4. (배포 후) HTTP/SSE 전송 + 인증 → 외부 에이전트 노출 검토.

## 7. 기대효과
- 챗봇 답변 정확도↑(정형 수치를 추측 안 하고 조회).
- 아키텍처 산출물에 "MCP 레이어" 추가 → PM/발표 시 기술 깊이 어필.
- 향후 B2B(다른 에이전트가 FINSIGHT 데이터 소비) 확장 포석.
