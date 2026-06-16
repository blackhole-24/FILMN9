import * as React from "react";
import { C } from "@/lib/valuation";

const SOURCES: [string, string, string][] = [
  ["🏛️", "DART", "금융감독원 전자공시 · 재무제표·사업보고서"],
  ["📈", "KRX", "한국거래소 · 주가·시가총액·상장정보"],
  ["🏦", "ECOS", "한국은행 경제통계 · 무위험수익률(국고채)"],
  ["📊", "KOFIA", "금융투자협회 · 채권시가평가수익률"],
];

const THEORY: [string, string, string][] = [
  ["DCF (현금흐름할인)", "재무학 표준", "기업가치 = 미래 잉여현금흐름(FCFF)의 현재가치 합"],
  ["CAPM", "Sharpe (1964)", "Ke = 무위험수익률 + β × 시장위험프리미엄"],
  ["베타 조정 (Hamada)", "Hamada (1972)", "자본구조 차이를 반영해 피어 베타 보정"],
  ["베타 안정화 (Blume)", "Blume (1971)", "조정베타 = ⅔×실측 + ⅓×1, 이상치 제거(±3σ)"],
  ["영구가치 (Gordon)", "Gordon (1959)", "예측기간 이후 가치 = NOPAT/(WACC−g), g ≤ 명목 GDP"],
  ["지속가능성장률 (SGR)", "Damodaran", "성장 상한 = ROIC × 재투자율"],
  ["EPV (이익창출가치)", "Greenwald (2001)", "성장 0 가정 본질가치 = NOPAT / WACC"],
  ["Reverse DCF", "Damodaran", "현재 주가를 정당화하는 영구성장률 역산"],
  ["기대 투자", "Rappaport & Mauboussin (2001)", "시장 함의 성장 vs 회사 펀더멘털 격차"],
  ["안전마진", "Graham", "본질가치 대비 현재가 할인폭 = 하방 방어막"],
];

const ASSUMPTIONS: React.ReactNode[] = [
  <>시장위험프리미엄(ERP) 8% — 한국 시장 장기 추정치로 고정</>,
  <>영구성장률 g = 2.5% (≤ 명목 GDP) — 어떤 회사도 영원히 경제보다 빨리 클 수 없음(Damodaran)</>,
  <>명시적 예측 5년 + 영구가치 — 성장률을 점진 수렴(fade) 후 영구가치 결합</>,
  <>지속가능성장률로 성장 상한 — 일시적 호황을 영구 외삽하지 않도록 제어</>,
  <>WACC 자본구조 — 실제 D/E로 계산하되 일시적 과부채는 산업 평균 상한 보정</>,
  <>한계세율 적용 — 과세구간별 실효세율로 세후이익 산출</>,
  <>TTM 하이브리드 — 손익은 최근 4분기로 최신화, 자본·부채는 연간 기준</>,
  <>비영업자산(NOA) 장부가 — 공정가 부재로 보수적 장부가 사용</>,
];

function Detail({ summary, children, open = false }: { summary: string; children: React.ReactNode; open?: boolean }) {
  return (
    <details open={open} className="mt-2.5 rounded-[10px] border bg-white px-4" style={{ borderColor: C.bd }}>
      <summary className="cursor-pointer py-3 text-sm font-bold" style={{ color: C.navy }}>{summary}</summary>
      <div className="pb-3.5">{children}</div>
    </details>
  );
}

const cell = "border-b px-2.5 py-2 text-left align-top text-[12.5px]";

/** 신뢰성 근거 — 이론·출처·가정·한계(원본 .method 재현, 상시 노출 정적). */
export function MethodSection() {
  return (
    <section className="mt-[34px] border-t-[3px] pt-5" style={{ borderColor: C.navy }}>
      <h2 className="mb-1 text-lg font-bold" style={{ color: C.navy }}>🔬 이 분석은 어떤 근거로 만들어졌나요?</h2>
      <div className="mb-4 text-[13px] leading-relaxed text-slate-500">
        모든 수치는 <b>공식·공개 데이터</b>와 <b>재무학 표준 이론</b>에 기반합니다. 임의의 값 없이 출처·이론·가정·한계를 투명하게 공개합니다.
      </div>

      <div className="mb-3.5 grid grid-cols-2 gap-3 md:grid-cols-4">
        {SOURCES.map(([ic, nm, dt]) => (
          <div key={nm} className="rounded-[10px] border bg-white p-3.5 text-center" style={{ borderColor: C.bd }}>
            <div className="text-2xl">{ic}</div>
            <div className="mt-1.5 text-[13px] font-bold" style={{ color: C.navy }}>{nm}</div>
            <div className="mt-1 text-[11px] leading-snug text-slate-500">{dt}</div>
          </div>
        ))}
      </div>

      <Detail summary="📐 이론적 토대 (재무학 표준 모델)" open>
        <table className="w-full border-collapse">
          <thead><tr><th className={cell + " text-slate-500"}>이론 / 모델</th><th className={cell + " text-slate-500"}>출처</th><th className={cell + " text-slate-500"}>역할</th></tr></thead>
          <tbody>
            {THEORY.map((r) => (
              <tr key={r[0]}>
                <td className={cell + " font-bold whitespace-nowrap"} style={{ color: C.blue }}>{r[0]}</td>
                <td className={cell + " whitespace-nowrap text-slate-500"}>{r[1]}</td>
                <td className={cell}>{r[2]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Detail>

      <Detail summary="⚙️ 핵심 가정 (투명 공개)">
        <ul className="list-disc pl-5 text-[13px] leading-8 text-slate-700">
          {ASSUMPTIONS.map((a, i) => <li key={i}>{a}</li>)}
        </ul>
      </Detail>

      <Detail summary="🧭 평가 방법론 흐름">
        <div className="flex flex-wrap items-center gap-1.5 py-2">
          {["① 공시·시장 데이터 수집", "② 유사기업 자동 선정", "③ 베타·WACC 산출", "④ DCF 내재가치 추정", "⑤ 멀티플 교차검증", "⑥ 현재가 적절성 진단 5종"].map((step, i, arr) => (
            <React.Fragment key={step}>
              <span className="rounded-lg border px-2.5 py-2 text-xs font-semibold" style={{ background: "#eff6ff", borderColor: "#bfdbfe", color: "#1e40af" }}>{step}</span>
              {i < arr.length - 1 && <span className="font-bold text-slate-400">→</span>}
            </React.Fragment>
          ))}
        </div>
        <div className="text-[11px] text-slate-500">미래 예측(DCF)과 예측이 거의 없는 현재가치(EPV·역산 진단)를 <b>함께</b> 제시해 한쪽에 치우치지 않도록 설계했습니다.</div>
      </Detail>

      <Detail summary="⚠️ 한계 (정직한 고지)">
        <ul className="list-disc pl-5 text-[13px] leading-8 text-slate-700">
          <li>미래 현금흐름은 <b>예측</b>이라 실제와 다를 수 있습니다(특히 경기민감·고성장주).</li>
          <li>경영진 역량·산업 구조 변화 등 <b>정성 요인</b>은 수치에 직접 반영되지 않습니다.</li>
          <li>결과는 공시 데이터의 <b>품질·시점</b>에 의존합니다.</li>
          <li>본 결과는 <b>참고 자료</b>이며 특정 종목의 매수·매도 권유가 아닙니다.</li>
        </ul>
      </Detail>
    </section>
  );
}
