import * as React from "react";
import { ValuationData, C, won, spct, pct } from "@/lib/valuation";
import { Modal } from "./Modal";

function numv(x: any): number | null {
  if (x == null) return null;
  if (typeof x === "number") return x;
  const n = parseFloat(String(x).replace(/[^0-9.\-]/g, ""));
  return isNaN(n) ? null : n;
}

/** 친근한 반올림 표시 (예: 113,239 → "약 11.3만원", 1,377,000 → "약 138만원"). */
function manWon(n: number | null | undefined): string {
  if (n == null) return "—";
  const m = n / 10000;
  if (m >= 100) return `약 ${Math.round(m).toLocaleString()}만원`;
  if (m >= 1) return `약 ${Math.round(m * 10) / 10}만원`;
  return `약 ${(Math.round(n / 100) * 100).toLocaleString()}원`;
}

const Pp = (children: React.ReactNode) => <p className="mt-2 leading-7">{children}</p>;
const Ex = ({ children }: { children: React.ReactNode }) => (
  <div className="mt-2 rounded-lg border px-3 py-2 text-[12.5px] leading-6" style={{ background: "#f0f9ff", borderColor: "#bae6fd", color: "#1e3a5f" }}>{children}</div>
);
const Warn = ({ children }: { children: React.ReactNode }) => (
  <div className="mt-2 rounded-lg border px-3 py-2 text-[12.5px] leading-6" style={{ background: "#fffbeb", borderColor: "#fde68a", color: "#78350f" }}>⚠️ {children}</div>
);

