/**
 * 밸류에이션 통합 JSON 데이터 계약 + 포맷 헬퍼.
 *
 * 백엔드 GET /api/valuation/{code} 가 반환하는 '통합 평가 JSON' 을 그대로 소비한다.
 * (설계 원본: VAR/valuation_engine/static/index.html 의 render 로직)
 * 멀티플·피어 등 일부 배열은 한글 키(`m['멀티플']`, `p['회사']`)를 그대로 읽는다.
 */

export interface Company {
  name?: string;
  ticker?: string;
  market?: string;
}

export interface DamodaranCheck {
  available?: boolean;
  peer_median_bU?: number;
  damodaran_bU?: number;
  gap?: number;
  warn_gt_0p3?: boolean;
  blended_bU?: number | null;
  weight_peer?: number | null;
  excluded_peers?: string[];
  agg_method?: string;
  damodaran_sector?: string;
  [k: string]: unknown;
}

export interface ValSummary {
  current_price?: number | null;
  fair_price?: number | null;
  fair_price_low?: number | null;
  fair_price_high?: number | null;
  upside_pct?: number | null; // 단위: 퍼센트(예: -30.6). 표시 시 /100 후 spct
  wacc?: number | null;
  ke?: number | null;
  rf?: number | null;
  implied_roic?: number | null;      // ROIC (정상화 NOPAT ÷ 투하자본)
  eva_spread?: number | null;        // ROIC − WACC (양수=가치 창출)
  invested_capital?: number | null;  // 투하자본
  WACC_low?: number | null;
  WACC_high?: number | null;
  dcf_grade?: string;
  dcf_grade_reason?: string;
  dcf_show_point_estimate?: boolean;
  dcf_tv_weight?: number | null;
  dcf_fcff_y1_negative?: boolean;
  // v9 추가 필드 (DCF 적합성·신뢰도·비영업자산)
  dcf_valid?: boolean;
  dcf_invalid_reason?: string | null;
  dcf_confidence?: string;
  noa_won?: number | null;
  industry_category?: string;
  industry_name?: string;
  opm_window_used?: string;
  opm_3yr_avg?: number | null;
  opm_8yr_avg?: number | null;
  opm_pattern?: string;
  damodaran_check?: DamodaranCheck;
  peer_confidence_grade?: string;
  peer_confidence_score?: number | null;
  leverage_cap_applied?: boolean;
  DE_own_pct?: number | null;
  DE_cap_pct?: number | null;
  DE_peer_median_pct?: number | null;
  leverage_disclosure?: string;
  [k: string]: unknown;
}

export interface Diagnostics {
  valid?: boolean;
  headline?: string;
  epv_price?: number | null;
  epv_operating?: number | null;
  epv_equity?: number | null;
  growth_premium?: number | null;
  implied_growth?: number | null;
  implied_growth_verdict?: string;
  expectations_gap?: number | null;
  margin_of_safety?: number | null;
  gdp_growth_ref?: number | null;
  [k: string]: unknown;
}

export interface Scenario {
  price?: number | null;
  upside_pct?: number | null;
  ev_ebitda?: number | null;
  [k: string]: unknown;
}

export interface PeerConfidence {
  grade?: string;
  score?: number;
  deductions?: { delta: number; reason: string }[];
  [k: string]: unknown;
}

export interface ValuationData {
  is_mock?: boolean;
  status?: string;
  unsupported_kind?: string;
  unsupported_reason?: string;
  as_of_date?: string;
  model_version?: string;
  _cache?: boolean;
  _file?: string;
  stock_code?: string;
  company?: Company;
  summary?: ValSummary;
  valuation_diagnostics?: Diagnostics;
  scenarios?: { Bear?: Scenario; Base?: Scenario; Bull?: Scenario; [k: string]: unknown };
  wacc_breakdown?: [string, string, string][];
  multiples?: Record<string, unknown>[];
  peer_beta?: Record<string, unknown>[];
  peer_confidence?: PeerConfidence;
  _meta?: Record<string, unknown>;
  [k: string]: unknown;
}

// ── 색상 팔레트 (원본 static/index.html 와 동일) ──────────────────────
export const C = {
  navy: "#1b3a5b",
  blue: "#2d6cb5",
  green: "#16a34a",
  red: "#dc2626",
  amber: "#d97706",
  gray: "#64748b",
  bd: "#e2e8f0",
} as const;

// ── 포맷 헬퍼 (원본 W / PCT / SPCT 와 동일 의미) ──────────────────────
const _num = (v: unknown): number | null =>
  v == null || isNaN(Number(v)) ? null : Number(v);

/** 원화 금액(이미 원 단위) → 천단위 콤마. null → '—'. */
export const won = (n?: number | null, d = 0): string => {
  const v = _num(n);
  return v == null ? "—" : v.toLocaleString("ko-KR", { maximumFractionDigits: d });
};

/** 비율(0~1) → 퍼센트 문자열. null → '—'. */
export const pct = (x?: number | null, d = 1): string => {
  const v = _num(x);
  return v == null ? "—" : (v * 100).toFixed(d) + "%";
};

/** 비율(0~1) → 부호 포함 퍼센트(+/−). null → '—'. */
export const spct = (x?: number | null, d = 1): string => {
  const v = _num(x);
  return v == null ? "—" : (v >= 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
};

/** 신호등 색: 양수가 좋으면(inv=false) 양수=초록, 음수=빨강. inv=true면 반대. */
export const signalColor = (x?: number | null, inv = false): string => {
  const v = _num(x);
  if (v == null) return C.gray;
  const good = inv ? v < 0 : v > 0;
  return good ? C.green : C.red;
};

// ── 페처 (page.tsx 가 이미 fetch 해 valData 로 넘기지만, 단독 사용 대비) ──
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchValuation(code: string): Promise<ValuationData> {
  const r = await fetch(`${API_BASE}/api/valuation/${encodeURIComponent(code)}`);
  if (!r.ok) throw new Error(`밸류에이션 조회 실패 (${r.status})`);
  return r.json();
}
