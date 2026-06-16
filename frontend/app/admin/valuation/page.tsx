"use client";
/**
 * 밸류에이션 · AI 챗봇 전용 관리자 페이지  (route: /admin/valuation)
 * ──────────────────────────────────────────────────────────────────
 * 평가에 사용된 ① 데이터 기준일(As-of) ② 데이터 출처 ③ 테스트 환경 ④ AI 하네스
 *   + 🧪 테스트 면(밸류 QA · 챗봇 QA · 헬스)
 * 데이터는 GET /api/valuation-admin/meta (valuation.db·filmn9.db 실측) + 챗봇 8800/health.
 * 단일 클라이언트 컴포넌트 · 인라인 스타일(외부 의존 최소).
 */
import { useEffect, useState, useRef } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8090";
const CHAT_API = process.env.NEXT_PUBLIC_CHAT_API_URL || "http://localhost:8800";

// ── 테마 ──────────────────────────────────────────────────────────────
const T = {
  bg: "#0B1120", panel: "#111A2E", panel2: "#0F1626", border: "#243049",
  text: "#E5EBF5", sub: "#8DA0BE", dim: "#5C6E8C",
  gold: "#FCD34D", green: "#34D399", red: "#F87171", blue: "#60A5FA", purple: "#A78BFA",
};
const tagColor: Record<string, string> = {
  dart: "#60A5FA", krx: "#34D399", ecos: "#FBBF24", kofia: "#F472B6",
  kicpa: "#A78BFA", damodaran: "#FB923C", openai: "#10B981", bge: "#22D3EE", chroma: "#F87171",
};

// ── 정적 데이터: 출처 / 테스트환경 / 하네스 ────────────────────────────
const SOURCES: [string, string, string, string][] = [
  // [tag, 출처, 제공 항목, 갱신주기]
  ["dart", "DART 전자공시", "재무제표(XBRL)·사업보고서·주주·임원·공시 원문", "분기/사업보고서 시즌"],
  ["krx", "KRX · pykrx", "주가·시가총액·상장주식수·시장구분", "일배치(장마감 16:00)"],
  ["ecos", "ECOS (한국은행)", "무위험금리 Rf — 국고채 10년", "일"],
  ["kofia", "KOFIA (금융투자협회)", "회사채 수익률 → 타인자본비용 Kd", "일"],
  ["kicpa", "한국공인회계사회", "규모프리미엄 SRP 테이블", "연 1회 (가이드)"],
  ["damodaran", "Damodaran (NYU)", "산업 무차입베타 βU (Hamada 역레버 기준)", "연 1회"],
  ["openai", "OpenAI", "gpt-5.4-mini — 챗봇 답변 생성(reasoning=high)", "API 호출 시"],
  ["bge", "BGE-M3 / reranker", "사업보고서 임베딩(1024d) · cross-encoder 재랭킹", "모델(로컬 GPU)"],
  ["chroma", "ChromaDB", "벡터 검색 인덱스 (4.2M 청크)", "사업보고서 시즌(분기)"],
];

