"use client";

import * as React from "react";

/* ────────────────────────────────────────────────────────────────────────
   밸류에이션 · AI 챗봇 — 관리자/QA 콘솔 (밸류에이션 파트 파트, 통합본)
   출처: feat/admin-qa-console 브랜치 frontend/app/admin/page.tsx (커밋 8918cac)
   통합 변경점(최소):
     1) 단일 페이지(2탭) → ValAdminTab / ValTestTab 컴포넌트로 분리 export
        (기업개요 관리자 페이지의 4탭 구조에 끼움)
     2) 밸류 QA: /api/valuation/{code}가 구 6파일 포맷(summary 없음)이면
        /api/valuation-full/{code}(엔진 v8 통합 JSON)로 자동 폴백
     3) is_mock 판정: === false → !== true (통합 JSON에 is_mock 필드 없음 호환)
   디자인(다크 테마)·문구·하네스 내용은 원본 그대로 보존.
   ──────────────────────────────────────────────────────────────────────── */

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8090";
const CHAT_API = process.env.NEXT_PUBLIC_CHAT_API_URL || "http://localhost:8800";

// ── 테마 ──────────────────────────────────────────────────────────────────
const T = {
  bg: "#0F172A", panel: "#1E293B", card: "#0F172A", border: "#334155",
  accent: "#FCD34D", text: "#E2E8F0", sub: "#94A3B8", mono: "'JetBrains Mono', ui-monospace, monospace",
  blue: "#93C5FD", green: "#22C55E", red: "#F87171", amber: "#FCD34D", pink: "#F472A4",
};

type TagKind = "sqlite" | "chroma" | "dart" | "openai" | "ecos" | "kofia" | "krx" | "gpu" | "ok" | "warn" | "err";
const TAG: Record<TagKind, { bg: string; fg: string }> = {
  sqlite: { bg: "#1E40AF", fg: "#BFDBFE" }, chroma: { bg: "#581C87", fg: "#E9D5FF" },
  dart: { bg: "#78350F", fg: "#FED7AA" }, openai: { bg: "#831843", fg: "#FBCFE8" },
  ecos: { bg: "#134E4A", fg: "#99F6E4" }, kofia: { bg: "#1E3A5F", fg: "#BAE6FD" },
  krx: { bg: "#3730A3", fg: "#C7D2FE" }, gpu: { bg: "#4C1D95", fg: "#DDD6FE" },
  ok: { bg: "#14532D", fg: "#BBF7D0" }, warn: { bg: "#713F12", fg: "#FDE68A" }, err: { bg: "#7F1D1D", fg: "#FECACA" },
};
function Tag({ k, children }: { k: TagKind; children: React.ReactNode }) {
  return <span style={{ fontFamily: T.mono, padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 700, background: TAG[k].bg, color: TAG[k].fg, whiteSpace: "nowrap" }}>{children}</span>;
}
function VCard({ title, right, children }: { title?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, padding: "14px 16px", marginBottom: 10 }}>
      {title && <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: "#F1F5F9" }}>{title}</div>{right}</div>}
      {children}
    </div>
  );
}
function Section({ id, title, children }: { id?: string; title: React.ReactNode; children: React.ReactNode }) {
  return (
    <section id={id} style={{ background: T.panel, border: `2px solid ${T.border}`, borderRadius: 12, padding: 20, marginBottom: 20 }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: T.accent, marginBottom: 14, borderBottom: `2px solid #475569`, paddingBottom: 8 }}>{title}</div>
      {children}
    </section>
  );
}
function KV({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: "4px 10px", fontSize: 12.5, padding: "3px 0" }}>
      <div style={{ color: T.sub, fontWeight: 700 }}>{k}</div>
      <div style={{ color: T.text }}>{children}</div>
    </div>
  );
}
const mono = (v: React.ReactNode) => <span style={{ fontFamily: T.mono, fontSize: 11.5, color: T.accent }}>{v}</span>;

// 타임아웃 가능한 fetch
async function tfetch(url: string, opts: RequestInit = {}, ms = 6000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  // 관리자 인증 토큰 주입(/api/admin/* 보호용, 다른 엔드포인트엔 무해)
  const tok = typeof window !== 'undefined' ? sessionStorage.getItem('adminToken') || '' : '';
  try { const r = await fetch(url, { ...opts, signal: ctl.signal, headers: { ...(opts.headers || {}), 'X-Admin-Token': tok } }); return await r.json(); }
  finally { clearTimeout(t); }
}

