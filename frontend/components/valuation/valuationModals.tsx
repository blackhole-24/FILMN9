import * as React from "react";
import { ValuationData, C, won, pct, spct } from "@/lib/valuation";

export type InfoKey =
  | "range" | "leverage" | "grade" | "peer" | "industry" | "damodaran" | "opm";

function HL({ children }: { children: React.ReactNode }) {
  return <span className="rounded px-1.5 font-bold" style={{ background: "#fef9c3", color: "#854d0e" }}>{children}</span>;
}
function Note({ children }: { children: React.ReactNode }) {
  return <div className="mt-3.5 rounded-lg border px-3.5 py-2.5 text-[12.5px] leading-relaxed" style={{ background: "#f0f9ff", borderColor: "#bae6fd", color: "#0c4a6e" }}>{children}</div>;
}
function Warn({ children }: { children: React.ReactNode }) {
  return <div className="mt-3 rounded-lg border px-3.5 py-2.5 text-[12.5px] leading-relaxed" style={{ background: "#fffbeb", borderColor: "#fde68a", color: "#78350f" }}>{children}</div>;
}
function H4({ children }: { children: React.ReactNode }) {
  return <h4 className="mb-1.5 mt-4 text-[13.5px] font-bold" style={{ color: "#0369a1" }}>{children}</h4>;
}
function MTable({ children }: { children: React.ReactNode }) {
  return <table className="my-2.5 w-full border-collapse text-[13px]">{children}</table>;
}
const td = "border-b px-2.5 py-2 text-left align-top";

const GRADE_ROWS: [string, string, string, string][] = [
  ["A", "#16a34a", "정상화·Terminal 안정", "내재가치 추정값 + 범위 모두 표시"],
  ["B", "#2d6cb5", "대체로 양호", "내재가치 추정값 + 범위 표시"],
  ["C", "#d97706", "이격·Terminal 의존 큼", "내재가치 추정값 + 범위 (주의)"],
  ["D", "#ea580c", "점추정 신뢰 곤란", "점추정 숨김 · 범위만"],
  ["E", "#dc2626", "구조적 적자·EV음수", "DCF 비표시(조건부)"],
];

