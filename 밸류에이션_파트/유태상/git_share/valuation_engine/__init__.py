"""valuation_engine — 아모레퍼시픽 기업가치 평가 통합 패키지.

설계서 v4 + 팀원 XBRL 모듈을 결합한 일반투자자용 DCF 산출 시스템.

모듈 구성:
  config.py                — 상수 (피어, ERP, SRP, Kd, Fade-out 등)
  fetch_peers_financials.py — Phase 1-B: 팀원 XBRL로 피어 4사 × 3년치 추출
  compute_equity.py        — Phase 2-A: 발행/자기주식수 + KRX 종가 → E
  ecos_client.py           — Phase 3-D: ECOS API Rf (국고채 10년)
  wacc_engine.py           — Phase 3: Hamada + Ke + Kd + WACC
  dcf_engine.py            — Phase 4: FCFF 5년 Fade-out + TV → EV
  equity_value.py          — Phase 5: EV → Equity → 주당가치
  multiples_engine.py      — Phase 6: 4종 멀티플 역산
  uncertainty_engine.py    — Phase 7: Bear/Base/Bull + 민감도 + 토네이도
  run_valuation.py         — 메인 진입점
"""
