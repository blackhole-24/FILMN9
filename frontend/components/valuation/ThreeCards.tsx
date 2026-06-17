import * as React from "react";
import { Tip } from "./Tooltip";
import { ValuationData, ValSummary, C, won, pct, spct } from "@/lib/valuation";

type InfoKey =
  | "range" | "leverage" | "grade" | "peer" | "industry" | "damodaran" | "opm";

const GRADE_META: Record<string, { color: string; label: string }> = {
  A: { color: "#16a34a", label: "A · 정밀" },
  B: { color: "#2d6cb5", label: "B · 양호" },
  C: { color: "#d97706", label: "C · 주의" },
  D: { color: "#ea580c", label: "D · 점추정 곤란" },
  E: { color: "#dc2626", label: "E · DCF 부적합" },
};

const PEER_COLOR: Record<string, string> = {
  A: "#16a34a", B: "#2d6cb5", C: "#d97706", D: "#ea580c", E: "#dc2626",
};

/** 내재가치 추정값 범위 막대(원본 fairRangeBar 재현): 보수~낙관 밴드 + 추정(점선) + 현재가(빨강). */
function FairRangeBar({ s }: { s: ValSummary }) {
  const lo = s.fair_price_low, hi = s.fair_price_high, fair = s.fair_price, cur = s.current_price;
  if (lo == null || hi == null || fair == null || hi <= lo) return null;
  const vals = [lo, hi, fair];
  if (cur != null) vals.push(cur);
  let dmin = Math.min(...vals), dmax = Math.max(...vals);
  const pad = (dmax - dmin) * 0.14 || dmax * 0.1;
  dmin -= pad; dmax += pad;
  const span = dmax - dmin || 1;
  const P = (v: number) => Math.max(0, Math.min(100, ((v - dmin) / span) * 100));
  const bl = P(lo), bw = P(hi) - P(lo), fp = P(fair), cp = cur != null ? P(cur) : null;

  return (
    <div className="relative mb-0.5 mt-7">
      <div className="relative h-3.5 rounded-lg" style={{ background: "linear-gradient(90deg,#fca5a5,#fde68a,#86efac)" }}>
        <div
          className="absolute top-0 h-3.5"
          style={{ left: `${bl}%`, width: `${bw}%`, background: "rgba(45,108,181,.30)", borderLeft: `2px solid ${C.blue}`, borderRight: `2px solid ${C.blue}` }}
        />
        <div className="absolute -top-1.5 h-6" style={{ left: `${fp}%`, borderLeft: `2px dashed ${C.navy}` }} />
        <div className="absolute -translate-x-1/2 whitespace-nowrap text-[10px] font-bold" style={{ left: `${fp}%`, top: -19, color: C.navy }}>
          추정 ₩{won(fair)}
        </div>
        {cp != null && (
          <>
            <div className="absolute -top-1.5 h-6" style={{ left: `${cp}%`, borderLeft: `2px solid ${C.red}` }} />
            <div className="absolute -translate-x-1/2 whitespace-nowrap text-[10px] font-bold" style={{ left: `${cp}%`, top: 25, color: C.red }}>
              현재 ₩{won(cur)}
            </div>
          </>
        )}
      </div>
      <div className="mt-1.5 flex justify-between text-[10.5px] text-slate-500">
        <span>보수 ₩{won(lo)}</span>
        <span>낙관 ₩{won(hi)}</span>
      </div>
    </div>
  );
}

function Pill({ bg, children, onClick }: { bg: string; children: React.ReactNode; onClick?: () => void }) {
  return (
    <span
      className={`ml-1.5 inline-block rounded-md px-2 py-0.5 align-middle text-[11px] font-extrabold text-white ${onClick ? "cursor-pointer" : ""}`}
      style={{ background: bg }}
      onClick={onClick}
    >
      {children}
    </span>
  );
}