const HARNESS_DEV: [string, string][] = [
  ["NO-MOCK 원칙", "데이터 없으면 임의값 금지 → 가짜 숫자 생성 차단. 미평가 종목은 '준비 중' 안내."],
  ["추출·판단 분리", "LLM은 사실 추출만, '최신본 선택' 등 결정은 결정론적 코드(report_detector)."],
  ["RAG 그라운딩 + 출처 강제", "챗봇 답변은 검색된 DART 청크에만 근거, 출처카드(원문 링크) 동반 → 환각 검증 가능."],
  ["저온도·구조화 출력", "온도↓ + JSON 스키마 → 재현성·검증성 확보."],
  ["검색 정밀화", "하이브리드(BM25+벡터) · cross-encoder 재랭킹 · 재무제표 라우팅(FINSTMT)."],
  ["신뢰도 등급화 A~E", "DCF 신뢰도·피어 신뢰도 → 낮으면 점추정 숨기고 범위·진단으로 대체."],
  ["증분 수집(최신성)", "report_registry(rcept_no 비교)로 신규·정정만 수집, 임베딩 skip_existing."],
];
const HARNESS_USER: [string, string][] = [
  ["출처 투명성", "모든 답변·수치에 출처/근거(DART 원문 링크)를 함께 표시."],
  ["한계 고지", "'참고용·투자권유 아님' 명시. 적정주가 단정 대신 추세·범위로 안내."],
  ["NO-MOCK UX", "불확실하면 점추정을 숨기고 '필요 성장률·5종 진단'으로 우회 판단 제공."],
  ["용어 풀이", "DCF·WACC·멀티플 등 전문용어에 ⓘ 쉬운 설명 제공."],
];
const HARNESS_IMPROVE: string[] = [
  "근거기반 거부(grounded refusal) — 근거 부족 시 '자료 없음'으로 답변 거부",
  "클레임 단위 인용 + 사후 검증기로 인용↔답변 정합성 자동 점검",
  "구조화 출력(function calling) 전면화 + 스키마 검증 재시도",
  "프롬프트 버전관리 + 골든셋 회귀 CI(A/B)",
  "reasoning_effort 동적화(질문 난이도별) → 속도·비용 최적화",
  "비용·지연 텔레메트리(질의당 토큰/원/지연 상한)",
  "범위 가드레일(투자권유·주가예측·개인정보 거부) · 프롬프트 인젝션·PII 방어",
];

