import * as React from "react";
import { Tip } from "./Tooltip";
import { Diagnostics, C, won, spct, pct, signalColor } from "@/lib/valuation";

/** 현재가 적절성 진단 5종 카드 (원본 .diag 재현). dg.valid 일 때만 렌더. */
export function DiagnosisCards({ dg }: { dg: Diagnostics }) {
  if (!dg?.valid) return null;
  const gp = dg.growth_premium ?? null;
  const ig = dg.implied_growth ?? null;
  const eg = dg.expectations_gap ?? null;
  const mos = dg.margin_of_safety ?? null;

  const cards = [
    {
      key: "epv",
      top: C.blue,
      lbl: "① 본질 값어치",
      tip: "EPV. 회사가 지금 버는 만큼만 앞으로도 번다고 가정(성장 0)했을 때의 1주 값어치예요. 미래 장밋빛 예측을 빼고 보수적으로 본 바닥 가치입니다.",
      val: `₩${won(dg.epv_price)}`,
      valColor: undefined,
      desc: "성장 0 가정 (보수적 바닥값)",
    },
    {
      key: "gp",
      top: signalColor(gp, true),
      lbl: "② 성장 기대분",
      tip: "성장 프리미엄. 현재 주가 중에서 앞으로 더 성장할 거라는 기대가 차지하는 비율이에요. +50%면 주가의 절반이 미래 기대. 너무 높으면 거품 위험.",
      val: spct(gp),
      valColor: signalColor(gp, true),
      desc: "주가에 섞인 기대 (낮을수록 안전)",
    },
    {
      key: "ig",
      top: C.gray,
      lbl: "③ 필요 성장률",
      tip: "시장 함의 성장률. 지금 주가가 정당하려면 회사가 매년 몇 %씩 영원히 성장해야 하는지 거꾸로 계산한 값이에요. 경제성장률(약 3%)보다 훨씬 높으면 비현실적입니다.",
      val: spct(ig),
      valColor: undefined,
      desc: `${dg.implied_growth_verdict || ""} (경제성장 ${pct(dg.gdp_growth_ref, 0)} 대비)`,
    },
    {
      key: "eg",
      top: signalColor(eg, true),
      lbl: "④ 기대 vs 실력",
      tip: "기대 격차. 시장이 요구하는 성장률(③)에서 회사가 스스로 벌어 성장할 수 있는 실력(SGR)을 뺀 값이에요. 양수면 시장 기대가 회사 실력보다 앞서간 것(과열).",
      val: spct(eg),
      valColor: signalColor(eg, true),
      desc: "시장 기대 − 회사 실력 (양수=과열)",
    },
    {
      key: "mos",
      top: signalColor(mos),
      lbl: "⑤ 안전마진",
      tip: "Margin of Safety. 본질 값어치(①)보다 현재가가 얼마나 더 싼지예요. +30%면 가치보다 30% 싸게 사는 셈이라 하락 방어막이 있고, 음수면 방어막이 없습니다.",
      val: spct(mos),
      valColor: signalColor(mos),
      desc: "본질가치 대비 할인 (+면 하락 방어막)",
    },
  ];

  return (
    <div className="mt-2">
      <h3 className="mb-1 mt-2 text-[15px] font-bold" style={{ color: C.navy }}>
        🔍 지금 가격, 5가지로 진단해 봤어요
      </h3>
      <div className="mb-2 mt-1 flex flex-wrap gap-4 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: C.green }} /> 초록 = 유리한 신호(싸거나 안전)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: C.red }} /> 빨강 = 주의 신호(비싸거나 기대 과함)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: C.gray }} /> 회색 = 중립/판단 보류
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {cards.map((c) => (
          <div
            key={c.key}
            className="rounded-xl border bg-white p-4 text-center"
            style={{ borderColor: C.bd, borderTop: `4px solid ${c.top}` }}
          >
            <div className="text-[11px] font-semibold text-slate-500">
              {c.lbl}
              <Tip text={c.tip} />
            </div>
            <div className="my-1.5 text-[22px] font-extrabold" style={{ color: c.valColor }}>
              {c.val}
            </div>
            <div className="text-[11px] leading-snug text-slate-500">{c.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
