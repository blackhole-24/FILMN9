"use client";

import * as React from "react";
import { ValuationData, won, pct, spct } from "@/lib/valuation";

/** 밸류에이션 탭 전용 튜토리얼 — 우측 슬라이드 패널.
 * 이 탭이 제공하는 모든 값의 [계산식 · 출처 · 해석 · 한글용어]를 한 곳에서.
 * 종목의 실제 값을 끼워 넣어 구체적으로 설명한다. (고정 아님 · 닫기 가능 · 스크롤)
 */
const NAVY = "#1f3a5f";
const BLUE = "#2563eb";

/** 한글 조사 자동 선택 — 받침 유무에 따라 (예: josa("삼성전기","이","가")="가"). */
function josa(word: string, withBatchim: string, withoutBatchim: string): string {
  if (!word) return withoutBatchim;
  const c = word.charCodeAt(word.length - 1);
  if (c >= 0xac00 && c <= 0xd7a3) return ((c - 0xac00) % 28 === 0) ? withoutBatchim : withBatchim;
  return withoutBatchim; // 비한글(영문·숫자)은 받침 없음으로 취급
}

function Sec({ icon, title, children }: { icon: string; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-white p-4" style={{ borderColor: "#e2e8f0" }}>
      <div className="mb-2 text-[16px] font-extrabold" style={{ color: NAVY }}>{icon} {title}</div>
      <div className="space-y-2 text-[14px] leading-7 text-slate-700">{children}</div>
    </div>
  );
}
/** 계산식 박스 */
function Calc({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg px-3 py-2 text-[14px] font-bold" style={{ background: "#eef4ff", color: "#1e40af" }}>
      🧮 {children}
    </div>
  );
}
/** 출처 라벨 */
function Src({ children }: { children: React.ReactNode }) {
  return <div className="text-[13px]" style={{ color: "#0f766e" }}>📍 <b>출처</b>: {children}</div>;
}
/** 해석 박스 */
function How({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border px-3 py-2 text-[13.5px] leading-6" style={{ borderColor: "#fde68a", background: "#fffbeb", color: "#78350f" }}>
      💡 <b>읽는 법</b>: {children}
    </div>
  );
}
/** 용어(영문) 한글 풀이 */
function Term({ en, ko, desc }: { en: string; ko: string; desc: string }) {
  return (
    <div className="text-[13.5px] leading-6">
      <b style={{ color: BLUE }}>{en}</b> = <b>{ko}</b> — {desc}
    </div>
  );
}

