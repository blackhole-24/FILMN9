import * as React from "react";
import { ValuationData, C, won } from "@/lib/valuation";

/** 문자/숫자 혼합 값에서 숫자만 파싱 (예: "17.54×" → 17.54, "-16.1" → -16.1). */
function numv(x: any): number | null {
  if (x == null) return null;
  if (typeof x === "number") return x;
  const n = parseFloat(String(x).replace(/[^0-9.\-]/g, ""));
  return isNaN(n) ? null : n;
}

/**
 * 멀티플(상대가치) — 밸류 탭 '맨 앞' 섹션.
 * 일반 투자자에게 가장 직관적인 "동종업계 대비 비싼가/싼가"를 먼저 제시.
 * data.multiples 한글 키 직접 사용: { 멀티플, 피어 중위, 역산가, vs 현재, 판정 }
 */
export function MultiplesSummary({ d }: { d: ValuationData }) {
  const rows = (d.multiples || []) as any[];
  if (!rows.length) return null;

  let cheap = 0, rich = 0;
  rows.forEach((m) => {
    const vs = numv(m["vs 현재"] ?? m["vs현재"]);
    if (vs != null) { if (vs > 3) cheap++; else if (vs < -3) rich++; }
  });
  const verdict =
    cheap > rich
      ? { txt: `${rows.length}개 지표 중 ${cheap}개가 "동종업계 대비 싼 편" 신호`, col: C.green, emo: "🟢" }
      : rich > cheap
      ? { txt: `${rows.length}개 지표 중 ${rich}개가 "동종업계 대비 비싼 편" 신호`, col: C.red, emo: "🔴" }
      : { txt: "동종업계와 대체로 비슷한 가격대", col: C.blue, emo: "⚖️" };

  return (
    <div className="mb-[18px] rounded-xl border bg-white p-5" style={{ borderColor: C.bd }}>
      <h3 className="text-[15px] font-bold" style={{ color: C.navy }}>
        ① 동종업계와 비교하면 — 지금 비싼가, 싼가?{" "}
        <span className="text-[12px] font-normal text-slate-400">상대가치 · 멀티플</span>
      </h3>
      <p className="mb-3 mt-1 text-[13px] leading-6 text-slate-500">
        비슷한 회사들이 시장에서 받는 <b>가격 배수</b>(PER · EV/EBITDA 등)를 이 회사에 적용하면 한 주의 가격이 나옵니다. 그 가격을 현재 주가와 견주는 <b>가장 직관적인 &lsquo;동종업계 대비&rsquo;</b> 판단이에요.
      </p>

      <div
        className="mb-3 inline-block rounded-lg px-3 py-1.5 text-[13px] font-bold"
        style={{ background: verdict.col + "1a", color: verdict.col }}
      >
        {verdict.emo} {verdict.txt}
      </div>

      <div className="grid gap-2.5 sm:grid-cols-2">
        {rows.map((m, i) => {
          const name = String(m["멀티플"] ?? "");
          const peer = String(m["피어 중위"] ?? m["피어중위"] ?? "—");
          const imp = numv(m["역산가"]);
          const vs = numv(m["vs 현재"] ?? m["vs현재"]);
          const col = vs == null ? C.gray : vs > 3 ? C.green : vs < -3 ? C.red : C.gray;
          const sig = vs == null ? "" : vs > 3 ? "싼 편" : vs < -3 ? "비싼 편" : "비슷";
          return (
            <div key={i} className="rounded-lg border p-3" style={{ borderColor: C.bd, borderLeft: `4px solid ${col}` }}>
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-bold text-slate-700">{name}</span>
                {vs != null && (
                  <span className="text-[12px] font-bold" style={{ color: col }}>
                    {sig} {vs > 0 ? "+" : ""}{vs.toFixed(0)}%
                  </span>
                )}
              </div>
              <div className="mt-1 text-[12px] text-slate-500">
                동종 중위 <b>{peer}</b> → 이 지표로 본 가격{" "}
                <b style={{ color: C.navy }}>₩{imp != null ? won(imp) : "—"}</b>
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-3 text-[11.5px] leading-5 text-slate-400">
        ※ <b>+%</b>는 동종업계 기준가가 현재 주가보다 높다(=저평가·싼 신호), <b>−%</b>는 낮다(=고평가·비싼 신호). 미래 예측이 아닌 <b>현재 시점의 상대 비교</b>라 가장 즉시적인 참고 지표예요. 한 지표만 보지 말고 아래 펀더멘털 분석과 함께 보세요.
      </p>
    </div>
  );
}
