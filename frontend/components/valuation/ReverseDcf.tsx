import * as React from "react";
import { ValuationData, C, pct, spct } from "@/lib/valuation";

/** 시장이 요구하는 성장 속도 — Reverse DCF 게이지(원본 reverse-hero + gaugeHtml 재현). */
export function ReverseDcf({ d }: { d: ValuationData }) {
  const dg = d.valuation_diagnostics || {};
  const s = d.summary || {};
  const ig = dg.implied_growth;
  if (ig == null) return null;

  const gdp = dg.gdp_growth_ref || 0.03;
  const wacc = s.wacc || 0.12;
  const lo = -0.1;
  const hi = Math.max(wacc, gdp * 2 + 0.02, 0.12);
  const span = hi - lo || 1;
  const col = ig <= gdp ? C.green : ig <= gdp * 2 ? C.amber : C.red;
  const verdict = dg.implied_growth_verdict || "";
  const gw = Math.max(0, (gdp - lo) / span);
  const yw = Math.max(0, (Math.min(gdp * 2, hi) - gdp) / span);
  const rw = Math.max(0, 1 - gw - yw);
  const markPct = Math.max(0, Math.min(1, (ig - lo) / span)) * 100;
  const name = d.company?.name || "이 회사";

  return (
    <div
      className="mb-[18px] rounded-[13px] border px-[22px] pb-[14px] pt-[18px]"
      style={{ background: "linear-gradient(135deg,#fffbeb,#fef3c7)", borderColor: "#fde68a", borderLeft: "5px solid #d97706" }}
    >
      <div className="text-[11.5px] font-extrabold tracking-wide" style={{ color: "#92400e" }}>
        📊 시장이 요구하는 성장 속도 · REVERSE DCF
      </div>
      <div className="my-1.5 mb-3 text-[14.5px] leading-relaxed" style={{ color: "#451a03" }}>
        지금 주가가 정당하려면 <b>{name}</b>는(은) <b>매년 영원히 {spct(ig)}</b> 성장해야 해요. 경제성장률 {pct(gdp, 0)}과 비교하면 <b>{verdict || "—"}</b>입니다.
      </div>

      {/* 게이지 */}
      <div className="my-1.5 text-center">
        <div className="text-[34px] font-extrabold leading-tight" style={{ color: col }}>
          {spct(ig)}
        </div>
        <div className="mt-1 text-[12.5px] leading-snug text-slate-500">
          매년 영원히 이만큼 성장해야<br />지금 주가가 정당화돼요
          {verdict ? (
            <>
              {" · "}
              <b style={{ color: col }}>{verdict}</b>
            </>
          ) : null}
        </div>
      </div>
      <div className="relative mx-2.5 mb-0.5 mt-8">
        <div
          className="absolute -top-6 -translate-x-1/2 whitespace-nowrap text-[12.5px] font-bold text-slate-800"
          style={{ left: `${markPct}%` }}
        >
          ▼ 이 종목
        </div>
        <div className="flex h-[15px] overflow-hidden rounded-lg">
          <div style={{ flex: gw, background: C.green }} />
          <div style={{ flex: yw, background: C.amber }} />
          <div style={{ flex: rw, background: C.red }} />
        </div>
        <div className="mt-1.5 flex justify-between text-[10.5px] text-slate-400">
          <span>현실적</span>
          <span>경제성장 {pct(gdp, 0)}</span>
          <span>비현실적</span>
        </div>
      </div>

      <div className="mt-2.5 text-xs leading-snug" style={{ color: "#78350f" }}>
        💡 내재가치 추정 추정이 불확실해도, 이 &lsquo;필요 성장률&rsquo; 한 숫자만으로 거품/저평가 신호를 즉시 판별할 수 있어요. (내재가치 추정에 의존하지 않는 1차 진단)
      </div>
    </div>
  );
}