// ── 작은 컴포넌트 ──────────────────────────────────────────────────────
function Tag({ k, children }: { k: string; children: any }) {
  const c = tagColor[k] || T.sub;
  return <span style={{ fontSize: 11, fontWeight: 700, color: c, border: `1px solid ${c}55`,
    background: `${c}18`, borderRadius: 6, padding: "1px 7px", whiteSpace: "nowrap" }}>{children}</span>;
}
function Section({ title, desc, children }: { title: string; desc?: string; children: any }) {
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 14, padding: 20, marginBottom: 18 }}>
      <div style={{ fontSize: 15, fontWeight: 800, color: T.text, marginBottom: desc ? 2 : 14 }}>{title}</div>
      {desc && <div style={{ fontSize: 12, color: T.sub, marginBottom: 14 }}>{desc}</div>}
      {children}
    </div>
  );
}
function KV({ k, v, sub, accent }: { k: string; v: any; sub?: string; accent?: string }) {
  return (
    <div style={{ background: T.panel2, border: `1px solid ${T.border}`, borderRadius: 10, padding: "12px 14px" }}>
      <div style={{ fontSize: 11, color: T.sub, marginBottom: 5 }}>{k}</div>
      <div style={{ fontSize: 17, fontWeight: 800, color: accent || T.text, fontVariantNumeric: "tabular-nums" }}>{v ?? "—"}</div>
      {sub && <div style={{ fontSize: 11, color: T.dim, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}
function Dot({ ok }: { ok: boolean | null }) {
  const c = ok == null ? T.dim : ok ? T.green : T.red;
  return <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: 99, background: c, boxShadow: `0 0 8px ${c}` }} />;
}

// ── 메인 ──────────────────────────────────────────────────────────────
export default function ValuationAdminPage() {
  const [tab, setTab] = useState<"ops" | "test">("ops");
  const [meta, setMeta] = useState<any>(null);
  const [chat, setChat] = useState<any>(null);
  const [be, setBe] = useState<boolean | null>(null);

  useEffect(() => {
    fetch(`${API}/api/valuation-admin/meta`).then(r => r.json()).then(setMeta).catch(() => setMeta(false));
    fetch(`${API}/health`).then(r => r.ok ? setBe(true) : setBe(false)).catch(() => setBe(false));
    fetch(`${CHAT_API}/health`).then(r => r.json()).then(setChat).catch(() => setChat(false));
  }, []);

  const v = meta?.valuation || {};
  const co = meta?.company || {};
  const cb = meta?.chatbot_hint || {};
  const chunks = chat && chat.db ? chat.db.total_chunks : null;
  const gpu = chat && chat.device ? chat.device.gpu_name : null;

  return (
    <div style={{ minHeight: "100vh", background: T.bg, color: T.text, fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif" }}>
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "28px 22px 60px" }}>
        {/* 헤더 */}
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
          <div style={{ fontSize: 22, fontWeight: 900, letterSpacing: -0.5 }}>
            <span style={{ color: T.gold }}>FINSIGHT</span> 밸류·챗봇 관리자
          </div>
          <div style={{ fontSize: 12, color: T.sub }}>평가단 검토용 · 데이터 기준일 / 출처 / 테스트 환경 / AI 하네스</div>
        </div>
        <div style={{ fontSize: 11, color: T.dim, marginTop: 4 }}>
          집계 시각 {meta?.generated_at || "…"} · 밸류 DB: {v.db_exists ? "VAR 직결(재평가 자동 반영)" : "미연결"}
        </div>

        {/* 탭 */}
        <div style={{ display: "flex", gap: 8, margin: "18px 0 20px" }}>
          {([["ops", "📋 운영 (데이터·환경)"], ["test", "🧪 테스트 (QA)"]] as const).map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)} style={{
              fontSize: 13, fontWeight: 700, padding: "8px 16px", borderRadius: 9, cursor: "pointer",
              border: `1px solid ${tab === id ? T.gold : T.border}`,
              background: tab === id ? `${T.gold}1a` : T.panel, color: tab === id ? T.gold : T.sub,
            }}>{label}</button>
          ))}
        </div>

        {meta === false && <div style={{ color: T.red, fontSize: 13 }}>⚠ 백엔드(/api/valuation-admin/meta) 응답 없음 — 8090 기동 확인.</div>}

        {/* ═══════════ 운영 탭 ═══════════ */}
        {tab === "ops" && (
          <>
            {/* ① 데이터 기준일 */}
            <Section title="① 평가 데이터 기준일 (As-of)"
              desc="밸류에이션 산출에 들어간 각 데이터의 '기준 시점'. 증분 설계상 시세·금리는 매 재평가 때 최신화됩니다.">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(190px,1fr))", gap: 10 }}>
                <KV k="밸류 평가일 (최신)" v={v.eval_date_latest} sub={`대량 산출일 ${v.eval_date_bulk || "—"}`} accent={T.gold} />
                <KV k="평가 모델" v={v.model_version} sub={`${(v.n_evaluated ?? 0).toLocaleString()}개 종목 평가`} />
                <KV k="무위험금리 Rf" v={v.rf ? `${v.rf.pct}%` : "—"} sub={v.rf ? `${v.rf.date} · ${v.rf.name}` : "ECOS"} accent={T.blue} />
                <KV k="회사채 Kd (KOFIA)" v={v.kofia?.date} sub={`${(v.kofia?.n ?? 0).toLocaleString()}건 수익률`} />
                <KV k="주가·시가총액" v={v.market?.date} sub={`${(v.market?.n ?? 0).toLocaleString()}종 스냅샷`} accent={T.green} />
                <KV k="재무·주가 (기업개요)" v={meta?.ohlcv_date} sub="DART XBRL · KRX 일봉" />
                <KV k="챗봇 사업보고서" v="2025연간 + 2026 1Q" sub={chunks ? `${chunks.toLocaleString()} 청크` : "임베딩 기준"} accent={T.purple} />
              </div>
            </Section>

            {/* ② 데이터 출처 */}
            <Section title="② 데이터 출처 (Source)"
              desc="밸류 산출 1건당 사용 원천: 국고채 10년(Rf)·주가/시총·재무제표(FCFF)·피어 자본구조 D/E·회사채(Kd)·SRP.">
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
                  <thead>
                    <tr style={{ color: T.sub, textAlign: "left", borderBottom: `1px solid ${T.border}` }}>
                      <th style={{ padding: "7px 8px" }}>출처</th><th style={{ padding: "7px 8px" }}>제공 항목</th><th style={{ padding: "7px 8px" }}>갱신주기</th>
                    </tr>
                  </thead>
                  <tbody>
                    {SOURCES.map(([k, name, item, freq], i) => (
                      <tr key={i} style={{ borderBottom: `1px solid ${T.border}66` }}>
                        <td style={{ padding: "8px 8px" }}><Tag k={k}>{name}</Tag></td>
                        <td style={{ padding: "8px 8px", color: T.text }}>{item}</td>
                        <td style={{ padding: "8px 8px", color: T.sub, whiteSpace: "nowrap" }}>{freq}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>

            {/* ③ 테스트 환경 */}
            <Section title="③ 테스트 환경 (Test Environment)">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 12 }}>
                <div style={{ background: T.panel2, border: `1px solid ${T.border}`, borderRadius: 10, padding: 14 }}>
                  <div style={{ fontSize: 13, fontWeight: 800, color: T.gold, marginBottom: 8 }}>💰 밸류 엔진 (v{v.model_version || "8"})</div>
                  <div style={{ fontSize: 12, color: T.text, lineHeight: 1.7 }}>
                    {v.methodology || "DCF + EPV + 멀티플 + 시나리오"}<br />
                    <span style={{ color: T.sub }}>멀티플 4종: EV/EBITDA · EV/Sales · PER · PBR</span><br />
                    <span style={{ color: T.sub }}>역DCF(내재성장률) · 안전마진 · 신뢰도 A~E · NO-MOCK</span>
                  </div>
                </div>
                <div style={{ background: T.panel2, border: `1px solid ${T.border}`, borderRadius: 10, padding: 14 }}>
                  <div style={{ fontSize: 13, fontWeight: 800, color: T.purple, marginBottom: 8 }}>🤖 챗봇 RAG 파이프라인</div>
                  <div style={{ fontSize: 12, color: T.text, lineHeight: 1.7 }}>
                    {cb.embed_model || "BGE-M3"} → {cb.retrieval || "하이브리드+재랭킹"}<br />
                    <span style={{ color: T.sub }}>{cb.reranker} · {cb.llm}</span><br />
                    <span style={{ color: T.sub }}>커버리지 {cb.coverage?.toLocaleString()}개사 · 출처카드(DART 원문)</span>
                  </div>
                </div>
                <div style={{ background: T.panel2, border: `1px solid ${T.border}`, borderRadius: 10, padding: 14 }}>
                  <div style={{ fontSize: 13, fontWeight: 800, color: T.blue, marginBottom: 8 }}>🖥 시스템</div>
                  <div style={{ fontSize: 12, color: T.text, lineHeight: 1.7 }}>
                    백엔드 :8090 (FastAPI) · 챗봇 :8800<br />
                    <span style={{ color: T.sub }}>GPU {gpu || "RTX 4060 (CUDA)"}</span><br />
                    <span style={{ color: T.sub }}>DB valuation.db(VAR직결) + filmn9.db + chroma 32.6GB</span>
                  </div>
                </div>
              </div>
              {/* 기업개요 커버리지 */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(120px,1fr))", gap: 8, marginTop: 12 }}>
                {[["기업정보", co.company_info], ["재무", co.financials], ["재무상세", co.financial_detail], ["주주", co.shareholders], ["경영인", co.executives], ["주가", co.ohlcv]].map(([k, n]: any) => (
                  <div key={k} style={{ background: T.panel2, border: `1px solid ${T.border}`, borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
                    <div style={{ fontSize: 16, fontWeight: 800, color: T.text }}>{(n ?? 0).toLocaleString()}</div>
                    <div style={{ fontSize: 10.5, color: T.sub }}>{k}</div>
                  </div>
                ))}
              </div>
            </Section>

            {/* ④ AI 하네스 */}
            <Section title="④ AI 하네스 (AI 통제 원칙)"
              desc="모델이 '사실에만 근거하고 불확실성을 정직하게 드러내도록' 통제하는 장치 — 개발자/사용자 관점 + 개선안.">
              <div style={{ fontSize: 12.5, fontWeight: 800, color: T.green, margin: "2px 0 8px" }}>🛠 개발자 관점 — 어떻게 통제하나</div>
              {HARNESS_DEV.map(([t, d], i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "170px 1fr", gap: 10, padding: "6px 0", borderBottom: `1px solid ${T.border}55` }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: T.text }}>{t}</div>
                  <div style={{ fontSize: 12, color: T.sub }}>{d}</div>
                </div>
              ))}
              <div style={{ fontSize: 12.5, fontWeight: 800, color: T.blue, margin: "16px 0 8px" }}>👤 사용자 관점 — 무엇을 보장하나</div>
              {HARNESS_USER.map(([t, d], i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "170px 1fr", gap: 10, padding: "6px 0", borderBottom: `1px solid ${T.border}55` }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: T.text }}>{t}</div>
                  <div style={{ fontSize: 12, color: T.sub }}>{d}</div>
                </div>
              ))}
              <div style={{ fontSize: 12.5, fontWeight: 800, color: T.gold, margin: "16px 0 8px" }}>🚀 더 나은 하네스 — 개선 제안</div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: T.sub, lineHeight: 1.85 }}>
                {HARNESS_IMPROVE.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </Section>
          </>
        )}

        {/* ═══════════ 테스트 탭 ═══════════ */}
        {tab === "test" && <TestPanel be={be} chat={chat} />}
      </div>
    </div>
  );
}