/** 멀티플 4종 + 피어 — 중학생 눈높이, 예시·비유 포함. */
const EXPLAIN: Record<string, { title: string; body: React.ReactNode }> = {
  "PER": { title: "PER · 주가수익비율 — 쉽게 알아보기", body: (
    <div className="text-[13px] text-slate-700">
      {Pp(<>한마디로 <b>&ldquo;지금 가격이, 회사가 1년에 버는 돈의 몇 배냐&rdquo;</b>예요.</>)}
      <Ex>🏪 <b>예시</b>: 가게를 <b>통째로 10억</b>에 사요. 1년에 <b>1억</b>을 벌어요. 10억 ÷ 1억 = <b>10</b> → PER 10배! 느낌상 &ldquo;이익으로 본전 뽑는 데 약 10년&rdquo;.</Ex>
      {Pp(<>• <b>낮으면</b> 이익 대비 싸게 사는 것 · <b>높으면</b> 비싸게 사는 것.</>)}
      <Warn>빨리 크는 회사는 미래에 더 벌 거라 PER이 높아도 괜찮을 수 있어요. 꼭 <b>같은 업종끼리</b> 비교!</Warn>
    </div>) },
  "EV/EBITDA": { title: "EV/EBITDA — 쉽게 알아보기", body: (
    <div className="text-[13px] text-slate-700">
      {Pp(<>PER과 비슷한데 <b>빚까지 포함한 &lsquo;진짜 회사 전체 가격&rsquo;</b>을 봐요.</>)}
      {Pp(<>• <b>EV</b> = 시가총액 + 빚 − 현금 (빚까지 떠안고 사는 값)<br />• <b>EBITDA</b> = 본업으로 버는 <b>현금이익</b></>)}
      <Ex>🏭 <b>예시</b>: 빚까지 합쳐 <b>200억</b>에 살 수 있고 본업으로 1년에 <b>20억</b> 벌면 → <b>10배</b>.</Ex>
      {Pp(<><b>장점</b>: 빚 많은 회사·적은 회사를 공정하게 비교. <b>전문가가 가장 즐겨 쓰는</b> 지표예요.</>)}
    </div>) },
  "EV/Sales": { title: "EV/Sales — 쉽게 알아보기", body: (
    <div className="text-[13px] text-slate-700">
      {Pp(<><b>&ldquo;회사 전체 가격이 1년 매출의 몇 배냐&rdquo;</b> (매출 = 판 돈 전체, 이익 아님).</>)}
      <Ex>🛒 <b>예시</b>: <b>200억</b>에 사는데 1년 매출 <b>100억</b>이면 → <b>2배</b>.</Ex>
      {Pp(<><b>언제</b>: 이익이 적거나 들쭉날쭉한 회사(신생·적자)에 PER 대신 써요.</>)}
      <Warn>같은 100억 팔아도 30억 남기는 회사·1억 남기는 회사가 달라요(<b>이익률 차이</b>). <b>참고용</b>으로만!</Warn>
    </div>) },
  "PBR": { title: "PBR · 주가순자산비율 — 쉽게 알아보기", body: (
    <div className="text-[13px] text-slate-700">
      {Pp(<><b>&ldquo;주가가 회사 재산(순자산)의 몇 배냐&rdquo;</b>. 순자산 = 재산 − 빚 (다 팔고 빚 갚으면 남는 돈).</>)}
      <Ex>🏦 <b>예시</b>: 한 주당 순자산이 <b>5만원</b>인데 주가가 <b>5만원</b>이면 PBR <b>1배</b>, 10만원이면 <b>2배</b>.</Ex>
      {Pp(<>• <b>1배 아래</b> = 재산보다 싸게 거래(저평가 신호 가능) · 은행·건설처럼 <b>자산 중요 업종</b>에 의미.</>)}
      <Warn>장부 재산이 실제 팔 때 가치와 다를 수 있어 참고로 봐요.</Warn>
    </div>) },
  "peer": { title: "피어(Peer) — 쉽게 알아보기", body: (
    <div className="text-[13px] text-slate-700">
      {Pp(<>피어는 <b>&lsquo;비교 친구들&rsquo;</b>이에요.</>)}
      <Ex>📝 <b>예시</b>: 내 시험이 <b>80점</b>인데 잘한 건지 혼자선 몰라요. 반 평균이 <b>60점</b>이면 잘한 거, <b>95점</b>이면 못한 거! 주식도 똑같아요.</Ex>
      {Pp(<>피어 = 사업·규모가 비슷한 <b>같은 업종 회사들</b>. 이들이 받는 가격과 비교해 우리 회사가 비싼지 싼지 가늠해요.</>)}
      {Pp(<><b>신뢰도 등급(A~E)</b> = 얼마나 비슷한 친구들을 잘 골랐나. <b>A면 아주 잘</b> 고른 거예요.</>)}
    </div>) },
};

function dcfDetail(d: ValuationData): { title: string; body: React.ReactNode } {
  const s = d.summary || {}, dg = d.valuation_diagnostics || {};
  const Row = ({ k, v, sub }: { k: string; v: any; sub?: string }) => (
    <div className="flex items-start justify-between border-b py-2" style={{ borderColor: C.bd }}>
      <span className="text-[13px] text-slate-500">{k}</span>
      <span className="text-right text-[14px] font-bold" style={{ color: C.navy }}>{v}{sub && <span className="block text-[11px] font-normal text-slate-400">{sub}</span>}</span>
    </div>
  );
  return {
    title: "DCF 가치평가 상세 (참고용)",
    body: (
      <>
        <div className="mb-3 rounded-lg border px-3 py-2.5 text-[12.5px] leading-6" style={{ background: "#fffbeb", borderColor: "#fde68a", color: "#78350f" }}>
          ⚠ <b>DCF</b>는 미래 현금흐름을 추정해 &lsquo;오늘 가치&rsquo;로 환산하는 <b>장기 내재가치</b> 평가예요. 가정에 민감해 <b>현재 시장가와 차이가 클 수 있어</b>, &lsquo;적정가&rsquo;가 아니라 <b>참고 지표</b>로만 보세요.
        </div>
        {s.fair_price != null && <Row k="내재가치(DCF) 추정" v={`₩${won(s.fair_price)}`} sub={s.fair_price_low != null ? `범위 ₩${won(s.fair_price_low)} ~ ₩${won(s.fair_price_high)}` : undefined} />}
        {dg.epv_price != null && <Row k="본질가치 (성장 0 가정)" v={`₩${won(dg.epv_price)}`} sub="가장 보수적인 바닥값" />}
        {dg.implied_growth != null && <Row k="시장 기대 성장률" v={spct(dg.implied_growth)} sub={dg.implied_growth_verdict || undefined} />}
        {s.wacc != null && <Row k="할인율 (WACC)" v={pct(s.wacc, 1)} sub="미래 돈을 깎는 비율" />}
        {s.dcf_grade && <Row k="DCF 신뢰도 등급" v={`${s.dcf_grade}등급`} sub={s.dcf_grade_reason || undefined} />}
        {s.current_price != null && <p className="mt-3 text-[12px] leading-6 text-slate-500">→ 현재가 <b>₩{won(s.current_price)}</b>와의 차이는 &lsquo;오류&rsquo;가 아니라 <b>시장이 반영한 성장 기대</b>예요.</p>}
      </>
    ),
  };
}

