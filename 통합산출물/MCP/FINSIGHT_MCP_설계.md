# #29 FINSIGHT MCP 설계 (Model Context Protocol)

> 산출물: 설계(이 문서) + **동작 스텁** `finsight_mcp_server.py`(의존성 0, stdio JSON-RPC) — 스모크테스트 통과.

## 1. MCP가 무엇인가 (한 줄)
**MCP = AI(클로드 등)가 외부 데이터/기능을 "표준 도구(tool)"로 직접 불러 쓰게 하는 규격.**
USB-C처럼, 어떤 AI든 우리 데이터에 같은 방식으로 꽂을 수 있게 하는 "AI 전용 콘센트".

## 2. 왜 FINSIGHT에 (발표 어필)
- 지금 우리 데이터는 **사람이 웹 화면**으로 봄. MCP를 달면 **AI 비서가 우리 DB를 API처럼** 질의.
- 예: 사용자가 클로드에게 "삼성전자 재무 어때?" → 클로드가 FINSIGHT MCP의 `get_company_overview("005930")` 호출 → 우리 서버가 실데이터 반환 → 클로드가 근거 기반 답변.
- = "우리 서비스는 AI가 바로 갖다 쓸 수 있게 설계됐다"는 아키텍처 차별점. (단, 서비스 작동에 필수는 아님 = 보너스/확장)

## 3. 아키텍처
```
[AI 클라이언트]            [FINSIGHT MCP 서버]           [FINSIGHT 백엔드]        [데이터]
 Claude Desktop  ──stdio──▶ finsight_mcp_server.py ──HTTP──▶ FastAPI :8090 ──▶ RDS/Mongo/파일
 (JSON-RPC: initialize·tools/list·tools/call)   (도구→엔드포인트 매핑)
```
- 전송: **stdio + JSON-RPC 2.0**(MCP 표준). 서버는 백엔드 :8090을 감싸는 얇은 어댑터.
- 도구 호출 → 해당 FastAPI 엔드포인트 호출 → JSON 반환. (DB 직접 접근 아님 = 기존 로직·NO-MOCK 그대로 재사용)

## 4. 노출 도구 (4종, 스텁 구현됨)
| 도구 | 설명 | 매핑 엔드포인트 |
|---|---|---|
| `get_company_overview(stock_code)` | 기업개요(회사·재무하이라이트·주주·히스토리) | `/api/overview/{code}` |
| `get_financial_statements(stock_code, statement)` | 3개년 재무제표 BS/IS | `/api/financial_detail/{code}/{BS\|IS}` |
| `get_valuation_ranking(sort)` | 밸류 요약 랭킹 | `/api/valuation-summary` |
| `get_market_signal()` | 글로벌 마켓 시그널 | `/api/morning` |
→ 추후 확장: search·sector·sankey·disclosures 등 엔드포인트 추가만 하면 도구 증가.

## 5. 연결 방법 (Claude Desktop 예시)
`claude_desktop_config.json`의 mcpServers에 추가:
```json
{ "mcpServers": {
    "finsight": {
      "command": "python",
      "args": ["C:/Users/Admin/FILMN9/통합산출물/MCP/finsight_mcp_server.py"]
    }
} }
```
※ 백엔드 :8090이 떠 있어야 함(로컬 또는 AWS면 API 상수만 교체).

## 6. 스모크테스트 (통과 확인)
- `initialize` → serverInfo finsight-mcp 0.1.0 ✅
- `tools/list` → 4개 도구 ✅
- `tools/call get_company_overview(005930)` → 삼성전자 데이터 반환 ✅

## 7. 위치 / 상태
- 우선순위 P2(배포 후 보너스). 발표에선 "확장 계획 + 동작 데모"로 어필 가능.
- 실서비스에는 영향 0(독립). 의존성 0이라 `python finsight_mcp_server.py`로 즉시 실행.
