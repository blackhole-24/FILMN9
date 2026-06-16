'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { ValAdminTab, ValTestTab } from './valuation-console';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

type MainTab = 'monitor' | 'val-admin' | 'verify' | 'val-test';   // 4탭: 기업개요운영·밸류운영·기업개요검증·밸류테스트

const adminToken = () => (typeof window !== 'undefined' ? sessionStorage.getItem('adminToken') || '' : '');

const fetchJSON = (path: string, opt: RequestInit = {}) =>
  fetch(`${API}${path}`, { ...opt, headers: { ...(opt.headers || {}), 'X-Admin-Token': adminToken() } })
    .then((r) => {
      if (r.status === 401) { sessionStorage.removeItem('adminToken'); location.reload(); throw new Error('unauthorized'); }
      return r.json();
    });

// ───────────────────────── (ⓘ) 툴팁 ─────────────────────────
function Info({ text, w = 'w-80' }: { text: string; w?: string }) {
  return (
    <span className="relative inline-flex group align-middle">
      {/* title 속성 = OS 기본 툴팁(커스텀이 안 떠도 무조건 글이 보이도록 이중 보장) */}
      <span title={text} className="ml-1 w-[15px] h-[15px] inline-flex items-center justify-center rounded-full bg-slate-300 text-white text-[10px] font-bold cursor-help leading-none select-none">i</span>
      <span className={`pointer-events-none absolute left-1/2 -translate-x-1/2 top-full mt-1.5 z-50 hidden group-hover:block ${w} max-w-[85vw] bg-slate-900 text-white text-[11px] leading-relaxed rounded-lg px-3 py-2 shadow-xl whitespace-pre-line text-left font-normal`}>
        {text}
      </span>
    </span>
  );
}

function Card({ title, sub, info, children }: { title: string; sub?: string; info?: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
      <div className="flex items-baseline gap-1 mb-3">
        <h3 className="text-sm font-bold text-slate-700">{title}</h3>
        {info && <Info text={info} />}
        {sub && <span className="text-[11px] text-slate-400 ml-1">{sub}</span>}
      </div>
      {children}
    </div>
  );
}

function Bar({ pct }: { pct: number }) {
  const c = pct >= 90 ? 'bg-emerald-500' : pct >= 30 ? 'bg-amber-500' : 'bg-rose-500';
  return (
    <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
      <div className={`h-full ${c} rounded-full`} style={{ width: `${Math.min(100, pct)}%` }} />
    </div>
  );
}

// 테이블별 정체/출처 (DB 현황 행 hover)
const TABLE_DESC: Record<string, string> = {
  company_customers: '주요 고객사·채널 — DART 사업보고서',
  company_info: '기업 기본정보(마스터) — DART 기업개황',
  credit_ratings: '신용등급 — 설계됨·미적재(빈 테이블)',
  dart_halt_events: '거래정지·관리 이벤트 — DART',
  disclosures: '최근 공시 목록 — DART(라이브 일부)',
  executives: '임원현황 — DART 사업보고서',
  financial_detail: '재무 상세(계정 단위) — DART XBRL',
  financials: '재무 요약(연도별) — DART',
  ohlcv: '주가 일봉 OHLCV — yfinance/pykrx',
  peer_competitors: '피어·경쟁사 — 자동 선정',
  shareholders: '주주현황 — DART',
  stock_status: '거래상태 — KRX/DART',
  ticker_suffix: '티커 접미사·시장',
  valuation_summary: '밸류 요약 20종 — DCF 엔진 v8',
  valuations: '밸류 상세 — 설계됨·미적재(빈 테이블)',
  wics_keywords: 'WICS 업종 유사어(검색용)',
};

// 커버리지 파트별 산출 근거
const COV_INFO: Record<string, string> = {
  '기업개요 (company_info)': 'SELECT COUNT(*) FROM company_info\n= 등록된 기업 수. 출처: DART 기업개황. 기준(2,580)보다 많아 100%로 캡.',
  '재무 (financials)': 'COUNT(DISTINCT stock_code) FROM financials\n= 재무요약 보유 종목수. 출처: DART 사업보고서(재무).',
  '주가 (ohlcv)': 'COUNT(DISTINCT stock_code) FROM ohlcv\n= 일봉 보유 종목수. 출처: yfinance/pykrx.',
  '주주 (shareholders)': 'COUNT(DISTINCT stock_code) FROM shareholders\n= 주주현황 보유 종목수. 출처: DART 주주현황.',
  '경영인 (executives)': 'COUNT(DISTINCT stock_code) FROM executives\n= 임원현황 보유 종목수. 출처: DART 임원현황.',
  '밸류 요약 (valuation_summary)': 'COUNT(*) FROM valuation_summary\n= 밸류 산출 완료 종목. 현재 산업 대표 20종만 → 0.8%. 출처: DCF 엔진 v8 → load_valuation_summary.py.',
  '손익흐름도 Sankey (파일)': 'outputs/sankey/*_sankey.html 파일 수(사전생성). 출처: build_sankey_v3.py(Plotly). 종목상세 손익흐름도에 그대로 서빙.',
  '재무제표 연결 (financial_detail·BS)': "COUNT(DISTINCT stock_code) WHERE statement_type='BS' AND scope='연결'\n= 연결 재무상태표 보유 종목. 재무제표 표(BS/IS)·Sankey의 원천. 출처: DART 파싱 financial_detail.",
  'Sankey 완전도 (영업이익 매칭)': "CIS(연결)에서 '영업이익' 포함매칭되는 종목수\n= 손익흐름도가 매출~영업이익까지 완전히 그려질 수 있는 종목. 계정명 정규화(로마숫자 접두사 제거) 후 기준.",
  '계열사 시각화 (샘플)': '계열회사시각화 폴더의 샘플 디렉터리/SVG 수. 현재 GitHub 샘플만(전종목 미수령). 출처: 기업개요_파트/계열회사시각화/.',
};