// ── 정적 데이터: 출처 / 하네스 ────────────────────────────────────────────
const SOURCES: { k: TagKind; name: string; desc: string }[] = [
  { k: "dart", name: "DART (금융감독원)", desc: "사업보고서 XBRL 재무 · 신용등급/주식수 원문 · 공시·임원·주주" },
  { k: "krx", name: "KRX (한국거래소)", desc: "주가·시가총액·상장정보 (peer β 회귀, 시총 E)" },
  { k: "ecos", name: "ECOS (한국은행)", desc: "무위험수익률 Rf — 국고채 10년" },
  { k: "kofia", name: "KOFIA (금융투자협회)", desc: "회사채 시가평가수익률 → Kd" },
  { k: "openai", name: "한공회 / Damodaran", desc: "SRP(규모위험프리미엄) 가이던스 · 산업 무차입베타 βU 교차검증" },
  { k: "openai", name: "OpenAI gpt-5.4-mini", desc: "신용등급·주식수 RAG 추출 · 챗봇 질문분석/답변생성" },
  { k: "gpu", name: "BAAI/bge-m3 + reranker-v2-m3", desc: "임베딩(1024d) + cross-encoder 리랭킹 (로컬 GPU)" },
  { k: "chroma", name: "Chroma 벡터DB", desc: "사업보고서 청크 임베딩 (annual_reports)" },
];

const HARNESS_POINTS = [
  { area: "밸류에이션", items: ["① 신용등급 추출 (사업보고서 RAG → Kd)", "② 자기주식수 추출 (시가총액 E)", "③ 피어 사업유사도 (임베딩)"] },
  { area: "AI 챗봇", items: ["① 질문 분석·회사 해석 (LLM)", "② 멀티쿼리·HyDE 가상답변 (LLM)", "③ 답변 생성 (LLM)", "④ 임베딩·리랭킹 (로컬 GPU, 비-LLM)"] },
];
const HARNESS_DEV = [
  ["실데이터 100% (NO-MOCK)", "데이터 없으면 임의값 금지 → RuntimeError/'미평가'. AI가 빈칸을 지어내지 못하게 강제."],
  ["추출·판단 분리", "LLM은 '사실 추출만'(예: 모든 신용등급 이력+평가일 나열). 최신 선택 등 결정은 결정론적 Python(_pick_latest 날짜정렬)이 담당."],
  ["구조화 출력 + 원문 인용", "등급/주식수는 JSON 스키마 강제 + 근거 원문 인용 요구. 형식 위반 시 재시도."],
  ["RAG 그라운딩 + 출처 강제", "챗봇 답변은 검색된 DART 청크에만 근거, 출처카드(원문 링크) 동반 → 환각 검증 가능."],
  ["저온도 (temperature 0.1)", "사실 재현성↑, 창의적 일탈↓."],
  ["검색 정밀도 하네스", "하이브리드(BM25+벡터) RRF · cross-encoder 리랭킹 · 재무제표 라우팅(FINSTMT) · stub 강등 → 정확한 근거 청크 확보."],
  ["신뢰도 등급화", "밸류 DCF 등급 A~E·피어 신뢰도 → 불확실하면 점추정 숨김(과신·앵커링 방지). 챗봇 빈응답 medium 폴백."],
  ["평가 하네스(eval)", "골든셋(층화표본) + 4-phase 품질평가로 프롬프트 변경 회귀 점검."],
];
const HARNESS_USER = [
  ["출처 투명성", "모든 답변·수치에 출처/근거를 함께 표시."],
  ["한계 고지", "'참고용·투자권유 아님' + 미래예측 불확실성 명시."],
  ["NO-MOCK UX", "미평가 종목은 가짜 숫자 대신 '준비 중' 안내."],
  ["용어 친절화", "어려운 용어 ⓘ 설명 · '쉽게 말하면' 평문 요약."],
];
const HARNESS_IMPROVE = [
  "① 근거기반 거부(grounded refusal): 검색 신뢰도 임계 미달 시 '자료 없음'으로 답변 거부 → 환각 원천 차단.",
  "② 클레임 단위 인용 + 사후 검증기(verifier)로 인용↔답변 정합성 자동 점검.",
  "③ 구조화 출력(JSON schema/function calling) 전면 적용 + 스키마 검증 자동 재시도.",
  "④ 적대적 자기검증(self-critique)·2nd-pass 사실확인으로 단정 오류 감소.",
  "⑤ 프롬프트 버전관리 + 골든셋 회귀 CI(A/B) — 프롬프트 변경의 품질영향 추적.",
  "⑥ reasoning_effort 동적화: 질문 난이도/유형별 effort·쿼리수 조절 → 속도·비용 최적화.",
  "⑦ 비용·지연 텔레메트리: 질의당 토큰/원/지연 기록·상한.",
  "⑧ 범위 가드레일: 투자권유·주가예측·개인정보 등 범위 외 질문 거부 정책.",
  "⑨ 프롬프트 인젝션·PII 방어: 사용자/문서 입력의 명령 주입 차단.",
];