/** 현재 주가 / 내재가치 추정(+범위·배지) / WACC 3카드(원본 grid g3 재현). */
export function ThreeCards({ d, onInfo }: { d: ValuationData; onInfo?: (k: InfoKey) => void }) {
  const s = d.summary || {};
  const cur = s.current_price, fair = s.fair_price, up = s.upside_pct;
  const grade = s.dcf_grade || "B";
  const gMeta = GRADE_META[grade] || GRADE_META.B;
  const showPoint = s.dcf_show_point_estimate !== false;

  const indCat = s.industry_category || "unknown";
  const indLabel = ({ cyclical: "경기민감", mature: "성숙안정", growth: "성장", unknown: "미분류" } as Record<string, string>)[indCat] || "미분류";
  const indColor = ({ cyclical: "#92400e", mature: "#166534", growth: "#1e3a8a", unknown: "#475569" } as Record<string, string>)[indCat] || "#475569";
  const indBg = ({ cyclical: "#fef3c7", mature: "#dcfce7", growth: "#dbeafe", unknown: "#f1f5f9" } as Record<string, string>)[indCat] || "#f1f5f9";

  const opmW = s.opm_window_used;
  const dmd = s.damodaran_check;
  const pcGrade = s.peer_confidence_grade || d.peer_confidence?.grade;

  return (
    <div className="mb-[18px] grid gap-4 md:grid-cols-3">
      {/* 현재 주가 */}
      <div className="rounded-xl border bg-white p-5" style={{ borderColor: C.bd }}>
        <h3 className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-slate-500">
          현재 주가
          <Tip text="지금 증권시장에서 거래되는 1주의 가격이에요. 평가 기준일의 종가(마감 가격)입니다." />
        </h3>
        <div className="text-[30px] font-extrabold" style={{ color: C.navy }}>₩{won(cur)}</div>
        <div className="text-[13px] text-slate-500">시장이 매기는 값</div>
      </div>

      {/* 내재가치 추정 */}
      <div className="rounded-xl border bg-white p-5" style={{ borderColor: C.bd }}>
        <h3 className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-slate-500">
          내재가치 추정
          <Tip text="회사의 미래 현금흐름을 예측해 추정한 1주의 정당한 가격(DCF). 현재가가 이보다 높으면 비싼 편, 낮으면 싼 편. 미래 예측이라 절대적 정답은 아니고 참고용입니다." />
          <Pill bg={gMeta.color} onClick={onInfo && (() => onInfo("grade"))}>{gMeta.label}</Pill>
          {pcGrade && (
            <Pill bg={PEER_COLOR[pcGrade] || C.blue} onClick={onInfo && (() => onInfo("peer"))}>👥 피어 {pcGrade}</Pill>
          )}
          <span
            className={`ml-1.5 inline-block rounded-xl border px-2 py-0.5 align-middle text-[11px] font-bold ${onInfo ? "cursor-pointer" : ""}`}
            style={{ background: indBg, color: indColor, borderColor: indColor }}
            onClick={onInfo && (() => onInfo("industry"))}
          >
            🏭 {indLabel}
          </span>
          {opmW && (
            <span
              className={`ml-1.5 inline-block rounded-xl px-1.5 py-0.5 align-middle text-[10.5px] ${onInfo ? "cursor-pointer" : ""}`}
              style={{ background: "#eef2ff", color: "#3730a3", border: "1px solid #c7d2fe" }}
              onClick={onInfo && (() => onInfo("opm"))}
            >
              OPM {opmW.startsWith("8yr") ? "8년" : "3년"}
            </span>
          )}
          {dmd?.available && dmd.warn_gt_0p3 && (
            <span
              className={`ml-1.5 inline-block rounded-xl px-2 py-0.5 align-middle text-[11px] font-bold ${onInfo ? "cursor-pointer" : ""}`}
              style={{ background: "#fee2e2", color: "#991b1b", border: "1px solid #fecaca" }}
              onClick={onInfo && (() => onInfo("damodaran"))}
            >
              ⚠ βU 산업 평균과 이격
            </span>
          )}
        </h3>

        {showPoint && fair != null ? (
          <>
            <div className="text-[30px] font-extrabold" style={{ color: C.navy }}>₩{won(fair)}</div>
            <div className="text-[13px]" style={{ color: up == null ? C.gray : up > 0 ? C.green : up < 0 ? C.red : C.gray }}>
              {up == null ? "계산 불가" : `상승여력 ${spct(up / 100)}`}
            </div>
          </>
        ) : (
          <>
            <div className="my-1 text-[15px] font-bold" style={{ color: gMeta.color }}>
              {grade === "E" ? "⚠ DCF 부적합" : "⚠ 점추정 신뢰 어려움"}
            </div>
            <div className="text-[13px] leading-snug text-slate-500">
              {grade === "E"
                ? (s.dcf_invalid_reason || "적자 또는 영업투하자본 비정상으로 현금흐름 기반 평가가 곤란합니다. 멀티플·EPV·5종 진단을 참고하세요.")
                : "정상화·Terminal 가정의 작은 변동에도 결과가 크게 흔들립니다. 점추정 대신 아래 추정 범위와 5종 진단으로 판단하세요."}
            </div>
          </>
        )}

        {fair != null && s.fair_price_low != null && s.fair_price_high != null && (
          <>
            <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[13px] text-slate-500">
              추정 범위 <b style={{ color: C.navy }}>₩{won(s.fair_price_low)} ~ ₩{won(s.fair_price_high)}</b>
              {onInfo && (
                <button
                  className="cursor-pointer rounded-full border px-2.5 py-0.5 text-xs font-semibold"
                  style={{ borderColor: C.bd, color: C.blue }}
                  onClick={() => onInfo("range")}
                >
                  왜 범위인가요?
                </button>
              )}
            </div>
            <FairRangeBar s={s} />
          </>
        )}
      </div>

      {/* WACC */}
      <div className="rounded-xl border bg-white p-5" style={{ borderColor: C.bd }}>
        <h3 className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-slate-500">
          WACC
          <Tip text="회사가 돈(주주 자본+빌린 돈)을 쓰는 데 드는 평균 비용률. 미래의 돈을 현재가치로 환산할 때 쓰는 할인율로, 높을수록 미래 이익을 깐깐하게 봅니다. 보통 8~13%." />
        </h3>
        <div className="text-[30px] font-extrabold" style={{ color: C.navy }}>{pct(s.wacc, 2)}</div>
        <div className="text-[13px] text-slate-500">자금 조달 비용 · Ke {pct(s.ke, 2)} · Rf {pct(s.rf, 2)}</div>
      </div>
    </div>
  );
}