// ───────────────────────── 탭1 · 운영 모니터링 ─────────────────────────
// ── 기능 모듈 운영 현황 (2026-06-14 고도화) — 서비스 구조대로 원천→화면 + 상태 ──
const ST_STYLE: Record<string, string> = {
  ok: 'bg-emerald-50 border-emerald-200', warn: 'bg-amber-50 border-amber-200',
  down: 'bg-rose-50 border-rose-200', realtime: 'bg-indigo-50 border-indigo-200',
};
const ST_DOT: Record<string, string> = { ok: 'bg-emerald-500', warn: 'bg-amber-500', down: 'bg-rose-500', realtime: 'bg-indigo-500' };
const ST_LABEL: Record<string, string> = { ok: '정상', warn: '부분', down: '점검필요', realtime: '실시간' };

function ModuleOpsCard() {
  const [data, setData] = useState<any>(null);
  useEffect(() => { fetchJSON('/api/admin/modules').then(setData).catch(() => {}); }, []);
  if (!data) return <Card title="🗺️ 기능 모듈 운영 현황"><div className="text-sm text-slate-400 py-4">불러오는 중…</div></Card>;
  return (
    <Card title="🗺️ 기능 모듈 운영 현황" sub="각 기능이 어느 원천→어떻게 화면까지 + 지금 정상 작동 중인지"
      info={'서비스 화면의 각 기능 모듈(재무하이라이트·손익흐름도 등)이 어느 DB/파일에서 나와 어떤 API로 화면까지 오는지와, 지금 데이터를 정상 보유 중인지(실측 종목수)를 보여줍니다. 출처: /api/admin/modules'}>
      {(data.groups || []).map((g: string) => (
        <div key={g} className="mb-3">
          <div className="text-xs font-bold text-slate-500 mb-1.5">{g}</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {(data.modules || []).filter((m: any) => m.group === g).map((m: any) => (
              <div key={m.id} className={`rounded-lg border p-2.5 ${ST_STYLE[m.status] || 'bg-slate-50 border-slate-200'}`}>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-bold text-slate-700">{m.name}</span>
                  <span className="text-[11px] font-bold flex items-center gap-1">
                    <span className={`w-2 h-2 rounded-full ${ST_DOT[m.status] || 'bg-slate-400'}`}></span>
                    {ST_LABEL[m.status] || m.status} {m.count !== '' && <b>{typeof m.count === 'number' ? m.count.toLocaleString() : m.count}{m.unit}</b>}
                  </span>
                </div>
                <div className="text-[11px] text-slate-500 mt-1 leading-relaxed">
                  <b>원천</b> {m.source} <span className="text-slate-300">›</span> <b>저장</b> {m.store}<br/>
                  <span className="font-mono text-[10px] text-blue-600">{m.api}</span> <span className="text-slate-300">·</span> {m.auto}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </Card>
  );
}

function QADashboardCard() {
  const [res, setRes] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const run = () => { setRunning(true); fetchJSON('/api/admin/qa/run').then(setRes).finally(() => setRunning(false)); };
  useEffect(() => { run(); }, []);
  const pct = res ? Math.round(res.passed / res.total * 100) : 0;
  return (
    <Card title="🧪 QA 테스트 대시보드" sub="핵심 기능 모듈 데이터 정량 테스트"
      info={'전수 데이터의 핵심 조건(분석가능 종목수·재무 3년·손익흐름도·이상치 0 등)을 자동 테스트해 통과/실패를 집계합니다. 출처: /api/admin/qa/run'}>
      <div className="flex items-center gap-3 mb-3">
        <button onClick={run} disabled={running} className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white disabled:opacity-50">{running ? '실행 중…' : '▶ 테스트 실행'}</button>
        {res && <span className="text-sm font-bold">{res.passed}/{res.total} 통과 <span className={pct === 100 ? 'text-emerald-600' : 'text-amber-600'}>({pct}%)</span></span>}
      </div>
      {res && (
        <div className="space-y-1">
          {res.tests.map((t: any, i: number) => (
            <div key={i} className={`flex items-center justify-between rounded-lg px-3 py-2 text-sm border ${t.pass ? 'bg-emerald-50 border-emerald-200' : 'bg-rose-50 border-rose-200'}`}>
              <span className="flex items-center gap-2">{t.pass ? '✅' : '❌'} {t.test}</span>
              <span className="text-xs text-slate-500 font-mono">{t.detail}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function DataMgmtCard() {
  const [d, setD] = useState<any>(null);
  useEffect(() => { fetchJSON('/api/admin/data-management').then(setD).catch(() => {}); }, []);
  if (!d) return null;
  return (
    <Card title="🗃️ 데이터 관리 (신선도·갱신 시점)" sub="각 데이터가 언제 기준·어디서·자동/수동 갱신인지"
      info={'사업보고서 등 원천 데이터의 최신 기준시점, 출처, 갱신 자동화 여부를 보여줍니다. 출처: /api/admin/data-management'}>
      <div className="overflow-x-auto"><table className="w-full text-xs">
        <thead><tr className="border-b border-slate-100 text-slate-400"><th className="text-left py-1.5">데이터</th><th className="text-left">기준 시점</th><th className="text-left">출처</th><th className="text-left">갱신</th></tr></thead>
        <tbody>{(d.items || []).map((it: any, i: number) => (
          <tr key={i} className="border-b border-slate-50"><td className="py-1.5 font-semibold text-slate-700">{it.name}</td><td className="text-slate-600">{it['기준']}</td><td className="text-slate-500">{it['출처']}</td><td className={it['자동화'].includes('✅') ? 'text-emerald-600 font-semibold' : 'text-slate-500'}>{it['자동화']}</td></tr>
        ))}</tbody></table></div>
      <div className="text-[11px] text-amber-600 mt-2">{d.note}</div>
    </Card>
  );
}

function AwsCostCard() {
  const [d, setD] = useState<any>(null);
  useEffect(() => { fetchJSON('/api/admin/aws-cost').then(setD).catch(() => {}); }, []);
  if (!d) return null;
  return (
    <Card title="☁️ AWS 비용·리소스" sub="배포 인프라 사용량·요금"
      info={'AWS Cost Explorer + 리소스 스냅샷. 로컬 _aws_cost_snapshot.py로 생성. 출처: /api/admin/aws-cost'}>
      {d.available === false ? <div className="text-sm text-slate-400 py-2">{d.note}</div> : (
        <div>
          <div className="flex gap-3 flex-wrap mb-2">
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2"><div className="text-[11px] text-slate-500">{d.month} 비용</div><div className="text-xl font-extrabold text-emerald-600">${d.cost_usd}</div></div>
            {Object.entries(d.resources || {}).map(([k, v]: any) => (
              <div key={k} className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2"><div className="text-[11px] text-slate-500">{k}</div><div className="text-lg font-bold text-slate-700">{v}</div></div>
            ))}
          </div>
          <div className="text-[11px] text-slate-500">{d.note} <span className="text-slate-400">· 스냅샷 {d.generated_at}</span></div>
        </div>
      )}
    </Card>
  );
}

function MonitorTab() {
  const [health, setHealth] = useState<any>(null);
  const [db, setDb] = useState<any>(null);
  const [fresh, setFresh] = useState<any>(null);
  const [cov, setCov] = useState<any>(null);
  const [smoke, setSmoke] = useState<any>(null);
  const [msg, setMsg] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      fetchJSON('/api/admin/health').then(setHealth),
      fetchJSON('/api/admin/db-stats').then(setDb),
      fetchJSON('/api/admin/freshness').then(setFresh),
      fetchJSON('/api/admin/coverage').then(setCov),
      fetchJSON('/api/admin/smoke').then(setSmoke),
    ]).finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const refreshCache = () => {
    setMsg('갱신 중…');
    fetchJSON('/api/admin/cache/refresh', { method: 'POST' })
      .then((d) => setMsg(d.msg || '완료'))
      .catch(() => setMsg('실패'));
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <span className="text-xs text-slate-400">
          {loading ? '불러오는 중…' : '실시간 점검'}
          <Info w="w-72" text="이 탭의 모든 값은 새로고침 시점에 실제 data/filmn9.db·파일시스템·TCP포트를 직접 조회한 실측값입니다(Mock 없음). 출처: backend/routers/admin.py" />
        </span>
        <button onClick={load} className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 text-white hover:bg-slate-700">↻ 새로고침</button>
      </div>

      {/* 기능 모듈 운영 현황 + QA + 데이터관리 + AWS비용 (2026-06-14~15 고도화) */}
      <ModuleOpsCard />
      <QADashboardCard />
      <DataMgmtCard />
      <AwsCostCard />

      {/* 서버 생존 */}
      <Card title="🖥️ 서비스 생존 (Liveness)" sub="포트 연결 + 응답시간"
        info={'각 서버의 TCP 포트가 열려있는지(생존)와 연결 응답시간(ms)을 측정합니다.\n방식: socket.create_connection(127.0.0.1, 포트) 성공 여부.\n※ 깊은 헬스체크(내부 DB연결 등)가 아니라 "포트 Liveness 체크"입니다.\n출처: admin.py _port_up()'}>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {(health?.servers || []).map((s: any) => (
            <div key={s.port} className={`rounded-lg p-3 border ${s.up ? 'border-emerald-200 bg-emerald-50' : 'border-rose-200 bg-rose-50'}`}>
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-700 flex items-center">
                  {s.name}
                  <Info w="w-72" text={
                    s.port === 8090 ? '백엔드(FastAPI) — 지금 이 API를 응답 중인 서버 자신(self)이라 항상 UP, 0ms.'
                    : s.port === 3000 ? '프론트엔드(Next.js dev) — 127.0.0.1:3000 TCP 연결 성공 여부 + 왕복 ms.'
                    : 'AI 챗봇(RAG, 별도 MSA) — 127.0.0.1:8800 TCP 연결. 포트 생존만 확인(13GB 모델 로딩 완료까지는 별도).'} />
                </span>
                <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${s.up ? 'bg-emerald-500 text-white' : 'bg-rose-500 text-white'}`}>{s.up ? 'UP' : 'DOWN'}</span>
              </div>
              <div className="text-xs text-slate-500 mt-1 font-mono">:{s.port} {s.ms != null ? `· ${s.ms}ms` : ''}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* 커버리지 */}
      <Card title="📊 종목 커버리지" sub={`기준 ${cov?.base_universe?.toLocaleString?.() || '—'}종목 대비`}
        info={'기준 종목수(2,580 = 산업분류 WICS 활성 종목, 동결 기준) 대비 각 파트가 데이터를 보유한 종목 수와 비율입니다.\n계산: pct = min(보유수, 2,580) / 2,580 × 100.\n출처: 각 테이블 COUNT(DISTINCT stock_code) 또는 파일 수.\n초록 ≥90% · 노랑 ≥30% · 빨강 <30%.'}>
        <div className="space-y-2">
          {(cov?.rows || []).map((r: any) => (
            <div key={r.part} className="flex items-center gap-3 text-sm">
              <span className="w-56 truncate text-slate-600 flex items-center">{r.part}{COV_INFO[r.part] && <Info text={COV_INFO[r.part]} />}</span>
              <Bar pct={r.pct} />
              <span className="w-28 text-right font-mono text-xs text-slate-500">{r.count?.toLocaleString()} ({r.pct}%)</span>
            </div>
          ))}
        </div>
        <div className="text-[11px] text-slate-400 mt-2">※ %가 100%여도 일부 종목은 결측 가능(분모=기준 2,580). 밸류·계열사가 낮은 건 사전계산/샘플만 적용됐기 때문(정상).</div>
        {cov?.sankey_meta && (
          <div className="mt-3 p-3 rounded-lg bg-indigo-50 border border-indigo-100 text-[11px] text-slate-600 space-y-0.5">
            <div className="font-bold text-indigo-700 mb-1">📐 손익흐름도(Sankey) 데이터 흐름 · 원천</div>
            <div>· <b>원천</b>: {cov.sankey_meta['원천']}</div>
            <div>· <b>추출값(10계정)</b>: {cov.sankey_meta['추출값']}</div>
            <div>· <b>생성방식</b>: {cov.sankey_meta['생성방식']}</div>
            <div>· <b>저장위치</b>: {cov.sankey_meta['저장위치']}</div>
            {cov['재무하이라이트_원천'] && <div className="mt-1 pt-1 border-t border-indigo-100">· <b>재무하이라이트 원천</b>: {cov['재무하이라이트_원천']}</div>}
          </div>
        )}
      </Card>

      <div className="grid md:grid-cols-2 gap-4">
        {/* DB 현황 */}
        <Card title="🗄️ DB 현황" sub={`${db?.table_count || 0}개 테이블 · 총 ${db?.total_rows?.toLocaleString?.() || 0}행`}
          info={'data/filmn9.db(SQLite)의 16개 테이블 각각의 행수입니다.\nSQL: SELECT COUNT(*) FROM <table> (테이블 목록은 sqlite_master에서 동적 조회).\n빈 테이블(0행)은 빨강 — 스키마는 있으나 미적재(NO-MOCK상 가짜로 채우지 않음).\n총행수는 ohlcv(주가 일봉, 종목×일자)가 대부분을 차지.'}>
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-[10px] text-slate-400 border-b"><th className="text-left py-1">테이블</th><th className="text-right py-1">행수</th><th className="text-left py-1 pl-3">정체 · 원천 출처</th></tr></thead>
              <tbody>
                {(db?.tables || []).map((t: any) => (
                  <tr key={t.table} className={`border-b border-slate-100 ${t.rows === 0 ? 'bg-rose-50' : ''}`}>
                    <td className="py-1.5 font-mono text-slate-600 align-top">{t.table}{t.rows === 0 && <span className="ml-1 text-[10px] text-rose-500">(빈)</span>}</td>
                    <td className="py-1.5 text-right font-mono align-top whitespace-nowrap">{t.rows < 0 ? '—' : t.rows.toLocaleString()}</td>
                    <td className="py-1.5 pl-3 text-[11px] text-slate-500 align-top">{TABLE_DESC[t.table] || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {db?.empty?.length > 0 && <div className="text-[11px] text-rose-500 mt-2">⚠️ 빈 테이블: {db.empty.join(', ')} — 스키마는 있으나 미적재(NO-MOCK상 가짜로 안 채움)</div>}
        </Card>

        {/* 신선도 + 스모크 + 유지보수 */}
        <div className="space-y-4">
          <Card title="⏱️ 데이터 신선도 (Freshness)" sub="원천별 최신 갱신 시각"
            info={'각 데이터 원천이 "가장 최근 언제 갱신됐는지"입니다(데이터 신선도).\n오래되면 갱신이 필요하다는 운영 신호.\n계산: 해당 테이블의 날짜/적재 컬럼 MAX() (주가=MAX(date), 재무·공시=MAX(loaded_at), 밸류=MAX(as_of_date)), Sankey=파일 최신 수정시각.'}>
            <div className="space-y-1.5">
              {(fresh?.items || []).map((it: any, i: number) => (
                <div key={i} className="flex justify-between text-sm">
                  <span className="text-slate-600 truncate mr-2 flex items-center">{it.source}
                    <Info w="w-72" text={
                      it.source.includes('OHLCV') ? 'ohlcv의 MAX(date) = 가장 최근 거래일 데이터. 매 거래일 16:00 작업스케줄러 자동 동기화(yfinance 1순위·pykrx 2순위).'
                      : it.source.includes('financials') ? 'financials의 MAX(loaded_at) = 마지막 적재 시각. 사업보고서 시즌 갱신. 출처 DART.'
                      : it.source.includes('disclosures') ? 'disclosures의 MAX(loaded_at) = 공시 마지막 적재. 출처 DART.'
                      : it.source.includes('valuation') ? 'valuation_summary의 MAX(as_of_date) = 밸류 평가 기준일. 출처 DCF 엔진 v8.'
                      : 'outputs/sankey 파일의 최신 수정시각 + 개수(사전배치). 출처 build_sankey_v3.py.'} />
                  </span>
                  <span className="font-mono text-xs text-slate-500 whitespace-nowrap">{it.latest || '—'} <span className="text-slate-300">· {it.kind}</span></span>
                </div>
              ))}
            </div>
          </Card>

          <Card title="🔎 스모크 테스트" sub="샘플 종목 핵심 데이터"
            info={'샘플 4종목(삼성전자·현대건설·삼성물산·NAVER)에 대해 종목상세가 정상 동작할 핵심 데이터를 즉석 조회합니다.\n검사: company_info·financials·ohlcv 존재(SQL EXISTS) + Sankey 파일 존재.\n실제 서비스 종목상세 화면이 깨지지 않을지 미리 점검(작동확인).\n출처: filmn9.db + outputs/sankey.'}>
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-2xl font-extrabold ${smoke?.fail ? 'text-rose-500' : 'text-emerald-500'}`}>{smoke?.ok ?? '—'}</span>
              <span className="text-sm text-slate-400">/ {(smoke?.ok ?? 0) + (smoke?.fail ?? 0)} 통과</span>
              <Info w="w-72" text="통과 = 해당 종목이 company_info·financials·ohlcv를 모두 보유 → 종목상세 정상. 칩의 ms는 4개 항목 조회에 걸린 시간." />
            </div>
            <div className="flex flex-wrap gap-1">
              {(smoke?.checks || []).map((c: any) => (
                <span key={c.code} className="relative inline-flex group">
                  <span className={`text-[11px] px-2 py-1 rounded font-mono cursor-pointer ${c.ok ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'}`}>{c.code} {c.ok ? '✓' : '✗'}{c.ms != null ? ` ${c.ms}ms` : ''}</span>
                  <span className="pointer-events-none absolute left-0 top-full mt-1 z-50 hidden group-hover:block w-64 bg-slate-900 text-white text-[11px] leading-relaxed rounded-lg px-3 py-2 shadow-xl whitespace-pre-line">{`기업개요:${c.detail?.company_info ? '있음' : '없음'} · 재무:${c.detail?.financials ? '있음' : '없음'} · 주가:${c.detail?.ohlcv ? '있음' : '없음'} · Sankey파일:${c.detail?.sankey_file ? '있음' : '없음'}\n조회 ${c.ms}ms · 출처 filmn9.db + outputs/sankey`}</span>
                </span>
              ))}
            </div>
          </Card>

          <Card title="🛠️ 유지보수">
            <button onClick={refreshCache} className="text-xs px-3 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700">📡 모닝 위젯 캐시 강제 갱신</button>
            <Info w="w-72" text="홈 화면 '글로벌 마켓 시그널' 위젯의 15분 캐시를 즉시 다시 채웁니다(prewarm). 실행: morning.py warm_cache() → yfinance 23지표 재수집. 멱등(여러 번 눌러도 안전)." />
            {msg && <span className="text-xs text-slate-500 ml-2">{msg}</span>}
          </Card>
        </div>
      </div>
    </div>
  );
}

// ───────────────────────── 탭2 · 신뢰도 검증 ─────────────────────────
const PARTS = [
  { key: 'financials', label: '재무 항등식 (자산=부채+자본)' },
  { key: 'ohlcv', label: '주가 OHLC 유효성' },
  { key: 'company_info', label: '기업개요 완전성' },
  { key: 'valuation', label: '밸류 정합성 (상승여력)' },
];
const PART_INFO: Record<string, string> = {
  financials: '회계 항등식 「자산총계 = 부채총계 + 자본총계」 성립 여부를 검사(허용오차 0.5%).\n대상: financials의 최신 연도 assets/liabilities/equity.\n불일치 = 재무 파싱/적재 오류 의심. 출처: DART 사업보고서.',
  ohlcv: '주가 일봉의 가격 논리 무결성 검사: low ≤ open,close ≤ high, high ≥ low, volume ≥ 0.\n대상: ohlcv 최신 1행. 출처: yfinance/pykrx.',
  company_info: '기업개요 핵심필드(corp_name·market·sector) 결측 여부.\n대상: company_info. 화면 종목상세 헤더/분류에 직접 쓰임. 출처: DART 기업개황.',
  valuation: '화면에 표시되는 상승여력 upside_pct 가 (적정가−현재가)/현재가×100 과 일치하는지(±1%p).\n대상: valuation_summary. 출처: DCF 엔진 v8.',
};

function InternalResult({ res }: { res: any }) {
  if (!res || res.error) return res?.error ? <div className="text-rose-500 text-sm">{res.error}</div> : null;
  const rate = res.error_rate ?? 0;
  const ok = rate === 0;
  return (
    <Card title={`📋 검증 결과 ${res.scope === 'full' ? '(전수)' : '(샘플)'}`} sub={res.method}>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
        <div className="rounded-lg p-3 bg-slate-50 text-center"><div className="text-xs text-slate-400 flex items-center justify-center">검사<Info w="w-60" text="실제로 값을 비교한 종목 수(데이터 없는 종목 제외)." /></div><div className="text-2xl font-extrabold font-mono">{res.checked?.toLocaleString()}</div></div>
        <div className="rounded-lg p-3 bg-emerald-50 text-center"><div className="text-xs text-emerald-500 flex items-center justify-center">통과<Info w="w-60" text="기준(항등식·유효성·완전성·계산식) 만족 = 검사−불일치." /></div><div className="text-2xl font-extrabold font-mono text-emerald-600">{res.pass?.toLocaleString()}</div></div>
        <div className="rounded-lg p-3 bg-rose-50 text-center"><div className="text-xs text-rose-500 flex items-center justify-center">불일치<Info w="w-60" text="기준 위반 종목 수. 아래 표에 종목·항목·DB값·기대값." /></div><div className="text-2xl font-extrabold font-mono text-rose-600">{res.fail?.toLocaleString()}</div></div>
        <div className={`rounded-lg p-3 text-center ${ok ? 'bg-emerald-50' : 'bg-rose-50'}`}><div className="text-xs text-slate-400 flex items-center justify-center">오류율<Info w="w-60" text="불일치 ÷ 검사 × 100 (%). 0%면 NO-MOCK 일치." /></div><div className={`text-2xl font-extrabold font-mono ${ok ? 'text-emerald-600' : 'text-rose-600'}`}>{rate}%</div></div>
      </div>
      <div className={`text-sm font-bold mb-3 ${ok ? 'text-emerald-600' : 'text-rose-600'}`}>{ok ? '✅ ' : '⚠️ '}{res.verdict}</div>
      {res.failures?.length > 0 && (
        <div className="max-h-64 overflow-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-xs text-slate-400 border-b"><th className="text-left py-1">종목</th><th className="text-left py-1">항목</th><th className="text-right py-1">DB값</th><th className="text-right py-1">기대값</th></tr></thead>
            <tbody>
              {res.failures.map((f: any, i: number) => (
                <tr key={i} className="border-b border-slate-100">
                  <td className="py-1.5 font-mono">{f.code}</td>
                  <td className="py-1.5 text-rose-600">{f.field}</td>
                  <td className="py-1.5 text-right font-mono">{typeof f.db === 'object' ? '…' : (f.db?.toLocaleString?.() ?? f.db ?? '—')}</td>
                  <td className="py-1.5 text-right font-mono">{f.expected?.toLocaleString?.() ?? f.expected ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function VerifyTab() {
  // A. 내부 정합성
  const [part, setPart] = useState('financials');
  const [n, setN] = useState(10);
  const [res, setRes] = useState<any>(null);
  const [running, setRunning] = useState<'' | 'sample' | 'full'>('');
  const runInternal = (full: boolean) => {
    setRunning(full ? 'full' : 'sample'); setRes(null);
    fetchJSON(full ? '/api/admin/verify/full' : '/api/admin/verify/sample', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(full ? { part } : { part, n }),
    }).then(setRes).catch(() => setRes({ error: '검증 실패' })).finally(() => setRunning(''));
  };

  // B. DART 원문 대조
  const [dart, setDart] = useState<any>(null);
  const [dartRun, setDartRun] = useState<'' | 'sample' | 'full'>('');
  const runDart = (full: boolean) => {
    setDartRun(full ? 'full' : 'sample'); setDart(null);
    fetchJSON('/api/admin/verify/dart', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ n: 40, full }),
    }).then(setDart).catch(() => setDart({ error: '대조 실패' })).finally(() => setDartRun(''));
  };

  // C. 히스토리브리핑 / D. 챗봇 / E. 계열사 (자동 로드)
  const [brief, setBrief] = useState<any>(null);
  const [chatbot, setChatbot] = useState<any>(null);
  const [affil, setAffil] = useState<any>(null);
  useEffect(() => {
    fetchJSON('/api/admin/verify/briefing').then(setBrief).catch(() => setBrief({ available: false }));
    fetchJSON('/api/admin/verify/affiliate').then(setAffil).catch(() => setAffil({ error: true }));
    fetchJSON('/api/admin/verify/chatbot').then(setChatbot).catch(() => setChatbot({ available: false, server_up: false, msg: '조회 실패' }));
  }, []);

  return (
    <div className="space-y-4">
      {/* A. 내부 정합성 */}
      <Card title="① 내부 정합성 검증" sub="NO-MOCK · DB 값 자체 검사"
        info={'화면에 쓰는 DB 값이 논리적으로 맞는지(항등식·유효성·완전성·계산식) 검사합니다.\n샘플=무작위 N개(즉시), 전수=전 종목 배치.\n출처: data/filmn9.db. 실측(가짜 점수 아님).'}>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-[11px] text-slate-400 mb-1 flex items-center">검증 파트<Info w="w-80" text={PART_INFO[part]} /></label>
            <select value={part} onChange={(e) => setPart(e.target.value)} className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white">
              {PARTS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] text-slate-400 mb-1 flex items-center">표본 수 (N)<Info w="w-64" text="샘플 검증 시 무작위로 뽑을 종목 수(1~50)." /></label>
            <input type="number" min={1} max={50} value={n} onChange={(e) => setN(Number(e.target.value))} className="w-20 text-sm border border-slate-200 rounded-lg px-3 py-2" />
          </div>
          <button onClick={() => runInternal(false)} disabled={!!running} className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-bold hover:bg-emerald-700 disabled:opacity-50">{running === 'sample' ? '검증 중…' : '샘플 검증'}</button>
          <button onClick={() => runInternal(true)} disabled={!!running} className="px-4 py-2 rounded-lg bg-slate-800 text-white text-sm font-bold hover:bg-slate-700 disabled:opacity-50">{running === 'full' ? '전수 검증 중…' : '전수 검증'}</button>
        </div>
      </Card>
      <InternalResult res={res} />

      {/* B. DART 원문 대조 */}
      <Card title="② DART 원문 대조" sub="요약 재무 ↔ XBRL 상세"
        info={'우리가 화면에 쓰는 요약 재무(financials)가 DART 사업보고서 XBRL을 직접 파싱한 상세(financial_detail)와 일치하는지 대조합니다.\n대상 항목: 자산·부채·자본총계 + 매출·영업이익·당기순이익(연결 우선).\n단위(백만원↔원) 차이는 자동 보정, ±1% 이내면 일치.\n불일치=파싱/집계 오류 의심(예: 삼천당제약 IS 오염).'}>
        <div className="flex gap-2">
          <button onClick={() => runDart(false)} disabled={!!dartRun} className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-bold hover:bg-indigo-700 disabled:opacity-50">{dartRun === 'sample' ? '대조 중…' : '원문 대조 (샘플 40)'}</button>
          <button onClick={() => runDart(true)} disabled={!!dartRun} className="px-4 py-2 rounded-lg bg-slate-800 text-white text-sm font-bold hover:bg-slate-700 disabled:opacity-50">{dartRun === 'full' ? '전수 대조 중…' : '전수 대조'}</button>
        </div>
      </Card>
      {dart && !dart.error && (
        <Card title={`📑 원문 대조 결과 ${dart.scope === 'full' ? '(전수)' : '(샘플)'}`} sub={dart.method}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
            <div className="rounded-lg p-3 bg-slate-50 text-center"><div className="text-xs text-slate-400">대조 항목</div><div className="text-2xl font-extrabold font-mono">{dart.compared?.toLocaleString()}</div></div>
            <div className="rounded-lg p-3 bg-emerald-50 text-center"><div className="text-xs text-emerald-500">일치</div><div className="text-2xl font-extrabold font-mono text-emerald-600">{dart.matched?.toLocaleString()}</div></div>
            <div className="rounded-lg p-3 bg-rose-50 text-center"><div className="text-xs text-rose-500">불일치</div><div className="text-2xl font-extrabold font-mono text-rose-600">{dart.mismatch?.toLocaleString()}</div></div>
            <div className={`rounded-lg p-3 text-center ${dart.mismatch === 0 ? 'bg-emerald-50' : 'bg-amber-50'}`}><div className="text-xs text-slate-400">일치율</div><div className={`text-2xl font-extrabold font-mono ${dart.mismatch === 0 ? 'text-emerald-600' : 'text-amber-600'}`}>{dart.match_rate}%</div></div>
          </div>
          <div className="flex flex-wrap gap-1 mb-3">
            {Object.entries(dart.field_stat || {}).map(([f, st]: any) => (
              <span key={f} className="text-[11px] px-2 py-1 rounded bg-slate-100 text-slate-600 font-mono">{f}: <span className="text-emerald-600">{st.match}✓</span>{st.mismatch ? <span className="text-rose-600"> {st.mismatch}✗</span> : null}{st.no_src ? <span className="text-slate-400"> {st.no_src}·원문없음</span> : null}</span>
            ))}
          </div>
          <div className={`text-sm font-bold mb-2 ${dart.mismatch === 0 ? 'text-emerald-600' : 'text-amber-600'}`}>{dart.mismatch === 0 ? '✅ ' : '⚠️ '}{dart.verdict}</div>
          {dart.mismatches?.length > 0 && (
            <div className="max-h-64 overflow-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-xs text-slate-400 border-b"><th className="text-left py-1">종목</th><th className="text-left py-1">항목</th><th className="text-right py-1">요약(financials)</th><th className="text-right py-1">DART상세</th><th className="text-right py-1">범위</th></tr></thead>
                <tbody>
                  {dart.mismatches.map((m: any, i: number) => (
                    <tr key={i} className="border-b border-slate-100">
                      <td className="py-1.5 font-mono">{m.code}</td>
                      <td className="py-1.5 text-rose-600">{m.field}</td>
                      <td className="py-1.5 text-right font-mono">{Math.round(m.summary).toLocaleString()}</td>
                      <td className="py-1.5 text-right font-mono">{Math.round(m.dart).toLocaleString()}</td>
                      <td className="py-1.5 text-right text-slate-400">{m.scope}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
      {dart?.error && <div className="text-rose-500 text-sm">{dart.error}</div>}

      {/* C. 히스토리브리핑 신뢰도 */}
      <Card title="③ 히스토리브리핑 신뢰도" sub="evaluate.py 4-Phase 평가 연동"
        info={'AI가 생성한 기업 스토리(히스토리 브리핑)의 품질 평가 결과를 연동 표시합니다.\n평가: ①수치 정확성 ②인용 정합 ③RAGAS ④LLM Judge → 100점 채점.\n출처: 통합산출물/result_report.md (배치 평가 결과). 실시간 재평가(유료 LLM)는 별도.'}>
        {brief?.available ? (
          <div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="rounded-lg p-3 bg-slate-50 text-center"><div className="text-xs text-slate-400">평가 종목</div><div className="text-2xl font-extrabold font-mono">{brief.count}</div></div>
              <div className={`rounded-lg p-3 text-center ${brief.pass ? 'bg-emerald-50' : 'bg-amber-50'}`}><div className="text-xs text-slate-400">평균 점수</div><div className={`text-2xl font-extrabold font-mono ${brief.pass ? 'text-emerald-600' : 'text-amber-600'}`}>{brief.avg_score}</div></div>
              <div className="rounded-lg p-3 bg-emerald-50 text-center"><div className="text-xs text-emerald-500">high(85+)</div><div className="text-2xl font-extrabold font-mono text-emerald-600">{brief.grades?.high ?? '—'}%</div></div>
              <div className="rounded-lg p-3 bg-amber-50 text-center"><div className="text-xs text-amber-500">low(&lt;70)</div><div className="text-2xl font-extrabold font-mono text-amber-600">{brief.grades?.low ?? '—'}%</div></div>
            </div>
            <div className="text-[11px] text-slate-500 mt-2">채점: {brief.method}</div>
            <div className="text-[11px] text-slate-400 mt-1">기준: {brief.threshold} · {brief.pass ? '✅ 통과' : '⚠️ 미달'} · 등급분포 high {brief.grades?.high}% / medium {brief.grades?.medium}% / low {brief.grades?.low}%</div>
            <div className="text-[11px] text-slate-400 mt-1">{brief.note}</div>
          </div>
        ) : (
          <div className="text-sm text-slate-400">{brief?.msg || '브리핑 평가 리포트를 불러오는 중…'}</div>
        )}
      </Card>

      {/* D. AI 챗봇 검증 */}
      <Card title="④ AI 챗봇 검증 (RAG)" sub="지식베이스·서버 (무료)"
        info={'AI 챗봇(RAG)의 준비 상태를 점검합니다(질의 안 함=무료).\n· 챗봇 서버(8800) 생존 · ChromaDB 임베딩 청크 수(사업보고서 지식베이스) · 임베딩 디바이스/모델.\n라이브 RAGAS(faithfulness)는 질의당 유료 LLM 필요 → 사전승인 후 별도 배치.'}>
        {chatbot == null ? <div className="text-sm text-slate-400">불러오는 중…</div>
          : (!chatbot.server_up || chatbot.msg) ? <div className="text-sm text-amber-600">⚠️ {chatbot.msg || 'AI 챗봇 서버(8800) DOWN'}</div>
            : (
              <div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="rounded-lg p-3 bg-emerald-50 text-center"><div className="text-xs text-emerald-500">챗봇 서버(8800)</div><div className="text-xl font-extrabold text-emerald-600">UP</div></div>
                  <div className="rounded-lg p-3 bg-slate-50 text-center"><div className="text-xs text-slate-400">RAG 청크</div><div className="text-xl font-extrabold font-mono">{chatbot.chunks?.toLocaleString?.() ?? '—'}</div></div>
                  <div className="rounded-lg p-3 bg-slate-50 text-center"><div className="text-xs text-slate-400">디바이스</div><div className="text-base font-bold mt-1">{chatbot.device?.device ?? '—'}</div></div>
                  <div className="rounded-lg p-3 bg-slate-50 text-center"><div className="text-xs text-slate-400">임베딩 모델</div><div className="text-[11px] font-mono mt-1.5">{chatbot.device?.model ?? '—'}</div></div>
                </div>
                <div className="text-[11px] text-slate-500 mt-2">{chatbot.method}</div>
                <div className="text-[11px] text-amber-600 mt-1">💸 {chatbot.ragas_note}</div>
              </div>
            )}
      </Card>

      {/* E. 계열사 검증 */}
      <Card title="⑤ 계열사 검증" sub="시각화 파일 커버리지·무결성"
        info={'계열회사 시각화 파일(소유지분도/구조도 SVG)의 커버리지·무결성(크기>0·SVG 루트태그)을 점검합니다.\n원천=DART 사업보고서 계열회사. 현재 GitHub 샘플만(전종목은 드라이브 수령 후) → 낮은 커버리지는 정상.'}>
        {affil == null ? <div className="text-sm text-slate-400">불러오는 중…</div>
          : affil.error ? <div className="text-rose-500 text-sm">조회 실패</div>
            : (
              <div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="rounded-lg p-3 bg-slate-50 text-center"><div className="text-xs text-slate-400">보유 종목</div><div className="text-2xl font-extrabold font-mono">{affil.available_count}</div></div>
                  <div className="rounded-lg p-3 bg-emerald-50 text-center"><div className="text-xs text-emerald-500">무결성 정상</div><div className="text-2xl font-extrabold font-mono text-emerald-600">{affil.valid}</div></div>
                  <div className={`rounded-lg p-3 text-center ${affil.broken?.length ? 'bg-rose-50' : 'bg-slate-50'}`}><div className="text-xs text-slate-400">손상</div><div className={`text-2xl font-extrabold font-mono ${affil.broken?.length ? 'text-rose-600' : ''}`}>{affil.broken?.length ?? 0}</div></div>
                  <div className="rounded-lg p-3 bg-slate-50 text-center"><div className="text-xs text-slate-400">커버리지</div><div className="text-2xl font-extrabold font-mono">{affil.coverage_pct}%</div></div>
                </div>
                <div className="text-[11px] text-slate-500 mt-2">{affil.verdict} · 샘플: <span className="font-mono">{affil.samples?.join(', ')}</span></div>
                <div className="text-[11px] text-slate-400 mt-1">{affil.note}</div>
              </div>
            )}
      </Card>

      <div className="text-[11px] text-slate-400 leading-relaxed">
        ※ ①내부 정합성(DB 논리) · ②DART 원문 대조(요약↔XBRL) · ③브리핑(LLM 평가) · ④AI 챗봇(RAG 지식베이스) · ⑤계열사(파일 무결성) — 5개 파트 검증.
        라이브 RAGAS·전수 LLM 재평가는 유료라 사전승인 후 별도 배치.
      </div>
    </div>
  );
}

// ───────────────────────── 로그인 게이트 ─────────────────────────
function AdminLogin({ onOk }: { onOk: () => void }) {
  const [pw, setPw] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setErr('');
    try {
      const r = await fetch(`${API}/api/admin/health`, { headers: { 'X-Admin-Token': pw } });
      if (r.ok) { sessionStorage.setItem('adminToken', pw); onOk(); }
      else setErr('비밀번호가 올바르지 않습니다');
    } catch { setErr('서버에 연결할 수 없습니다'); }
    setBusy(false);
  };
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-8 w-[340px]">
        <div className="text-xl font-extrabold text-indigo-600 mb-1">FINSIGHT 관리자</div>
        <div className="text-xs text-slate-400 mb-5">접근하려면 관리자 비밀번호를 입력하세요</div>
        <input type="password" value={pw} onChange={(e) => setPw(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()} placeholder="비밀번호" autoFocus
          className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm mb-2 outline-none focus:border-indigo-500" />
        {err && <div className="text-xs text-rose-500 mb-2">{err}</div>}
        <button onClick={submit} disabled={busy}
          className="w-full bg-indigo-600 text-white rounded-lg py-2 text-sm font-bold disabled:opacity-50">
          {busy ? '확인 중…' : '입장'}
        </button>
      </div>
    </div>
  );
}

// ───────────────────────── 페이지 ─────────────────────────
export default function AdminPage() {
  const [tab, setTab] = useState<MainTab>('monitor');
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    const t = typeof window !== 'undefined' ? sessionStorage.getItem('adminToken') : '';
    if (!t) { setChecking(false); return; }
    fetch(`${API}/api/admin/health`, { headers: { 'X-Admin-Token': t } })
      .then((r) => { if (r.ok) setAuthed(true); else sessionStorage.removeItem('adminToken'); })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);
  if (checking) return <div className="min-h-screen bg-slate-50 flex items-center justify-center text-slate-400 text-sm">확인 중…</div>;
  if (!authed) return <AdminLogin onOk={() => setAuthed(true)} />;
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-4">
          <Link href="/" className="text-xl font-extrabold text-indigo-600">FINSIGHT</Link>
          <span className="text-slate-300">|</span>
          <span className="text-sm font-bold text-slate-700 flex items-center">관리자<Info w="w-80" text="FINSIGHT 내부 운영 도구. 모든 값은 실시간으로 실제 DB·파일·포트를 조회한 실측값(NO-MOCK). 각 항목의 ⓘ에 계산식·출처가 있습니다." /></span>
          <span className="ml-auto text-[11px] text-slate-400">기업개요·밸류 운영/검증 통합 콘솔 (4탭)</span>
        </div>
        <div className="max-w-6xl mx-auto px-4 flex gap-1 h-11 items-stretch overflow-x-auto">
          <button onClick={() => setTab('monitor')} className={`px-4 text-sm whitespace-nowrap border-b-2 ${tab === 'monitor' ? 'border-indigo-600 text-indigo-600 font-bold' : 'border-transparent text-slate-500'}`}>🖥️ 기업개요 · 운영</button>
          <button onClick={() => setTab('verify')} className={`px-4 text-sm whitespace-nowrap border-b-2 ${tab === 'verify' ? 'border-emerald-600 text-emerald-600 font-bold' : 'border-transparent text-slate-500'}`}>✅ 기업개요 · 검증</button>
          <button onClick={() => setTab('val-admin')} className={`px-4 text-sm whitespace-nowrap border-b-2 ${tab === 'val-admin' ? 'border-amber-500 text-amber-600 font-bold' : 'border-transparent text-slate-500'}`}>💰 밸류에이션 · 운영</button>
          <button onClick={() => setTab('val-test')} className={`px-4 text-sm whitespace-nowrap border-b-2 ${tab === 'val-test' ? 'border-amber-500 text-amber-600 font-bold' : 'border-transparent text-slate-500'}`}>🧪 밸류에이션 · 테스트</button>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-5">
        {tab === 'monitor' && <MonitorTab />}
        {tab === 'val-admin' && <ValAdminTab />}
        {tab === 'verify' && <VerifyTab />}
        {tab === 'val-test' && <ValTestTab />}
      </main>
      <footer className="text-center py-6 text-[11px] text-slate-400">FINSIGHT 관리자 · NO-MOCK 운영 도구 · <span className="tracking-widest">FILMN9 Inc.</span></footer>
    </div>
  );
}
