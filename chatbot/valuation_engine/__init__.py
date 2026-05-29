"""valuation_engine — 한국 주식 정량 가치평가 패키지.

설계 결정 (현행):
  - Forward DCF (FCFF 5년 + Gordon TV) 표준 채택
  - FCFF Y+1 < 0 또는 EV < 0 회사 → DCF 결과 숨김, 멀티플만 표시
  - Tier A: 적정주가 구간(WACC 신뢰구간), DCF 신뢰도 A~E 등급(D/E 점추정 숨김),
    NCI cross-check, Terminal OPM/ROIC 민감도 토네이도, 자본구조 캡 고지
  - Tier B: B2(다중 성장률 winsorized median), B1(영구 OPM min(자기8년, 피어중위)),
    B3(CapEx 유지보수/성장 분리), B1+(OPM 윈도우 자동 분기 — cyclical/evolution/stable)
  - Tier C: C1(산업 3분류 prior), C2(8분기 가중평균 TTM), C3(Damodaran βU 교차검증)

모듈 구성:
  ── 데이터 수집 ──
  config.py                 — 상수 (TARGET·PEERS·FISCAL_YEARS·ERP·SRP·Fade-out 등)
  ticker_lookup.py          — 사용자 입력 → (ticker, corp_name, market) 정규화
  fetch_peers_financials.py — XBRL 최근 3년 재무 추출 (팀원 모듈 호출)
  extended_history.py       — 타깃 5년/8년 매출·영업이익(Tier B/C 보강)
  compute_equity.py         — 시가총액 E (RAG + LLM)
  fetch_credit_rating.py    — 신용등급 (RAG + LLM)
  ecos_client.py            — Rf (한국은행 10년 국고채, ECOS API 817Y002/010210000)
  kofia_fetcher.py, kd_loader.py — Kd (KOFIA hidden API)
  quarterly_financials.py   — TTM(4Q 단독 합산) + 8Q 가중평균(C2) + 최신분기 BS
  ibd_extractor.py          — IBD 키워드 합산 + RCPS LLM 분류
  industry_classifier.py    — 산업 3분류(성숙/경기민감/고성장) — Tier C1
  damodaran_betas.py        — 산업 무차입베타 교차검증 — Tier C3
  report_detector.py        — 정기보고서 신규 탐지

  ── 가치평가 핵심 ──
  wacc_engine.py            — WACC + 신뢰구간(βU σ + ERP 7~9% RSS) + C3 교차검증
  dcf_engine.py             — FCFF 5년 + Gordon TV + Tier B/C OPM 윈도우 자동분기
  equity_value.py           — EV → Equity Value (NCI cross-check) → 주당가치
  multiples_engine.py       — 멀티플 4종 (EV/EBITDA·EV/Sales·PER·PBR)
  uncertainty_engine.py     — Bear/Base/Bull + 민감도 + 토네이도 + Terminal 시나리오
  epv_engine.py             — EPV·성장프리미엄·시장함의 성장률·기대격차·안전마진(5종 진단)
  cycle_indicator.py        — 산업 사이클 z-score (보조 정보)

  ── 진입점 / 영속화 ──
  run_valuation.py          — Phase 1~8 orchestrator
  run_valuation_auto.py     — ticker 해석 + peer 자동선정 + run_valuation 호출
  api.py                    — FastAPI 백엔드 (/api/evaluate·status·result·recent)
  static/index.html         — 정적 단일 페이지 UI (Chart.js + 모달)
  db/__init__.py, store.py, mongo_json.py — SQLite 14테이블 + JSON 문서

  ── 피어 산정 ──
  peer_selector.py          — 사업유사도(BGE-M3) + WICS 동종 + 거래대금 필터
  peer_universe_data.py     — 피어 풀 마스터·진단

  ── 검증 ──
  tests/rag_validation_cases.py — 임베딩 RAG 검증 (5산업×10케이스)

FCFF 음수 처리 정책:
  - dcf_engine 산출 후 fcff_table[0].fcff (Y+1 FCFF) 또는 EV 가 음수면
    → result["dcf_valid"] = False, dcf_grade="E" → UI에서 DCF 가치 숨김
  - 사용자 화면: "DCF 부적합 — 멀티플·EPV·5종 진단 참고"
"""