// ── 공용 데이터 훅 (meta + 헬스) ─────────────────────────────────────────
function useConsoleData() {
  const [meta, setMeta] = React.useState<any>(null);
  const [beHealth, setBeHealth] = React.useState<any>(null);
  const [cbHealth, setCbHealth] = React.useState<any>(null);
  const [cbErr, setCbErr] = React.useState<string>("");
  React.useEffect(() => {
    tfetch(`${API}/api/admin/meta`).then(setMeta).catch(() => setMeta({ _error: true }));
    tfetch(`${API}/health`).then(setBeHealth).catch(() => setBeHealth({ status: "down" }));
    tfetch(`${CHAT_API}/health`, {}, 60000).then(setCbHealth).catch((e) => { setCbHealth({ status: "down" }); setCbErr(String(e).slice(0, 40)); });
  }, []);
  return { meta, beHealth, cbHealth, cbErr };
}

// 다크 컨테이너 (밸류에이션 파트 페이지 톤 보존)
function Dark({ subtitle, children }: { subtitle: string; children: React.ReactNode }) {
  return (
    <div style={{ background: T.bg, color: T.text, fontFamily: "'Noto Sans KR', sans-serif", padding: "20px 22px", borderRadius: 14 }}>
      <p style={{ color: T.sub, fontSize: 12.5, margin: "0 0 14px" }}>{subtitle}</p>
      {children}
      <div style={{ textAlign: "center", marginTop: 8, paddingTop: 12, borderTop: `1px dashed #475569`, color: "#64748B", fontSize: 11 }}>
        밸류에이션 · AI 챗봇 파트(밸류에이션 파트) · NO-MOCK(실데이터 100%) 원칙 · 평가위원 검토용
      </div>
    </div>
  );
}