type DirKey = "up" | "hold" | "down";
type CharKey = "growth" | "stable" | "value" | "unknown";

function classifyDir(cur: number | null, lo?: number, hi?: number): { key: DirKey; e: string; t: string; c: string; bg: string } {
  if (cur == null || lo == null || hi == null) return { key: "hold", e: "➡️", t: "적정 수준 (유지)", c: "#b45309", bg: "#fffbeb" };
  if (cur < lo * 0.93) return { key: "up", e: "📈", t: "상승 여력 있음", c: "#15803d", bg: "#ecfdf3" };
  if (cur > hi * 1.07) return { key: "down", e: "📉", t: "조정 위험 있음", c: "#b91c1c", bg: "#fef2f2" };
  return { key: "hold", e: "➡️", t: "적정 수준 (유지)", c: "#b45309", bg: "#fffbeb" };
}

function classifyChar(dg: any): { key: CharKey; e: string; t: string; c: string; d: string } {
  const igv = String(dg.implied_growth_verdict || ""), gp = dg.growth_premium, ig = dg.implied_growth;
  if (!igv && gp == null && ig == null) return { key: "unknown", e: "❔", t: "판단 보류", c: "#64748b", d: "평가 지표가 부족해 성격을 단정하기 어려워요. 위 멀티플·재무를 참고하세요." };
  if (/쇠퇴/.test(igv) || (gp != null && gp < -0.1)) return { key: "value", e: "💎", t: "가치형", c: "#15803d", d: "시장이 성장 기대를 거의 안 해, 펀더멘털 대비 싸게 거래될 수 있어요." };
  if (/낙관/.test(igv)) { const v = /매우/.test(igv); return { key: "growth", e: "🚀", t: "성장형", c: "#1d4ed8", d: v ? "시장이 미래 성장을 매우 크게 기대해요 — 기대가 큰 만큼 변동성도 커요." : "시장이 성장을 기대하는 회사예요." }; }
  return { key: "stable", e: "⚖️", t: "안정형", c: "#b45309", d: "성장 기대가 과하지 않고 현재 실력에 맞게 안정적이에요." };
}

