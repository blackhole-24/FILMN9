# -*- coding: utf-8 -*-
"""FINSIGHT MCP 서버 (의존성 0 · stdlib만) — AI(클로드 등)가 FINSIGHT 데이터를 '도구'로 호출.

MCP(Model Context Protocol) = AI가 외부 데이터/기능을 표준 방식으로 불러 쓰는 규격.
이 서버는 FINSIGHT 백엔드(:8090)를 감싸 4개 도구를 노출한다. stdio(JSON-RPC) 전송.

실행:  python finsight_mcp_server.py   (백엔드 8090이 떠 있어야 함)
연결:  Claude Desktop 등 MCP 클라이언트의 mcpServers 설정에 이 파일 경로 등록.
스모크테스트:  echo 요청들을 stdin으로 파이프 (파일 하단 주석 참고).
"""
import sys, json, urllib.request, urllib.parse

API = "http://localhost:8090"

def _get(path):
    try:
        with urllib.request.urlopen(API + path, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

# ── 도구 정의 ──────────────────────────────────────────────────────────────
TOOLS = [
    {"name": "get_company_overview", "description": "종목코드로 기업개요(회사정보·재무 하이라이트·주주·히스토리브리핑)를 가져온다.",
     "inputSchema": {"type": "object", "properties": {"stock_code": {"type": "string", "description": "6자리 종목코드 (예: 005930)"}}, "required": ["stock_code"]}},
    {"name": "get_financial_statements", "description": "종목의 3개년 재무제표(재무상태표 BS 또는 손익계산서 IS)를 가져온다.",
     "inputSchema": {"type": "object", "properties": {"stock_code": {"type": "string"}, "statement": {"type": "string", "enum": ["BS", "IS"], "description": "BS=재무상태표, IS=손익계산서"}}, "required": ["stock_code", "statement"]}},
    {"name": "get_valuation_ranking", "description": "산업 대표주 밸류에이션 요약 랭킹(적정가·신뢰도·상승여력)을 가져온다.",
     "inputSchema": {"type": "object", "properties": {"sort": {"type": "string", "enum": ["grade", "upside", "wacc", "name"], "description": "정렬 기준"}}, "required": []}},
    {"name": "get_market_signal", "description": "글로벌 마켓 시그널(S&P선물·VIX·환율 등 실시간 지표와 한국장 종합판정).",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
]

def call_tool(name, args):
    if name == "get_company_overview":
        return _get(f"/api/overview/{args['stock_code']}")
    if name == "get_financial_statements":
        return _get(f"/api/financial_detail/{args['stock_code']}/{args.get('statement', 'BS')}")
    if name == "get_valuation_ranking":
        return _get(f"/api/valuation-summary?sort={args.get('sort', 'grade')}")
    if name == "get_market_signal":
        return _get("/api/morning")
    return {"error": f"unknown tool: {name}"}

# ── JSON-RPC (MCP stdio · newline-delimited) ───────────────────────────────
def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def handle(req):
    mid = req.get("id"); method = req.get("method"); params = req.get("params", {})
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "finsight-mcp", "version": "0.1.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        nm = params.get("name"); args = params.get("arguments", {})
        result = call_tool(nm, args)
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)[:60000]}]}}
    if method in ("notifications/initialized", "initialized"):
        return None  # 알림 → 응답 없음
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        resp = handle(req)
        if resp is not None:
            send(resp)

if __name__ == "__main__":
    main()

# ── 스모크테스트 (PowerShell) ──────────────────────────────────────────────
#  $reqs = @(
#    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
#    '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}',
#    '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_market_signal","arguments":{}}}'
#  ) -join "`n"
#  $reqs | python finsight_mcp_server.py
