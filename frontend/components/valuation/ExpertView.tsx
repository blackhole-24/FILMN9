import * as React from "react";
import { ValuationData, C, pct, spct } from "@/lib/valuation";

function numv(x: any): number | null {
  if (x == null) return null;
  if (typeof x === "number") return x;
  const n = parseFloat(String(x).replace(/[^0-9.\-]/g, ""));
  return isNaN(n) ? null : n;
}
/** 친근한 반올림 (예: 113,239 → "약 11.3만원"). */
function manWon(n: number | null | undefined): string {
  if (n == null) return "—";
  const m = n / 10000;
  if (m >= 100) return `약 ${Math.round(m).toLocaleString()}만원`;
  if (m >= 1) return `약 ${Math.round(m * 10) / 10}만원`;
  return `약 ${(Math.round(n / 100) * 100).toLocaleString()}원`;
}
/** 큰 금액(원 단위) → 조/억 (예: 12.08조 → "약 12.1조원", 5,017억 → "약 5,017억원"). */
function bigWon(n: number | null | undefined): string {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `약 ${(n / 1e12).toFixed(1)}조원`;
  if (a >= 1e8) return `약 ${Math.round(n / 1e8).toLocaleString()}억원`;
  return manWon(n);
}

function SectionTitle({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <div className="mb-2.5">
      <h3 className="text-[16px] font-extrabold" style={{ color: C.navy }}>{children}</h3>
      {sub && <p className="mt-1 text-[12.5px] leading-6 text-slate-500">{sub}</p>}
    </div>
  );
}

/** 필요성장률 게이지 (Reverse DCF) — 가격이 아닌 '성장률'이라 현재가와 괴리 없음. */
function GrowthGauge({ ig, gdp, verdict }: { ig: number; gdp: number; verdict?: string }) {
  if (ig < 0) {
    return (
      <div className="mt-3 text-center">
        <div className="text-[30px] font-extrabold leading-tight" style={{ color: C.green }}>{spct(ig)}</div>
        <div className="mx-auto mt-1 max-w-md text-[12px] leading-6 text-slate-500">시장은 이 회사가 앞으로 <b>매년 약 {(Math.abs(ig) * 100).toFixed(1)}%씩 줄어들 것</b>(마이너스 성장)으로 보고 있어요 — 성장 기대가 <b>바닥</b>이라는 뜻이에요.</div>
        {verdict && <div className="mt-2.5 text-[13px] font-bold" style={{ color: C.green }}>판정: {verdict}</div>}
        <div className="mx-auto mt-2.5 max-w-md rounded-lg border px-3 py-2 text-left text-[11.5px] leading-5 text-slate-500" style={{ borderColor: C.bd, background: "#f8fafc" }}>💡 기대가 너무 낮아 <b>저평가 기회</b>일 수도 있지만, 회사가 <b>정말 그렇게 나빠지는 중인지</b>(업황·실적) 꼭 확인하세요.</div>
      </div>
    );
  }
  const lo = -0.05;
  const hi = Math.max(gdp * 3 + 0.02, 0.15);
  const span = hi - lo || 1;
  const col = ig <= gdp ? C.green : ig <= gdp * 2 ? "#d97706" : C.red;
  const Q = (v: number) => Math.max(0, Math.min(100, ((v - lo) / span) * 100));
  const gw = Q(gdp), yw = Q(gdp * 2) - Q(gdp), rw = 100 - Q(gdp * 2);
  const mk = Q(ig);
  return (
    <div className="mt-3">
      <div className="text-center text-[30px] font-extrabold leading-tight" style={{ color: col }}>{spct(ig)}</div>
      <div className="text-center text-[12px] text-slate-500">매년 영원히 이만큼 성장해야 지금 주가가 정당화돼요</div>
      <div className="relative mx-2 mt-8">
        <div className="absolute -top-6 -translate-x-1/2 whitespace-nowrap text-[12px] font-bold text-slate-800" style={{ left: `${mk}%` }}>▼ 이 종목</div>
        <div className="flex h-3.5 overflow-hidden rounded-lg">
          <div style={{ width: `${gw}%`, background: C.green }} />
          <div style={{ width: `${yw}%`, background: "#fbbf24" }} />
          <div style={{ width: `${rw}%`, background: C.red }} />
        </div>
        <div className="mt-1.5 flex justify-between text-[10.5px] text-slate-400">
          <span>현실적</span><span>경제성장 {pct(gdp, 0)}</span><span>비현실적</span>
        </div>
      </div>
      {verdict && <div className="mt-3.5 text-center text-[13px] font-bold" style={{ color: col }}>판정: {verdict}</div>}
    </div>
  );
}

