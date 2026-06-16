import * as React from "react";
import { ValuationData, C, won, spct, pct } from "@/lib/valuation";

type InfoKey =
  | "range" | "leverage" | "grade" | "peer" | "industry" | "damodaran" | "opm";

function Em({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-bold" style={{ color: "#0c4a6e" }}>
      {children}
    </span>
  );
}

/** 숫자들을 평범한 말로 풀어주는 '쉽게 말하면' 문단(원본 plainLanguage 재현). */
function plainLanguage(d: ValuationData): React.ReactNode[] {
  const s = d.summary || {};
  const dg = d.valuation_diagnostics || {};
  const cur = s.current_price;
  const fair = s.fair_price;
  const gp = dg.growth_premium;
  const ig = dg.implied_growth;
  const name = d.company?.name || "이 회사";
  const lines: React.ReactNode[] = [];

  if (cur != null && fair != null) {
    if (cur > fair) {
      const p = Math.round((cur / fair - 1) * 100);
      lines.push(<>지금 <b>{name}</b> 주가는 <Em>₩{won(cur)}</Em>인데, 우리가 계산한 &lsquo;내재가치(펀더멘털 추정)&rsquo;은 <Em>₩{won(fair)}</Em>이에요. 즉 지금은 그 추정값보다 <Em>약 {p}% 비싼</Em> 편입니다.</>);
    } else {
      const p = Math.round((1 - cur / fair) * 100);
      lines.push(<>지금 <b>{name}</b> 주가는 <Em>₩{won(cur)}</Em>인데, 우리가 계산한 &lsquo;내재가치(펀더멘털 추정)&rsquo;은 <Em>₩{won(fair)}</Em>이에요. 즉 지금은 그 추정값보다 <Em>약 {p}% 싼</Em> 편입니다.</>);
    }
  } else if (cur != null) {
    lines.push(<>지금 <b>{name}</b> 주가는 <Em>₩{won(cur)}</Em>입니다. 이 회사는 미래 이익을 예측하기 불안정해 &lsquo;내재가치(펀더멘털 추정)&rsquo;을 숫자로 못 냈어요. 대신 아래 &lsquo;성장 기대&rsquo; 지표로 판단해 보세요.</>);
  }

  if (gp != null && dg.epv_price != null) {
    if (gp > 0.05) {
      lines.push(<>지금 주가에는 &ldquo;<b>앞으로 더 크게 성장할 것</b>&rdquo;이라는 기대가 <Em>약 {Math.round(gp * 100)}%</Em> 들어 있어요. 성장이 멈추고 지금 버는 만큼만 번다면 한 주의 값어치는 <Em>₩{won(dg.epv_price)}</Em> 정도예요.</>);
    } else if (gp < -0.05) {
      lines.push(<>특이하게도 지금 주가는 회사가 <b>더 성장하지 않아도</b> 될 만큼 낮아요. 성장이 0이어도 값어치(₩{won(dg.epv_price)})가 현재가보다 높습니다 — 싸게 거래되고 있다는 신호일 수 있어요.</>);
    } else {
      lines.push(<>지금 주가는 회사의 &lsquo;현재 버는 힘&rsquo;에 거의 딱 맞는 수준이에요(성장 기대가 크지 않음). 본질 값어치는 한 주당 <Em>₩{won(dg.epv_price)}</Em> 정도입니다.</>);
    }
  }

  if (ig != null && dg.implied_growth_verdict) {
    lines.push(<>그 기대가 현실적인지 보려면: 지금 주가가 맞으려면 회사가 <Em>매년 {spct(ig)}씩 영원히</Em> 커져야 해요. 우리나라 경제 성장률(약 {pct(dg.gdp_growth_ref, 0)})과 견주면 <Em>{dg.implied_growth_verdict}</Em>입니다.</>);
  }
  return lines;
}

/** 헤드라인 진단 + 분류 배지 + 고부채 경고 + '쉽게 말하면'(원본 .headline/.alert/.plain). */
export function Headline({ d, onInfo }: { d: ValuationData; onInfo?: (k: InfoKey) => void }) {
  const s = d.summary || {};
  const dg = d.valuation_diagnostics || {};
  const gp = dg.growth_premium;

  let badge = "";
  let bcol: string = C.gray;
  if (gp != null) {
    if (gp > 1) { badge = "🚀 성장 기대주"; bcol = C.amber; }
    else if (gp < -0.1) { badge = "💰 가치주 (저평가 신호)"; bcol = C.green; }
    else { badge = "⚖️ 펀더멘털 근접"; bcol = C.blue; }
  }

  const lines = plainLanguage(d);

  return (
    <>
      {/* 헤드라인 */}
      <div
        className="mb-[18px] rounded-xl px-6 py-[22px] text-white"
        style={{ background: "linear-gradient(135deg,#1b3a5b,#2d6cb5)" }}
      >
        <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[13px] opacity-85">
          <span>
            {d.company?.name || ""} ({d.company?.ticker || ""}) · 평가일 {d.as_of_date || ""}
            {d.model_version ? ` · ${d.model_version}` : ""}
            {d._cache ? " · 캐시" : ""}
          </span>
          {badge && (
            <span className="rounded-full px-2.5 py-0.5 text-xs font-bold" style={{ background: bcol }}>
              {badge}
            </span>
          )}
        </div>
        <div className="text-[17px] font-semibold leading-relaxed">
          {dg.headline || "현재가 적절성 진단 데이터 없음"}
        </div>
      </div>

      {/* 고부채 보정 경고 */}
      {s.leverage_cap_applied && (
        <div
          className="mb-[18px] flex items-center gap-3 rounded-xl border px-4 py-[13px]"
          style={{ background: "#fff7ed", borderColor: "#fed7aa", borderLeft: "5px solid #d97706" }}
        >
          <div className="text-[22px]">⚠️</div>
          <div className="flex-1 text-[13.5px] leading-snug" style={{ color: "#7c2d12" }}>
            <b style={{ color: "#9a3412" }}>고부채 보정 적용</b> — 실제 부채비율이 업계 상한을 초과해, 내재가치 추정값가 &lsquo;재무구조 정상화&rsquo; 가정을 포함합니다. 실제 부채위험은 별도로 확인하세요.
          </div>
          {onInfo && (
            <button
              className="cursor-pointer rounded-full border px-2.5 py-0.5 text-xs font-semibold"
              style={{ borderColor: C.bd, color: C.blue }}
              onClick={() => onInfo("leverage")}
            >
              자세히
            </button>
          )}
        </div>
      )}

      {/* 쉽게 말하면 */}
      {lines.length > 0 && (
        <div
          className="mb-[18px] rounded-[10px] border px-[18px] py-4"
          style={{ background: "#f0f9ff", borderColor: "#bae6fd", borderLeft: "5px solid #2d6cb5" }}
        >
          <h4 className="mb-2 text-sm font-bold" style={{ color: "#0369a1" }}>🗣️ 쉽게 말하면</h4>
          {lines.map((l, i) => (
            <p key={i} className="my-1.5 text-sm leading-7" style={{ color: "#1e3a5f" }}>{l}</p>
          ))}
        </div>
      )}
    </>
  );
}
