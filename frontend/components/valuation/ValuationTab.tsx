"use client";

import * as React from "react";
import { ValuationData } from "@/lib/valuation";
import { SimpleValuation } from "./SimpleValuation";
import { ExpertView } from "./ExpertView";
import { ValuationTutorial } from "./ValuationTutorial";

/** 미평가 종목 안내 (NO-MOCK — 가짜 숫자 미표시). */
function NotEvaluated({ code }: { code?: string }) {
  return (
    <div className="rounded-xl border px-6 py-[22px]" style={{ background: "#f0f9ff", borderColor: "#bae6fd", borderLeft: "5px solid #0ea5e9" }}>
      <h3 className="mb-2.5 text-[17px] font-bold" style={{ color: "#0369a1" }}>
        ⏳ 아직 평가되지 않은 종목이에요{code ? ` (${code})` : ""}
      </h3>
      <p className="text-sm leading-7" style={{ color: "#1e3a5f" }}>
        실데이터만 보여주는 원칙(NO-MOCK)에 따라 <b>가짜 숫자를 표시하지 않습니다.</b> 백그라운드 평가가 완료되면 동종업계 비교·진단이 자동으로 채워집니다.
      </p>
    </div>
  );
}

/** 금융·지주 등 DCF 미지원 종목 안내. */
function Unsupported({ d }: { d: ValuationData }) {
  const kindMap: Record<string, string> = {
    financial: "DDM(배당할인) · RIM(잔여이익) · P-B-ROE",
    holding: "NAV(순자산합산) · SOTP(사업부별 합산)",
  };
  const alt = kindMap[d.unsupported_kind || ""] || "별도 평가 모델 필요";
  return (
    <div className="rounded-xl border px-6 py-[22px]" style={{ background: "#f0f9ff", borderColor: "#bae6fd", borderLeft: "5px solid #0ea5e9" }}>
      <h3 className="mb-2.5 text-[17px] font-bold" style={{ color: "#0369a1" }}>
        ⚠ {d.company?.name || "이 종목"}은(는) 현금흐름 평가(DCF) 대상이 아닙니다
      </h3>
      <p className="text-sm leading-7" style={{ color: "#1e3a5f" }}>
        {d.unsupported_reason || "이 종목은 일반 현금흐름 방식이 맞지 않습니다."}
      </p>
      <p className="mt-3 text-[13px]" style={{ color: "#0c4a6e" }}>
        💡 <b>권장 평가 방법:</b> {alt}
      </p>
    </div>
  );
}

/**
 * 밸류에이션 탭.
 * 기본: 일반 투자자용 단순 화면(SimpleValuation) — 방향 결론 + 근거 + 종합 한마디 + 멀티플 + 다음 안내.
 * '전문가용 자세히'를 누르면 ExpertView(한 걸음 더, 고등~대학 수준)가 펼쳐진다.
 *  - 현재가와 괴리 큰 가격(DCF 적정주가·EPV·시나리오)은 숫자로 내세우지 않고 설명·방향으로 제공.
 */
export function ValuationTab({ data, realtimePrice, tutOpen, onTutChange }: { data: ValuationData | null; realtimePrice?: number | null; tutOpen?: boolean; onTutChange?: (v: boolean) => void }) {
  const [expert, setExpert] = React.useState(false);

  if (!data) {
    return <div className="py-12 text-center text-sm text-slate-400">밸류에이션 데이터를 불러오는 중…</div>;
  }
  if (data.is_mock) {
    return <NotEvaluated code={data.stock_code} />;
  }
  if (data.status === "unsupported") {
    return <Unsupported d={data} />;
  }

  return (
    <div className="text-slate-800">
      {/* ── 일반 투자자용 단순 화면 (기본) ── */}
      <SimpleValuation d={data} realtimePrice={realtimePrice} expert={expert} onToggle={() => setExpert((v) => !v)} />

      {/* ── 전문가용 상세 (접기/펼치기) ── */}
      {expert && (
        <div className="mt-6 border-t border-slate-200 pt-6">
          <div className="mb-4 text-[12px] font-bold uppercase tracking-wide text-slate-400">🔬 전문가용 상세 — 한 걸음 더 (고등~대학 수준)</div>
          <ExpertView d={data} />
        </div>
      )}

      {/* ── 튜토리얼 패널 (우측 슬라이드) — 버튼은 상단 탭바(page.tsx)에 위치 ── */}
      <ValuationTutorial data={data} realtimePrice={realtimePrice} open={!!tutOpen} onClose={() => onTutChange?.(false)} />
    </div>
  );
}