/** 종합 한마디 — 방향 + 성격 + 주의 통합 (상충 신호 혼란 해소). */
function synthesize(dir: DirKey, char: CharKey, veryOpt: boolean, cyclical: boolean): { sentence: string; guide: string } {
  const dirP = dir === "up" ? "동종업계 평균보다 싸게 거래되고 있어요"
    : dir === "down" ? "동종업계 평균보다 비싸게 거래되고 있어요"
    : "동종업계와 비슷한 수준에서 거래되고 있어요";
  const charP = char === "growth" ? (veryOpt ? "시장이 미래 성장을 매우 크게 기대하는 성장주예요" : "시장이 성장을 기대하는 성장주예요")
    : char === "value" ? "시장 기대는 낮은 편이라 저평가 가능성도 있어요"
    : char === "unknown" ? ""
    : "현재 실력에 맞게 안정적으로 평가받고 있어요";
  let guide: string;
  if (dir === "down" && char === "growth") guide = "비싼 데다 기대도 높게 반영돼 있어, 신중히 접근하세요.";
  else if (dir === "up" && char === "value") guide = "저평가 기회일 수 있지만, 시장이 왜 신중한지(업황 등)도 꼭 확인하세요.";
  else if (veryOpt) guide = "성장 기대가 큰 만큼, 실적이 기대에 못 미치면 변동성에 유의하세요.";
  else if (cyclical) guide = "경기에 따라 실적이 오르내리는 업종이라, 한 시점보다 추세로 보세요.";
  else if (dir === "up") guide = "단, 동종 대비 싸다고 반드시 오르는 건 아니에요 — 실적·뉴스도 함께 보세요.";
  else if (dir === "down") guide = "한 지표만 믿지 말고, 재무 건전성·뉴스도 함께 확인하세요.";
  else guide = "큰 상·하 여지는 제한적 — 재무 건전성·뉴스로 보강해서 보세요.";
  return { sentence: charP ? `${dirP}, ${charP}.` : `${dirP}.`, guide };
}

function Info({ onClick }: { onClick: () => void }) {
  return <button onClick={onClick} className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold align-middle" style={{ background: "#e0e7ff", color: "#4338ca" }} aria-label="설명">i</button>;
}

function MultCard({ m, primary, onInfo }: { m: any; primary: boolean; onInfo: () => void }) {
  const name = String(m["멀티플"] ?? "");
  const peer = String(m["피어 중위"] ?? "—");
  const imp = numv(m["역산가"]);
  const valid = imp != null && imp > 0;
  const vs = numv(m["vs 현재"] ?? m["vs현재"]);
  const vcol = vs == null ? C.gray : vs > 8 ? C.green : vs < -8 ? C.red : "#b45309";
  const sig = vs == null ? "" : vs > 8 ? "이 기준으론 싼 편" : vs < -8 ? "이 기준으론 비싼 편" : "현재가와 비슷";
  const vsTxt = vs == null ? "" : Math.abs(vs) > 500 ? (vs > 0 ? "+500%↑" : "−99%") : `${vs > 0 ? "+" : ""}${vs.toFixed(0)}%`;
  return (
    <div className="rounded-xl border bg-white p-3.5" style={{ borderColor: primary ? "#bfdbfe" : C.bd, borderTop: `4px solid ${primary ? C.blue : "#cbd5e1"}` }}>
      <div className="flex items-center justify-between">
        <span className="text-[13.5px] font-bold text-slate-700">{name}<Info onClick={onInfo} /></span>
        <span className="rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ background: primary ? "#dbeafe" : "#f1f5f9", color: primary ? "#1d4ed8" : "#64748b" }}>{primary ? "이익 기준 · 신뢰" : "참고"}</span>
      </div>
      <div className="mt-1.5 text-[12px] text-slate-500">동종 평균 <b>{peer}</b></div>
      <div className="text-[18px] font-extrabold" style={{ color: valid ? C.navy : C.gray }}>{valid ? manWon(imp) : "산출 불가"}</div>
      {valid && vs != null && <div className="text-[12px] font-semibold" style={{ color: vcol }}>{sig} ({vsTxt})</div>}
    </div>
  );
}

/** 현재가의 '가치 미터' 위치(%) — 적정 zone[36~64%]=동종 기준 밴드(lo*0.93~hi*1.07), 좌=저평가, 우=고평가. */
function meterPos(cur: number, lo: number, hi: number): number {
  const loT = lo * 0.93, hiT = hi * 1.07;
  if (cur < loT) {
    const min = Math.min(loT * 0.6, cur);
    const t = (cur - min) / (loT - min || 1);
    return 3 + Math.max(0, Math.min(1, t)) * 33;
  }
  if (cur > hiT) {
    const max = Math.max(hiT * 1.6, cur);
    const t = (cur - hiT) / (max - hiT || 1);
    return 64 + Math.max(0, Math.min(1, t)) * 33;
  }
  const t = (cur - loT) / (hiT - loT || 1);
  return 36 + t * 28;
}