/** 모달 키 → {title, body}. 원본 static/index.html 의 show*Modal 들을 재현. */
export function getModal(key: InfoKey, d: ValuationData): { title: string; body: React.ReactNode } {
  const s = d.summary || {};

  switch (key) {
    case "range": {
      const lo = s.fair_price_low, hi = s.fair_price_high, fair = s.fair_price, cur = s.current_price;
      const wrange = s.WACC_low != null && s.WACC_high != null ? `${pct(s.WACC_low, 1)}~${pct(s.WACC_high, 1)}` : "베타 변동 + ERP 7~9%";
      let posTxt: React.ReactNode = null;
      if (cur != null && lo != null && hi != null) {
        if (cur < lo) posTxt = <>현재 주가(₩{won(cur)})는 내재가치 추정값 범위의 <HL>아래</HL>에 있어요 — 저평가(싼) 신호.</>;
        else if (cur > hi) posTxt = <>현재 주가(₩{won(cur)})는 내재가치 추정값 범위의 <HL>위</HL>에 있어요 — 고평가(비싼) 신호.</>;
        else posTxt = <>현재 주가(₩{won(cur)})는 내재가치 추정값 범위 <HL>안</HL>에 있어요 — 대체로 합리적인 수준.</>;
      }
      return {
        title: "내재가치 추정는 왜 하나가 아니라 '범위'일까요?",
        body: (
          <>
            <p>내재가치 추정는 <b>딱 떨어지는 하나의 숫자가 아니라</b>, 어떤 가정을 쓰느냐에 따라 달라지는 추정치예요. 그래서 정직하게 <b>범위</b>로 보여드립니다.</p>
            <H4>가장 큰 변수 — 할인율(WACC)</H4>
            <ul className="my-2 list-disc pl-5">
              <li><b>WACC가 낮으면</b> → 미래 이익을 덜 깎음 → 내재가치 추정값 <b>높아짐</b> (낙관 ₩{won(hi)})</li>
              <li><b>WACC가 높으면</b> → 미래 이익을 더 깎음 → 내재가치 추정값 <b>낮아짐</b> (보수 ₩{won(lo)})</li>
            </ul>
            <p>WACC 합리적 구간({wrange})을 적용해 범위 <HL>₩{won(lo)} ~ ₩{won(hi)}</HL>, 가운데 기준값 <b>₩{won(fair)}</b>(WACC {pct(s.wacc, 1)}).</p>
            {posTxt && <><H4>그래서 지금은?</H4><p>{posTxt}</p></>}
            <Note>📚 Fernandez(IESE, 2019): &ldquo;WACC 불확실성을 하나의 숫자로 숨기면 오해를 부른다&rdquo; — 베타 표준편차와 ERP 범위를 결합(RSS)해 구간 산출.</Note>
            <Warn>⚠ 범위 안이라고 &lsquo;정답&rsquo;은 아닙니다. 미래 예측이 포함된 <b>참고용</b>이며 여러 신호를 함께 보세요.</Warn>
          </>
        ),
      };
    }

    case "leverage": {
      const f1 = (x?: number | null) => (x == null ? "—" : x.toFixed(0) + "%");
      return {
        title: "이 종목은 '고부채 보정'이 적용됐어요",
        body: (
          <>
            <p>실제 부채비율(D/E)이 동종업계 기준보다 훨씬 높아, 할인율(WACC) 계산에 <b>보정</b>을 적용했습니다.</p>
            <H4>왜 보정하나요? — distress 역설</H4>
            <p>부채가 아주 많은 회사는 계산식상 WACC가 <b>오히려 낮아져</b> 기업가치가 부풀려지는 모순이 생겨요. 이를 막으려 부채비율을 <b>업계 상한까지만</b> 인정합니다.</p>
            <MTable>
              <tbody>
                <tr><td className={td}>이 회사 <b>실제</b></td><td className={`${td} text-right font-bold`} style={{ color: C.red }}>{f1(s.DE_own_pct)}</td></tr>
                <tr><td className={td}>계산에 <b>적용</b>(상한)</td><td className={`${td} text-right font-bold`}>{f1(s.DE_cap_pct)}</td></tr>
                <tr><td className={td}>동종업계 중위값</td><td className={`${td} text-right text-slate-500`}>{f1(s.DE_peer_median_pct)}</td></tr>
              </tbody>
            </MTable>
            <p>이 내재가치 추정는 <b>&ldquo;재무구조가 정상 수준으로 회복된다&rdquo;는 가정</b> 하의 값이에요. <HL>실제 과도한 부채 위험(이자 부담·부도 가능성)은 별도 확인</HL>하세요.</p>
            {s.leverage_disclosure ? <Warn>{s.leverage_disclosure}</Warn> : null}
          </>
        ),
      };
    }

    case "grade": {
      const g = s.dcf_grade || "B";
      const tvw = s.dcf_tv_weight;
      return {
        title: "이 종목의 DCF 신뢰도 등급은요…",
        body: (
          <>
            <p>현재 등급: <b style={{ color: (GRADE_ROWS.find((r) => r[0] === g) || GRADE_ROWS[1])[1] }}>{g}</b> · 판정 근거: <b>{s.dcf_grade_reason || "—"}</b></p>
            {s.dcf_fcff_y1_negative && <Note>💡 <b>투자기 성장주</b> — 증설·운전자본 확대로 1년차 FCFF는 음수지만 EV는 양수라 평가에 포함. 가치가 먼 미래에 집중돼 등급이 낮을 수 있어요.</Note>}
            <H4>5단계 등급의 의미</H4>
            <MTable>
              <thead><tr><th className={td}>등급</th><th className={td}>의미</th><th className={td}>표시 정책</th></tr></thead>
              <tbody>
                {GRADE_ROWS.map((r) => (
                  <tr key={r[0]}><td className={td}><b style={{ color: r[1] }}>{r[0]}</b></td><td className={td}>{r[2]}</td><td className={td}>{r[3]}</td></tr>
                ))}
              </tbody>
            </MTable>
            <p>모델 내부 지표(Terminal Value 비중 <b>{tvw != null ? (tvw * 100).toFixed(0) + "%" : "—"}</b>, OPM 이격, 흑자 여부 등)로 자동 산정.</p>
            <Note>📚 점추정 단일 숫자에 과도하게 앵커링되지 않도록 &lsquo;D&rsquo;부터 점추정을 숨깁니다 (Tversky &amp; Kahneman 1974).</Note>
          </>
        ),
      };
    }

    case "peer": {
      const c = d.peer_confidence || {};
      const g = s.peer_confidence_grade || c.grade || "B";
      const score = s.peer_confidence_score ?? c.score ?? 75;
      const ded = c.deductions || [];
      return {
        title: "피어셋 신뢰도 — 왜 이 등급인가요?",
        body: (
          <>
            <p className="text-[13px] text-slate-500">&lsquo;피어셋&rsquo;은 이 회사와 사업·규모가 비슷해 비교 기준으로 고른 동종 회사들이에요.</p>
            <p>현재 등급: <b>{g}</b> · 점수: <b>{score}/100</b></p>
            <H4>감점 내역</H4>
            {ded.length ? (
              <MTable>
                <thead><tr><th className={td}>감점</th><th className={td}>사유</th></tr></thead>
                <tbody>{ded.map((x, i) => (<tr key={i}><td className={td}>{x.delta > 0 ? "+" : ""}{x.delta}점</td><td className={td}>{x.reason}</td></tr>))}</tbody>
              </MTable>
            ) : <p>감점 없음 — 만점에 가까운 피어셋입니다.</p>}
            <H4>등급별 의미</H4>
            <MTable>
              <tbody>
                <tr><td className={td}><b style={{ color: "#16a34a" }}>A</b> ≥90</td><td className={td}>매우 적합 — 동종업계 표준에 가까움</td></tr>
                <tr><td className={td}><b style={{ color: "#2d6cb5" }}>B</b> 75~89</td><td className={td}>양호 — 작은 차이</td></tr>
                <tr><td className={td}><b style={{ color: "#d97706" }}>C</b> 60~74</td><td className={td}>주의 — 일부 PARTIAL/소섹터 부족</td></tr>
                <tr><td className={td}><b style={{ color: "#ea580c" }}>D</b> 40~59</td><td className={td}>곤란 — 신뢰도 낮음</td></tr>
                <tr><td className={td}><b style={{ color: "#dc2626" }}>E</b> &lt;40</td><td className={td}>부적합 — 비교가능성 거의 없음</td></tr>
              </tbody>
            </MTable>
          </>
        ),
      };
    }

    case "industry": {
      const cat = s.industry_category || "unknown";
      const meta: Record<string, { t: string; d: string; c: string }> = {
        cyclical: { t: "경기민감(cyclical)", d: "반도체·화학·철강·조선·자동차 등. 호황/불황 OPM 변동 큼 → 8년 평균으로 평탄화.", c: "#92400e" },
        mature: { t: "성숙안정(mature)", d: "통신·유틸리티·은행·식음료 등 수요 비탄력. 변동 작음 → 3년 평균 충분.", c: "#166534" },
        growth: { t: "성장·기타(growth)", d: "IT 플랫폼·바이오·콘텐츠 등. 사업모델 진화 빨라 옛 데이터 오염 회피 위해 3년 우선.", c: "#1e3a8a" },
        unknown: { t: "미분류", d: "산업 정보 불충분 — 보수적으로 3년 적용.", c: "#475569" },
      };
      const m = meta[cat] || meta.unknown;
      return {
        title: "산업 분류 (3분류)",
        body: (
          <>
            <p>이 종목의 산업 분류: <b style={{ color: m.c }}>{m.t}</b></p>
            <p>업종: <b>{s.industry_name || "—"}</b></p>
            <H4>분류가 내재가치 추정에 미치는 영향</H4>
            <p>{m.d}</p>
            <MTable>
              <thead><tr><th className={td}>분류</th><th className={td}>OPM 윈도우</th><th className={td}>예시</th></tr></thead>
              <tbody>
                <tr><td className={td}><b style={{ color: "#92400e" }}>경기민감</b></td><td className={td}>8년</td><td className={td}>반도체·화학·조선</td></tr>
                <tr><td className={td}><b style={{ color: "#166534" }}>성숙안정</b></td><td className={td}>3년</td><td className={td}>통신·은행·식음료</td></tr>
                <tr><td className={td}><b style={{ color: "#1e3a8a" }}>성장·기타</b></td><td className={td}>3년</td><td className={td}>IT·바이오</td></tr>
              </tbody>
            </MTable>
            <Note>한국표준산업분류 + 회사명 보정 휴리스틱. 100% 정확하진 않습니다.</Note>
          </>
        ),
      };
    }

    case "damodaran": {
      const dmd = s.damodaran_check || {};
      if (!dmd.available) {
        return { title: "βU 산출 (Damodaran 미가용)", body: <p>해당 산업의 Damodaran 평균 βU 데이터를 찾지 못해, <b>피어 회귀 βU</b>(이상치 제외 + 사업유사도 가중평균)만 사용했습니다.</p> };
      }
      const f3 = (x?: number) => (x == null ? "—" : Number(x).toFixed(3));
      return {
        title: "βU 산출 — 피어 + Damodaran 혼합",
        body: (
          <>
            <p>무차입 베타(βU = 순수 영업위험)를 <b>피어 회귀 + Damodaran 산업 평균</b>으로 혼합(Vasicek shrinkage)합니다.</p>
            <MTable>
              <thead><tr><th className={td}>구성</th><th className={td}>βU</th></tr></thead>
              <tbody>
                <tr><td className={td}>피어 집계</td><td className={td}>{f3(dmd.peer_median_bU)}</td></tr>
                <tr><td className={td}>Damodaran {dmd.damodaran_sector || "산업"}</td><td className={td}>{f3(dmd.damodaran_bU)}</td></tr>
                {dmd.blended_bU != null && <tr style={{ background: "#eef6ff" }}><td className={td}><b>혼합 최종</b>{dmd.weight_peer != null ? ` (피어 ${(dmd.weight_peer * 100).toFixed(0)}%)` : ""}</td><td className={td}><b>{f3(dmd.blended_bU)}</b></td></tr>}
                <tr><td className={td}>피어 − Damodaran</td><td className={td} style={{ color: dmd.warn_gt_0p3 ? C.red : C.green }}>{dmd.gap != null ? (dmd.gap >= 0 ? "+" : "") + Number(dmd.gap).toFixed(3) : "—"}</td></tr>
              </tbody>
            </MTable>
            {dmd.warn_gt_0p3 ? <Warn>⚠ 차이 0.3 초과 — Damodaran 가중을 자동으로 낮춰 피어 중심으로 혼합.</Warn> : <Note>차이 0.3 이내 — 피어와 산업 평균이 정합.</Note>}
          </>
        ),
      };
    }

    case "opm": {
      const w = s.opm_window_used || "3yr";
      const fmt = (x?: number | null) => (x == null ? "—" : (x * 100).toFixed(2) + "%");
      return {
        title: "OPM 정상화 윈도우 자동 선택",
        body: (
          <>
            <p>내재가치 추정 출발 영업이익률(OPM)을 어떤 기간 평균으로 잡았는지: <b>{w.startsWith("8yr") ? "8년 (사이클 평탄화)" : "3년"}</b></p>
            <MTable>
              <thead><tr><th className={td}>구분</th><th className={td}>OPM 평균</th></tr></thead>
              <tbody>
                <tr><td className={td}>최근 3년</td><td className={td}>{fmt(s.opm_3yr_avg)}</td></tr>
                <tr><td className={td}>최근 8년</td><td className={td}>{fmt(s.opm_8yr_avg)}</td></tr>
                <tr><td className={td}>패턴 분석</td><td className={td}><b>{s.opm_pattern || "—"}</b></td></tr>
              </tbody>
            </MTable>
            <Note>사이클성 종목은 호황·불황을 모두 포함한 평균이 정상치에 가깝습니다(한 사이클 ~3~10년). 단순 진화 종목은 최근 3년이 낫습니다.</Note>
          </>
        ),
      };
    }
  }
}