// ════════════ 탭: 밸류·챗봇 관리자 (평가위원 검토용) ════════════
export function ValAdminTab() {
  const { meta, cbHealth } = useConsoleData();
  const v = meta?.valuation || {};
  const co = meta?.company || {};
  const cbChunks = cbHealth?.db?.total_chunks;
  const cbDevice = cbHealth?.device?.device;
  const cbGpu = cbHealth?.device?.gpu_name;
  const dash = (x: any) => (x === null || x === undefined ? "—" : x);
  const pct = (x: any) => (typeof x === "number" ? (x * 100).toFixed(3) + "%" : "—");
  return (
    <Dark subtitle={`밸류에이션 · AI 챗봇 — 데이터 기준일 / 출처 / 테스트 환경 / AI 하네스 · 포트 3000·8090·8800 · 생성 ${meta?.generated_at || "…"}`}>
      <Section title="① 데이터 기준일 (평가에 사용된 데이터의 As-of)">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 10 }}>
          <VCard title={<>💰 밸류에이션 <Tag k="sqlite">valuation.db</Tag></>}>
            <KV k="평가 기준일">{mono(dash(v.latest_eval_date))} <span style={{ color: T.sub }}>(평가일 {dash(v.n_eval_dates)}종)</span></KV>
            <KV k="모델 버전">{mono(dash(v.model_version))} <span style={{ color: T.sub }}>(DCF+EPV+멀티플)</span></KV>
            <KV k="XBRL 재무연도">{mono(`FY${dash(v.xbrl_years?.[0])}~${dash(v.xbrl_years?.[1])}`)}</KV>
            <KV k="무위험금리 Rf"><Tag k="ecos">ECOS</Tag> {mono(dash(v.rf?.rate_date))} · {pct(v.rf?.rf)}</KV>
            <KV k="회사채(Kd)"><Tag k="kofia">KOFIA</Tag> {mono(dash(v.kofia_latest))}</KV>
            <KV k="시총(KRX)"><Tag k="krx">KRX</Tag> {mono(dash(v.market_snapshot_latest))}</KV>
            <KV k="평가 종목수">{mono(`${dash(v.n_stocks)} 종목 / ${dash(v.n_runs)} runs`)}</KV>
            {!v.db_exists && (
              <div style={{ marginTop: 6, fontSize: 11.5, color: T.amber, background: "#312E81", borderLeft: `3px solid ${T.accent}`, padding: "6px 10px", borderRadius: "0 4px 4px 0" }}>
                ※ valuation.db 미배치 — 밸류 파트에서 수령 후 data/valuation.db 에 두면 실데이터로 채워짐 (NO-MOCK: 그 전까지 — 표시)
              </div>
            )}
          </VCard>
          <VCard title={<>📋 기업개요 <Tag k="sqlite">filmn9.db</Tag></>}>
            <KV k="주가(OHLCV)">{mono(dash(co.ohlcv_latest))} <span style={{ color: T.sub }}>({dash(co.ohlcv_rows?.toLocaleString?.() ?? co.ohlcv_rows)}행)</span></KV>
            <KV k="재무연도">{mono(`FY${dash(co.fiscal_years?.[0])}~${dash(co.fiscal_years?.[1])}`)}</KV>
            <KV k="기업정보">{mono(`${dash(co.company_info)} 종목`)}</KV>
            <KV k="재무상세(BS/IS)">{mono(`${dash(co.financial_detail_stocks)} 종목 / ${dash(co.financial_detail_rows?.toLocaleString?.() ?? co.financial_detail_rows)}행`)}</KV>
          </VCard>
          <VCard title={<>🤖 AI 챗봇 <Tag k="chroma">Chroma</Tag></>}>
            <KV k="임베딩 청크">{mono(cbChunks ? cbChunks.toLocaleString() + " 청크" : "조회중/지연")}</KV>
            <KV k="임베딩 모델">{mono("BAAI/bge-m3 (1024d)")}</KV>
            <KV k="리랭커">{mono("bge-reranker-v2-m3")}</KV>
            <KV k="디바이스"><Tag k="gpu">{cbDevice || "GPU"}</Tag> {cbGpu || "RTX 4060"}</KV>
            <KV k="원천 기준">{mono("DART 2025 사업보고서 + 2026 1Q")}</KV>
            <KV k="생성 LLM"><Tag k="openai">gpt-5.4-mini</Tag></KV>
          </VCard>
        </div>
      </Section>

      <Section title="② 데이터 출처 (Source)">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(330px, 1fr))", gap: 10 }}>
          {SOURCES.map((s, i) => (
            <VCard key={i}><div style={{ display: "flex", gap: 8, alignItems: "baseline" }}><Tag k={s.k}>SRC</Tag>
              <div><div style={{ fontWeight: 700, color: "#F1F5F9", fontSize: 13.5 }}>{s.name}</div>
                <div style={{ color: T.sub, fontSize: 12, marginTop: 2 }}>{s.desc}</div></div></div></VCard>
          ))}
        </div>
      </Section>

      <Section title="③ 테스트 환경 (Test Environment)">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 10 }}>
          <VCard title="💰 밸류에이션 엔진">
            <KV k="엔진/방식">{mono("v8")} · Forward DCF + EPV + Reverse DCF + 멀티플 + 시나리오</KV>
            <KV k="이론">CAPM·Hamada·Blume·Gordon·Greenwald(EPV)·Damodaran</KV>
            <KV k="진입점">{mono("GET /api/valuation/{code}")} ← valuation.db 통합 JSON</KV>
            <KV k="신뢰도">DCF 등급 A~E · 피어셋 신뢰도 · 점추정 숨김 정책</KV>
            <KV k="원칙"><Tag k="ok">NO-MOCK</Tag> 실데이터만, 미평가는 '준비 중'</KV>
          </VCard>
          <VCard title="🤖 RAG 챗봇 파이프라인">
            <KV k="검색">질문분석 → 멀티쿼리·HyDE·온톨로지 → 하이브리드(BM25+BGE-M3) → RRF</KV>
            <KV k="정밀화">cross-encoder 리랭킹 → 재무제표 라우팅(FINSTMT) → stub 강등</KV>
            <KV k="생성"><Tag k="openai">gpt-5.4-mini</Tag> SSE 스트리밍 + 출처카드(DART)</KV>
            <KV k="서버">{mono("Port 8800")} 독립 마이크로서비스 (GPU·30GB 벡터)</KV>
            <KV k="비용">질의당 ~₩5 (임베딩·리랭킹은 로컬 GPU 무료)</KV>
          </VCard>
          <VCard title="🖥 시스템">
            <KV k="구성">{mono("Next.js :3000")} + {mono("FastAPI :8090")} + {mono("Chatbot :8800")}</KV>
            <KV k="DB">SQLite(valuation.db·filmn9.db) · Chroma(벡터) · (MongoDB→파일폴백)</KV>
            <KV k="런타임">conda dart-rag · GPU RTX 4060 (CUDA)</KV>
          </VCard>
        </div>
      </Section>

      <Section title="④ AI 하네스 (AI 통제 원칙) — 개발자·사용자 관점">
        <VCard title="🎯 AI 사용 지점">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(320px,1fr))", gap: 10 }}>
            {HARNESS_POINTS.map((p) => (
              <div key={p.area} style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 6, padding: "10px 12px" }}>
                <div style={{ color: T.accent, fontWeight: 700, fontSize: 13, marginBottom: 6 }}>{p.area}</div>
                {p.items.map((it, i) => <div key={i} style={{ fontSize: 12.5, color: T.text, padding: "2px 0" }}>{it}</div>)}
              </div>
            ))}
          </div>
        </VCard>
        <VCard title="🛡 현재 하네스 통제 (개발자 관점)">
          {HARNESS_DEV.map(([t, d], i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "190px 1fr", gap: 10, padding: "6px 0", borderBottom: i < HARNESS_DEV.length - 1 ? `1px solid ${T.border}` : "none" }}>
              <div style={{ color: T.green, fontWeight: 700, fontSize: 12.5 }}>{t}</div>
              <div style={{ color: T.text, fontSize: 12.5 }}>{d}</div>
            </div>
          ))}
        </VCard>
        <VCard title="👤 사용자 관점 통제">
          {HARNESS_USER.map(([t, d], i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "190px 1fr", gap: 10, padding: "6px 0", borderBottom: i < HARNESS_USER.length - 1 ? `1px solid ${T.border}` : "none" }}>
              <div style={{ color: T.blue, fontWeight: 700, fontSize: 12.5 }}>{t}</div>
              <div style={{ color: T.text, fontSize: 12.5 }}>{d}</div>
            </div>
          ))}
        </VCard>
        <VCard title="🚀 더 나은 하네스 조절 제안 (개선안)">
          {HARNESS_IMPROVE.map((s, i) => (
            <div key={i} style={{ fontSize: 12.5, color: "#FDE68A", padding: "4px 0", lineHeight: 1.6 }}>{s}</div>
          ))}
        </VCard>
      </Section>
    </Dark>
  );
}