/** 가치 미터 — 저평가↔고평가 3색 막대 + 현재가 마커. (PeerBand 진화형) */
function ValueMeter({ cur, lo, hi, single }: { cur: number; lo: number; hi: number; single?: boolean }) {
  const pos = meterPos(cur, lo, hi);
  const lbl = pos < 18 ? { left: 0 } : pos > 82 ? { right: 0 } : { left: `${pos}%`, transform: "translateX(-50%)" };
  return (
    <div className="mt-4">
      <div className="mb-1 flex justify-between text-[11px] font-semibold text-slate-400">
        <span>싸다 · 저평가</span><span>적정</span><span>비싸다 · 고평가</span>
      </div>
      <div className="relative">
        <div className="flex h-3.5 overflow-hidden rounded-full">
          <div style={{ flex: 36, background: "#bbf7d0" }} />
          <div style={{ flex: 28, background: "#fde68a" }} />
          <div style={{ flex: 36, background: "#fecaca" }} />
        </div>
        <div className="absolute -translate-x-1/2" style={{ left: `${pos}%`, top: -5 }}>
          <div style={{ width: 0, height: 0, borderLeft: "6px solid transparent", borderRight: "6px solid transparent", borderTop: `9px solid ${C.navy}` }} />
        </div>
        <div className="absolute whitespace-nowrap text-[11px] font-extrabold" style={{ top: 15, color: C.navy, ...lbl }}>현재 ₩{won(cur)}</div>
      </div>
      <div className="mt-7 text-center text-[12px] text-slate-500">동종업계 기준 <b style={{ color: C.navy }}>{single ? manWon(lo) : `${manWon(lo)} ~ ${manWon(hi)}`}</b></div>
    </div>
  );
}