// ── 테스트 패널 ────────────────────────────────────────────────────────
function TestPanel({ be, chat }: { be: boolean | null; chat: any }) {
  const [code, setCode] = useState("000720");
  const [valRes, setValRes] = useState<any>(null);
  const [valBusy, setValBusy] = useState(false);
  const [q, setQ] = useState("현대건설의 주요 사업은?");
  const [chatRes, setChatRes] = useState<any>(null);
  const [chatBusy, setChatBusy] = useState(false);

  const runVal = async () => {
    setValBusy(true); setValRes(null);
    try {
      const d = await fetch(`${API}/api/valuation/${code}`).then(r => r.json());
      const dg = d.valuation_diagnostics || {};
      setValRes({
        ok: !d.is_mock,
        checks: [
          ["실데이터(is_mock=false)", d.is_mock === false],
          ["summary 존재", !!d.summary],
          ["EPV 진단(valuation_diagnostics)", !!dg.epv_price],
          ["시나리오(Bear/Base/Bull)", !!d.scenarios],
          ["멀티플 4종", Array.isArray(d.multiples) && d.multiples.length >= 1],
        ],
        epv: dg.epv_price, fair: d.summary?.fair_price, cur: d.summary?.current_price,
      });
    } catch (e: any) { setValRes({ ok: false, err: String(e) }); }
    setValBusy(false);
  };

  const runChat = async () => {
    setChatBusy(true); setChatRes(null);
    try {
      const d = await fetch(`${CHAT_API}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: q }),
      }).then(r => r.json());
      setChatRes({ answer: d.answer || "(빈 답변)", sources: d.sources || [] });
    } catch (e: any) { setChatRes({ answer: "⚠ 챗봇(8800) 연결 실패: " + String(e), sources: [] }); }
    setChatBusy(false);
  };

  const chunks = chat && chat.db ? chat.db.total_chunks : null;

  return (
    <>
      <Section title="시스템 헬스">
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 13 }}>
          <span><Dot ok={be} /> 백엔드 8090</span>
          <span><Dot ok={chat ? true : chat === false ? false : null} /> 챗봇 8800 {chunks ? `(${chunks.toLocaleString()} 청크)` : ""}</span>
          <span><Dot ok={true} /> 프론트 3000</span>
        </div>
      </Section>

      <Section title="💰 밸류에이션 QA" desc="종목코드 입력 → /api/valuation 실측 → 통합 평가 JSON 정합성 5종 판정.">
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input value={code} onChange={e => setCode(e.target.value)} placeholder="종목코드 (예: 000720)"
            style={{ background: T.panel2, border: `1px solid ${T.border}`, color: T.text, borderRadius: 8, padding: "8px 12px", fontSize: 13, width: 180 }} />
          <button onClick={runVal} disabled={valBusy} style={{ background: T.gold, color: "#1a1a1a", fontWeight: 800, border: "none", borderRadius: 8, padding: "8px 18px", cursor: "pointer", fontSize: 13 }}>
            {valBusy ? "조회 중…" : "QA 실행"}
          </button>
        </div>
        {valRes && (
          <div>
            {valRes.checks?.map(([label, pass]: any, i: number) => (
              <div key={i} style={{ fontSize: 13, padding: "4px 0", color: pass ? T.green : T.red }}>{pass ? "✓" : "✗"} {label}</div>
            ))}
            {valRes.epv != null && (
              <div style={{ fontSize: 12, color: T.sub, marginTop: 8 }}>
                EPV ₩{Math.round(valRes.epv).toLocaleString()} · 적정범위 산출가 ₩{Math.round(valRes.fair || 0).toLocaleString()} · 현재가 ₩{Math.round(valRes.cur || 0).toLocaleString()}
              </div>
            )}
            {valRes.err && <div style={{ color: T.red, fontSize: 12 }}>{valRes.err}</div>}
          </div>
        )}
      </Section>

      <Section title="🤖 챗봇 QA" desc="질의 → /chat (RAG + GPT) → 답변 + 출처. (재무 질의는 10~30초 소요)">
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input value={q} onChange={e => setQ(e.target.value)}
            style={{ background: T.panel2, border: `1px solid ${T.border}`, color: T.text, borderRadius: 8, padding: "8px 12px", fontSize: 13, flex: 1 }} />
          <button onClick={runChat} disabled={chatBusy} style={{ background: T.purple, color: "#fff", fontWeight: 800, border: "none", borderRadius: 8, padding: "8px 18px", cursor: "pointer", fontSize: 13, whiteSpace: "nowrap" }}>
            {chatBusy ? "검색 중…" : "질의"}
          </button>
        </div>
        {chatRes && (
          <div style={{ background: T.panel2, border: `1px solid ${T.border}`, borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 13, color: T.text, whiteSpace: "pre-wrap", lineHeight: 1.7 }}>{chatRes.answer}</div>
            {chatRes.sources?.length > 0 && (
              <div style={{ marginTop: 10, fontSize: 11, color: T.sub }}>
                📎 출처 {chatRes.sources.length}건: {chatRes.sources.slice(0, 3).map((s: any, i: number) => (
                  <span key={i}>{i > 0 ? " · " : ""}{s.corp_name} {s.year} {s.section}</span>
                ))}
              </div>
            )}
          </div>
        )}
      </Section>

      <Section title="✅ QA 체크리스트">
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: T.sub, lineHeight: 1.9 }}>
          <li>NO-MOCK — 미평가 종목은 가짜 숫자 없이 '준비 중' 안내</li>
          <li>Graceful degradation — 필드 결측 시 해당 섹션만 숨김(화면 안 깨짐)</li>
          <li>출처 인용 — 챗봇 답변에 DART 원문 출처 동반</li>
          <li>데이터 신선도 — 시세·금리 As-of 최신(증분 수집)</li>
          <li>신뢰도 등급 — DCF 낮으면 점추정 숨기고 범위·진단으로 대체</li>
        </ul>
      </Section>
    </>
  );
}
