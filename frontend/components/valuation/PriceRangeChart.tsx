"use client";

import * as React from "react";
import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Tip } from "./Tooltip";
import { ValuationData, C, won } from "@/lib/valuation";

/** 여러 방법으로 본 가격대 — EPV/Bear/Base/Bull/DCF 막대 + 현재가 라인(원본 drawRange 재현). */
export function PriceRangeChart({ d }: { d: ValuationData }) {
  const s = d.summary || {};
  const dg = d.valuation_diagnostics || {};
  const sc = d.scenarios || {};
  const cur = s.current_price ?? null;

  const items: { name: string; value: number; color: string }[] = [];
  if (dg.epv_price != null) items.push({ name: "EPV(성장0)", value: Number(dg.epv_price), color: "#94a3b8" });
  if (sc.Bear?.price != null) items.push({ name: "Bear", value: Number(sc.Bear.price), color: "#f87171" });
  if (sc.Base?.price != null) items.push({ name: "Base", value: Number(sc.Base.price), color: "#60a5fa" });
  if (sc.Bull?.price != null) items.push({ name: "Bull", value: Number(sc.Bull.price), color: "#34d399" });
  if (s.fair_price != null) items.push({ name: "DCF", value: Number(s.fair_price), color: C.blue });

  if (items.length === 0) return null;

  return (
    <div className="mt-4 rounded-xl border bg-white p-[18px]" style={{ borderColor: C.bd }}>
      <h3 className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-slate-500">
        여러 방법으로 본 가격대
        <Tip text="한 가지 방법만 믿지 않도록, 보수적 가치(본질값어치)·낙관/비관 시나리오·동종업계 비교 등 여러 잣대로 추정한 가격을 한눈에 모았어요. 빨간 선이 현재가입니다." />
      </h3>
      <div style={{ width: "100%", height: 280 }}>
        <ResponsiveContainer>
          <BarChart data={items} margin={{ top: 10, right: 12, left: 8, bottom: 4 }}>
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#64748b" }} axisLine={{ stroke: C.bd }} tickLine={false} />
            <YAxis
              tickFormatter={(v: number) => "₩" + won(v)}
              tick={{ fontSize: 11, fill: "#64748b" }}
              axisLine={{ stroke: C.bd }}
              tickLine={false}
              width={72}
            />
            <RTooltip
              formatter={(v) => ["₩" + won(Number(v)), "추정가"]}
              labelStyle={{ color: C.navy, fontWeight: 700 }}
              contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${C.bd}` }}
            />
            <Bar dataKey="value" radius={[5, 5, 0, 0]}>
              {items.map((it, i) => (
                <Cell key={i} fill={it.color} />
              ))}
            </Bar>
            {cur != null && (
              <ReferenceLine
                y={cur}
                stroke={C.red}
                strokeWidth={2}
                strokeDasharray="6 4"
                label={{ value: `현재가 ₩${won(cur)}`, position: "right", fill: C.red, fontSize: 11 }}
              />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1.5 text-[11px] text-slate-500">
        막대 = 방법별 추정 가격 / 빨간 점선 = 현재 주가. 현재가가 막대들보다 위면 비싼 편.
      </div>
    </div>
  );
}