export function SimpleValuation({ d, expert, onToggle }: { d: ValuationData; expert?: boolean; onToggle?: () => void }) {
  const [mk, setMk] = React.useState<string | null>(null);
  const [showMults, setShowMults] = React.useState(false);
  const s = d.summary || {}, dg = d.valuation_diagnostics || {};
  const cur = s.current_price, name = d.company?.name || "이 회사";
  const ticker = d.stock_code || d.company?.ticker;

  const rows = (d.multiples || []) as any[];
  const EARN = ["PER", "EV/EBITDA"];
  // 역산가가 양수이고 현재가와 과도하게(20배↑) 벌어지지 않은 '정상' 값만 밴드 계산에 사용 (퇴화·이상치 제외)
  const validImp = (m: any): number | null => {
    const iv = numv(m["역산가"]);
    if (iv == null || iv <= 0) return null;
    if (cur != null && cur > 0 && (iv > cur * 20 || iv < cur / 20)) return null;
    return iv;
  };
  const earnRows = rows.filter((m) => EARN.includes(String(m["멀티플"])));
  const otherRows = rows.filter((m) => !EARN.includes(String(m["멀티플"])));
  const median = (a: number[]): number | undefined => (a.length ? a[Math.floor((a.length - 1) / 2)] + (a.length % 2 === 0 ? (a[a.length / 2] - a[Math.floor((a.length - 1) / 2)]) / 2 : 0) : undefined);
  const earnPrices = earnRows.map(validImp).filter((x): x is number => x != null).sort((a, b) => a - b);
  const allPrices = rows.map(validImp).filter((x): x is number => x != null).sort((a, b) => a - b);
  // 이익 기준(PER·EV/EBITDA) 우선 → 없으면 자산·매출 기준 폴백(신뢰도 낮음) → 그것도 없으면 밴드 없음
  const usePrices = earnPrices.length ? earnPrices : allPrices;
  const earnBasis = earnPrices.length > 0;
  const hasBand = usePrices.length > 0;
  const lo = usePrices[0], hi = usePrices[usePrices.length - 1];
  const single = hasBand && lo === hi;
  const mid = median(usePrices);

  const dir = classifyDir(cur ?? null, lo, hi);
  const INSUF = { key: "hold" as DirKey, c: "#64748b", bg: "#f8fafc", e: "ℹ️", t: "비교 정보 부족" };
  const v = hasBand ? dir : INSUF;
  // 동종 기준가가 현재가와 과도하게(5배↑) 벌어지면 신뢰도 낮음 — 가치함정·데이터 특이 경고
  const divRatio = mid != null && cur != null && cur > 0 ? (mid > cur ? mid / cur : cur / mid) : null;
  const divHigh = hasBand && divRatio != null && divRatio > 5;
  const char = classifyChar(dg);
  const cyclical = s.industry_category === "cyclical" || s.opm_pattern === "cyclical";
  const veryOpt = /매우 낙관/.test(String(dg.implied_growth_verdict || ""));
  const syn = synthesize(dir.key, char.key, veryOpt, cyclical);

  const peerNames = ((d.peers_hamada || d.peer_capital_detail || []) as any[])
    .map((p) => String(p["회사"] ?? "")).filter((n) => n && !/중위|TARGET|^—$/.test(n) && n !== name);
  const pcGrade = d.peer_confidence?.grade || s.peer_confidence_grade;
  const peerGood = pcGrade === "A" || pcGrade === "B";

  const modalContent = mk === "dcf" ? dcfDetail(d) : mk ? EXPLAIN[mk] : null;
  const subTxt = dir.key === "up" ? "동종 대비 싼 편" : dir.key === "down" ? "동종 대비 비싼 편" : "동종과 비슷한 수준";

  return (
    <div className="text-slate-800">
      {/* ── 한눈 스코어카드 ── */}
      <div className="mb-4 rounded-2xl border-2 bg-white p-5" style={{ borderColor: v.c }}>
        {/* 헤더: 종목명 + 칩(성격·신뢰도) */}
        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1.5">
          <div className="flex items-baseline gap-2">
            <span className="whitespace-nowrap text-[16px] font-extrabold text-slate-800">{name}</span>
            {ticker && <span className="text-[12px] text-slate-400">{ticker}</span>}
          </div>
          <div className="flex flex-wrap justify-end gap-1.5">
            {char.key !== "unknown" && <span className="rounded-md px-2 py-0.5 text-[11px] font-bold" style={{ background: char.c + "1a", color: char.c }}>{char.e} {char.t}</span>}
            {pcGrade && <span className="rounded-md px-2 py-0.5 text-[11px] font-bold" style={{ background: "#f1f5f9", color: peerGood ? C.green : "#b45309" }}>신뢰 {pcGrade}</span>}
          </div>
        </div>

        {/* 결론: 아이콘 원 + 큰 결론 */}
        <div className="mt-3 flex items-center gap-3">
          <div className="flex h-12 w-12 flex-none items-center justify-center rounded-full text-[26px]" style={{ background: v.c + "1a" }}>{v.e}</div>
          <div>
            <div className="text-[22px] font-extrabold leading-tight" style={{ color: v.c }}>{v.t}</div>
            {cur != null && <div className="text-[13px] text-slate-600">현재 <b>₩{won(cur)}</b>{hasBand && <span className="text-slate-400"> · {subTxt}</span>}</div>}
          </div>
        </div>

        {hasBand && cur != null ? (
          <>
            <ValueMeter cur={cur} lo={lo} hi={hi} single={single} />
            {(divHigh || !earnBasis) && (
              <div className="mt-3 rounded-lg border px-3 py-2 text-[11.5px] leading-5" style={{ background: "#fffbeb", borderColor: "#fde68a", color: "#78350f" }}>
                {divHigh && divRatio != null && <>⚠️ 동종 기준가가 <b>현재가와 약 {Math.round(divRatio)}배</b> 차이 — 가치 함정·데이터 특이일 수 있어 <b>신뢰도 낮음</b>. </>}
                {!earnBasis && <>⚠️ 이익 기준(PER·EV/EBITDA) 지표가 없어 <b>자산·매출 기준 추정</b> — 신뢰도 낮음.</>}
              </div>
            )}
            <div className="mt-3 flex items-start gap-2 rounded-xl border px-3.5 py-2.5" style={{ borderColor: v.c + "44", background: "#fbfdff" }}>
              <span className="flex-none text-[15px]" style={{ marginTop: 1 }}>💡</span>
              <div className="text-[13px] leading-6"><span className="text-slate-800">{syn.sentence}</span> <span style={{ color: dir.c }}>{syn.guide}</span></div>
            </div>
          </>
        ) : (
          <div className="mt-3 rounded-xl border px-4 py-3 text-[13px] leading-6 text-slate-600" style={{ borderColor: v.c + "44", background: "#fbfdff" }}>
            이 종목은 <b>동종업계 비교에 쓸 지표(멀티플)가 부족</b>해 방향을 단정하기 어려워요. 아래 <b>회사 성격</b>·<b>다음에 볼 것</b>을 참고하세요.
          </div>
        )}
        <div className="mt-2.5 text-center text-[10.5px] text-slate-400">※ 가격 예측이 아니라 동종업계 비교상 &lsquo;여지·위험&rsquo; · 참고용 (투자 권유 아님)</div>
      </div>

      {/* ── 동종업계 비교 자세히 (접기) ── */}
      {rows.length > 0 && (
        <div className="mb-4 rounded-xl border bg-white p-4" style={{ borderColor: C.bd }}>
          <button onClick={() => setShowMults((x) => !x)} className="flex w-full items-center justify-between text-[13.5px] font-bold" style={{ color: C.navy }}>
            <span>🏢 동종업계 비교 자세히 <span className="text-[11px] font-normal text-slate-400">멀티플 {rows.length}종</span></span>
            <span style={{ color: C.blue }}>{showMults ? "접기 ▴" : "펼치기 ▾"}</span>
          </button>
          {showMults && (
            <div className="mt-3">
              {!hasBand && <div className="mb-3 rounded-lg border px-3 py-2 text-[12px] leading-5 text-slate-500" style={{ borderColor: C.bd, background: "#f8fafc" }}>유효한 비교 가격을 산출하지 못했어요(역산가 비정상). 개별 지표는 참고용으로만 보세요.</div>}
              {earnRows.length > 0 && (<>
                <div className="mb-1.5 text-[12.5px] font-bold" style={{ color: C.blue }}>💰 이익 기준 (가장 신뢰) — 각 지표 ⓘ 설명</div>
                <div className="grid grid-cols-2 gap-2.5">{earnRows.map((m, i) => <MultCard key={i} m={m} primary onInfo={() => setMk(String(m["멀티플"]))} />)}</div>
              </>)}
              {otherRows.length > 0 && (<>
                <div className="mb-1.5 mt-3.5 text-[12.5px] font-bold text-slate-500">📦 자산·매출 기준 (참고 — 편차 큼)</div>
                <div className="grid grid-cols-2 gap-2.5">{otherRows.map((m, i) => <MultCard key={i} m={m} primary={false} onInfo={() => setMk(String(m["멀티플"]))} />)}</div>
              </>)}
            </div>
          )}
        </div>
      )}

      {/* ── 피어 (compact) ── */}
      {peerNames.length > 0 && (
        <div className="mb-4 rounded-xl border bg-white p-4" style={{ borderColor: C.bd }}>
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-bold text-slate-700">👥 비교한 회사들 ({peerNames.length})<Info onClick={() => setMk("peer")} /></span>
            {pcGrade && <span className="text-[11.5px] text-slate-500">신뢰도 <b style={{ color: peerGood ? C.green : "#b45309" }}>{pcGrade}</b></span>}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {peerNames.slice(0, 8).map((n, i) => <span key={i} className="rounded-full border px-2.5 py-0.5 text-[12px] font-semibold" style={{ borderColor: "#bfdbfe", background: "#eff6ff", color: "#1d4ed8" }}>{n}</span>)}
          </div>
          <div className="mt-2 text-[11px] leading-5 text-slate-400">⚠️ 자동 선정이라 가끔 업종이 다른 회사가 섞일 수 있어요 {peerGood ? "(이 종목은 비교적 잘 골라진 편)" : "(참고만 하세요)"}.</div>
        </div>
      )}

      {/* ── 회사 성격 설명 + DCF (참고) ── */}
      <div className="mb-4 rounded-xl border bg-white p-4" style={{ borderColor: C.bd, borderLeft: `5px solid ${char.c}` }}>
        <div className="text-[13px] font-bold text-slate-700">📊 회사 성격 — <span style={{ color: char.c }}>{char.e} {char.t}</span> <span className="text-[11px] font-normal text-slate-400">(참고)</span></div>
        <p className="mt-1 text-[12.5px] leading-6 text-slate-600">{char.d}</p>
        {cyclical && <p className="mt-1 text-[11.5px] text-slate-400">🔄 경기에 따라 실적이 오르내리는 경기민감 업종이에요.</p>}
        <button onClick={() => setMk("dcf")} className="mt-2.5 rounded-lg border px-3 py-1.5 text-[12px] font-bold" style={{ borderColor: C.bd, color: C.blue, background: "#f8fafc" }}>🔢 DCF 적정주가·계산값 (참고) →</button>
      </div>

      {/* ── 다음에 볼 것 ── */}
      <div className="mb-4 rounded-xl border bg-white p-4" style={{ borderColor: C.bd }}>
        <div className="text-[13px] font-bold text-slate-700">🧭 다음엔 이걸 보면 좋아요</div>
        <ul className="mt-2 space-y-1 text-[12px] text-slate-600">
          <li>📈 <b>과거 매출·이익 추세</b> — 회사가 크고 있는지 <span className="text-slate-400">(기업개요 탭)</span></li>
          <li>💪 <b>재무 건전성</b> — 빚이 너무 많진 않은지 <span className="text-slate-400">(기업개요 탭)</span></li>
          <li>📰 <b>최신 뉴스</b> — 최근 무슨 일이 있었는지 <span className="text-slate-400">(기업개요 탭)</span></li>
          <li>💬 <b>AI에게 질문</b> — 사업보고서에 직접 <span className="text-slate-400">(AI분석 탭)</span></li>
        </ul>
      </div>

      {/* ── 한계 ── */}
      <div className="rounded-xl border px-4 py-2.5 text-[12px] leading-5" style={{ background: "#fffbeb", borderColor: "#fde68a", color: "#78350f" }}>
        ⚠️ <b>참고용이에요.</b> &lsquo;정답 가격&rsquo;이나 &lsquo;반드시 오른다/내린다&rsquo;가 아니라, 동종업계 비교로 <b>판단 근거</b>를 돕는 정보예요. (투자 권유 아님)
      </div>

      {/* ── 전문가용 ── */}
      {onToggle && (
        <button onClick={onToggle} className="mt-4 w-full rounded-xl border py-3 text-[13.5px] font-bold" style={{ borderColor: C.bd, color: C.blue, background: "#f8fafc" }}>
          {expert ? "🔬 전문가용 상세 접기 ▴" : "🔬 전문가용 자세히 — 멀티플·필요성장률·기대분석·WACC ▾"}
        </button>
      )}

      <Modal open={mk != null} title={modalContent?.title} onClose={() => setMk(null)}>{modalContent?.body}</Modal>
    </div>
  );
}