/**
 * 전문가용 상세 — '한 걸음 더(고등학생~대학생)'.
 * 설계 원칙:
 *  - 현재가와 괴리 큰 가격(DCF 적정주가·EPV·Bear/Bull)은 '숫자로' 내세우지 않고 '왜 다른가'를 설명한다.
 *  - 핵심은 가격이 아닌 '비율' 지표: 필요성장률 · 성장기대분 · 기대vs실력 (현재가와 괴리 없음).
 *  - 베타 회귀(R²)·Hamada·학술 인용 등 대학원/실무 수준은 제거, 개념만 쉽게.
 */
export function ExpertView({ d }: { d: ValuationData }) {
  const s = d.summary || {};
  const dg = d.valuation_diagnostics || {};
  const name = d.company?.name || "이 회사";
  const ig = dg.implied_growth;
  const gdp = dg.gdp_growth_ref || 0.03;
  const gp = dg.growth_premium;
  const eg = dg.expectations_gap;
  const rows = (d.multiples || []) as any[];
  const pcGrade = s.peer_confidence_grade || d.peer_confidence?.grade;

  return (
    <div className="text-slate-800">
      {/* 안내: 두 가지 눈 */}
      <div className="mb-5 rounded-xl border px-5 py-4 text-[13px] leading-7" style={{ background: "#f8fafc", borderColor: C.bd, borderLeft: `5px solid ${C.navy}` }}>
        <b style={{ color: C.navy }}>🎓 한 걸음 더 — 전문가는 이렇게 봅니다</b><br />
        주가를 <b>두 가지 눈</b>으로 봐요. ① <b>상대가치(멀티플)</b> — 비슷한 회사와 비교하는 방식으로, <b>현재가에 가까워</b> 바로 참고하기 좋아요. ② <b>내재가치(DCF)</b> — 미래에 벌 현금을 추정하는 방식인데, <b>가정에 민감</b>해 현재가와 차이가 클 수 있어요. 그래서 ②는 <b>&lsquo;가격 숫자&rsquo;로 못 박지 않고</b>, <b>지금 주가에 어떤 기대가 담겼는지</b>를 읽는 데 씁니다.
      </div>

      {/* 1. 상대가치 깊이 — 멀티플 표 (현재가 근처라 수치 OK) */}
      {rows.length > 0 && (
        <div className="mb-5 rounded-xl border bg-white p-5" style={{ borderColor: C.bd }}>
          <SectionTitle sub="비슷한 회사들이 받는 '가격 배수'를 이 회사에 적용해 본 가격이에요. 현재가에 가까워 가장 즉시적인 참고치입니다.">🏢 상대가치 — 동종업계 배수로 본 가격</SectionTitle>
          <div className="overflow-hidden rounded-lg border" style={{ borderColor: C.bd }}>
            <table className="w-full border-collapse text-[13px]">
              <thead><tr style={{ background: "#f8fafc" }}>
                <th className="px-3 py-2 text-left text-[11.5px] font-bold text-slate-500">잣대</th>
                <th className="px-3 py-2 text-right text-[11.5px] font-bold text-slate-500">동종 평균</th>
                <th className="px-3 py-2 text-right text-[11.5px] font-bold text-slate-500">이 지표로 본 가격</th>
                <th className="px-3 py-2 text-right text-[11.5px] font-bold text-slate-500">현재가 대비</th>
              </tr></thead>
              <tbody>
                {rows.map((m, i) => {
                  const nm = String(m["멀티플"] ?? "");
                  const peer = String(m["피어 중위"] ?? "—");
                  const imp = numv(m["역산가"]);
                  const valid = imp != null && imp > 0;
                  const vs = numv(m["vs 현재"] ?? m["vs현재"]);
                  const earn = ["PER", "EV/EBITDA"].includes(nm);
                  const col = vs == null ? C.gray : vs > 8 ? C.green : vs < -8 ? C.red : "#b45309";
                  const vsTxt = vs == null ? "—" : Math.abs(vs) > 500 ? (vs > 0 ? "+500%↑" : "−99%") : `${vs > 0 ? "+" : ""}${vs.toFixed(0)}%`;
                  return (
                    <tr key={i} style={{ borderTop: `1px solid ${C.bd}` }}>
                      <td className="px-3 py-2 font-semibold text-slate-700">{nm} {earn ? <span className="text-[10px] font-bold text-blue-600">·이익</span> : <span className="text-[10px] text-slate-400">·참고</span>}</td>
                      <td className="px-3 py-2 text-right text-slate-500">{peer}</td>
                      <td className="px-3 py-2 text-right font-bold" style={{ color: valid ? C.navy : C.gray }}>{valid ? manWon(imp) : "산출 불가"}</td>
                      <td className="px-3 py-2 text-right font-bold" style={{ color: col }}>{valid ? vsTxt : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2.5 text-[12px] leading-6 text-slate-500">💡 <b>이익 기준</b>(PER·EV/EBITDA)이 가장 신뢰도 높고, 자산·매출 기준은 참고예요. <b>여러 잣대가 비슷한 가격</b>을 가리킬수록 믿을 만합니다. <b>+%</b>는 현재가가 그 기준보다 싸다(상승 여지), <b>−%</b>는 비싸다는 신호예요.</p>
        </div>
      )}

      {/* 2. 내재가치 = 기대를 읽는 도구 (괴리 큰 가격 숫자 없이) */}
      <div className="mb-5 rounded-xl border bg-white p-5" style={{ borderColor: C.bd }}>
        <SectionTitle sub="DCF는 '적정가격'을 못 박는 도구가 아니라, 지금 주가에 '시장의 기대'가 얼마나 들어있는지 읽는 도구로 씁니다.">📈 내재가치(DCF) — 가격이 아니라 &lsquo;기대&rsquo;를 읽기</SectionTitle>
        <div className="rounded-lg border px-4 py-3 text-[13px] leading-7" style={{ background: "#fffbeb", borderColor: "#fde68a", color: "#78350f" }}>
          <b>왜 DCF &lsquo;적정주가&rsquo;를 크게 보여주지 않나요?</b><br />
          DCF는 미래에 벌 현금을 추정해 오늘 가치로 환산해요. 그런데 <b>&lsquo;매년 몇 % 성장할까&rsquo;, &lsquo;할인율은 얼마일까&rsquo;</b> 같은 가정을 조금만 바꿔도 결과가 <b>크게 출렁입니다.</b> 그래서 하나의 적정가격으로 못 박으면 오해를 줘요. 대신 우리는 DCF를 <b>거꾸로</b> 써서 더 단단한 질문에 답해요 — <b>&ldquo;지금 주가가 맞으려면, 시장은 어떤 기대를 하고 있어야 하나?&rdquo;</b>
        </div>

        {ig == null && gp == null && eg == null && (
          <div className="mt-4 rounded-lg border px-4 py-3 text-[12.5px] leading-6 text-slate-500" style={{ borderColor: C.bd, background: "#f8fafc" }}>ℹ️ 이 종목은 <b>미래 이익 추정이 불안정</b>해(적자·변동성 큼 등) 기대 지표(필요성장률 등)를 산출하지 못했어요. 위 <b>멀티플 비교</b>를 중심으로 참고하세요.</div>
        )}

        {/* 필요성장률 hero */}
        {ig != null && (
          <div className="mt-4 rounded-xl border px-4 pb-4 pt-3.5" style={{ background: "linear-gradient(135deg,#fffbeb,#fef3c7)", borderColor: "#fde68a" }}>
            <div className="text-[12px] font-extrabold tracking-wide" style={{ color: "#92400e" }}>📊 필요 성장률 (Reverse DCF) — 가장 단단한 신호</div>
            <p className="mt-1.5 text-[13px] leading-7" style={{ color: "#451a03" }}>{ig < 0 ? <>지금 주가에는 <b>{name}</b>의 <b>성장 기대가 거의 없어요</b> — 오히려 시장은 앞으로 이익이 줄어들 것으로 보고 있어요. <b>이 신호는 &lsquo;적정주가 추정&rsquo;에 기대지 않아</b> 가정에 덜 흔들려, 거품·저평가를 가늠하는 데 가장 단단합니다.</> : <>지금 주가가 정당하려면 <b>{name}</b>는 <b>매년 영원히 {spct(ig)}</b> 성장해야 해요. 우리나라 경제성장률 <b>{pct(gdp, 0)}</b>과 비교해 현실적인지 보세요. <b>이 신호는 &lsquo;적정주가 추정&rsquo;에 기대지 않아</b> 가정에 덜 흔들리고, 그래서 거품·저평가를 가늠하는 데 가장 단단합니다.</>}</p>
            <GrowthGauge ig={ig} gdp={gdp} verdict={dg.implied_growth_verdict} />
          </div>
        )}

        {/* 성장기대분 + 기대vs실력 (비율 — 괴리 없음) */}
        {(gp != null || eg != null) && (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {gp != null && (
              <div className="rounded-xl border p-4" style={{ borderColor: C.bd }}>
                <div className="text-[12.5px] font-bold text-slate-600">현재 주가에 담긴 &lsquo;성장 기대&rsquo;</div>
                <div className="my-1 text-[22px] font-extrabold" style={{ color: gp >= 0.5 ? C.red : gp < 0 ? C.green : "#b45309" }}>{gp < 0 ? "기대 없음 (저평가 신호)" : gp >= 0.9 ? "대부분이 성장 기대" : `약 ${Math.round(gp * 100)}%`}</div>
                <p className="text-[12px] leading-6 text-slate-500">{gp < 0 ? <>지금 주가는 회사가 <b>더 안 커도 될 만큼 낮게</b> 매겨져 있어요 — 저평가 신호일 수 있어요.</> : gp >= 0.9 ? <>현재 주가의 <b>대부분이 미래 성장 기대</b>로 채워져 있어요. 기대가 매우 큰 만큼, 실적이 못 따라오면 크게 출렁일 수 있어요.</> : <>현재 주가의 약 {Math.round(gp * 100)}%가 <b>&lsquo;앞으로 더 클 것&rsquo;이라는 기대</b>예요. 높을수록 기대가 크고, 실망하면 출렁일 수 있어요.</>}</p>
              </div>
            )}
            {eg != null && (
              <div className="rounded-xl border p-4" style={{ borderColor: C.bd }}>
                <div className="text-[12.5px] font-bold text-slate-600">시장 기대 vs 회사 실력</div>
                <div className="my-1 text-[22px] font-extrabold" style={{ color: eg > 0.02 ? C.red : eg < -0.02 ? C.green : "#b45309" }}>{eg > 0.02 ? "기대가 앞섬" : eg < -0.02 ? "실력에 여유" : "균형"}</div>
                <p className="text-[12px] leading-6 text-slate-500">시장이 요구하는 성장 속도가, 회사가 스스로 벌어 성장할 수 있는 실력(SGR)보다 {eg > 0.02 ? <><b>앞서</b> 있어요 — 기대가 과열일 수 있어요.</> : eg < -0.02 ? <><b>여유</b>가 있어요 — 기대가 보수적이에요.</> : <><b>비슷</b>해요 — 균형 잡힌 편이에요.</>}</p>
              </div>
            )}
          </div>
        )}

        {/* EPV 개념 (괴리 큰 숫자 없이 설명만) */}
        <div className="mt-3 rounded-lg border px-4 py-3 text-[12.5px] leading-7 text-slate-600" style={{ borderColor: C.bd, background: "#f8fafc" }}>
          ⓘ <b>&lsquo;성장 0&rsquo; 보수적 시각(EPV)</b>: 회사가 더 안 크고 지금 버는 만큼만 영원히 번다고 보면, 이론적 가치는 현재가보다 낮게 나오는 경우가 많아요. 이건 <b>회사가 나빠서가 아니라</b>, 현재 주가에 <b>&lsquo;성장 기대&rsquo;가 많이 반영</b>돼 있다는 뜻이에요. (그래서 현재가와 괴리 큰 가격 숫자는 일부러 앞세우지 않습니다.)
        </div>
      </div>

      {/* 3. WACC 개념 + 자본구조(이자발생부채·자기자본 크기) */}
      {s.wacc != null && (() => {
        const kd = numv(s.kd_aftertax);
        // 자기자본(E·시가총액)·이자발생부채(D)는 peer_capital_detail의 TARGET 행 = WACC에 실제 투입된 값
        const pcd = (d.peer_capital_detail as any[]) || [];
        const tgt = pcd.find((r: any) => String(r?.tag ?? "").includes("TARGET")) || pcd.find((r: any) => { const c = String(r?.["회사"] ?? ""); return !!c && (c === name || name.includes(c) || c.includes(name)); });
        const eqMkt = tgt ? numv(tgt["E (시총)"]) : null;
        const dPcd = tgt ? numv(tgt["D (IBD)"]) : null;
        const floatSh = tgt ? numv(tgt["유통주식"]) : null;
        const closePx = tgt ? numv(tgt["종가"]) : null;
        // 이자발생부채 상세(차입금·사채·리스) — ibd_breakdown (백만원 단위)
        const ibdRows = (d.ibd_breakdown as any[]) || [];
        const myIbd = ibdRows.find((r: any) => { const c = String(r?.["회사"] ?? ""); return !!c && (c === name || name.includes(c) || c.includes(name)); });
        const ibdSumWon = myIbd ? ((numv(myIbd["합계"]) ?? 0) * 1e6) : null;
        const sumKeys = (ks: string[]) => myIbd ? ks.reduce((acc, k) => acc + (numv(myIbd[k]) ?? 0), 0) * 1e6 : 0;
        const borrow = sumKeys(["단기차입금", "유동성장기차입금", "장기차입금"]);
        const bond = sumKeys(["유동성사채", "비유동사채", "사채"]);
        const lease = sumKeys(["유동리스부채", "비유동리스부채", "리스부채"]);
        const debtWon = ibdSumWon != null ? ibdSumWon : dPcd;
        const spotDE = (eqMkt != null && eqMkt > 0 && debtWon != null) ? (debtWon / eqMkt * 100) : null;
        const wb = d.wacc_breakdown || [];
        const wRow = (kw: string) => wb.find((r) => String(r?.[0] ?? "").replace(/\s/g, "").includes(kw));
        const eWeight = wRow("E비중")?.[1] ?? null;
        const dWeight = wRow("D비중")?.[1] ?? null;
        const showWhy = s.ke != null && s.wacc != null && s.ke > s.wacc && !!dWeight;
        const bigGap = s.ke != null && s.wacc != null && (s.ke - s.wacc) >= 0.01;
        const hasCap = eqMkt != null || debtWon != null;
        return (
          <div className="mb-5 rounded-xl border bg-white p-5" style={{ borderColor: C.bd }}>
            <SectionTitle sub="미래의 1만원은 지금 1만원보다 가치가 작아요(기다림+불확실). 그 깎는 비율이 WACC(할인율)입니다.">⚙️ 할인율(WACC) — 미래의 돈을 깎는 비율</SectionTitle>
            <div className="flex flex-wrap items-end gap-x-7 gap-y-2">
              <div><div className="text-[11.5px] text-slate-500">할인율 (WACC)</div><div className="text-[26px] font-extrabold" style={{ color: C.navy }}>{pct(s.wacc, 1)}</div></div>
              {s.rf != null && <div><div className="text-[11.5px] text-slate-500">기본 금리 (국채 Rf)</div><div className="text-[18px] font-bold text-slate-600">{pct(s.rf, 1)}</div></div>}
              {s.ke != null && <div><div className="text-[11.5px] text-slate-500">자기자본 비용 (Ke)</div><div className="text-[18px] font-bold text-slate-600">{pct(s.ke, 1)}</div></div>}
              {kd != null && <div><div className="text-[11.5px] text-slate-500">세후 빚이자 (Kd)</div><div className="text-[18px] font-bold text-slate-600">{pct(kd, 1)}</div></div>}
            </div>

            {hasCap && (
              <div className="mt-4 rounded-xl border p-4" style={{ borderColor: "#dbeafe", background: "#f8fbff" }}>
                <div className="text-[13.5px] font-extrabold" style={{ color: C.navy }}>🏗️ 자본 구조 — WACC를 섞는 비율의 근거</div>
                <p className="mt-1 text-[12px] leading-6 text-slate-500">WACC는 <b>자기자본의 비용(Ke)</b>과 <b>빚의 비용(Kd)</b>을, 회사가 실제로 쓰는 <b>자기자본·빚의 크기 비율</b>대로 섞은 값이에요.</p>
                <div className="mt-3 space-y-2 text-[13px]">
                  {eqMkt != null && eqMkt > 0 && (
                    <div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-semibold text-slate-700">자기자본 <span className="text-[11px] font-normal text-slate-400">(E · 시가총액)</span></span>
                        <span className="whitespace-nowrap font-extrabold" style={{ color: C.navy }}>{bigWon(eqMkt)}</span>
                      </div>
                      {floatSh != null && closePx != null && <div className="mt-0.5 text-right text-[11px] text-slate-400">유통주식 {Math.round(floatSh / 1e6).toLocaleString()}백만주 × {Math.round(closePx).toLocaleString()}원</div>}
                    </div>
                  )}
                  {debtWon != null && (
                    <div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-semibold text-slate-700">이자발생부채 <span className="text-[11px] font-normal text-slate-400">(D · 이자 내는 빚)</span></span>
                        <span className="whitespace-nowrap font-extrabold" style={{ color: C.navy }}>{bigWon(debtWon)}</span>
                      </div>
                      {(borrow > 0 || bond > 0 || lease > 0) && (
                        <div className="mt-0.5 text-right text-[11px] text-slate-400">{[borrow > 0 ? `차입금 ${bigWon(borrow)}` : null, bond > 0 ? `사채 ${bigWon(bond)}` : null, lease > 0 ? `리스 ${bigWon(lease)}` : null].filter(Boolean).join(" · ")}</div>
                      )}
                    </div>
                  )}
                  {(eWeight || dWeight) && (
                    <div className="flex items-center justify-between gap-3 border-t pt-2" style={{ borderColor: "#dbeafe" }}>
                      <span className="font-semibold text-slate-700">WACC 적용 비중 <span className="text-[11px] font-normal text-slate-400">(목표 자본구조)</span></span>
                      <span className="whitespace-nowrap font-extrabold" style={{ color: C.navy }}>{eWeight && <>자기자본 {eWeight}</>}{eWeight && dWeight ? " · " : ""}{dWeight && <>부채 {dWeight}</>}</span>
                    </div>
                  )}
                </div>
                {showWhy && (
                  <p className="mt-3 rounded-lg px-3 py-2 text-[12px] leading-6" style={{ background: "#eff6ff", color: "#1e3a5f" }}>💡 WACC <b>{pct(s.wacc, 1)}</b>가 자기자본 비용 <b>{pct(s.ke, 1)}</b>보다 {bigGap ? "꽤" : "조금"} 낮은 건, <b>빚의 이자(세후 Kd {kd != null ? pct(kd, 1) : "—"})</b>가 자기자본보다 싸서 <b>부채 비중 {dWeight}</b>만큼 섞였기 때문이에요.</p>
                )}
                <p className="mt-1.5 text-[11px] leading-5 text-slate-400">※ <b>적용 비중</b>은 일시적 변동에 흔들리지 않도록 비슷한 회사들과 함께 <b>장기 목표 자본구조</b>로 정규화한 값이에요{spotDE != null ? <> — 이 회사의 현재 빚 비율(D/E)은 <b>약 {spotDE < 10 ? spotDE.toFixed(1) : Math.round(spotDE).toLocaleString()}%</b>입니다.</> : <>.</>}</p>
              </div>
            )}

            <p className="mt-3 text-[12.5px] leading-7 text-slate-500">
              <b>구성</b>: ① <b>국채금리(Rf)</b> — 가장 안전한 기본 수익률 · ② <b>주식 위험 보상</b> — 이 회사 주가가 시장보다 얼마나 출렁이는지에 따라 더 얹어요 · ③ <b>빚 이자(Kd)</b> — 빌린 돈의 비용(세후). 보통 <b>8~13%</b>이고, <b>높을수록</b> 미래 이익을 더 깐깐하게(작게) 봐서 내재가치가 낮아집니다.
            </p>
          </div>
        );
      })()}

      {/* 4. 신뢰도 + 한계 + 용어 + 출처 */}
      <div className="mb-2 rounded-xl border bg-white p-5" style={{ borderColor: C.bd }}>
        <SectionTitle>🎓 이 분석, 얼마나 믿을 수 있나요?</SectionTitle>
        {(s.dcf_grade || pcGrade) && (
          <div className="mb-3 flex flex-wrap gap-2 text-[12.5px]">
            {s.dcf_grade && <span className="rounded-lg border px-3 py-1.5" style={{ borderColor: C.bd }}>DCF 신뢰도 <b style={{ color: C.navy }}>{s.dcf_grade}등급</b></span>}
            {pcGrade && <span className="rounded-lg border px-3 py-1.5" style={{ borderColor: C.bd }}>피어 신뢰도 <b style={{ color: C.navy }}>{pcGrade}등급</b></span>}
            <span className="text-[11.5px] leading-7 text-slate-400">등급이 높을수록(A쪽) 데이터·비교가 탄탄해 결과를 더 믿을 만해요.</span>
          </div>
        )}
        <div className="rounded-lg border px-4 py-3 text-[12.5px] leading-7" style={{ background: "#fffbeb", borderColor: "#fde68a", color: "#78350f" }}>
          <b>⚠️ 한계 (정직하게)</b>
          <ul className="mt-1 list-disc pl-5">
            <li>미래에 벌 돈은 <b>예측</b>이라 실제와 다를 수 있어요 (특히 경기 타는 회사·고성장주).</li>
            <li>경영진 역량·산업 변화처럼 <b>숫자로 안 잡히는 요인</b>은 반영이 어려워요.</li>
            <li>결과는 공시 데이터의 <b>품질·시점</b>에 의존해요. <b>참고용</b>이며 매수·매도 권유가 아닙니다.</li>
          </ul>
        </div>
        <details className="mt-3 rounded-lg border px-4" style={{ borderColor: C.bd }}>
          <summary className="cursor-pointer py-2.5 text-[13px] font-bold" style={{ color: C.navy }}>📚 용어 쉬운 풀이 (펼치기)</summary>
          <dl className="grid grid-cols-1 gap-y-2 pb-3 text-[12.5px] md:grid-cols-[170px_1fr] md:gap-x-3">
            {([
              ["멀티플", "비슷한 회사가 받는 가격 배수(PER 등)로 본 가격 — 교차 검증용."],
              ["내재가치 (DCF)", "미래에 벌 현금을 오늘 가치로 환산한 이론적 가치. 가정에 민감해요."],
              ["필요 성장률", "지금 주가가 맞으려면 매년 몇 %씩 영원히 커져야 하는지(거꾸로 계산)."],
              ["성장 기대분", "현재 주가 중 ‘앞으로 더 클 것’ 기대가 차지하는 비율."],
              ["WACC (할인율)", "미래의 돈을 오늘 가치로 깎는 비율 = 회사의 자본 비용."],
              ["SGR (지속가능성장률)", "회사가 외부 도움 없이 스스로 벌어 성장할 수 있는 속도."],
            ] as [string, string][]).map(([t, v]) => (
              <React.Fragment key={t}><dt className="font-bold" style={{ color: C.blue }}>{t}</dt><dd className="m-0 leading-6 text-slate-600">{v}</dd></React.Fragment>
            ))}
          </dl>
        </details>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11.5px] text-slate-500">
          <span className="font-semibold">📌 데이터 출처:</span>
          <span className="rounded border px-2 py-0.5" style={{ borderColor: C.bd }}>DART 전자공시</span>
          <span className="rounded border px-2 py-0.5" style={{ borderColor: C.bd }}>KRX 한국거래소</span>
          <span className="rounded border px-2 py-0.5" style={{ borderColor: C.bd }}>한국은행 ECOS</span>
          <span className="rounded border px-2 py-0.5" style={{ borderColor: C.bd }}>금융투자협회</span>
        </div>
      </div>
    </div>
  );
}