export function ValuationTutorial({ data, realtimePrice, open, onClose }: { data: ValuationData; realtimePrice?: number | null; open: boolean; onClose: () => void }) {
  const s = data.summary || {};
  const dg = (data.valuation_diagnostics || {}) as any;
  const name = data.company?.name || "이 회사";
  // 현재가는 화면 헤더와 동일한 realtime 으로 통일 (없으면 엔진 current_price)
  const cur = (realtimePrice != null && realtimePrice > 0) ? realtimePrice : s.current_price;
  const fair = s.fair_price;
  const epv = dg.epv_price;
  const ig = dg.implied_growth;                 // 시장 기대 영구성장률 (역산)
  const verdict = dg.implied_growth_verdict;    // "매우 낙관적" 등
  const gp = dg.growth_premium;                 // 성장 기대 프리미엄 (시총/EPV − 1, 배수)
  const gap = dg.expectations_gap;              // 시장기대 − 지속가능성장 (%p)
  const sgr = dg.inputs?.sgr;                   // 펀더멘털 지속가능 성장률 (ROIC×재투자율)
  const gdp = dg.gdp_growth_ref ?? 0.03;
  // 성장 프리미엄 표기: gp=18.5 → "약 1,853% (현재가 ≈ 바닥가치의 19.5배)"
  const gpPct = gp != null ? Math.round(gp * 100) : null;
  const gpX = gp != null ? (gp + 1) : null;

  if (!open) return null;

  return (
    <>
      {/* 반투명 배경(클릭 시 닫힘) */}
      <div className="fixed inset-0 z-[80] bg-black/30" onClick={onClose} />
      {/* 우측 슬라이드 패널 */}
      <aside className="fixed right-0 top-0 z-[90] flex h-full w-[460px] max-w-[94vw] flex-col bg-[#f8fafc] shadow-2xl">
        <div className="flex items-center justify-between border-b bg-white px-5 py-3.5" style={{ borderColor: "#e2e8f0" }}>
          <div>
            <div className="text-[17px] font-extrabold" style={{ color: NAVY }}>📚 밸류에이션 튜토리얼</div>
            <div className="text-[12px] text-slate-500">{name} — 이 탭의 모든 값, 계산식·출처·해석</div>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-full text-slate-500 hover:bg-slate-100" aria-label="닫기">✕</button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {/* 0. 한눈에 */}
          <div className="rounded-xl border-l-4 px-4 py-3" style={{ background: "#eff6ff", borderColor: BLUE }}>
            <div className="text-[14.5px] font-bold" style={{ color: "#1e40af" }}>이 탭은 "{name}{josa(name, "이", "가")} 지금 비싼지 싼지"를 두 가지 눈으로 봅니다</div>
            <div className="mt-1.5 text-[13.5px] leading-7 text-slate-700">
              ① <b>상대가치(멀티플)</b> — 비슷한 회사들이 받는 가격과 견줌. 현재가에 가까워 즉시 참고용<br/>
              ② <b>절대가치(DCF·바닥가치)</b> — 회사가 벌 현금을 직접 계산한 <b>보수적 내재가치</b><br/>
              ③ <b>둘의 '차이' 읽기</b> — 현재가에 담긴 <b>시장의 미래 기대</b>를 숫자로 해석<br/>
              ④ <b>WACC·신뢰도</b> — 위 계산에 쓰는 '할인율'과 결과를 '얼마나 믿을지'<br/>
              <span className="text-slate-500">※ <b>핵심</b>: 한쪽 숫자만 믿지 않습니다. DCF가 현재가와 다른 건 대개 <b>오류가 아니라 정보</b>예요 — DCF는 '증명된 과거 실적' 기준의 보수적 값이고, 시장가는 '미래 기대'까지 반영하기 때문입니다. 그 차이를 ③에서 풀어 읽습니다.</span>
            </div>
          </div>

          {/* 1. 동종업계 비교 (멀티플) */}
          <Sec icon="🏢" title="동종업계 비교 (멀티플)">
            <p>비슷한 회사들의 "가격 배수"로 적정가를 거꾸로 추정합니다. <b>배수(×)</b>가 핵심.</p>
            <Term en="PER" ko="주가수익비율" desc="주가 ÷ 주당순이익(EPS). '순이익의 몇 배에 거래되나'. 낮을수록 싸 보임." />
            <Calc>적정가 ≈ 동종업계 평균 PER × 우리 회사 EPS</Calc>
            <Term en="PBR" ko="주가순자산비율" desc="주가 ÷ 주당순자산(BPS). '장부가치의 몇 배'. 1배 미만이면 청산가치 이하." />
            <Term en="EV/EBITDA" ko="기업가치/세전영업현금이익" desc="빚까지 포함한 '진짜 회사 전체 가격'을 본업 현금이익으로 나눈 배수." />
            <Term en="EV" ko="기업가치(Enterprise Value)" desc="시가총액 + 순부채. '빚까지 떠안고 회사를 통째로 사는 값'." />
            <Term en="EV/Sales" ko="기업가치/매출" desc="이익이 적자라 PER을 못 쓸 때, 매출 대비로 보는 보조 지표." />
            <Src>각 멀티플 배수 = DART 재무제표(EPS·BPS·EBITDA·매출) + 피어 평균. 적정가는 우리 회사 실적에 적용해 역산.</Src>
            <How>이익 기준(PER·EV/EBITDA)이 <b>가장 신뢰</b>. 자산·매출 기준(PBR·EV/Sales)은 편차가 커서 참고용. 여러 지표가 같은 방향이면 신뢰↑.</How>
          </Sec>

          {/* 2. 피어 그룹 */}
          <Sec icon="👥" title="피어 그룹 (비교한 회사들)">
            <p>멀티플은 '비교 대상'이 절반입니다. 사람이 고르지 않고, 코스피·코스닥 약 2,000개 종목을 <b>10가지 '닮은 정도'로 채점</b>해 자동 선정합니다.</p>
            <Calc>업종(WICS) + 규모(시총) + 사업 내용 유사도 <b>(LLM)</b> + 수익성·성장·D/E·베타… 10개 가중채점 → 상위 3사</Calc>
            <Term en="WICS" ko="업종 분류" desc="같은 소섹터면 만점, 밸류체인상 인접 업종이면 부분 점수 (가중치 18% — 가장 큼)." />
            <Term en="사업 내용 유사도 (LLM)" ko="AI 의미 비교" desc="사업보고서 '사업의 내용'을 다국어 임베딩 모델(BGE-M3)로 읽어, 분류표상 같은 칸이 아니라 '실제로 비슷한 일을 하는가'를 비교." />
            <Src>WICS 산업분류 + DART 사업보고서 AI 임베딩 + 재무 유사도. ETF·리츠·스팩·우선주, 거래대금 1억 미만, 지주·복합기업은 자동 제외.</Src>
            <How>자동 선정이라 가끔 업종이 다른 회사가 섞일 수 있어 <b>신뢰도 등급(A~E)</b>을 함께 공개합니다. <b>A·B면 안심</b>, D·E면 멀티플 결과도 그만큼 조심해서 보세요.</How>
          </Sec>

          {/* 4. DCF — 보수적 내재가치 */}
          <Sec icon="🔢" title="DCF — 펀더멘털 기반 '보수적' 내재가치">
            <p>회사가 <b>앞으로 벌 현금(FCFF)</b>을 <b>오늘 값</b>으로 환산한 내재가치. 단, 우리 엔진은 <b>일부러 보수적</b>으로 잡습니다.</p>
            <Term en="DCF" ko="현금흐름할인법(Discounted Cash Flow)" desc="미래 잉여현금흐름(FCFF)을 WACC로 할인해 합산." />
            <Term en="FCFF" ko="기업잉여현금흐름" desc="영업이익에서 세금·설비투자(CapEx)·운전자본을 뺀, 회사가 실제로 남기는 현금." />
            <Calc>회사 가치(EV) = Σ (미래 FCFF ÷ (1+WACC)<sup>년수</sup>) + 잔존가치(TV)</Calc>
            <div className="rounded-lg border px-3 py-2.5 text-[13px] leading-6" style={{ borderColor: "#bfdbfe", background: "#f5f9ff", color: "#1e3a5f" }}>
              <b style={{ color: "#1e40af" }}>왜 '보수적'인가 (엔진이 실제로 거는 안전장치)</b>
              <ul className="mt-1 space-y-0.5">
                <li>• <b>성장률 상한</b>: 과거 호황의 고성장을 그대로 미래로 늘리지 않고, 펀더멘털상 <b>지속가능한 성장률(SGR=ROIC×재투자율)</b>로 깎음{sgr != null ? <> — 이 종목 SGR <b>{spct(sgr)}</b></> : null}.</li>
                <li>• <b>성장 감속(Fade-out)</b>: 첫해 과거 성장률에서 시작해 5년에 걸쳐 <b>영구성장률 약 2.5%</b>(경제성장률 이하)로 수렴.</li>
                <li>• <b>마진 정상화</b>: 미래 마진을 최근 3~8년 <b>평균</b>으로 (개선 기대는 절반만 인정).</li>
                <li>• <b>초과수익 소멸</b>: 독점적 해자(moat)가 확실치 않으면 장기 수익률을 WACC로 수렴(영구 초과이익 미인정).</li>
              </ul>
            </div>
            <Src>FCFF = DART 재무제표(영업이익·감가상각·CapEx·운전자본) <b>과거 실적</b> 정상화. → 결과는 "회사가 지금까지 보여준 실력대로만 벌 때"의 <b>보수적 하단</b>.</Src>
            {fair != null && cur != null && (
              <How>이 종목: DCF <b>₩{won(fair)}</b> vs 현재가 <b>₩{won(cur)}</b>. DCF가 낮은 건 <b>오류가 아니라</b> 위 안전장치 때문 — 시장은 여기에 <b>미래 기대</b>를 더 얹습니다(다음 칸 ▼).</How>
            )}
          </Sec>

          {/* 5. ★ 현재가와 DCF의 '차이' 읽는 법 (핵심) */}
          <Sec icon="🪜" title="현재가와 DCF의 '차이', 어떻게 읽나">
            <p>가장 많이 받는 질문입니다 — "DCF 가치와 현재가가 다른데 어느 쪽이 맞나요?" 답은 분명합니다. <b>그 차이는 '오류'가 아니라 '정보'</b>입니다. <b>현재 주가 = 펀더멘털 가치(지금 실력) + 시장의 미래 기대분</b>이기 때문이죠. 그 차이 안에 무엇이 들었는지를 경우의 수로 나눠 봅니다.</p>

            <div className="rounded-lg border px-3 py-2.5 text-[13px] leading-6" style={{ borderColor: "#fecaca", background: "#fff7f7", color: "#9f1239" }}>
              <b style={{ color: "#be123c" }}>① 현재가 &gt; DCF (지금 종목이 여기에 해당)</b> — 시장은 (1) 과거보다 빠른 미래 성장을 기대하거나, (2) 신제품·신사업처럼 과거 재무에 아직 안 잡힌 모멘텀을 반영하거나, (3) 업황 회복을 선반영하고 있을 수 있습니다. 물론 (4) 단순히 과열된 거품일 수도 있죠. → <b>"시장이 이미 낙관 — 거품 주의"</b>로 읽되, 아래 '기대 성장률'로 그 기대가 합리적인지 가늠하세요.
            </div>
            <div className="rounded-lg border px-3 py-2.5 text-[13px] leading-6" style={{ borderColor: "#bbf7d0", background: "#f0fdf4", color: "#166534" }}>
              <b style={{ color: "#15803d" }}>② 현재가 &lt; DCF</b> — (1) 시장이 이 회사를 지나치게 보수적으로 봐 <b>저평가 기회</b>일 수 있고, (2) 반대로 시장이 아는 악재(업황 둔화·일회성 이익 소멸)를 주가가 먼저 반영했을 수도 있습니다. → <b>"저평가 기회일 수 있지만, 시장이 왜 신중한지(업황 등)도 꼭 확인"</b>.
            </div>

            <p className="text-[13px] text-slate-500">그래서 DCF는 절대 숫자에 매달리기보다 <b>거꾸로</b> 씁니다 — "이 가치가 얼마다"가 아니라, <b>"지금 주가가 정당화되려면 시장은 매년 몇 % 성장을 기대해야 하나"</b>를 역산해 거품·저평가를 가늠합니다. 다음 세 지표가 그 도구입니다.</p>
            <Term en="EPV" ko="바닥가치(성장 0)" desc="성장을 0으로 본 '지금 실력만'의 가치 = 정상화 영업이익 ÷ WACC (Greenwald)." />
            <Term en="Growth Premium" ko="성장 기대 프리미엄" desc="현재가 중 '미래 성장 기대분'의 비율 = 시가총액 ÷ 바닥가치(EPV) − 1." />
            <Term en="Implied Growth" ko="시장 기대 성장률" desc="현재가가 정당화되려면 시장이 기대해야 하는 영구성장률 (역산·Damodaran). 적정주가 추정에 기대지 않아 가정에 가장 덜 흔들리는 단단한 신호." />
            {(epv != null && gpPct != null) && (
              <div className="rounded-lg border px-3 py-2.5 text-[13px] leading-6" style={{ borderColor: "#fde68a", background: "#fffdf5", color: "#78350f" }}>
                <b style={{ color: "#92400e" }}>이 종목 숫자로 풀면</b>
                <ul className="mt-1 space-y-0.5">
                  <li>• 바닥가치(성장 0) <b>₩{won(epv)}</b> ↔ 현재가 <b>₩{won(cur)}</b></li>
                  <li>• 성장 기대 프리미엄 <b>약 {gpPct.toLocaleString()}%</b>{gpX != null && <> (현재가 ≈ 바닥가치의 <b>{gpX.toFixed(1)}배</b>)</> } → 주가의 상당부분이 <b>미래 기대분</b></li>
                  {ig != null && <li>• 시장 기대 성장률 <b>{spct(ig)}</b> (경제성장률 {pct(gdp, 0)}의 약 {gdp ? (ig / gdp).toFixed(1) : "—"}배){verdict ? <> → <b>{verdict}</b></> : null}</li>}
                  {gap != null && <li>• 기대 격차 <b>{spct(gap)}</b> = 시장 기대 − 펀더멘털 지속가능(SGR)</li>}
                </ul>
              </div>
            )}
            <How><b>보수적인 DCF 값도 그 자체로 쓸모가 있습니다</b> — '회사가 지금 실력대로만 벌어도 받쳐주는 하단(안전마진 기준선)'이거든요. 현재가가 이 값에 가깝거나 아래면 하방이 단단한 편, 훨씬 위면 그만큼 미래 기대에 기대고 있다는 뜻입니다. <b>애널리스트 목표가가 우리 DCF보다 높은 것도 같은 이유</b> — 그들은 미래 성장을 더 적극적으로 반영하니까요. 둘 다 틀린 게 아니라 <b>'가정'이 다른 것</b>입니다.</How>
          </Sec>

          {/* 6. WACC */}
          <Sec icon="⚙️" title="WACC (가중평균자본비용)">
            <p>미래의 돈을 오늘 값으로 환산하는 <b>할인율</b>. 회사가 자본(주주 돈 + 빌린 돈)을 끌어다 쓰는 데 드는 <b>평균 비용</b> = 회사가 사업으로 넘어야 할 <b>최소 합격선(hurdle)</b>입니다. <span className="text-slate-500">(주주 개인이 주식에 요구하는 최소 수익률은 WACC가 아니라 <b>Ke</b>예요 — 아래 참고)</span></p>
            <Term en="WACC" ko="가중평균자본비용" desc="자기자본비용(Ke)과 세후 부채비용(Kd)을, 회사가 실제 쓰는 자본·부채 비중대로 섞은 값." />
            <Calc>WACC = Ke × (자기자본 비중) + Kd(세후) × (부채 비중)</Calc>
            <Term en="Ke" ko="자기자본비용" desc="주주가 기대하는 수익률 = Rf(국채금리) + β(베타) × ERP(주식위험프리미엄) + 규모 프리미엄. CAPM." />
            <Term en="Rf" ko="무위험수익률" desc="국고채 10년 금리. 가장 안전한 기본 수익. 모든 위험자산 수익률의 출발점." />
            <Term en="β (베타)" ko="시장민감도" desc="시장이 1% 움직일 때 이 주식이 몇 % 움직이나. 높을수록 위험↑ → Ke↑." />
            <Src>Rf = ECOS(한국은행) 국고채 10년 · ERP 8%(한공회 7~9% 중간값) · β = 피어 베타(Hamada 언레버·리레버) · Kd = KOFIA 신용등급별 회사채 금리.</Src>
            {s.wacc != null && <How>이 종목 <b>{pct(s.wacc, 1)}</b> (보통 8~13%). <b>높을수록</b> 미래 이익을 더 깐깐하게(작게) 봐서 DCF 가치가 <b>낮아집니다</b>. 빚이 비싸거나 변동성이 큰 회사일수록 높아요.</How>}
            <div className="rounded-lg border px-3 py-2.5 text-[13px] leading-6" style={{ borderColor: "#bfdbfe", background: "#f5f9ff", color: "#1e3a5f" }}>
              <b style={{ color: "#1e40af" }}>투자 판단에 쓰는 법 — 비교 대상을 구분하세요</b>
              <div className="mt-1">WACC는 <b>'회사'</b>가 자본비용 이상 버는지 보는 합격선이지, <b>'주주 개인'</b>이 주식에서 기대하는 수익률의 비교 대상이 아니에요. 두 잣대는 따로 봅니다.</div>
              <div className="mt-1.5 space-y-1">
                <div className="rounded-md px-2.5 py-1.5 text-center font-bold" style={{ background: "#dcfce7", color: "#166534" }}>
                  회사 차원: ROIC &gt; WACC&nbsp;&nbsp;→&nbsp;&nbsp;가치 창출 (자본비용 이상 벌어들임)
                </div>
                <div className="rounded-md px-2.5 py-1.5 text-center font-bold" style={{ background: "#dbeafe", color: "#1d4ed8" }}>
                  주주 차원: 내 기대수익률 &gt; Ke(자기자본비용)&nbsp;&nbsp;→&nbsp;&nbsp;매수 관점
                </div>
              </div>
              <div className="mt-1.5 text-[12.5px] text-slate-500">※ WACC는 자기자본비용(Ke)에 더 싼 세후 부채비용(Kd)을 섞어 보통 <b>Ke보다 낮습니다</b>. 그래서 &lsquo;기대수익률 &gt; WACC면 매수&rsquo;로 쓰면 문턱이 너무 낮아 과대평가돼요 — <b>주주 개인의 잣대는 WACC가 아니라 Ke</b>(보통 WACC보다 1~2%p 높음)입니다.</div>
            </div>
          </Sec>

          {/* 7. 신뢰도 */}
          <Sec icon="🎯" title="이 분석을 얼마나 믿을 수 있나 (DCF 신뢰도)">
            <Calc>등급 A~E = 데이터 충실도 + 가정 민감도 + Terminal(잔존가치) 비중</Calc>
            <Src>FCFF 음수 여부 · 피어 신뢰도 · Terminal 비중(높을수록 먼 미래 의존=불확실) 등 종합.</Src>
            {s.dcf_grade && <How>이 종목 <b>{s.dcf_grade}등급</b>. A·B면 비교적 탄탄, D·E(또는 부적합)면 멀티플·바닥가치를 더 참고하세요.</How>}
            <div className="rounded-lg px-3 py-2 text-[13px]" style={{ background: "#f1f5f9", color: "#334155" }}>
              📌 <b>최종 정리</b>: 한 숫자만 믿지 말고 <b>멀티플 · DCF · 바닥가치 · 신뢰도</b>를 함께 보세요. 모두 같은 방향이면 신뢰↑.
            </div>
          </Sec>

          <div className="pb-4 pt-1 text-center text-[12px] text-slate-400">
            ※ 모든 값은 DART 공시·시장 데이터 기반 실측(NO-MOCK) · 투자 판단 책임은 이용자에게 있습니다.
          </div>
        </div>
      </aside>
    </>
  );
}