// ════════════ 탭: 밸류·챗봇 테스트(QA) ════════════
function HealthBadge({ ok, label, detail }: { ok: boolean | null; label: string; detail?: string }) {
  const c = ok === null ? T.sub : ok ? T.green : T.red;
  return (
    <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, padding: "12px 14px", minWidth: 180 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 10, height: 10, borderRadius: "50%", background: c, display: "inline-block" }} />
        <span style={{ fontWeight: 700, color: "#F1F5F9" }}>{label}</span>
      </div>
      <div style={{ color: T.sub, fontSize: 11.5, marginTop: 4 }}>{ok === null ? "확인 중…" : ok ? "정상" : "응답 없음"}{detail ? ` · ${detail}` : ""}</div>
    </div>
  );
}

export function ValTestTab() {
  const { meta, beHealth, cbHealth, cbErr } = useConsoleData();
  const v = meta?.valuation || {};
  const [code, setCode] = React.useState("009150");
  const [valRes, setValRes] = React.useState<any>(null);
  const [valLoading, setValLoading] = React.useState(false);
  const [q, setQ] = React.useState("주요 사업 부문과 대표 제품은?");
  const [chat, setChat] = React.useState<any>(null);
  const [chatLoading, setChatLoading] = React.useState(false);

  const runVal = async () => {
    setValLoading(true); setValRes(null);
    try {
      let d = await tfetch(`${API}/api/valuation/${code.trim()}`, {}, 15000);
      // 구 6파일 포맷(summary 없음)이면 엔진 v8 통합 JSON으로 폴백
      if (d && !d.summary && !d._error) {
        try {
          const full = await tfetch(`${API}/api/valuation-full/${code.trim()}`, {}, 15000);
          if (full && full.summary) d = { ...full, _endpoint: "valuation-full(통합 JSON 폴백)" };
        } catch { /* 폴백 실패 시 원 응답 유지 */ }
      }
      setValRes(d);
    }
    catch (e) { setValRes({ _error: String(e).slice(0, 80) }); }
    finally { setValLoading(false); }
  };
  const runChat = async () => {
    setChatLoading(true); setChat(null);
    try {
      const r = await fetch(`${CHAT_API}/chat`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: q, ticker: code.trim(), current_year: 2026 }) });
      setChat(await r.json());
    } catch (e) { setChat({ _error: String(e).slice(0, 120) }); }
    finally { setChatLoading(false); }
  };

  // 밸류 QA 판정 (is_mock 은 명시적 true 만 미평가로 간주 — 통합 JSON 호환)
  const checks = valRes && !valRes._error ? [
    ["실데이터(is_mock≠true)", valRes.is_mock !== true],
    ["summary 존재", !!valRes.summary],
    ["valuation_diagnostics 존재", !!valRes.valuation_diagnostics && Object.keys(valRes.valuation_diagnostics).length > 0],
    ["scenarios 존재", !!valRes.scenarios && Object.keys(valRes.scenarios).length > 0],
    ["wacc_breakdown 존재", Array.isArray(valRes.wacc_breakdown) && valRes.wacc_breakdown.length > 0],
  ] : [];

  return (
    <Dark subtitle="QA 관점 서비스 검증 — 시스템 헬스 / 밸류 실측 판정 5종 / 챗봇 RAG 실측 / 체크리스트">
      <Section title="시스템 상태 (Health)">
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <HealthBadge ok={beHealth ? beHealth.status === "ok" : null} label="백엔드 :8090" detail={beHealth?.parsed_codes != null ? `parsed ${beHealth.parsed_codes}` : ""} />
          <HealthBadge ok={cbHealth ? cbHealth.status === "ok" : null} label="챗봇 :8800"
            detail={cbHealth?.db?.total_chunks ? `${cbHealth.db.total_chunks.toLocaleString()} 청크` : (cbErr || "지연 가능")} />
          <HealthBadge ok={true} label="프론트 :3000" detail="이 페이지" />
        </div>
        <div style={{ marginTop: 8, fontSize: 11.5, color: T.sub }}>밸류 평가 종목수 {v?.n_stocks ?? "—"} · 기준일 {v?.latest_eval_date ?? "—"}</div>
      </Section>

      <Section title="🧪 밸류에이션 QA (종목 실측)">
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="종목코드 (예: 009150)"
            style={{ padding: "9px 12px", borderRadius: 8, border: `1px solid ${T.border}`, background: T.card, color: T.text, width: 200, fontFamily: T.mono }} />
          <button onClick={runVal} disabled={valLoading}
            style={{ padding: "9px 18px", borderRadius: 8, border: "none", background: T.accent, color: T.bg, fontWeight: 700, cursor: "pointer" }}>
            {valLoading ? "조회 중…" : "밸류 검증"}</button>
          <span style={{ color: T.sub, fontSize: 12, alignSelf: "center" }}>대표 20종: 009150 · 035420 · 034020 · 000660 등 (그 외는 '준비중' 정상)</span>
        </div>
        {valRes?._error && <VCard><span style={{ color: T.red }}>오류: {valRes._error}</span></VCard>}
        {valRes && !valRes._error && (
          <VCard title={<>결과 · {valRes.company?.name || valRes.summary?.corp_name || code} {valRes.is_mock === true ? <Tag k="warn">미평가(준비중)</Tag> : <Tag k="ok">실데이터</Tag>} {valRes._endpoint ? <Tag k="warn">{valRes._endpoint}</Tag> : null}</>}>
            {valRes.is_mock === true ? <div style={{ color: T.amber, fontSize: 13 }}>이 종목은 아직 평가 전 → NO-MOCK 정책상 가짜 숫자 미표시 (정상 동작)</div> : (
              <>
                <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginBottom: 10, fontSize: 13 }}>
                  <span>적정주가 <b style={{ color: T.accent }}>{valRes.summary?.fair_price != null ? "₩" + Math.round(valRes.summary.fair_price).toLocaleString() : "범위만"}</b></span>
                  <span>현재가 <b>₩{Math.round(valRes.summary?.current_price || 0).toLocaleString()}</b></span>
                  <span>WACC <b>{((valRes.summary?.wacc || 0) * 100).toFixed(2)}%</b></span>
                  <span>등급 <b style={{ color: T.accent }}>{valRes.summary?.dcf_grade || "—"}</b></span>
                  <span>EPV <b>{valRes.valuation_diagnostics?.epv_price != null ? "₩" + Math.round(valRes.valuation_diagnostics.epv_price).toLocaleString() : "—"}</b></span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 6 }}>
                  {checks.map(([label, ok], i) => (
                    <div key={i} style={{ fontSize: 12.5 }}>
                      <span style={{ color: ok ? T.green : T.red, fontWeight: 700 }}>{ok ? "✓" : "✗"}</span> <span style={{ color: T.text }}>{label as string}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </VCard>
        )}
      </Section>

      <Section title="🤖 챗봇 QA (RAG 실측)">
        <div style={{ fontSize: 12, color: T.amber, marginBottom: 8 }}>
          ⚠️ 현재 설정(reasoning='high' + 멀티쿼리)은 정확도↑·속도↓ — 첫 질의는 수십초~수분 소요될 수 있습니다. 💸 질의당 ~₩5(유료 LLM).
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="질문"
            style={{ padding: "9px 12px", borderRadius: 8, border: `1px solid ${T.border}`, background: T.card, color: T.text, flex: 1, minWidth: 260 }} />
          <button onClick={runChat} disabled={chatLoading}
            style={{ padding: "9px 18px", borderRadius: 8, border: "none", background: chatLoading ? T.sub : T.accent, color: T.bg, fontWeight: 700, cursor: "pointer" }}>
            {chatLoading ? "질의 중… (느림)" : `질의 (${code})`}</button>
        </div>
        {chat?._error && <VCard><span style={{ color: T.red }}>오류: {chat._error}</span></VCard>}
        {chat && !chat._error && (
          <VCard title={<>답변 {Array.isArray(chat.sources) ? <Tag k="ok">출처 {chat.sources.length}건</Tag> : null}</>}>
            <div style={{ fontSize: 13, lineHeight: 1.7, whiteSpace: "pre-wrap", color: T.text }}>{(chat.answer || "(빈 응답)").slice(0, 1200)}</div>
            {Array.isArray(chat.sources) && chat.sources.length > 0 && (
              <div style={{ marginTop: 10, borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
                {chat.sources.slice(0, 4).map((s: any, i: number) => (
                  <div key={i} style={{ fontSize: 11.5, color: T.sub, padding: "2px 0" }}>
                    <Tag k="dart">출처</Tag> {String(s.corp_name || s.title || "").slice(0, 24)} · {String(s.report_nm || s.section_path || s.section || "").slice(0, 50)}
                  </div>
                ))}
              </div>
            )}
          </VCard>
        )}
      </Section>

      <Section title="✅ QA 체크리스트 (평가 기준)">
        {[
          "NO-MOCK: 미평가/무데이터는 가짜 숫자 대신 '준비 중' 표시되는가",
          "Graceful degradation: 일부 필드(EPV·시나리오) 누락 시 해당 섹션만 숨고 화면이 깨지지 않는가",
          "출처 인용: 챗봇 답변에 DART 원문 출처가 동반되는가",
          "데이터 신선도: 평가 기준일·주가일이 최신 영업일 기준인가 (관리자 탭 ① 참조)",
          "신뢰도 표기: DCF 등급 A~E·피어 신뢰도가 표시되고, 낮으면 점추정을 숨기는가",
        ].map((t, i) => (
          <div key={i} style={{ fontSize: 12.5, color: T.text, padding: "4px 0" }}>
            <span style={{ color: T.accent }}>▢</span> {t}
          </div>
        ))}
      </Section>
    </Dark>
  );
}
