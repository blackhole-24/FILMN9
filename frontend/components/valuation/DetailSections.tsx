import * as React from "react";
import { Tip } from "./Tooltip";
import { ValuationData, C, won } from "@/lib/valuation";

const numv = (x: unknown): number | null => (x == null || isNaN(Number(x)) ? null : Number(x));
const strv = (x: unknown): string => (x == null ? "" : String(x));

const TH = "border-b px-2 py-1.5 text-right text-[11px] font-semibold uppercase text-slate-500 first:text-left";
const TD = "border-b px-2 py-1.5 text-right first:text-left";

/** 멀티플 역산 표(원본 fillMult 재현). 한글 키 직접 사용. */
function MultiplesTable({ d }: { d: ValuationData }) {
  const cur = numv(d.summary?.current_price);
  const rows = d.multiples || [];
  return (
    <table className="w-full border-collapse text-[13px]">
      <thead><tr><th className={TH}>멀티플</th><th className={TH}>피어중위</th><th className={TH}>역산가</th><th className={TH}>vs 현재</th></tr></thead>
      <tbody>
        {rows.map((m, i) => {
          const v = numv(m["역산가"]);
          const vs = v != null && cur ? (v / cur - 1) * 100 : null;
          const tag = vs == null ? "n" : vs > 0 ? "u" : "o";
          const tagStyle = tag === "u" ? { background: "#dcfce7", color: C.green } : tag === "o" ? { background: "#fee2e2", color: C.red } : { background: "#f1f5f9", color: C.gray };
          return (
            <tr key={i}>
              <td className={TD}>{strv(m["멀티플"])}</td>
              <td className={TD}>{strv(m["피어 중위"])}</td>
              <td className={TD}>₩{won(v)}</td>
              <td className={TD}><span className="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold" style={tagStyle}>{vs == null ? "—" : (vs > 0 ? "+" : "") + vs.toFixed(0) + "%"}</span></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** 피어 베타 표(원본 fillPeer 재현). */
function PeerBetaTable({ d }: { d: ValuationData }) {
  const rows = d.peer_beta || [];
  return (
    <table className="w-full border-collapse text-[13px]">
      <thead><tr><th className={TH}>회사</th><th className={TH}>β(adj)</th><th className={TH}>R²</th><th className={TH}>경고</th></tr></thead>
      <tbody>
        {rows.map((p, i) => {
          const warn = strv(p["warn"]);
          return (
            <tr key={i}>
              <td className={TD}>{strv(p["회사"])}</td>
              <td className={TD}>{strv(p["β_adj"]) || "—"}</td>
              <td className={TD}>{strv(p["R²"]) || "—"}</td>
              <td className={`${TD} text-[11px]`} style={{ color: C.amber }}>{warn === "-" ? "" : warn}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** WACC 분해 표(원본 fillWacc 재현). wacc_breakdown = [항목, 값, 근거][]. */
function WaccTable({ d }: { d: ValuationData }) {
  const rows = d.wacc_breakdown || [];
  return (
    <table className="w-full border-collapse text-[13px]">
      <thead><tr><th className={TH}>항목</th><th className={TH}>값</th><th className={TH}>근거</th></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td className={TD}>{strv(r?.[0])}</td>
            <td className={TD}>{strv(r?.[1])}</td>
            <td className={`${TD} text-[11px] text-slate-500`}>{strv(r?.[2])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const GLOSSARY: [string, string][] = [
  ["내재가치 (DCF)", "회사가 미래에 벌 현금을 예측해 오늘 가치로 환산한, 1주의 '정당한' 가격."],
  ["WACC (할인율)", "회사가 돈을 쓰는 평균 비용률. 미래의 돈을 오늘 가치로 깎을 때 쓰는 비율."],
  ["본질 값어치 (EPV)", "지금 버는 만큼만 계속 번다고 볼 때(성장 0)의 보수적 1주 가치 — '바닥값'."],
  ["성장 기대분", "현재 주가 중 '앞으로 더 클 것'이라는 기대가 차지하는 비율. 높을수록 거품 위험↑."],
  ["필요 성장률", "지금 주가가 맞으려면 매년 몇 %씩 영원히 커져야 하는지. 경제성장률보다 크게 높으면 비현실적."],
  ["안전마진", "본질 값어치보다 현재가가 얼마나 더 싼지. 클수록 하락 방어막이 두텁습니다."],
  ["베타", "시장이 1% 움직일 때 이 주식이 몇 % 움직이는지. 1보다 크면 변동이 큼."],
  ["멀티플", "비슷한 회사들이 받는 가격 배수(PER 등)를 적용해 본 가격 — 교차 검증용."],
  ["피어셋 (비교 대상)", "사업·규모가 비슷해 비교 기준으로 고른 동종 회사들. 신뢰도 등급(A~E)으로 표시."],
  ["영업이익률 (OPM)", "매출 100원당 본업에서 남기는 이익. 멀티플·내재가치 추정값에 큰 영향."],
  ["순부채", "이자 내는 차입금에서 보유 현금을 뺀 '실질 빚'. 기업가치에서 빼야 주주 몫이 남음."],
];

/** 계산 근거 + 용어사전(원본 detail grid + glossary 재현). */
export function DetailSections({ d }: { d: ValuationData }) {
  return (
    <>
      {/* 용어 사전 */}
      <details className="mt-5 rounded-[10px] border bg-white px-[18px]" style={{ borderColor: C.bd }}>
        <summary className="cursor-pointer py-3 text-sm font-bold" style={{ color: C.navy }}>📚 용어가 어렵다면 — 쉬운 풀이 펼치기</summary>
        <dl className="grid grid-cols-1 gap-x-3.5 gap-y-2 py-1.5 pb-3.5 text-[13px] md:grid-cols-[150px_1fr]">
          {GLOSSARY.map(([t, dd]) => (
            <React.Fragment key={t}>
              <dt className="font-bold" style={{ color: C.blue }}>{t}</dt>
              <dd className="m-0 leading-relaxed text-slate-600">{dd}</dd>
            </React.Fragment>
          ))}
        </dl>
      </details>

      {/* 계산 근거 */}
      <div className="mb-3 mt-[22px] border-t border-dashed pt-4 text-[13.5px] font-bold text-slate-500" style={{ borderColor: C.bd }}>
        🧮 아래는 위 결과가 <b>어떻게 나왔는지</b> 보여주는 계산 근거예요 (자세히 보고 싶을 때만)
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border bg-white p-[18px]" style={{ borderColor: C.bd }}>
          <h3 className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-slate-500">동종업계와 비교한 가격 수준<Tip text="비슷한 회사들이 시장에서 받는 가격 배수(PER·EV/EBITDA 등)를 이 회사에 적용한 값. DCF와 다른 각도의 교차 검증." /></h3>
          <MultiplesTable d={d} />
        </div>
        <div className="rounded-xl border bg-white p-[18px]" style={{ borderColor: C.bd }}>
          <h3 className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-slate-500">주가 변동성(베타) 비교<Tip text="베타는 시장이 1% 움직일 때 이 주식이 몇 % 움직이는지. 1보다 크면 변동이 크고 위험이 커 WACC도 올라갑니다." /></h3>
          <PeerBetaTable d={d} />
        </div>
      </div>
      <div className="mt-4 rounded-xl border bg-white p-[18px]" style={{ borderColor: C.bd }}>
        <h3 className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-slate-500">할인율(WACC)은 어떻게 나왔나<Tip text="미래 현금을 깎는 비율(WACC)이 어떤 재료로 계산됐는지: 국채금리(Rf), 주식 위험 보상, 빌린 돈 이자 등." /></h3>
        <WaccTable d={d} />
      </div>

      <div className="mt-6 border-t pt-3.5 text-center text-[11px] leading-relaxed text-slate-500" style={{ borderColor: C.bd }}>
        본 결과는 공개된 재무·공시 데이터를 바탕으로 한 <b>자동 추정치</b>이며, 미래 예측이 포함되어 오차가 있을 수 있습니다.<br />
        특정 종목의 매수·매도를 권유하지 않으며, 투자 판단과 책임은 투자자 본인에게 있습니다. (학습·참고용)
      </div>
    </>
  );
}
