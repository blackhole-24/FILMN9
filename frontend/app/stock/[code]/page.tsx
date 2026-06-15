'use client';

import { useParams } from 'next/navigation';
import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts';
import { Skeleton } from '@/components/ui/skeleton';

// 캔들스틱 차트 — SSR 비활성화 (lightweight-charts는 window 필요)
const CandlestickChart = dynamic(() => import('@/components/candlestick-chart'), { ssr: false });
const FullChart = dynamic(() => import('@/components/full-chart'), { ssr: false });

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const CHAT_API = process.env.NEXT_PUBLIC_CHAT_API_URL || 'http://localhost:8800';  // RAG 챗봇 서버

// ─── 색상·상수 ────────────────────────────────────────────────────
const DONUT_COLORS = ['#6366F1', '#3B82F6', '#10B981', '#8B5CF6', '#F59E0B', '#6B7280'];
const BRAND = '#6366F1';
const GRADE_TO_NUM: Record<string, number> = {
  'AAA':10,'AA+':9,'AA':8,'AA-':7,'A+':6,'A':5,'A-':4,'BBB+':3,'BBB':2,'BBB-':1
};
const NUM_TO_GRADE = Object.fromEntries(Object.entries(GRADE_TO_NUM).map(([k,v])=>[v,k]));

// ─── 유틸 ─────────────────────────────────────────────────────────
/** 백만원 단위 입력 → 조/억/만 문자열 (재무제표 수치용) */
function fmtAmt(v: number|null|undefined): string {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return (v/1_000_000).toFixed(2)+'조';  // 1조 = 1,000,000백만
  if (abs >= 100)       return (v/100).toFixed(0)+'억';         // 1억 = 100백만
  return v.toLocaleString()+'백만';
}
/** 원(won) 단위 입력 → 조/억 문자열 (yfinance market_cap / 주가×주식수 등) */
function fmtWon(v: number|null|undefined): string {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e12) return (v/1e12).toFixed(2)+'조';
  if (abs >= 1e8)  return (v/1e8).toFixed(0)+'억';
  return v.toLocaleString();
}
function fmtPrice(v: number|null|undefined): string {
  return v != null ? '₩'+v.toLocaleString() : '—';
}
function yoyColor(v: number|null): string {
  if (v == null) return 'text-slate-400';
  return v >= 0 ? 'text-red-500' : 'text-blue-500';
}
function yoyText(v: number|null): string {
  if (v == null) return '';
  return (v>=0?'+':'')+v.toFixed(1)+'%';
}

// ─── Mock 밸류에이션 데이터 ──────────────────────────────────────
const _sens = (base: number, w0: number, g0: number, wR: number[], gR: number[]) =>
  wR.map(w => gR.map(g => Math.round(base * (w0 - g0) / (w - g) / 1000) * 1000));

const MOCK_VAL: Record<string, any> = {
  '090430': {
    equityValueLabel: '₩11.7조',
    fairPrices: { bear: 142000, base: 199800, bull: 251000 },
    upsides:    { bear: '+9.7%', base: '+54.4%', bull: '+93.9%' },
    dcfYears: ['2025E','2026E','2027E','2028E','2029E'],
    dcfRows: [
      { label:'매출액 (억원)',    values:[34800,37200,39600,42100,44700], bold:true },
      { label:'성장률 (%)',       values:[2.1,6.9,6.5,6.3,6.2],          fmt:'pct' },
      { label:'EBIT (억원)',      values:[1980,2380,2780,3120,3450] },
      { label:'EBIT Margin (%)',  values:[5.7,6.4,7.0,7.4,7.7],          fmt:'pct' },
      { label:'NOPAT (억원)',     values:[1544,1856,2168,2434,2691] },
      { label:'D&A (억원)',       values:[1450,1520,1590,1660,1730] },
      { label:'CapEx (억원)',     values:[-1200,-1280,-1350,-1410,-1470] },
      { label:'ΔNWC (억원)',      values:[-420,-310,-280,-250,-220] },
      { label:'FCFF (억원)',      values:[1374,1786,2128,2434,2731], bold:true },
      { label:'할인계수',         values:[0.924,0.854,0.789,0.729,0.673], fmt:'decimal3' },
      { label:'PV of FCFF (억원)',values:[1270,1526,1679,1774,1838], bold:true },
    ],
    dcfSummary: { pvFCFF:8087, pvTerminalValue:27700, enterpriseValue:35800, netDebt:4500, equityValue:31300, shares:1566 },
    wacc: { rf:3.5, beta:0.85, erp:5.0, ke:7.8, kd:4.2, tax:22.0, eWeight:75, dWeight:25, wacc:8.2, terminalG:2.0 },
    multiples: [
      { metric:'EV/EBITDA',  peerAvg:'12.3x', implied:'₩213,000', impliedAmt:213000, current:'9.2x',  premium:'+63.8%' },
      { metric:'P/E (NTM)',  peerAvg:'22.4x', implied:'₩196,000', impliedAmt:196000, current:'18.3x', premium:'+50.8%' },
      { metric:'P/B',        peerAvg:'2.8x',  implied:'₩187,000', impliedAmt:187000, current:'2.3x',  premium:'+43.8%' },
      { metric:'EV/Revenue', peerAvg:'1.9x',  implied:'₩208,000', impliedAmt:208000, current:'1.5x',  premium:'+60.0%' },
    ],
    sensitivityWacc:[7.2,7.7,8.2,8.7,9.2], sensitivityG:[1.0,1.5,2.0,2.5,3.0],
    sensitivityPrices: _sens(199800,8.2,2.0,[7.2,7.7,8.2,8.7,9.2],[1.0,1.5,2.0,2.5,3.0]),
    tornado: [
      { variable:'WACC (±1%)',           low:-28400, high:33600 },
      { variable:'터미널 성장률 (±0.5%)', low:-18200, high:22100 },
      { variable:'매출 성장률 (±5%)',     low:-15300, high:17800 },
      { variable:'EBIT 마진 (±2%)',       low:-12400, high:14200 },
      { variable:'베타 (±0.2)',           low:-9800,  high:10500 },
      { variable:'D&A (±10%)',            low:-4200,  high:4600  },
      { variable:'CapEx (±10%)',          low:-3800,  high:4100  },
      { variable:'ΔNWC (±10%)',           low:-2100,  high:2300  },
    ],
    peers: [
      { name:'아모레퍼시픽', ticker:'090430', beta:0.85, evEbitda:'9.2x',  pe:'18.3x', pb:'2.3x', roe:'8.4%',  isSelf:true },
      { name:'LG생활건강',   ticker:'051900', beta:0.72, evEbitda:'8.4x',  pe:'16.2x', pb:'1.9x', roe:'11.2%' },
      { name:'코스맥스',     ticker:'192820', beta:0.91, evEbitda:'13.8x', pe:'24.6x', pb:'3.4x', roe:'14.8%' },
      { name:'한국콜마',     ticker:'161890', beta:0.88, evEbitda:'11.2x', pe:'20.1x', pb:'2.8x', roe:'13.9%' },
      { name:'Shiseido',     ticker:'4911.T', beta:0.79, evEbitda:'14.1x', pe:'25.3x', pb:'2.6x', roe:'10.4%' },
      { name:'Estée Lauder', ticker:'EL',     beta:1.12, evEbitda:'15.6x', pe:'28.4x', pb:'4.2x', roe:'18.3%' },
    ],
  },
  '009150': {
    equityValueLabel: '₩15.2조',
    fairPrices: { bear: 162000, base: 220000, bull: 285000 },
    upsides:    { bear: '+9.5%', base: '+48.6%', bull: '+92.6%' },
    dcfYears: ['2025E','2026E','2027E','2028E','2029E'],
    dcfRows: [
      { label:'매출액 (억원)',    values:[92800,98100,104000,110200,116800], bold:true },
      { label:'성장률 (%)',       values:[1.9,5.7,6.0,6.0,5.9],             fmt:'pct' },
      { label:'EBIT (억원)',      values:[4640,5390,6240,7160,8170] },
      { label:'EBIT Margin (%)',  values:[5.0,5.5,6.0,6.5,7.0],             fmt:'pct' },
      { label:'NOPAT (억원)',     values:[3619,4204,4867,5585,6373] },
      { label:'D&A (억원)',       values:[4200,4400,4600,4800,5000] },
      { label:'CapEx (억원)',     values:[-5100,-5400,-5700,-6000,-6300] },
      { label:'ΔNWC (억원)',      values:[-800,-650,-600,-550,-500] },
      { label:'FCFF (억원)',      values:[1919,2554,3167,3835,4573], bold:true },
      { label:'할인계수',         values:[0.917,0.840,0.770,0.706,0.647], fmt:'decimal3' },
      { label:'PV of FCFF (억원)',values:[1759,2145,2439,2707,2959], bold:true },
    ],
    dcfSummary: { pvFCFF:12009, pvTerminalValue:33800, enterpriseValue:45800, netDebt:7200, equityValue:38600, shares:1752 },
    wacc: { rf:3.5, beta:1.05, erp:5.0, ke:8.8, kd:4.8, tax:22.0, eWeight:70, dWeight:30, wacc:9.1, terminalG:2.5 },
    multiples: [
      { metric:'EV/EBITDA',  peerAvg:'9.8x',  implied:'₩235,000', impliedAmt:235000, current:'7.2x',  premium:'+58.8%' },
      { metric:'P/E (NTM)',  peerAvg:'18.6x', implied:'₩214,000', impliedAmt:214000, current:'14.1x', premium:'+44.6%' },
      { metric:'P/B',        peerAvg:'2.1x',  implied:'₩198,000', impliedAmt:198000, current:'1.6x',  premium:'+33.8%' },
      { metric:'EV/Revenue', peerAvg:'1.4x',  implied:'₩207,000', impliedAmt:207000, current:'1.1x',  premium:'+39.9%' },
    ],
    sensitivityWacc:[8.1,8.6,9.1,9.6,10.1], sensitivityG:[1.5,2.0,2.5,3.0,3.5],
    sensitivityPrices: _sens(220000,9.1,2.5,[8.1,8.6,9.1,9.6,10.1],[1.5,2.0,2.5,3.0,3.5]),
    tornado: [
      { variable:'WACC (±1%)',           low:-32000, high:39000 },
      { variable:'터미널 성장률 (±0.5%)', low:-19500, high:24200 },
      { variable:'매출 성장률 (±5%)',     low:-16800, high:19400 },
      { variable:'EBIT 마진 (±2%)',       low:-14200, high:16600 },
      { variable:'베타 (±0.2)',           low:-11200, high:12100 },
      { variable:'D&A (±10%)',            low:-5100,  high:5600  },
      { variable:'CapEx (±10%)',          low:-4700,  high:5200  },
      { variable:'ΔNWC (±10%)',           low:-2400,  high:2600  },
    ],
    peers: [
      { name:'삼성전기',  ticker:'009150', beta:1.05, evEbitda:'7.2x',  pe:'14.1x', pb:'1.6x', roe:'11.4%', isSelf:true },
      { name:'LG이노텍', ticker:'011070', beta:1.18, evEbitda:'8.9x',  pe:'16.8x', pb:'2.1x', roe:'12.6%' },
      { name:'삼성SDI',  ticker:'006400', beta:0.95, evEbitda:'9.2x',  pe:'17.4x', pb:'1.8x', roe:'10.8%' },
      { name:'무라타',   ticker:'6981.T', beta:0.88, evEbitda:'11.2x', pe:'20.3x', pb:'2.3x', roe:'13.2%' },
      { name:'TDK',      ticker:'6762.T', beta:0.92, evEbitda:'10.4x', pe:'18.9x', pb:'2.0x', roe:'10.6%' },
      { name:'Amphenol', ticker:'APH',    beta:1.21, evEbitda:'15.3x', pe:'28.1x', pb:'4.8x', roe:'20.4%' },
    ],
  },
  '035420': {
    equityValueLabel: '₩52.4조',
    fairPrices: { bear: 220000, base: 320000, bull: 420000 },
    upsides:    { bear: '+12.8%', base: '+64.1%', bull: '+115.4%' },
    dcfYears: ['2025E','2026E','2027E','2028E','2029E'],
    dcfRows: [
      { label:'매출액 (억원)',    values:[108000,119000,131000,144000,158000], bold:true },
      { label:'성장률 (%)',       values:[6.9,10.2,10.1,9.9,9.7],             fmt:'pct' },
      { label:'EBIT (억원)',      values:[18360,21420,26200,31680,37920] },
      { label:'EBIT Margin (%)',  values:[17.0,18.0,20.0,22.0,24.0],          fmt:'pct' },
      { label:'NOPAT (억원)',     values:[14321,16708,20436,24710,29578] },
      { label:'D&A (억원)',       values:[5200,5600,6100,6700,7300] },
      { label:'CapEx (억원)',     values:[-7800,-8500,-9200,-9900,-10600] },
      { label:'ΔNWC (억원)',      values:[-1200,-1100,-1000,-900,-800] },
      { label:'FCFF (억원)',      values:[10521,12708,16336,20610,25478], bold:true },
      { label:'할인계수',         values:[0.907,0.823,0.747,0.678,0.615], fmt:'decimal3' },
      { label:'PV of FCFF (억원)',values:[9543,10459,12203,13974,15669], bold:true },
    ],
    dcfSummary: { pvFCFF:61848, pvTerminalValue:227000, enterpriseValue:288800, netDebt:12400, equityValue:276400, shares:1641 },
    wacc: { rf:3.5, beta:1.32, erp:5.0, ke:10.1, kd:4.5, tax:22.0, eWeight:85, dWeight:15, wacc:10.2, terminalG:3.5 },
    multiples: [
      { metric:'EV/EBITDA',  peerAvg:'22.4x', implied:'₩312,000', impliedAmt:312000, current:'16.8x', premium:'+60.0%' },
      { metric:'P/E (NTM)',  peerAvg:'36.8x', implied:'₩298,000', impliedAmt:298000, current:'28.1x', premium:'+52.8%' },
      { metric:'P/B',        peerAvg:'4.2x',  implied:'₩284,000', impliedAmt:284000, current:'3.2x',  premium:'+45.6%' },
      { metric:'EV/Revenue', peerAvg:'3.8x',  implied:'₩328,000', impliedAmt:328000, current:'2.9x',  premium:'+68.2%' },
    ],
    sensitivityWacc:[9.2,9.7,10.2,10.7,11.2], sensitivityG:[2.5,3.0,3.5,4.0,4.5],
    sensitivityPrices: _sens(320000,10.2,3.5,[9.2,9.7,10.2,10.7,11.2],[2.5,3.0,3.5,4.0,4.5]),
    tornado: [
      { variable:'WACC (±1%)',           low:-52000, high:68000 },
      { variable:'터미널 성장률 (±0.5%)', low:-38000, high:48000 },
      { variable:'매출 성장률 (±5%)',     low:-28000, high:33000 },
      { variable:'EBIT 마진 (±2%)',       low:-22000, high:26000 },
      { variable:'베타 (±0.2)',           low:-18000, high:21000 },
      { variable:'D&A (±10%)',            low:-7800,  high:8400  },
      { variable:'CapEx (±10%)',          low:-6900,  high:7500  },
      { variable:'ΔNWC (±10%)',           low:-3100,  high:3400  },
    ],
    peers: [
      { name:'NAVER',    ticker:'035420',  beta:1.32, evEbitda:'16.8x', pe:'28.1x', pb:'3.2x', roe:'11.4%', isSelf:true },
      { name:'카카오',   ticker:'035720',  beta:1.41, evEbitda:'18.4x', pe:'31.2x', pb:'3.8x', roe:'12.2%' },
      { name:'크래프톤', ticker:'259960',  beta:1.08, evEbitda:'19.8x', pe:'22.4x', pb:'2.9x', roe:'13.1%' },
      { name:'카카오페이',ticker:'377300', beta:1.65, evEbitda:'28.2x', pe:'48.6x', pb:'4.1x', roe:'8.6%'  },
      { name:'Tencent',  ticker:'0700.HK', beta:0.98, evEbitda:'23.4x', pe:'38.2x', pb:'4.8x', roe:'21.4%' },
      { name:'Meta',     ticker:'META',    beta:1.24, evEbitda:'25.6x', pe:'42.8x', pb:'6.2x', roe:'28.6%' },
    ],
  },
};

// ─── 탭 타입 ──────────────────────────────────────────────────────
type MainTab = 'overview' | 'valuation' | 'ai';
type FinTab  = 'BS' | 'IS' | 'SANKEY';
type ValTab  = 'dcf' | 'wacc' | 'multiples' | 'sensitivity' | 'tornado' | 'peers';

// ─── Bear/Base/Bull 설정 ──────────────────────────────────────────
const SCENARIO_CONFIG = [
  {
    key: 'bear' as const,
    label: 'BEAR',
    upKey: 'bear' as const,
    bg: 'bg-red-50',
    border: 'border-red-200',
    topBorder: 'border-t-red-500',
    textColor: 'text-red-600',
    badge: 'bg-red-100 text-red-700',
    icon: '🐻',
    desc: '비관 시나리오',
  },
  {
    key: 'base' as const,
    label: 'BASE',
    upKey: 'base' as const,
    bg: 'bg-indigo-50',
    border: 'border-indigo-200',
    topBorder: 'border-t-indigo-600',
    textColor: 'text-indigo-700',
    badge: 'bg-indigo-100 text-indigo-700',
    icon: '📊',
    desc: '기본 시나리오',
  },
  {
    key: 'bull' as const,
    label: 'BULL',
    upKey: 'bull' as const,
    bg: 'bg-emerald-50',
    border: 'border-emerald-200',
    topBorder: 'border-t-emerald-500',
    textColor: 'text-emerald-700',
    badge: 'bg-emerald-100 text-emerald-700',
    icon: '🐂',
    desc: '낙관 시나리오',
  },
];

/** 상장폐지·거래정지·관리종목 배너 (주가차트/재무탭 빈 영역 대체) */
function ListingStatusBanner({ s, compact = false }: { s: any; compact?: boolean }) {
  if (!s || s.status === 'NORMAL' || !s.label) return null;
  const theme: Record<string, { box: string; emoji: string }> = {
    DELISTED: { box: 'bg-rose-50 border-rose-300 text-rose-800',     emoji: '🚫' },
    HALT:     { box: 'bg-amber-50 border-amber-300 text-amber-800',  emoji: '⏸️' },
    ADMIN:    { box: 'bg-yellow-50 border-yellow-300 text-yellow-800',emoji: '⚠️' },
  };
  const t = theme[s.status] || theme.HALT;
  return (
    <div className={`flex items-start gap-3 border rounded-lg ${t.box} ${compact ? 'px-4 py-3' : 'px-5 py-6 justify-center text-center flex-col items-center'}`}>
      <div className={compact ? 'text-xl' : 'text-3xl'}>{t.emoji}</div>
      <div>
        <div className={`font-bold ${compact ? 'text-sm' : 'text-base'}`}>{s.label}</div>
        {s.reason && <div className="text-xs mt-1 opacity-80">사유: {s.reason}</div>}
        {s.ref_date && (
          <div className="text-xs mt-1 opacity-70">
            {s.status === 'DELISTED' ? `상장폐지일: ${s.ref_date}` :
             s.status === 'ADMIN'    ? `지정일: ${s.ref_date}` :
             s.status === 'HALT'     ? `거래정지일: ${s.ref_date}` : ''}
          </div>
        )}
        {!compact && <div className="text-[11px] mt-2 opacity-60">출처: 한국거래소</div>}
      </div>
    </div>
  );
}

// 계열회사 시각화 — 접이식 토글 (기업개요 탭: 최신뉴스 다음 · 주가차트 앞)
function AffiliateToggle({ code }: { code: string }) {
  const [open, setOpen]     = useState(false);
  const [meta, setMeta]     = useState<any>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let alive = true;
    fetch(`${API}/api/affiliate/${code}`)
      .then(r => r.json())
      .then(d => { if (alive) setMeta(d); })
      .catch(() => { if (alive) setMeta({ available: false }); })
      .finally(() => { if (alive) setLoaded(true); });
    return () => { alive = false; };
  }, [code]);

  const available = meta?.available;
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
      <button onClick={() => setOpen(o => !o)}
        className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors text-left">
        <span className="flex items-center gap-2">
          <span className="text-sm font-bold text-slate-700 dark:text-slate-200">🏢 계열회사 구조</span>
          {loaded && (available
            ? <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 font-medium">
                {meta.source_type === 'original_dart_image' ? 'DART 원본' : '구조도'}
              </span>
            : <span className="text-[11px] text-slate-400">데이터 준비중</span>)}
        </span>
        <svg className={`w-4 h-4 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
        </svg>
      </button>
      {open && (
        <div className="px-5 pb-5 border-t border-slate-100 dark:border-slate-700">
          {available ? (
            <div className="pt-4">
              <div className="rounded-lg bg-white border border-slate-100 overflow-auto max-h-[70vh]">
                <img src={`${API}${meta.file_url}`} alt={`${code} 계열회사 구조`}
                  className="w-full h-auto block" loading="lazy" />
              </div>
              <div className="text-[11px] text-slate-400 mt-1.5 text-right">↕ 스크롤하여 전체 구조 보기</div>
              <div className="text-[11px] text-slate-400 mt-2">
                출처: DART 사업보고서 계열회사 시각화 · {meta.label} ({meta.source_type})
              </div>
            </div>
          ) : (
            <div className="py-10 text-center text-sm text-slate-400 leading-relaxed">
              계열회사 시각화 데이터 준비 중<br/>
              <span className="text-xs">(현재 샘플 종목만 제공 — 전 종목 적용 예정)</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// AI 탭 = 팀원 RAG 챗봇 화면(8800) 전체를 iframe으로 임베드 (AI 종합분석 제거, 챗봇만)
function AIChatbotTab() {
  const [status, setStatus] = useState<'checking' | 'up' | 'down'>('checking');
  useEffect(() => {
    let alive = true;
    fetch(`${CHAT_API}/health`)
      .then(r => { if (alive) setStatus(r.ok ? 'up' : 'down'); })
      .catch(() => { if (alive) setStatus('down'); });
    return () => { alive = false; };
  }, []);

  // 탭 바(상단 100px = 헤더56 + 탭44) 아래를 꽉 채움
  const H = 'calc(100vh - 100px)';
  if (status === 'checking') {
    return <div style={{ height: H }} className="flex items-center justify-center bg-[#0f1115] text-slate-400 text-sm">AI 챗봇 연결 확인 중…</div>;
  }
  if (status === 'down') {
    return (
      <div style={{ height: H }} className="flex flex-col items-center justify-center bg-[#0f1115] text-center px-4">
        <div className="text-4xl mb-3">💬</div>
        <div className="text-base font-bold text-slate-100 mb-2">AI 챗봇 서버가 꺼져 있습니다</div>
        <div className="text-sm text-slate-400 mb-5">DART 사업보고서 RAG 챗봇(포트 8800)을 켜면 여기에서 바로 대화할 수 있어요.</div>
        <div className="text-xs text-slate-300 bg-[#171a21] border border-[#2a2f3a] rounded-lg p-4 inline-block text-left font-mono leading-relaxed">
          cd C:\Users\Admin\FILMN9\chatbot<br/>
          conda activate FILMN9_chatbot_env<br/>
          python -m uvicorn embedding.chatbot.api:app --port 8800
        </div>
        <div className="text-[11px] text-slate-500 mt-4">※ 서버를 켠 뒤 이 탭을 다시 누르면 챗봇 화면이 나타납니다.</div>
      </div>
    );
  }
  return (
    <iframe
      src={CHAT_API}
      title="DART 사업보고서 RAG 챗봇"
      className="w-full block border-0"
      style={{ height: H, background: '#0f1115' }}
    />
  );
}

export default function StockPage() {
  const { code } = useParams<{ code: string }>();
  const router = useRouter();

  // ─── 상태 ─────────────────────────────────────────────────────
  const [mainTab,  setMainTab]  = useState<MainTab>('overview');
  const [finTab,   setFinTab]   = useState<FinTab>('SANKEY');
  const [valTab,   setValTab]   = useState<ValTab>('dcf');
  const [period,   setPeriod]   = useState('3M');
  const [dark,     setDark]     = useState(false);

  const [overview,     setOverview]     = useState<any>(null);
  const [valData,      setValData]      = useState<any>(null);
  const [ohlcv,        setOhlcv]        = useState<any[]>([]);
  const [bsData,       setBsData]       = useState<any>(null);
  const [isData,       setIsData]       = useState<any>(null);
  const [shareholders, setShareholders] = useState<any[]>([]);
  const [executives,   setExecutives]   = useState<any[]>([]);
  const [disclosures,  setDisclosures]  = useState<any[]>([]);
  const [health,       setHealth]       = useState<any>(null);
  const [credit,       setCredit]       = useState<any[]>([]);
  const [realtime,     setRealtime]     = useState<any>(null);
  const [news,         setNews]         = useState<any[]>([]);
  const [listStatus,   setListStatus]   = useState<any>(null);  // 상장폐지/거래정지 상태
  const [loadingMain,  setLoadingMain]  = useState(true);
  // 서비스 내 DART 뷰어 (다중 탭 + 드래그 + 리사이즈 + 전체화면)
  type DartTab = { rcept_no: string; title: string };
  type DartViewerState = {
    tabs: DartTab[];
    activeIdx: number;
    pos: { x: number; y: number };
    size: { w: number; h: number };
    isFullscreen: boolean;
  };
  const [dartViewer, setDartViewer] = useState<DartViewerState | null>(null);
  // 분리된 독립 팝업들 (하이브리드)
  type DetachedDart = { id: string; rcept_no: string; title: string; pos: {x:number,y:number}; size: {w:number,h:number}; isFullscreen: boolean };
  const [detachedDarts, setDetachedDarts] = useState<DetachedDart[]>([]);
  const dartDragRef = useRef<{
    startX:number, startY:number,
    origPos:{x:number,y:number},
    mode:'drag'|'resize'|null,
    edge?:string,
    origSize?:{w:number,h:number},
    target:'main' | string,   // 'main' = 메인 팝업, string = detached id
  } | null>(null);

  const openDart = (item: DartTab) => {
    setDartViewer(prev => {
      if (typeof window === 'undefined') return prev;
      if (!prev) {
        const w = Math.min(1100, window.innerWidth - 80);
        const h = Math.min(720, window.innerHeight - 80);
        return {
          tabs: [item], activeIdx: 0,
          pos: { x: Math.max(20, (window.innerWidth - w) / 2), y: Math.max(20, (window.innerHeight - h) / 2) },
          size: { w, h }, isFullscreen: false,
        };
      }
      const existing = prev.tabs.findIndex(t => t.rcept_no === item.rcept_no);
      if (existing >= 0) return { ...prev, activeIdx: existing };
      // 최대 5개 제한 (메모리 부담 방지)
      if (prev.tabs.length >= 5) {
        alert('최대 5개까지만 동시에 열 수 있습니다. 일부 탭을 닫아주세요.');
        return prev;
      }
      return { ...prev, tabs: [...prev.tabs, item], activeIdx: prev.tabs.length };
    });
  };

  const closeDartTab = (idx: number) => {
    setDartViewer(prev => {
      if (!prev) return null;
      if (prev.tabs.length === 1) return null;
      const newTabs = prev.tabs.filter((_, i) => i !== idx);
      const newActive = idx < prev.activeIdx ? prev.activeIdx - 1
                       : idx === prev.activeIdx ? Math.min(idx, newTabs.length - 1)
                       : prev.activeIdx;
      return { ...prev, tabs: newTabs, activeIdx: Math.max(0, newActive) };
    });
  };

  const toggleDartFullscreen = () => {
    setDartViewer(prev => prev ? { ...prev, isFullscreen: !prev.isFullscreen } : prev);
  };

  // 메인·분리 팝업 공통 드래그·리사이즈
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = dartDragRef.current;
      if (!d || !d.mode) return;
      const dx = e.clientX - d.startX;
      const dy = e.clientY - d.startY;
      const applyToMain = (prev: DartViewerState | null) => {
        if (!prev) return prev;
        if (d.mode === 'drag') return { ...prev, pos: { x: d.origPos.x + dx, y: d.origPos.y + dy } };
        if (d.mode === 'resize' && d.origSize && d.edge) {
          let newW = d.origSize.w, newH = d.origSize.h, newX = d.origPos.x, newY = d.origPos.y;
          if (d.edge.includes('e')) newW = Math.max(400, d.origSize.w + dx);
          if (d.edge.includes('w')) { newW = Math.max(400, d.origSize.w - dx); newX = d.origPos.x + dx; }
          if (d.edge.includes('s')) newH = Math.max(300, d.origSize.h + dy);
          if (d.edge.includes('n')) { newH = Math.max(300, d.origSize.h - dy); newY = d.origPos.y + dy; }
          return { ...prev, size: { w: newW, h: newH }, pos: { x: newX, y: newY } };
        }
        return prev;
      };
      const applyToDetached = (arr: DetachedDart[]) => arr.map(p => {
        if (p.id !== d.target) return p;
        if (d.mode === 'drag') return { ...p, pos: { x: d.origPos.x + dx, y: d.origPos.y + dy } };
        if (d.mode === 'resize' && d.origSize && d.edge) {
          let newW = d.origSize.w, newH = d.origSize.h, newX = d.origPos.x, newY = d.origPos.y;
          if (d.edge.includes('e')) newW = Math.max(400, d.origSize.w + dx);
          if (d.edge.includes('w')) { newW = Math.max(400, d.origSize.w - dx); newX = d.origPos.x + dx; }
          if (d.edge.includes('s')) newH = Math.max(300, d.origSize.h + dy);
          if (d.edge.includes('n')) { newH = Math.max(300, d.origSize.h - dy); newY = d.origPos.y + dy; }
          return { ...p, size: { w: newW, h: newH }, pos: { x: newX, y: newY } };
        }
        return p;
      });
      if (d.target === 'main') setDartViewer(applyToMain);
      else setDetachedDarts(applyToDetached);
    };
    const onUp = () => { if (dartDragRef.current) dartDragRef.current.mode = null; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  const startDartDrag = (e: React.MouseEvent) => {
    if (!dartViewer || dartViewer.isFullscreen) return;
    dartDragRef.current = { startX: e.clientX, startY: e.clientY, origPos: dartViewer.pos, mode: 'drag', target: 'main' };
  };

  const startDartResize = (edge: string) => (e: React.MouseEvent) => {
    if (!dartViewer || dartViewer.isFullscreen) return;
    e.stopPropagation();
    dartDragRef.current = {
      startX: e.clientX, startY: e.clientY,
      origPos: dartViewer.pos, origSize: dartViewer.size,
      mode: 'resize', edge, target: 'main',
    };
  };

  const startDetachedDrag = (id: string) => (e: React.MouseEvent) => {
    const p = detachedDarts.find(x => x.id === id);
    if (!p || p.isFullscreen) return;
    dartDragRef.current = { startX: e.clientX, startY: e.clientY, origPos: p.pos, mode: 'drag', target: id };
  };

  const startDetachedResize = (id: string, edge: string) => (e: React.MouseEvent) => {
    const p = detachedDarts.find(x => x.id === id);
    if (!p || p.isFullscreen) return;
    e.stopPropagation();
    dartDragRef.current = {
      startX: e.clientX, startY: e.clientY,
      origPos: p.pos, origSize: p.size,
      mode: 'resize', edge, target: id,
    };
  };

  // 탭을 별도 팝업으로 분리
  const detachTab = (idx: number) => {
    if (!dartViewer) return;
    const tab = dartViewer.tabs[idx];
    if (!tab) return;
    const offset = detachedDarts.length * 32;
    const w = 800, h = 560;
    const newPopup: DetachedDart = {
      id: `${tab.rcept_no}_${Date.now()}`,
      rcept_no: tab.rcept_no, title: tab.title,
      pos: { x: 80 + offset, y: 80 + offset },
      size: { w, h }, isFullscreen: false,
    };
    setDetachedDarts(prev => [...prev, newPopup]);
    // 메인 팝업에서 탭 제거 (마지막이면 메인 팝업 자체 닫음)
    setDartViewer(prev => {
      if (!prev) return null;
      if (prev.tabs.length === 1) return null;
      const newTabs = prev.tabs.filter((_, i) => i !== idx);
      const newActive = idx < prev.activeIdx ? prev.activeIdx - 1
                       : idx === prev.activeIdx ? Math.min(idx, newTabs.length - 1)
                       : prev.activeIdx;
      return { ...prev, tabs: newTabs, activeIdx: Math.max(0, newActive) };
    });
  };

  const closeDetached = (id: string) =>
    setDetachedDarts(prev => prev.filter(p => p.id !== id));

  const toggleDetachedFullscreen = (id: string) =>
    setDetachedDarts(prev => prev.map(p => p.id === id ? { ...p, isFullscreen: !p.isFullscreen } : p));
  // 공시 탭 (전자공시 / 공급계약)
  const [discTab, setDiscTab] = useState<'dart'|'supply'>('dart');
  const [supplyContracts, setSupplyContracts] = useState<any[]>([]);
  const [supplyLoading, setSupplyLoading] = useState(false);
  // 고객사·경쟁사 (히스토리 브리핑 3번)
  const [peers, setPeers] = useState<any>(null);
  // 전자공시 (DART 실시간)
  const [dartList, setDartList] = useState<any>(null);
  const [dartLoading, setDartLoading] = useState(false);
  const [dartPeriod, setDartPeriod] = useState<'1m'|'6m'|'1y'|'3y'|'5y'|'10y'>('1y');
  const [dartTypes, setDartTypes] = useState<Set<string>>(new Set());  // 빈 set = 전체
  const [dartPage, setDartPage] = useState(1);
  const [dartPageSize, setDartPageSize] = useState(15);

  // 전자공시 조회 함수
  const fetchDartList = (period=dartPeriod, types=dartTypes, page=dartPage, pageSize=dartPageSize) => {
    setDartLoading(true);
    const typesParam = types.size > 0 ? `&types=${Array.from(types).join(',')}` : '';
    fetch(`${API}/api/dart_disclosures/${code}?period=${period}&page=${page}&page_count=${pageSize}${typesParam}`)
      .then(r => r.json())
      .then(d => setDartList(d))
      .catch(() => setDartList({items:[], total_count:0, total_page:0}))
      .finally(() => setDartLoading(false));
  };

  const [miniSearch,   setMiniSearch]   = useState('');
  const [miniResults,  setMiniResults]  = useState<any[]>([]);
  const [miniOpen,     setMiniOpen]     = useState(false);
  const [recent,       setRecent]       = useState<{stock_code:string;corp_name:string}[]>([]);
  const [chatInput,    setChatInput]    = useState('');
  const [chatMessages, setChatMessages] = useState<{text:string;isUser:boolean}[]>([
    { text:'안녕하세요! DART 사업보고서를 실시간 검색(RAG)해 답변드립니다.\n아래 추천 질문을 클릭하거나 직접 질문해주세요. (답변에 10~30초 소요)', isUser:false }
  ]);

  const miniRef    = useRef<HTMLDivElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // ─── RAG 사업보고서 응답 매핑 (PoC 데모용) ──────────────────────
  // 출처: DART 2024 사업보고서 II.사업의 내용 + 시장 데이터
  // 정식 RAG 엔진 출시 전 미리 작성한 종목별 Q&A 매핑
  type QA = { keywords: string[]; answer: string };
  const QA_BY_CODE: Record<string, QA[]> = {
    // ── 아모레퍼시픽 090430 ─────────────────────────────────
    '090430': [
      {
        keywords: ['브랜드', '포트폴리오', '주요 사업', '주력', '사업'],
        answer: '아모레퍼시픽은 럭셔리·프리미엄·매스 전 가격대 화장품 포트폴리오를 운영합니다.\n\n' +
                '• 럭셔리: 설화수·헤라·바이오스템셀(럭셔리 한방·안티에이징)\n' +
                '• 프리미엄: 라네즈·이니스프리·아이오페·마몽드\n' +
                '• 매스: 에뛰드·미장센·해피바스\n\n' +
                '2024년 화장품 부문 매출 비중이 약 89%, 생활용품·식품(설록차 등) 약 11%입니다. ' +
                '특히 라네즈는 미국 아마존·세포라 채널에서 24년 매출 47% 성장, K-뷰티 대표 브랜드로 자리잡았습니다.\n\n' +
                '출처: DART 2024 사업보고서 II.사업의 내용 · 1. 사업의 개요',
      },
      {
        keywords: ['중국', '글로벌', '해외', '시장 다변화', '미국', '일본'],
        answer: '아모레퍼시픽은 중국 의존도 축소와 서구 시장 확대 전략을 추진 중입니다.\n\n' +
                '• 중국: 매출 비중 30%대로 축소 (2018년 50%+ → 2024년 32%). 럭셔리(설화수) 중심 재편\n' +
                '• 미국: 라네즈가 아마존 베스트셀러, 세포라 매장 확대. 24년 미주 매출 +47%\n' +
                '• 일본: 이니스프리 직진출, MZ 채널 강화. 24년 일본 매출 +29%\n' +
                '• 동남아: 베트남·태국·인도네시아 e커머스 채널 확대\n\n' +
                '"차이나 리스크" 해소를 위한 시장 다변화가 핵심 성장 전략입니다.\n\n' +
                '출처: DART 2024 사업보고서 II.4. 매출 및 수주상황 (지역별)',
      },
      {
        keywords: ['R&D', '연구', '기술', '특허', '경쟁력', '강점'],
        answer: '아모레퍼시픽은 매출 대비 약 3% 수준의 R&D 투자를 지속하는 화장품 기술 기반 기업입니다.\n\n' +
                '• 자체 원천기술: 녹차 추출물(설록차밭 자체 운영), 인삼·한방 약용식물 추출\n' +
                '• 안티에이징: 자체 펩타이드·줄기세포 기술 (설화수 자음생 라인)\n' +
                '• 피부과학: 미국·일본·중국 3대 글로벌 R&D 센터\n' +
                '• 특허: 24년 기준 누적 화장품 특허 약 4,200건, 글로벌 톱5\n\n' +
                '단순 유통이 아닌 자체 원료·제형 개발 능력이 LG생활건강 등 경쟁사 대비 차별점입니다.\n\n' +
                '출처: DART 2024 사업보고서 II.2. 연구개발활동 · III. 재무에 관한 사항',
      },
    ],
    // ── 삼성전기 009150 ─────────────────────────────────────
    '009150': [
      {
        keywords: ['MLCC', '적층세라믹', '시장 점유율', '경쟁력', '주력'],
        answer: '삼성전기의 주력 사업은 MLCC(적층세라믹콘덴서)이며, 글로벌 시장 점유율 약 23%로 일본 무라타(35%)에 이은 세계 2위입니다.\n\n' +
                '• 시장 규모: 글로벌 MLCC 시장 약 20조원, 연 6~8% 성장\n' +
                '• 주요 경쟁사: 무라타(일본), 교세라(일본), TDK(일본), 야게오(대만)\n' +
                '• 강점: 초소형 고용량(0201 사이즈) 양산 기술, 자동차용 고신뢰성 MLCC\n' +
                '• AI 서버·전기차 수요 확대로 24년 MLCC 부문 매출 +18%\n\n' +
                '특히 AI 가속기·자동차 전장용 고부가 MLCC 비중을 확대하며 일반 IT용 대비 ASP가 3~5배 높습니다.\n\n' +
                '출처: DART 2024 사업보고서 II.사업의 내용 · 컴포넌트 사업부문',
      },
      {
        keywords: ['전장', '자동차', '전기차', '자율주행', '카메라', 'ADAS'],
        answer: '삼성전기 전장(자동차 전자장비) 부문은 24년 매출 비중 약 18%까지 확대된 핵심 성장 사업입니다.\n\n' +
                '• 자동차용 MLCC: 한 대당 1만~1.5만개 탑재 (전기차는 일반차 대비 2배)\n' +
                '• 카메라모듈: ADAS·자율주행용 고화소 카메라, 라이다 부품\n' +
                '• 패키지기판: 차량용 반도체용 FC-BGA, 통신모듈 기판\n' +
                '• 주요 고객: 테슬라, 현대차, BMW, Toyota, 보쉬 등\n\n' +
                '2027년까지 전장 매출 비중을 30%대로 확대 목표. 전기차·자율주행 확산이 직접적 수혜로 작용합니다.\n\n' +
                '출처: DART 2024 사업보고서 II.사업의 내용 · 전장 사업 전략',
      },
      {
        keywords: ['삼성전자', '고객', '의존도', '매출처', '계열사', '리스크'],
        answer: '삼성전기는 모회사 삼성전자에 대한 매출 의존도가 약 30~35% 수준이며, 외부 고객 다변화를 진행 중입니다.\n\n' +
                '• 삼성전자(갤럭시 시리즈): 카메라모듈·패키지기판·MLCC 공급, 매출 비중 약 33%\n' +
                '• 외부 고객: Apple(아이폰 카메라모듈), 샤오미·OPPO·Vivo, 테슬라, Qualcomm\n' +
                '• 매출 다변화: 5년 전 삼성전자 비중 50%+ → 24년 33%로 축소\n\n' +
                '리스크: 갤럭시 판매 부진 시 직접 영향. 다만 AI 서버용 FC-BGA, 자동차 부품으로 의존도 ' +
                '추가 완화 중. AMD·NVIDIA 등 AI 가속기 고객 확보가 핵심 모멘텀입니다.\n\n' +
                '출처: DART 2024 사업보고서 II.4. 매출 및 수주상황 (고객별)',
      },
    ],
    // ── NAVER 035420 ───────────────────────────────────────
    '035420': [
      {
        keywords: ['사업', '부문', '비중', '구성', '서치플랫폼', '주요'],
        answer: 'NAVER는 5대 사업 부문 체제로 운영되며 24년 매출 비중은 다음과 같습니다.\n\n' +
                '• 서치플랫폼 (40%): 네이버 검색, 디스플레이/검색광고 — 캐시카우\n' +
                '• 커머스 (28%): 스마트스토어, 네이버페이, 크림(KREAM) — 최대 성장 부문\n' +
                '• 핀테크 (15%): 네이버페이 결제·송금·금융상품\n' +
                '• 콘텐츠 (10%): 웹툰, 시리즈온, V LIVE — 글로벌 확장 중\n' +
                '• 클라우드 (7%): 네이버클라우드플랫폼(NCP), 하이퍼클로바X B2B\n\n' +
                '단일 검색엔진 기업에서 검색·커머스·핀테크·콘텐츠·클라우드 종합 IT 플랫폼으로 전환했습니다.\n\n' +
                '출처: DART 2024 사업보고서 II.사업의 내용 · 사업부문별 매출',
      },
      {
        keywords: ['AI', '클로바', '하이퍼클로바', '클라우드', '투자'],
        answer: 'NAVER는 자체 LLM 하이퍼클로바X를 기반으로 글로벌 AI 시장에 도전 중입니다.\n\n' +
                '• 하이퍼클로바X: 한국어 특화 LLM, 23년 8월 공개. 파라미터 2,040억개\n' +
                '• B2B 적용: 삼성·HD현대·KB금융 등 국내 대기업 사내 AI 도입\n' +
                '• 일본 LINE·소뱅 협업: 한일 데이터 기반 멀티모달 모델 공동 개발\n' +
                '• AI 인프라: 세종 데이터센터 "각 세종" 가동, AI 클라우드 GPU 확충\n' +
                '• 사우디 진출: 디지털 트윈 + AI 솔루션, 약 1조원 규모 프로젝트\n\n' +
                '구글·MS와 직접 경쟁이 아닌 "한국어·일본어 sovereign AI" 전략으로 차별화합니다.\n\n' +
                '출처: DART 2024 사업보고서 II.2. 연구개발활동 · 사업의 내용',
      },
      {
        keywords: ['규제', '리스크', '경쟁', '독점', '온플법', '공정거래'],
        answer: 'NAVER가 사업보고서에서 밝힌 주요 리스크는 규제·경쟁·트래픽 3가지입니다.\n\n' +
                '• 플랫폼 규제: 온라인플랫폼법(온플법) 입법 진행 중, 자사 우대·끼워팔기 규제 강화\n' +
                '• 검색 경쟁: 구글 한국 점유율 30%+ 상승, 유튜브가 종합 정보 채널화\n' +
                '• 생성형 AI 위협: ChatGPT·Gemini 검색 대체 가능성, 검색 광고 매출 잠식 우려\n' +
                '• 커머스 경쟁: 쿠팡(로켓배송), 알리·테무(C2M) 진입으로 마진 압박\n' +
                '• 콘텐츠 규제: 웹툰 글로벌 진출 시 각국 콘텐츠 검열·과세 이슈\n\n' +
                '대응: 자체 LLM(하이퍼클로바X)으로 AI 검색 선제 대응, 멤버십·페이로 락인 강화.\n\n' +
                '출처: DART 2024 사업보고서 II.3. 위험관리 및 파생거래',
      },
    ],
  };

  const DEFAULT_ANSWER = '죄송합니다, 해당 질문에 대한 사업보고서 답변이 PoC 데모용 데이터에 포함되어 있지 않습니다. ' +
                        '추천 질문 칩을 클릭해주시면 사업보고서 기반 상세 답변을 제공해드립니다. ' +
                        '(정식 RAG 엔진 출시 시 자유 질의응답 지원 예정)';

  // 키워드 매칭으로 답변 선택
  const findAnswer = (question: string): string => {
    const qaList = QA_BY_CODE[code || ''] || [];
    if (!qaList.length) return DEFAULT_ANSWER;
    const q = question.toLowerCase();
    // 가장 많은 키워드가 매칭되는 QA 선택
    let bestQA: QA | null = null;
    let bestScore = 0;
    for (const qa of qaList) {
      const score = qa.keywords.filter(k => q.includes(k.toLowerCase())).length;
      if (score > bestScore) { bestScore = score; bestQA = qa; }
    }
    return bestQA ? bestQA.answer : DEFAULT_ANSWER;
  };

  // 다크모드
  const toggleDark = () => {
    document.documentElement.classList.toggle('dark');
    setDark(d => !d);
  };

  // ─── 데이터 로드 ──────────────────────────────────────────────
  useEffect(() => {
    if (!code) return;
    setLoadingMain(true);
    const load = async () => {
      await Promise.allSettled([
        fetch(`${API}/api/overview/${code}`).then(r=>r.json()).then(setOverview).catch(()=>{}),
        fetch(`${API}/api/valuation/${code}`).then(r=>r.json()).then(setValData).catch(()=>{}),
        fetch(`${API}/api/ohlcv/${code}`).then(r=>r.json()).then(d=>setOhlcv(d.data||[])).catch(()=>{}),
        fetch(`${API}/api/financial_detail/${code}/BS`).then(r=>r.json()).then(setBsData).catch(()=>{}),
        fetch(`${API}/api/financial_detail/${code}/IS`).then(r=>r.json()).then(setIsData).catch(()=>{}),
        fetch(`${API}/api/shareholders/${code}`).then(r=>r.json()).then(d=>setShareholders(d.items||[])).catch(()=>{}),
        fetch(`${API}/api/executives/${code}`).then(r=>r.json()).then(d=>setExecutives(d.items||[])).catch(()=>{}),
        fetch(`${API}/api/disclosures/${code}?limit=10`).then(r=>r.json()).then(d=>setDisclosures(d.items||[])).catch(()=>{}),
        fetch(`${API}/api/health/${code}`).then(r=>r.json()).then(setHealth).catch(()=>{}),
        fetch(`${API}/api/credit/${code}`).then(r=>r.json()).then(d=>setCredit(d.items||[])).catch(()=>{}),
        fetch(`${API}/api/news/${code}?limit=6`).then(r=>r.json()).then(d=>setNews(d.items||[])).catch(()=>{}),
        // 전자공시 초기 로드 (1년, 15건)
        fetch(`${API}/api/dart_disclosures/${code}?period=1y&page=1&page_count=15`).then(r=>r.json()).then(setDartList).catch(()=>setDartList({items:[],total_count:0,total_page:0})),
        // 고객사·경쟁사
        fetch(`${API}/api/peers/${code}`).then(r=>r.json()).then(setPeers).catch(()=>{}),
        // 상장 상태 (상장폐지/거래정지/관리종목)
        fetch(`${API}/api/stock_status/${code}`).then(r=>r.json()).then(setListStatus).catch(()=>{}),
      ]);
      setLoadingMain(false);
    };
    load();
  }, [code]);

  // ─── 실시간 주가 polling (60초 간격) ──────────────────────────
  useEffect(() => {
    if (!code) return;
    const fetchRealtime = () =>
      fetch(`${API}/api/realtime/${code}`)
        .then(r=>r.json()).then(setRealtime).catch(()=>{});
    fetchRealtime();
    const timer = setInterval(fetchRealtime, 300_000);  // 5분 (yfinance 15분 지연 대비 충분)
    return () => clearInterval(timer);
  }, [code]);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior:'smooth' }); }, [chatMessages]);

  // 최근 검색 종목 로드 (localStorage)
  useEffect(() => {
    try { setRecent(JSON.parse(localStorage.getItem('filmn9_recent') || '[]')); } catch {}
  }, []);

  // 현재 종목을 최근 검색에 저장 (기업명 확보 시)
  useEffect(() => {
    const nm = overview?.tab1?.company?.corp_name;
    if (!code || !nm) return;
    setRecent(prev => {
      const next = [{ stock_code: code, corp_name: nm },
                    ...prev.filter(r => r.stock_code !== code)].slice(0, 6);
      try { localStorage.setItem('filmn9_recent', JSON.stringify(next)); } catch {}
      return next;
    });
  }, [code, overview]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (miniRef.current && !miniRef.current.contains(e.target as Node)) setMiniOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const doMiniSearch = async (q: string) => {
    if (!q.trim()) { setMiniResults([]); setMiniOpen(true); return; }  // 빈입력 → 최근검색 표시 유지
    try {
      const res = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}&limit=8`).then(r=>r.json());
      setMiniResults(res.results||[]);
      setMiniOpen(true);
    } catch {}
  };

  // 최근 검색 즉시 저장 (네비게이션 시점)
  const pushRecent = (sc: string, nm: string) => {
    setRecent(prev => {
      const next = [{ stock_code: sc, corp_name: nm || sc },
                    ...prev.filter(r => r.stock_code !== sc)].slice(0, 6);
      try { localStorage.setItem('filmn9_recent', JSON.stringify(next)); } catch {}
      return next;
    });
  };

  // 엔터로 즉시 이동: 입력값을 코드로 해석해 바로 종목 페이지로 push
  const goMiniSearch = async () => {
    const q = miniSearch.trim();
    if (!q) return;
    // 6자리 종목코드를 그대로 입력한 경우
    if (/^[0-9A-Z]{6}$/.test(q)) { router.push(`/stock/${q}`); setMiniOpen(false); return; }
    // 이미 받아온 결과가 있으면 우선 사용 (정확한 기업명 일치 → 없으면 첫 결과)
    let list = miniResults;
    if (!list.length) {
      try {
        const res = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}&limit=8`).then(r=>r.json());
        list = res.results || [];
      } catch {}
    }
    if (!list.length) return;
    const exact = list.find((r:any)=> (r.corp_name||'').replace(/\s/g,'') === q.replace(/\s/g,''))
               || list.find((r:any)=> r.stock_code === q);
    const target = exact || list[0];
    pushRecent(target.stock_code, target.corp_name);
    router.push(`/stock/${target.stock_code}`);
    setMiniOpen(false);
    setMiniSearch('');
  };

  // ─── 파생 데이터 ─────────────────────────────────────────────
  const mv = MOCK_VAL[code || '090430'] || MOCK_VAL['090430'];
  const vd = (valData && valData.is_mock === false) ? valData : mv;
  const company  = overview?.tab1?.company || {};
  const fins: any[] = overview?.tab1?.financials || [];
  const hdr      = overview?.header || {};
  const latest   = fins[0] || {};
  // YoY는 같은 보고서 유형(분기/연간)끼리, 직전 연도와 비교 (fins는 fiscal_year DESC 정렬).
  // 분기 데이터에 연간 데이터가 섞여 있어도(예: 2025 연간+2025 1분기) 같은 reprt_code의 전년 행만 집음.
  const prev     = fins.find((f: any) => f.reprt_code === latest.reprt_code && f.fiscal_year < latest.fiscal_year) || {};
  // 분기/연간 라벨 (reprt_code: 11013=1분기·11012=반기·11014=3분기·그외=연간)
  const _RC: Record<string,string> = {'11013':'1분기','11012':'반기','11014':'3분기'};
  const finLabel = latest.fiscal_year ? `${latest.fiscal_year}${_RC[latest.reprt_code] ? ' '+_RC[latest.reprt_code] : ''}` : '';
  const finSameType = !!prev.reprt_code && latest.reprt_code === prev.reprt_code;  // 전년 동기(같은 유형)가 있을 때만 YoY
  const corpName = company.corp_name || code;

  // ─── 업종명 매핑 (DART KSIC 코드 → 한글 업종명) ──────────────
  // 출처: DART company.json의 induty_code 필드 (한국표준산업분류코드 기반)
  // GPT/Claude 없이 DART API + 매핑테이블로 자동화 가능
  const SECTOR_MAP: Record<string, string> = {
    '20423': '화장품·비누·방향제 제조',
    '20424': '화장품 제조',
    '2622':  '인쇄회로기판·전자부품 제조',
    '26220': '인쇄회로기판·전자부품 제조',
    '63120': '포털·인터넷 정보매개 서비스',
    '63110': '데이터 처리·호스팅 서비스',
    '35111': '화력발전',
    '24111': '철강 제조',
    '30110': '자동차 제조',
    '26110': '반도체 제조',
    '26210': '디스플레이 제조',
  };
  // 업종명: 코드매핑 → WICS(peers, 전 종목 보유) → DART industry → 코드 표기 순
  const industryName = SECTOR_MAP[String(company.sector)] || peers?.wics || company.industry || (company.sector ? `업종코드 ${company.sector}` : '—');

  // ─── 시총 추정 (주주 데이터 기반: 최대주주 지분율 역산) ─────────
  // 출처: DART 주주현황(shareholders) + OHLCV 종가
  // 수식: 총발행주식 ≈ 최대주주보유주식 / (보유비율/100)
  const totalSharesEst = (() => {
    if (!shareholders.length) return null;
    const top = shareholders[0];
    if (!top.shares || !top.ratio || top.ratio <= 0) return null;
    return Math.round(top.shares / (top.ratio / 100));
  })();
  const marketCapCalc = (totalSharesEst && hdr.current_price)
    ? totalSharesEst * hdr.current_price : null;
  const marketCapFinal = company.market_cap || marketCapCalc;

  // OHLCV 기간 필터 (캔들스틱용 — open/high/low/close 포함)
  const filteredOhlcv = (() => {
    if (!ohlcv.length) return [];
    const days = { '1M':30,'3M':90,'6M':180,'1Y':365,'5Y':1825 }[period] || 90;
    const cut = new Date(ohlcv[ohlcv.length-1].date);
    cut.setDate(cut.getDate()-days);
    const cutStr = cut.toISOString().slice(0,10);
    return ohlcv.filter(d=>d.date>=cutStr);
  })();

  // 신용등급 차트 데이터
  const creditChartData = credit.map(r=>({
    year: String(r.year), num: GRADE_TO_NUM[r.grade]||0, grade: r.grade
  }));

  // 건전성 바 설정 + 의미 설명
  const healthMetaMap: Record<string,{label:string;max:number;hint:string}> = {
    debt_ratio:    { label:'부채비율',   max:300, hint:'부채/자본 · 100%↓ 우량, 100~200% 주의, 200%↑ 위험' },
    current_ratio: { label:'유동비율',   max:300, hint:'유동자산/유동부채 · 200%↑ 우량, 150~200% 주의, 150%↓ 위험' },
    op_margin:     { label:'영업이익률', max:30 , hint:'영업이익/매출 · 10%↑ 우량, 5~10% 주의, 5%↓ 위험' },
  };
  const gradeColor: Record<string,string> = {
    green: 'bg-emerald-100 text-emerald-700',
    yellow:'bg-yellow-100 text-yellow-700',
    red:   'bg-red-100 text-red-700',
    gray:  'bg-slate-100 text-slate-500',
  };
  const overallColor = gradeColor[health?.overall_grade] || gradeColor.gray;
  const overallLabel: Record<string,string> = {green:'우량 🟢',yellow:'주의 🟡',red:'위험 🔴',gray:'데이터없음'};

  // 챗봇 — 진짜 RAG 응답 (사업보고서 기반, 8800 서버). NO-MOCK
  const sendChat = async (text?: string) => {
    const msg = text || chatInput;
    if (!msg.trim()) return;
    // 사용자 메시지 + 임시 로딩 메시지 추가
    setChatMessages(prev=>[...prev,
      {text:msg, isUser:true},
      {text:'⏳ 사업보고서를 검색하고 있어요… (10~30초)', isUser:false}]);
    setChatInput('');
    try {
      const res = await fetch(`${CHAT_API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, ticker: code, current_year: 2026 }),
      });
      const d = await res.json();
      let ans = d.answer || '답변을 생성하지 못했습니다.';
      const srcs = (d.sources || []).slice(0,3)
        .map((s:any)=>`· ${s.corp_name||''} ${s.year||''} ${s.section||s.title||''}`.trim())
        .filter(Boolean).join('\n');
      if (srcs) ans += `\n\n📄 출처\n${srcs}`;
      // 로딩 메시지를 실제 답변으로 교체
      setChatMessages(prev=>[...prev.slice(0,-1), {text:ans, isUser:false}]);
    } catch {
      setChatMessages(prev=>[...prev.slice(0,-1),
        {text:'⚠️ 챗봇 서버에 연결하지 못했습니다. (RAG 서버 8800 확인 필요)', isUser:false}]);
    }
  };

  // 종목별 추천 질문 칩 (3개씩)
  const SUGGESTED_BY_CODE: Record<string, string[]> = {
    '090430': [
      '주요 브랜드 포트폴리오는?',
      '중국 의존도와 미국·일본 시장 성과는?',
      'R&D 투자와 기술 경쟁력은?',
    ],
    '009150': [
      'MLCC 시장 지위와 경쟁력은?',
      '전장(자동차) 사업 성장 전망은?',
      '삼성전자 매출 의존도는?',
    ],
    '035420': [
      '주요 사업 부문과 매출 비중은?',
      'AI(하이퍼클로바X)·클라우드 전략은?',
      '주요 규제·경쟁 리스크는?',
    ],
  };
  const suggestedQuestions = SUGGESTED_BY_CODE[code || ''] || [
    '주요 사업은?', '매출 성장률은?', '주요 리스크는?',
  ];

  // ─── 재무제표 테이블 ──────────────────────────────────────────
  const FinTable = ({ data }: { data: any }) => {
    const [expanded, setExpanded] = useState(false);
    if (!data?.items) return <div className="text-sm text-slate-400 text-center py-6">데이터 없음</div>;
    const years = data.fiscal_years || [];
    const rows = data.items;
    const LIMIT = 8;
    const visible = expanded ? rows : rows.slice(0, LIMIT);
    const hasMore = rows.length > LIMIT;
    return (
      <div>
        <div className="flex justify-end mb-2">
          <span className="text-[11px] font-semibold text-indigo-600 bg-indigo-50 border border-indigo-100 dark:bg-indigo-900/40 dark:text-indigo-300 dark:border-indigo-800 px-2.5 py-1 rounded-full">
            단위: {data.unit || '원'}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-100">
                <th className="text-left py-1.5 text-slate-400 font-medium w-48">계정</th>
                {years.map((y:string)=>(
                  <th key={y} className="text-right py-1.5 text-slate-400 font-medium pr-2">{y}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((row:any, i:number)=>{
                const bold = row.account_nm.includes('이익')||row.account_nm.includes('매출액')||row.account_nm.includes('합계');
                return (
                  <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                    <td className={`py-1.5 ${bold?'font-semibold text-slate-800':'text-slate-600'}`}>{row.account_nm}</td>
                    {years.map((y:string)=>{
                      const v = row.values?.[y];
                      return (
                        <td key={y} className={`text-right py-1.5 font-mono pr-2 ${bold?'font-semibold text-slate-800':'text-slate-600'}`}>
                          {v!=null?v.toLocaleString():'—'}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {hasMore && (
          <button onClick={() => setExpanded(e => !e)}
            className="w-full mt-2 py-2 flex items-center justify-center gap-1 text-xs text-slate-400 hover:text-indigo-600 hover:bg-slate-50 rounded-lg transition-colors">
            {expanded ? '접기 ▲' : `더보기 (${rows.length - LIMIT}개 더) ▼`}
          </button>
        )}
      </div>
    );
  };

  // ─── 로딩 스켈레톤 ────────────────────────────────────────────
  const LoadingSkeleton = () => (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">
      <Skeleton className="h-36 w-full rounded-2xl" />
      <div className="grid grid-cols-12 gap-5">
        <div className="col-span-8 space-y-4">
          <Skeleton className="h-48 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
        <div className="col-span-4 space-y-4">
          <Skeleton className="h-64 rounded-xl" />
          <Skeleton className="h-32 rounded-xl" />
        </div>
      </div>
    </div>
  );

  // ─── 렌더 ────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900">

      {/* ── DART 뷰어 팝업 (드래그·8방향 리사이즈·전체화면·다중탭) ── */}
      {dartViewer && (() => {
        const fs = dartViewer.isFullscreen;
        const activeTab = dartViewer.tabs[dartViewer.activeIdx];
        const style: React.CSSProperties = fs
          ? { position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', zIndex: 110 }
          : { position: 'fixed', top: dartViewer.pos.y, left: dartViewer.pos.x,
              width: dartViewer.size.w, height: dartViewer.size.h, zIndex: 110 };
        return (
          <>
            {!fs && <div className="fixed inset-0 z-[105] bg-black/20 pointer-events-none" />}
            <div style={style}
                 className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl flex flex-col border-2 border-indigo-500/40 overflow-hidden">
              {/* 헤더 (드래그 영역) */}
              <div className={`flex items-center px-4 py-2 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 ${fs ? '' : 'cursor-move'} select-none`}
                   onMouseDown={fs ? undefined : startDartDrag}>
                <span className="px-2 py-0.5 bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300 text-xs font-bold rounded flex-shrink-0">DART 공시</span>
                <span className="ml-2 text-xs text-slate-500 hidden sm:inline">
                  {dartViewer.tabs.length > 1 ? `${dartViewer.tabs.length}개 동시 열림 (최대 5)` : (fs ? '전체화면' : '드래그·모서리 리사이즈 가능')}
                </span>
                <div className="ml-auto flex items-center gap-1 flex-shrink-0" onMouseDown={(e)=>e.stopPropagation()}>
                  <a href={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${activeTab.rcept_no}`}
                     target="_blank" rel="noreferrer"
                     className="text-xs text-slate-500 hover:text-indigo-600 px-2 py-1 rounded border border-slate-200 dark:border-slate-600">
                    새 탭 ↗
                  </a>
                  <button onClick={toggleDartFullscreen}
                          title={fs ? '원래 크기' : '전체화면'}
                          className="w-8 h-8 rounded hover:bg-slate-200 dark:hover:bg-slate-700 flex items-center justify-center text-slate-600 dark:text-slate-300 text-base">
                    {fs ? '⊟' : '⛶'}
                  </button>
                  <button onClick={()=>setDartViewer(null)}
                          title="모두 닫기"
                          className="w-8 h-8 rounded-full hover:bg-red-100 hover:text-red-700 dark:hover:bg-red-900 flex items-center justify-center text-slate-500 font-bold">
                    ✕
                  </button>
                </div>
              </div>

              {/* 탭 바 (공시 여러 개) */}
              <div className="flex items-stretch gap-0.5 px-2 py-1 bg-slate-100 dark:bg-slate-900/50 overflow-x-auto border-b border-slate-200 dark:border-slate-700"
                   onMouseDown={(e)=>e.stopPropagation()}>
                {dartViewer.tabs.map((tab, i) => (
                  <div key={tab.rcept_no}
                       className={`flex items-center gap-1 px-3 py-1.5 rounded-t cursor-pointer max-w-[280px] flex-shrink-0 group ${
                         i === dartViewer.activeIdx
                           ? 'bg-white dark:bg-slate-800 border-t border-l border-r border-slate-300 dark:border-slate-600 text-slate-800 dark:text-slate-100 font-semibold'
                           : 'bg-slate-200/60 dark:bg-slate-700/50 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
                       }`}
                       onClick={()=>setDartViewer(prev => prev ? { ...prev, activeIdx: i } : prev)}>
                    <span className="text-xs truncate" title={tab.title}>{tab.title}</span>
                    <button onClick={(e)=>{e.stopPropagation(); detachTab(i);}}
                            title="새 창으로 분리"
                            className="w-4 h-4 rounded hover:bg-indigo-200 dark:hover:bg-indigo-700 flex items-center justify-center text-indigo-500 text-[10px] opacity-60 group-hover:opacity-100">
                      🗗
                    </button>
                    <button onClick={(e)=>{e.stopPropagation(); closeDartTab(i);}}
                            title="탭 닫기"
                            className="w-4 h-4 rounded-full hover:bg-slate-300 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 text-[10px] opacity-60 group-hover:opacity-100">
                      ✕
                    </button>
                  </div>
                ))}
                <div className="flex items-center px-2 text-[10px] text-slate-400 whitespace-nowrap">
                  💡 새 공시 클릭 → 탭 추가 · 🗗 → 별도 창 분리
                </div>
              </div>

              {/* iframe 본문 */}
              <iframe src={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${activeTab.rcept_no}`}
                      key={activeTab.rcept_no}
                      className="flex-1 w-full"
                      style={{border:'none'}}
                      title={activeTab.title}
                      sandbox="allow-scripts allow-same-origin allow-forms allow-popups"/>

              {/* 8방향 리사이즈 핸들 (전체화면 아닐 때만) */}
              {!fs && (
                <>
                  <div onMouseDown={startDartResize('nw')} className="absolute top-0 left-0 w-3 h-3 cursor-nwse-resize z-10" />
                  <div onMouseDown={startDartResize('ne')} className="absolute top-0 right-0 w-3 h-3 cursor-nesw-resize z-10" />
                  <div onMouseDown={startDartResize('sw')} className="absolute bottom-0 left-0 w-3 h-3 cursor-nesw-resize z-10" />
                  <div onMouseDown={startDartResize('se')} className="absolute bottom-0 right-0 w-3 h-3 cursor-nwse-resize z-10" />
                  <div onMouseDown={startDartResize('n')} className="absolute top-0 left-3 right-3 h-1 cursor-ns-resize z-10" />
                  <div onMouseDown={startDartResize('s')} className="absolute bottom-0 left-3 right-3 h-1 cursor-ns-resize z-10" />
                  <div onMouseDown={startDartResize('w')} className="absolute left-0 top-3 bottom-3 w-1 cursor-ew-resize z-10" />
                  <div onMouseDown={startDartResize('e')} className="absolute right-0 top-3 bottom-3 w-1 cursor-ew-resize z-10" />
                </>
              )}
            </div>
          </>
        );
      })()}

      {/* ── 분리된 독립 DART 팝업들 ── */}
      {detachedDarts.map((p) => {
        const fs = p.isFullscreen;
        const style: React.CSSProperties = fs
          ? { position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', zIndex: 115 }
          : { position: 'fixed', top: p.pos.y, left: p.pos.x, width: p.size.w, height: p.size.h, zIndex: 112 };
        return (
          <div key={p.id} style={style}
               className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl flex flex-col border-2 border-emerald-500/50 overflow-hidden">
            {/* 헤더 (드래그 영역) */}
            <div className={`flex items-center px-4 py-2 border-b border-slate-200 dark:border-slate-700 bg-emerald-50 dark:bg-emerald-900/20 ${fs ? '' : 'cursor-move'} select-none`}
                 onMouseDown={fs ? undefined : startDetachedDrag(p.id)}>
              <span className="px-2 py-0.5 bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300 text-xs font-bold rounded flex-shrink-0">분리 창</span>
              <span className="ml-2 font-semibold text-slate-800 dark:text-slate-100 truncate text-xs">{p.title}</span>
              <div className="ml-auto flex items-center gap-1 flex-shrink-0" onMouseDown={(e)=>e.stopPropagation()}>
                <a href={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${p.rcept_no}`}
                   target="_blank" rel="noreferrer"
                   className="text-xs text-slate-500 hover:text-indigo-600 px-2 py-1 rounded border border-slate-200 dark:border-slate-600">
                  새 탭 ↗
                </a>
                <button onClick={()=>toggleDetachedFullscreen(p.id)}
                        title={fs ? '원래 크기' : '전체화면'}
                        className="w-8 h-8 rounded hover:bg-slate-200 dark:hover:bg-slate-700 flex items-center justify-center text-slate-600 dark:text-slate-300 text-base">
                  {fs ? '⊟' : '⛶'}
                </button>
                <button onClick={()=>closeDetached(p.id)}
                        title="닫기"
                        className="w-8 h-8 rounded-full hover:bg-red-100 hover:text-red-700 dark:hover:bg-red-900 flex items-center justify-center text-slate-500 font-bold">
                  ✕
                </button>
              </div>
            </div>
            <iframe src={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${p.rcept_no}`}
                    className="flex-1 w-full"
                    style={{border:'none'}}
                    title={p.title}
                    sandbox="allow-scripts allow-same-origin allow-forms allow-popups"/>
            {/* 8방향 리사이즈 핸들 */}
            {!fs && (
              <>
                <div onMouseDown={startDetachedResize(p.id, 'nw')} className="absolute top-0 left-0 w-3 h-3 cursor-nwse-resize z-10" />
                <div onMouseDown={startDetachedResize(p.id, 'ne')} className="absolute top-0 right-0 w-3 h-3 cursor-nesw-resize z-10" />
                <div onMouseDown={startDetachedResize(p.id, 'sw')} className="absolute bottom-0 left-0 w-3 h-3 cursor-nesw-resize z-10" />
                <div onMouseDown={startDetachedResize(p.id, 'se')} className="absolute bottom-0 right-0 w-3 h-3 cursor-nwse-resize z-10" />
                <div onMouseDown={startDetachedResize(p.id, 'n')} className="absolute top-0 left-3 right-3 h-1 cursor-ns-resize z-10" />
                <div onMouseDown={startDetachedResize(p.id, 's')} className="absolute bottom-0 left-3 right-3 h-1 cursor-ns-resize z-10" />
                <div onMouseDown={startDetachedResize(p.id, 'w')} className="absolute left-0 top-3 bottom-3 w-1 cursor-ew-resize z-10" />
                <div onMouseDown={startDetachedResize(p.id, 'e')} className="absolute right-0 top-3 bottom-3 w-1 cursor-ew-resize z-10" />
              </>
            )}
          </div>
        );
      })}

      {/* ── 헤더 ── */}
      <header className="sticky top-0 z-50 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 h-14 shadow-sm">
        <div className="max-w-7xl mx-auto h-full flex items-center gap-3 px-4">

          {/* 로고 */}
          <Link href="/" className="text-xl font-extrabold text-indigo-600 hover:text-indigo-700 transition-colors flex-shrink-0">
            FINSIGHT
          </Link>

          {/* 미니 검색 */}
          <div className="relative hidden sm:flex" ref={miniRef}>
            <input
              value={miniSearch}
              onChange={e=>{setMiniSearch(e.target.value);doMiniSearch(e.target.value);}}
              onFocus={()=>setMiniOpen(true)}
              onKeyDown={e=>{ if(e.key==='Enter'){ e.preventDefault(); goMiniSearch(); } }}
              placeholder="다른 종목 검색... (엔터로 이동)"
              className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 outline-none w-48 bg-slate-50 focus:border-indigo-400 focus:bg-white transition-all dark:bg-slate-700 dark:border-slate-600 dark:text-white"
            />
            {/* 입력 중 → 검색결과 / 입력 없음 + 포커스 → 최근 검색 3개 */}
            {miniOpen && miniSearch.trim() && miniResults.length>0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-slate-200 rounded-xl shadow-xl z-50 overflow-hidden">
                {miniResults.map(r=>(
                  <button key={r.stock_code} onClick={()=>{pushRecent(r.stock_code, r.corp_name);router.push(`/stock/${r.stock_code}`);setMiniOpen(false);}}
                    className="w-full flex items-center gap-2 px-3 py-2 hover:bg-indigo-50 text-left">
                    <span className="font-mono text-xs text-slate-400 w-14">{r.stock_code}</span>
                    <span className="text-sm font-semibold text-slate-800">{r.corp_name}</span>
                  </button>
                ))}
              </div>
            )}
            {miniOpen && !miniSearch.trim() && recent.filter(r=>r.stock_code!==code).length>0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-slate-200 rounded-xl shadow-xl z-50 overflow-hidden dark:bg-slate-800 dark:border-slate-700">
                <div className="px-3 py-1.5 text-[10px] font-semibold text-slate-400 border-b border-slate-100 dark:border-slate-700">🕘 최근 검색</div>
                {recent.filter(r=>r.stock_code!==code).slice(0,3).map(r=>(
                  <button key={r.stock_code} onClick={()=>{router.push(`/stock/${r.stock_code}`);setMiniOpen(false);}}
                    className="w-full flex items-center gap-2 px-3 py-2 hover:bg-indigo-50 dark:hover:bg-slate-700 text-left">
                    <span className="font-mono text-xs text-slate-400 w-14">{r.stock_code}</span>
                    <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">{r.corp_name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 종목 정보 + 실시간 주가 */}
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <span className="font-mono text-xs text-slate-400 hidden sm:inline">{code}</span>
            <span className="font-bold text-slate-800 dark:text-white text-sm truncate">{corpName}</span>
            {company.market && (
              <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white bg-blue-600 flex-shrink-0">{company.market}</span>
            )}
            {industryName && industryName !== '—' && (
              <span className="text-xs text-slate-400 flex-shrink-0 hidden lg:inline">
                {industryName} <span className="text-slate-300 text-[10px]">(WICS)</span>
              </span>
            )}
            {(realtime?.price || hdr.current_price) && (
              <div className="hidden md:flex items-center gap-1.5 ml-2 flex-wrap">
                <span className="font-mono text-sm font-extrabold text-slate-800 dark:text-white">
                  {fmtPrice(realtime?.price || hdr.current_price)}
                </span>
                {hdr.change != null && (
                  <span className={`text-xs font-semibold ${hdr.change>=0?'text-red-500':'text-blue-500'}`}>
                    {hdr.change>=0?'+':''}{hdr.change?.toLocaleString()} ({hdr.change>=0?'+':''}{hdr.change_pct?.toFixed(1)}%)
                  </span>
                )}
                {/* 출처·기준시점 */}
                <span className="text-xs text-slate-400 font-normal">
                  {realtime?.price_time
                    ? `(Yahoo Finance ${realtime.price_time} KST, ~15분 지연${realtime.is_market_open ? ' · 장중' : ' · 장마감'})`
                    : '(KRX 전일 종가)'}
                </span>
              </div>
            )}
          </div>

          {/* 다크모드 토글 */}
          <button onClick={toggleDark}
            className="w-8 h-8 rounded-full bg-slate-100 hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600 flex items-center justify-center transition-colors flex-shrink-0"
            title="다크모드 토글">
            <span className="text-sm">{dark ? '☀️' : '🌙'}</span>
          </button>
        </div>
      </header>

      {/* ── 탭 바 (헤더 바로 아래, sticky) ── */}
      <div className="sticky top-14 z-40 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 flex h-11">
          {(['overview','valuation','ai'] as MainTab[]).map(t => {
            const label = {overview:'기업개요', valuation:'밸류에이션', ai:'AI 챗봇'}[t];
            return (
              <button key={t} onClick={() => setMainTab(t)}
                className={`px-5 text-sm h-full border-b-2 transition-colors whitespace-nowrap ${mainTab===t
                  ? 'border-indigo-600 text-indigo-700 font-bold'
                  : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* ═══ 로딩 중 ═══ */}
      {loadingMain && <LoadingSkeleton />}

      {/* ═══ TAB1: 기업개요 ═══ */}
      {!loadingMain && mainTab === 'overview' && (
        <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">

          {/* Hero 배너 */}
          <div className="rounded-2xl p-6 text-white" style={{background:'linear-gradient(135deg,#0A1628,#1E3A8A)'}}>
            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs px-2 py-0.5 rounded font-mono" style={{background:'rgba(255,255,255,0.15)'}}>{code}</span>
                  {company.market && <span className="text-xs px-2 py-0.5 rounded" style={{background:'rgba(255,255,255,0.15)'}}>{company.market}</span>}
                </div>
                <h2 className="text-2xl font-bold mb-1">{corpName}</h2>
                {industryName && industryName !== '—' && (
                  <p className="text-xs opacity-55 mb-0.5">
                    {industryName} <span className="opacity-70">(WICS)</span>
                  </p>
                )}
                <p className="text-sm opacity-70">
                  시총 <span className="font-mono font-semibold">
                    {realtime?.market_cap
                      ? fmtWon(realtime.market_cap)+'원'
                      : marketCapFinal ? fmtWon(marketCapFinal)+'원' : '—'}
                  </span>
                  {company.ceo && <span className="ml-3">대표 {company.ceo}</span>}
                </p>
              </div>
              <div className="text-right">
                {/* 실시간 주가 (yfinance ~15분 지연) */}
                <div className="text-3xl font-extrabold font-mono">
                  {realtime?.price
                    ? fmtPrice(realtime.price)
                    : fmtPrice(hdr.current_price)}
                </div>
                {hdr.change != null && (
                  <div className={`text-sm mt-0.5 ${hdr.change>=0?'text-red-300':'text-blue-300'}`}>
                    {hdr.change>=0?'+':''}{hdr.change?.toLocaleString()} ({hdr.change>=0?'+':''}{hdr.change_pct?.toFixed(1)}%)
                  </div>
                )}
                {/* 출처·시점 표시 */}
                <div className="mt-2 text-right">
                  {realtime?.price_time ? (
                    <span className="text-xs opacity-50 font-mono">
                      {realtime.is_market_open ? '🟢 장중 ' : '⚫ 장마감 '}
                      Yahoo Finance · {realtime.price_time} KST (~15분 지연)
                    </span>
                  ) : (
                    <span className="text-xs opacity-50 font-mono">KRX 전일 종가 기준</span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* ── 1컬럼 메인 레이아웃 ── */}
          <div className="space-y-5">

            {/* 히스토리 브리핑 */}
            {(() => {
              const hist  = overview?.tab1?.history;
              const brief = hist?.brief;
              if (!brief) return (
                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-5">
                  <div className="text-sm font-bold text-slate-700 dark:text-slate-200 mb-3">📖 히스토리 브리핑</div>
                  <div className="text-sm text-slate-400 bg-slate-50 dark:bg-slate-700 rounded-lg px-4 py-3 text-center mb-4">
                    분석 데이터 준비 중 (데이터 도착 시 자동 반영)
                  </div>
                  {news.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-slate-400 mb-2">📰 최신 뉴스</div>
                      <div className="space-y-1.5">
                        {news.map((n, i) => (
                          <a key={i} href={n.link} target="_blank" rel="noreferrer"
                            className="flex items-start gap-2 group hover:bg-slate-50 dark:hover:bg-slate-700 rounded-lg px-2 py-1.5 transition-colors">
                            <span className="text-xs text-slate-300 w-24 flex-shrink-0 font-mono">{n.pubdate?.slice(5,16)}</span>
                            <span className="text-xs text-slate-700 dark:text-slate-300 group-hover:text-indigo-600 flex-1">{n.title}</span>
                            <svg className="w-3 h-3 text-slate-300 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
                            </svg>
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
              return (
                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-sm font-bold text-slate-700 dark:text-slate-200">📖 히스토리 브리핑</span>
                    <div className="flex items-center gap-2">
                      {hist.meta?.wics && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600 border border-indigo-200 font-medium">
                          {hist.meta.wics}
                        </span>
                      )}
                      <span className="text-xs text-slate-300">{hist._generated_at?.slice(0,10)}</span>
                    </div>
                  </div>
                  <div className="mb-4">
                    <div className="text-xs font-semibold text-slate-400 mb-1.5">🏢 기업 개요</div>
                    <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{brief.company_overview}</p>
                  </div>
                  {brief.business_model && (
                    <div className="mb-4">
                      <div className="text-xs font-semibold text-slate-400 mb-1.5">💼 사업 모델</div>
                      <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{brief.business_model}</p>
                    </div>
                  )}
                  {/* ── 고객사 & 경쟁사 (히스토리 브리핑 3번) ── */}
                  {peers && (peers.competitors?.length > 0 || peers.customers) && (
                    <div className="mb-4">
                      <div className="text-xs font-semibold text-slate-400 mb-2">🤝 고객사 &amp; 경쟁사</div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {/* 고객사 */}
                        <div className="bg-slate-50 dark:bg-slate-700 rounded-lg px-3 py-2">
                          <div className="flex items-center gap-1.5 mb-1">
                            <span className="text-xs font-semibold text-emerald-600 dark:text-emerald-400">고객사</span>
                            {peers.customers?.type && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">
                                {({B2B:'B2B (기업)', B2C:'B2C (개인)', MIXED:'B2B+B2C'} as any)[peers.customers.type] || peers.customers.type}
                              </span>
                            )}
                          </div>
                          {peers.customers?.items?.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {peers.customers.items.map((c: string, i: number) => (
                                <span key={i} className={`text-xs px-2 py-0.5 rounded-full border ${c.includes('일반 소비자')||c.includes('불특정')
                                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-300 dark:border-emerald-700'
                                  : 'bg-white dark:bg-slate-600 border-slate-200 dark:border-slate-500 text-slate-700 dark:text-slate-200'}`}>
                                  {c}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <div className="text-xs text-slate-400">정보 없음</div>
                          )}
                          {peers.customers?.channels && (
                            <div className="text-[10px] text-slate-400 mt-1.5">🛒 판매채널: {peers.customers.channels}</div>
                          )}
                        </div>
                        {/* 경쟁사 */}
                        <div className="bg-slate-50 dark:bg-slate-700 rounded-lg px-3 py-2">
                          <div className="flex items-center gap-1.5 mb-1">
                            <span className="text-xs font-semibold text-indigo-600 dark:text-indigo-400">경쟁사</span>
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300">
                              동종업계 · 사업유사도
                            </span>
                          </div>
                          {peers.competitors?.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {peers.competitors.map((c: any, i: number) => (
                                <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-white dark:bg-slate-600 border border-slate-200 dark:border-slate-500 text-slate-700 dark:text-slate-200">
                                  {c.name}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <div className="text-xs text-slate-400">정보 없음</div>
                          )}
                        </div>
                      </div>
                      {peers.customers?.source_text && (
                        <div className="text-[10px] text-slate-400 mt-1.5 leading-relaxed line-clamp-2">
                          📄 {peers.customers.source_text}
                        </div>
                      )}
                    </div>
                  )}

                  {brief.price_factors?.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-slate-400 mb-2">📌 주가 영향 요인</div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {brief.price_factors.map((f: any, i: number) => (
                          <div key={i} className="bg-slate-50 dark:bg-slate-700 rounded-lg px-3 py-2">
                            <div className="text-xs font-semibold text-slate-600 dark:text-slate-300 mb-0.5">{f.factor}</div>
                            <div className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">{f.detail}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {/* ── 최신 뉴스 ── */}
                  <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-700">
                    <div className="text-xs font-semibold text-slate-400 mb-2">📰 최신 뉴스</div>
                    {news.length > 0 ? (
                      <div className="space-y-1.5">
                        {news.map((n, i) => (
                          <a key={i} href={n.link} target="_blank" rel="noreferrer"
                            className="flex items-start gap-2 group hover:bg-slate-50 dark:hover:bg-slate-700 rounded-lg px-2 py-1.5 transition-colors">
                            <span className="text-xs text-slate-300 w-24 flex-shrink-0 mt-0.5 font-mono">
                              {n.pubdate ? n.pubdate.slice(5,16) : ''}
                            </span>
                            <span className="text-xs text-slate-700 dark:text-slate-300 group-hover:text-indigo-600 dark:group-hover:text-indigo-400 leading-relaxed flex-1">
                              {n.title}
                            </span>
                            <svg className="w-3 h-3 text-slate-300 group-hover:text-indigo-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
                            </svg>
                          </a>
                        ))}
                        <div className="text-xs text-slate-300 px-2 mt-1">출처: 네이버 검색 (실패 시 파이낸셜뉴스 · 한국경제)</div>
                      </div>
                    ) : (
                      <div className="text-xs text-slate-400 px-2 py-2 bg-slate-50 dark:bg-slate-700 rounded-lg text-center">
                        뉴스 로딩 중...
                      </div>
                    )}
                  </div>

                  <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-700 flex items-center gap-2 text-xs text-slate-300">
                    <span>출처: DART 사업보고서 ({hist._llm_model})</span>
                    {hist._source === 'file' && <span className="text-amber-400">· 로컬 파일</span>}
                    {brief.confidence && <span className="ml-auto">신뢰도: {brief.confidence}</span>}
                  </div>
                </div>
              );
            })()}

            {/* 계열회사 구조 — 접이식 토글 (히스토리·최신뉴스 다음, 주가차트 앞) */}
            <AffiliateToggle code={code} />

            {/* 주가 차트 - full width */}
            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
              <div className="px-5 pt-4 pb-2 flex items-center justify-between border-b border-slate-100">
                <span className="text-sm font-bold text-slate-700">📈 주가 차트</span>
                <div className="text-xs text-slate-400">MA · 볼린저밴드 · 거래량</div>
              </div>
              <div className="p-3">
                {listStatus && !listStatus.tradable
                  ? <ListingStatusBanner s={listStatus} />
                  : <FullChart data={ohlcv} />}
              </div>
            </div>

            {/* ── 재무 하이라이트 (주가차트 바로 아래, full width) ── */}
            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-5">
              <div className="text-sm font-bold text-slate-700 dark:text-slate-200 mb-3">💰 재무 하이라이트 <span className="text-xs font-normal text-slate-400">(연결 기준)</span></div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {[
                  {label:'매출액',    key:'revenue',    icon:'💰'},
                  {label:'영업이익', key:'op_income',  icon:'📊'},
                  {label:'당기순이익',key:'net_income', icon:'💵'},
                ].map(({label,key,icon})=>{
                  const v = latest[key], pv = prev[key];
                  const yoy = (finSameType && pv) ? (v-pv)/Math.abs(pv)*100 : null;
                  return (
                    <div key={key} className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-700 rounded-xl">
                      <div>
                        <div className="text-xs text-slate-400">{icon} {label} ({finLabel})</div>
                        <div className="text-lg font-extrabold text-slate-800 dark:text-white font-mono mt-0.5">{fmtAmt(v)}원</div>
                      </div>
                      <div className="flex flex-col items-end gap-0.5 shrink-0"
                        title={yoy!=null ? `전년 동기(${prev.fiscal_year} ${_RC[prev.reprt_code]||'연간'}) 대비 증감률` : '전년 동기 데이터 없음'}>
                        <span className="text-[9px] leading-none text-slate-400 font-semibold tracking-wide">YoY <span className="font-normal">(전년比)</span></span>
                        <div
                          className={`text-xs font-bold px-2 py-1 rounded-full ${yoy!=null && yoy>=0 ? 'bg-red-50 text-red-600' : 'bg-blue-50 text-blue-600'}`}>
                          {yoyText(yoy) || '—'}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* ── 재무 건전성 + 주주 구성 (2컬럼) ── */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* 재무 건전성 */}
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-bold text-slate-700 dark:text-slate-200 inline-flex items-center">
                    💪 재무 건전성 <span className="text-xs font-normal text-slate-400 ml-1">(연결 기준)</span>
                    {/* ⓘ 등급 설명 툴팁 */}
                    <span className="group relative inline-flex items-center ml-1.5 cursor-help align-middle">
                      <span className="flex items-center justify-center w-4 h-4 rounded-full bg-slate-300 dark:bg-slate-600 text-white text-[10px] font-bold leading-none">i</span>
                      <div className="hidden group-hover:block absolute z-50 p-3 bg-slate-800 text-white text-[11px] leading-relaxed rounded-lg shadow-xl border border-slate-700 font-normal text-left"
                           style={{width:'18rem', left:'1.4rem', top:0, whiteSpace:'normal'}}>
                        <div className="font-bold mb-1.5 text-slate-100">등급 의미</div>
                        <div className="mb-0.5">🟢 <b>우량</b> = 좋음 (안전)</div>
                        <div className="mb-0.5">🟡 <b>주의</b> = 보통 · 경계</div>
                        <div className="mb-2">🔴 <b>위험</b> = 나쁨</div>
                        <div className="font-bold mb-1 text-slate-100">등급 기준</div>
                        <div>• 부채비율: 100%↓ 🟢 · 100~200% 🟡 · 200%↑ 🔴</div>
                        <div>• 유동비율: 200%↑ 🟢 · 150~200% 🟡 · 150%↓ 🔴</div>
                        <div>• 영업이익률: 10%↑ 🟢 · 5~10% 🟡 · 5%↓ 🔴</div>
                        <div className="mt-1.5 text-[10px] text-slate-400">출처: 2025 사업보고서(연결) 자동 계산</div>
                      </div>
                    </span>
                  </span>
                  {health && <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${overallColor}`}>
                    {overallLabel[health.overall_grade]||'—'}
                  </span>}
                </div>
                {health ? (
                  <div className="space-y-4">
                    {Object.entries(health.metrics||{}).map(([k,m]:any)=>{
                      const meta = healthMetaMap[k] || {label:k,max:100,hint:''};
                      const pct = m.value!=null ? Math.min(100,(m.value/meta.max)*100) : 0;
                      const barCol = {green:'#10B981',yellow:'#F59E0B',red:'#EF4444',gray:'#CBD5E1'}[m.grade as string]||'#CBD5E1';
                      const gradeBadge = {green:'우량',yellow:'주의',red:'위험',gray:'—'}[m.grade as string]||'—';
                      return (
                        <div key={k}>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 w-20">{meta.label}</span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                              m.grade==='green'?'bg-emerald-100 text-emerald-700':
                              m.grade==='yellow'?'bg-yellow-100 text-yellow-700':
                              m.grade==='red'?'bg-red-100 text-red-700':'bg-slate-100 text-slate-500'
                            }`}>{gradeBadge}</span>
                            <span className="ml-auto text-xs font-mono font-bold text-slate-700 dark:text-slate-200">
                              {m.value!=null?m.value.toFixed(2)+'%':'—'}
                            </span>
                          </div>
                          <div className="bg-slate-100 dark:bg-slate-700 rounded-full h-1.5">
                            <div className="h-1.5 rounded-full transition-all" style={{width:`${pct}%`,background:barCol}}/>
                          </div>
                          <div className="text-[10px] text-slate-400 mt-1">{meta.hint}</div>
                        </div>
                      );
                    })}
                  </div>
                ) : <div className="text-xs text-slate-400 text-center py-2">데이터 없음</div>}
              </div>

              {/* 주주 구성 */}
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-5">
                <div className="flex items-center justify-between mb-3">
                  <div className="text-sm font-bold text-slate-700 dark:text-slate-200">🍩 주주 구성</div>
                  <div className="text-[10px] text-slate-400">출처: DART 사업보고서</div>
                </div>
                {(() => {
                  const list = shareholders.filter(r => (r.ratio||0) > 0).slice(0,8);
                  if (list.length === 0) return <div className="text-xs text-slate-400 text-center py-4">데이터 없음</div>;
                  const fmtPct = (v:number) => v >= 1 ? v.toFixed(2) + '%' : v >= 0.01 ? v.toFixed(3) + '%' : v.toFixed(4) + '%';
                  const relColor = (rel:string) => {
                    if (rel?.includes('최대주주') && rel?.includes('본인')) return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300';
                    if (rel?.includes('5%')) return 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300';
                    if (rel?.includes('계열')) return 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300';
                    if (rel?.includes('임원')) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300';
                    return 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300';
                  };
                  return (
                    <div className="flex gap-3 items-start">
                      <PieChart width={120} height={120}>
                        <Pie data={list} dataKey="ratio" cx={55} cy={55} innerRadius={32} outerRadius={52} paddingAngle={2}>
                          {list.map((_,i)=><Cell key={i} fill={DONUT_COLORS[i%DONUT_COLORS.length]}/>)}
                        </Pie>
                      </PieChart>
                      <div className="space-y-1 flex-1 min-w-0">
                        {list.map((r,i)=>(
                          <div key={i} className="flex items-center gap-1.5 text-xs">
                            <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{background:DONUT_COLORS[i%DONUT_COLORS.length]}}/>
                            <span className="flex-1 text-slate-700 dark:text-slate-300 truncate" title={r.name}>{r.name}</span>
                            {r.relation && <span className={`text-[9px] px-1 py-0.5 rounded ${relColor(r.relation)}`}>{r.relation.length>6 ? r.relation.slice(0,5)+'…' : r.relation}</span>}
                            <span className="font-mono font-semibold text-xs w-16 text-right">{fmtPct(r.ratio||0)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>

            {/* 재무제표 (B/S · I/S · 손익흐름도) */}
            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-5">
              <div className="flex gap-1 mb-4 border-b border-slate-100 dark:border-slate-700 pb-3">
                {(['SANKEY','BS','IS'] as FinTab[]).map(t=>(
                  <button key={t} onClick={()=>setFinTab(t)}
                    className={`px-4 py-1.5 text-xs rounded-full font-semibold transition-colors ${finTab===t
                      ? 'text-white bg-indigo-600'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300'}`}>
                    {t==='BS'?`재무상태표(${bsData?.scope||'연결'})`:t==='IS'?`손익계산서(${isData?.scope||'연결'})`:'손익흐름도'}
                  </button>
                ))}
              </div>
              {listStatus && !listStatus.tradable && (
                <div className="mb-3"><ListingStatusBanner s={listStatus} compact /></div>
              )}
              {finTab==='BS' && <FinTable data={bsData}/>}
              {finTab==='IS' && <FinTable data={isData}/>}
              {finTab==='SANKEY' && (
                <iframe src={`${API}/sankey/${code}`} className="w-full rounded-lg" style={{height:520,border:'none'}}/>
              )}
            </div>

            {/* ── 기업 개요 + 경영인 (2컬럼) ── */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* 기업 개요 */}
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-5">
                <div className="text-sm font-bold text-slate-700 dark:text-slate-200 mb-3">🏢 기업 개요</div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                  {[
                    ['시총',     realtime?.market_cap ? fmtWon(realtime.market_cap)+'원' : marketCapFinal ? fmtWon(marketCapFinal)+'원' : '—'],
                    ['업종',     industryName],
                    ['대표이사', company.ceo || '—'],
                    ['결산월',   company.fiscal_month ? company.fiscal_month+'월' : '—'],
                    ['상장일',   (()=>{ const d=String(company.listing_date||company.listed_date||''); const m=d.match(/^(\d{4})(\d{2})(\d{2})$/); return m?`${m[1]}-${m[2]}-${m[3]}`:(d||'—'); })()],
                    ['주소',     company.address ? company.address.slice(0,18)+'…' : '—'],
                    ['홈페이지', company.homepage || '—'],
                    ['전화',     company.phone || '—'],
                  ].map(([k,v])=>(
                    <div key={k}>
                      <div className="text-slate-400 font-medium mb-0.5">{k}</div>
                      <div className="text-slate-700 dark:text-slate-300 truncate">{v||'—'}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 경영인 */}
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-5">
                <div className="flex items-center justify-between mb-3">
                  <div className="text-sm font-bold text-slate-700 dark:text-slate-200">👤 경영인 <span className="text-xs font-normal text-slate-400">({executives.length}명)</span></div>
                </div>
                {executives.length>0 ? (
                  <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
                    {executives.map((e,i)=>{
                      const isInside = (e.role||'').includes('사내') || (e.position||'').match(/사장|회장|부사장|대표/);
                      const isOutside = (e.role||'').includes('사외');
                      const age = e.birth_year ? (new Date().getFullYear() - parseInt(e.birth_year)) : null;
                      return (
                        <div key={i} className="border border-slate-100 dark:border-slate-700 rounded-lg p-2.5 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-semibold text-sm text-slate-800 dark:text-slate-100">{e.name||'—'}</span>
                            <span className="text-xs text-slate-500">{e.position||'—'}</span>
                            {isInside && <span className="text-[10px] px-1.5 py-0.5 bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300 rounded">사내</span>}
                            {isOutside && <span className="text-[10px] px-1.5 py-0.5 bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300 rounded">사외</span>}
                            {age && <span className="text-[10px] text-slate-400 ml-auto">{age}세 ({e.birth_year})</span>}
                          </div>
                          {e.role && <div className="text-[11px] text-slate-500 mb-1">{e.role}</div>}
                          {e.career && (
                            <div className="text-[11px] text-slate-600 dark:text-slate-400 leading-relaxed whitespace-pre-line line-clamp-3">
                              {e.career.replace(/ㆍ/g, '· ')}
                            </div>
                          )}
                          {e.appointed_at && <div className="text-[10px] text-slate-400 mt-1">재임 {e.appointed_at}</div>}
                        </div>
                      );
                    })}
                  </div>
                ) : <div className="text-xs text-slate-400 text-center py-4">데이터 없음</div>}
              </div>
            </div>

            {/* ── 공시 (탭: 전자공시 / 공급계약) ── */}
            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-5">
              <div className="flex items-center gap-1 mb-3 border-b border-slate-100 dark:border-slate-700 pb-2">
                <button onClick={()=>{
                    setDiscTab('dart'); setDartViewer(null);
                    if (!dartList) { setDartLoading(true); fetchDartList(); }
                  }}
                  className={`px-3 py-1 text-xs rounded-full font-semibold transition-colors ${discTab==='dart'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300'}`}>
                  📋 전자공시
                </button>
                <button onClick={()=>{
                    setDiscTab('supply');
                    setDartViewer(null);
                    if (!supplyContracts.length) {
                      setSupplyLoading(true);
                      fetch(`${API}/api/supply_contracts/${code}?years=5`)
                        .then(r=>r.json())
                        .then(d=>setSupplyContracts(d.items||[]))
                        .catch(()=>{})
                        .finally(()=>setSupplyLoading(false));
                    }
                  }}
                  className={`px-3 py-1 text-xs rounded-full font-semibold transition-colors ${discTab==='supply'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300'}`}>
                  📑 단일판매ㆍ공급계약
                </button>
              </div>

              {discTab==='dart' && (() => {
                const TYPES: [string,string][] = [
                  ['A','정기공시'], ['B','주요사항'], ['C','발행공시'], ['D','지분공시'], ['E','기타공시'],
                  ['F','외부감사관련'], ['G','펀드공시'], ['H','자산유동화'], ['I','거래소공시'], ['J','공정위공시'],
                ];
                const PERIODS: [string,string][] = [['1m','1개월'],['6m','6개월'],['1y','1년'],['3y','3년'],['5y','5년'],['10y','10년']];
                const toggleType = (t:string) => {
                  const next = new Set(dartTypes);
                  if (next.has(t)) next.delete(t); else next.add(t);
                  setDartTypes(next);
                  setDartPage(1);
                  fetchDartList(dartPeriod, next, 1, dartPageSize);
                };
                const changePeriod = (p:any) => {
                  setDartPeriod(p);
                  setDartPage(1);
                  fetchDartList(p, dartTypes, 1, dartPageSize);
                };
                const goPage = (p:number) => {
                  setDartPage(p);
                  fetchDartList(dartPeriod, dartTypes, p, dartPageSize);
                };

                const total = dartList?.total_page || 0;
                const cur = dartPage;
                // 페이지 번호 (현재 기준 앞뒤 2개씩)
                const pages: number[] = [];
                const start = Math.max(1, cur - 2);
                const end = Math.min(total, start + 4);
                for (let i = start; i <= end; i++) pages.push(i);

                return (
                  <div>
                    {/* DART 헤더 */}
                    <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-100 dark:border-slate-700">
                      <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">📄 공시자료</div>
                      <div className="text-xs text-slate-400">대한민국 기업정보의 창 DART</div>
                    </div>

                    {/* 기간 필터 */}
                    <div className="flex items-center gap-1 mb-2 text-xs flex-wrap">
                      <span className="text-slate-500 mr-2 font-semibold">기간</span>
                      {PERIODS.map(([k,lbl])=>(
                        <button key={k} onClick={()=>changePeriod(k)}
                          className={`px-2.5 py-1 rounded border ${dartPeriod===k
                            ? 'bg-indigo-600 text-white border-indigo-600'
                            : 'bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600 hover:bg-slate-50'}`}>
                          {lbl}
                        </button>
                      ))}
                    </div>

                    {/* 공시유형 체크박스 */}
                    <div className="flex items-center gap-2 mb-3 text-xs flex-wrap">
                      <span className="text-slate-500 mr-1 font-semibold">유형</span>
                      <button onClick={()=>{setDartTypes(new Set()); setDartPage(1); fetchDartList(dartPeriod, new Set(), 1, dartPageSize);}}
                        className={`px-2 py-1 rounded border ${dartTypes.size===0
                          ? 'bg-slate-700 text-white border-slate-700'
                          : 'bg-white dark:bg-slate-700 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300'}`}>
                        전체
                      </button>
                      {TYPES.map(([k,lbl])=>(
                        <label key={k} className={`px-2 py-1 rounded border cursor-pointer ${dartTypes.has(k)
                          ? 'bg-indigo-100 border-indigo-400 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-200'
                          : 'bg-white dark:bg-slate-700 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-50'}`}>
                          <input type="checkbox" checked={dartTypes.has(k)} onChange={()=>toggleType(k)}
                            className="mr-1 align-middle"/>{lbl}
                        </label>
                      ))}
                    </div>

                    {/* 조회건수 + 통계 */}
                    <div className="flex items-center justify-between mb-2 text-xs">
                      <div className="flex items-center gap-2">
                        <span className="text-slate-500">조회건수</span>
                        <select value={dartPageSize}
                          onChange={(e)=>{
                            const ps = parseInt(e.target.value);
                            setDartPageSize(ps); setDartPage(1);
                            fetchDartList(dartPeriod, dartTypes, 1, ps);
                          }}
                          className="px-2 py-1 border border-slate-200 dark:border-slate-600 rounded bg-white dark:bg-slate-700">
                          <option value={10}>10</option>
                          <option value={15}>15</option>
                          <option value={30}>30</option>
                          <option value={50}>50</option>
                        </select>
                      </div>
                      <div className="text-slate-500">
                        총 <span className="font-bold text-slate-700 dark:text-slate-200">{dartList?.total_count || 0}</span>건 ·
                        <span className="ml-1">{cur}/{total} 페이지</span>
                      </div>
                    </div>

                    {/* 테이블 */}
                    <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
                      <table className="w-full text-xs">
                        <thead className="bg-slate-50 dark:bg-slate-700/50 text-slate-600 dark:text-slate-300">
                          <tr>
                            <th className="px-2 py-2 text-center font-semibold w-12">번호</th>
                            <th className="px-2 py-2 text-left font-semibold w-36">공시대상회사</th>
                            <th className="px-2 py-2 text-left font-semibold">보고서명</th>
                            <th className="px-2 py-2 text-left font-semibold w-24">제출인</th>
                            <th className="px-2 py-2 text-center font-semibold w-24">접수일자</th>
                          </tr>
                        </thead>
                        <tbody>
                          {dartLoading && (
                            <tr><td colSpan={5} className="text-center py-6 text-slate-400">로딩 중...</td></tr>
                          )}
                          {!dartLoading && dartList?.items?.length === 0 && (
                            <tr><td colSpan={5} className="text-center py-6 text-slate-400">공시 데이터 없음</td></tr>
                          )}
                          {!dartLoading && dartList?.items?.map((d:any, i:number) => {
                            const num = (cur - 1) * dartPageSize + i + 1;
                            const clsColor = d.corp_cls === 'Y' ? 'bg-red-100 text-red-700' :
                                             d.corp_cls === 'K' ? 'bg-blue-100 text-blue-700' :
                                             d.corp_cls === 'N' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600';
                            const clsLabel = {Y:'유', K:'코', N:'넥', E:'기'}[d.corp_cls as 'Y'|'K'|'N'|'E'] || '?';
                            return (
                              <tr key={i} className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/50">
                                <td className="px-2 py-2 text-center text-slate-500">{num}</td>
                                <td className="px-2 py-2">
                                  <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold mr-1 ${clsColor}`}>{clsLabel}</span>
                                  <span className="text-slate-700 dark:text-slate-200">{d.corp_name}</span>
                                </td>
                                <td className="px-2 py-2">
                                  <button onClick={()=>openDart({rcept_no:d.rcept_no, title:d.report_nm})}
                                    className="text-left text-slate-700 dark:text-slate-200 hover:text-indigo-600 hover:underline">
                                    {d.report_nm}
                                  </button>
                                </td>
                                <td className="px-2 py-2 text-slate-600 dark:text-slate-300 truncate">{d.flr_nm || '-'}</td>
                                <td className="px-2 py-2 text-center font-mono text-slate-500">
                                  {d.rcept_dt ? `${d.rcept_dt.slice(0,4)}.${d.rcept_dt.slice(4,6)}.${d.rcept_dt.slice(6,8)}` : '-'}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>

                    {/* 페이지네이션 */}
                    {total > 1 && (
                      <div className="flex items-center justify-center gap-1 mt-3 text-xs">
                        <button onClick={()=>goPage(1)} disabled={cur===1}
                          className="px-2 py-1 rounded border border-slate-200 dark:border-slate-600 disabled:opacity-30">{'<<'}</button>
                        <button onClick={()=>goPage(Math.max(1,cur-1))} disabled={cur===1}
                          className="px-2 py-1 rounded border border-slate-200 dark:border-slate-600 disabled:opacity-30">{'<'}</button>
                        {pages.map(p=>(
                          <button key={p} onClick={()=>goPage(p)}
                            className={`px-2.5 py-1 rounded border ${p===cur
                              ? 'bg-indigo-600 text-white border-indigo-600 font-semibold'
                              : 'border-slate-200 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700'}`}>{p}</button>
                        ))}
                        <button onClick={()=>goPage(Math.min(total,cur+1))} disabled={cur===total}
                          className="px-2 py-1 rounded border border-slate-200 dark:border-slate-600 disabled:opacity-30">{'>'}</button>
                        <button onClick={()=>goPage(total)} disabled={cur===total}
                          className="px-2 py-1 rounded border border-slate-200 dark:border-slate-600 disabled:opacity-30">{'>>'}</button>
                      </div>
                    )}

                    <div className="text-[10px] text-slate-400 mt-2 text-center">
                      출처: 금융감독원 전자공시시스템 (dart.fss.or.kr) 실시간
                    </div>
                  </div>
                );
              })()}

              {discTab==='supply' && (
                <div>
                  {/* 공급계약 헤더 */}
                  <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-100 dark:border-slate-700">
                    <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">📑 단일판매ㆍ공급계약 공시</div>
                    <div className="text-xs text-slate-400">최근 5년 · 실시간 DART 조회</div>
                  </div>

                  {/* 통계 */}
                  <div className="flex items-center justify-end mb-2 text-xs text-slate-500">
                    총 <span className="font-bold mx-1 text-slate-700 dark:text-slate-200">{supplyContracts.length}</span>건
                  </div>

                  {/* 테이블 */}
                  {supplyLoading ? (
                    <div className="text-xs text-slate-400 text-center py-12 border border-slate-200 dark:border-slate-700 rounded">
                      DART API 호출 중...
                    </div>
                  ) : supplyContracts.length === 0 ? (
                    <div className="text-sm text-slate-400 text-center py-12 border border-slate-200 dark:border-slate-700 rounded">
                      최근 5년 내 단일판매ㆍ공급계약 공시 없음
                    </div>
                  ) : (
                    <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
                      <table className="w-full text-xs">
                        <thead className="bg-slate-50 dark:bg-slate-700/50 text-slate-600 dark:text-slate-300">
                          <tr>
                            <th className="px-2 py-2 text-center font-semibold w-12">번호</th>
                            <th className="px-2 py-2 text-center font-semibold w-16">유형</th>
                            <th className="px-2 py-2 text-left font-semibold">보고서명</th>
                            <th className="px-2 py-2 text-left font-semibold w-24">제출인</th>
                            <th className="px-2 py-2 text-center font-semibold w-24">접수일자</th>
                          </tr>
                        </thead>
                        <tbody>
                          {supplyContracts.map((d:any, i:number) => (
                            <tr key={i} className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/50">
                              <td className="px-2 py-2 text-center text-slate-500">{i + 1}</td>
                              <td className="px-2 py-2 text-center">
                                <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                  d.event_type==='체결'
                                    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300'
                                    : 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300'
                                }`}>{d.event_type}</span>
                              </td>
                              <td className="px-2 py-2">
                                <button onClick={()=>openDart({rcept_no:d.rcept_no, title:d.report_nm})}
                                  className="text-left text-slate-700 dark:text-slate-200 hover:text-indigo-600 hover:underline">
                                  {d.report_nm.trim()}
                                </button>
                              </td>
                              <td className="px-2 py-2 text-slate-600 dark:text-slate-300 truncate">{d.flr_nm || '-'}</td>
                              <td className="px-2 py-2 text-center font-mono text-slate-500">
                                {d.rcept_dt ? `${d.rcept_dt.slice(0,4)}.${d.rcept_dt.slice(4,6)}.${d.rcept_dt.slice(6,8)}` : '-'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <div className="text-[10px] text-slate-400 mt-2 text-center">
                    출처: 금융감독원 전자공시시스템 (dart.fss.or.kr) · 최근 5년
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ═══ TAB2: 밸류에이션 — DCF 엔진 v8 대시보드(index.html) 임베드 ═══ */}
      {/* 합본 평가 JSON(/api/valuation-full)을 받아 엔진 원본 대시보드를 그대로 렌더. 산업 대표 20종 지원, 그 외 자동 "준비중" 안내. */}
      {mainTab === 'valuation' && (
        <div className="w-full">
          <iframe
            src={`/valuation-dashboard.html?code=${code}&api=${encodeURIComponent(API)}`}
            title="밸류에이션 대시보드"
            className="w-full block"
            style={{ height: 'calc(100vh - 110px)', minHeight: '880px', border: 'none', background: '#f8fafc' }}
          />
        </div>
      )}

      {/* (구) 6분리 파일 기반 밸류 렌더 — 대시보드로 대체됨(비활성). 추후 정리 예정. */}
      {false && !loadingMain && mainTab === 'valuation' && valData && !valData.is_mock && (
        <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">

          {/* Hero */}
          <div className="rounded-2xl p-6 text-white" style={{background:'linear-gradient(135deg,#0e1c44,#1f4ed8)'}}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div>
                <div className="flex gap-2 mb-2">
                  <span className="text-xs px-2 py-0.5 rounded" style={{background:'rgba(255,255,255,0.15)'}}>{company.market||'KOSPI'}</span>
                  <span className="font-mono text-xs px-2 py-0.5 rounded" style={{background:'rgba(255,255,255,0.15)'}}>{code}</span>
                </div>
                <h2 className="text-2xl font-bold mb-1">{corpName}</h2>
                <p className="text-xs opacity-60">DCF(FCFF) 기반 적정주가 산출 · A2 방식</p>
                {valData && !valData.is_mock && (
                  <span className="inline-block mt-1 text-xs px-2 py-0.5 rounded font-medium" style={{background:'rgba(16,185,129,0.25)',color:'#6ee7b7'}}>
                    ✓ 실데이터 ({valData._file})
                  </span>
                )}
                <div className="mt-4 text-sm opacity-80">기업가치 (Equity Value)</div>
                <div className="text-2xl font-bold">{vd.equityValueLabel}</div>
              </div>
              <div className="text-right">
                <div className="text-xs opacity-60 mb-1">적정주가 (Base case)</div>
                <div className="text-4xl font-extrabold font-mono">{fmtPrice(vd.fairPrices.base)}</div>
                <div className="text-sm mt-1 text-green-300">
                  현재 {fmtPrice(hdr.current_price)} · 상승여력 {vd.upsides.base} ↑
                </div>
              </div>
            </div>
          </div>

          {/* Bear / Base / Bull — 색상 차별화 */}
          <div className="grid grid-cols-3 gap-4">
            {SCENARIO_CONFIG.map(sc => (
              <div key={sc.label}
                className={`rounded-xl p-5 text-center border-2 border-t-4 ${sc.bg} ${sc.border} ${sc.topBorder} shadow-sm`}>
                <div className={`text-xs font-bold mb-0.5 ${sc.textColor}`}>{sc.icon} {sc.label}</div>
                <div className={`text-xs mb-2 ${sc.textColor} opacity-70`}>{sc.desc}</div>
                <div className="text-2xl font-extrabold font-mono text-slate-800">
                  {fmtPrice(vd.fairPrices[sc.key])}
                </div>
                <div className={`text-xs mt-2 font-semibold px-2 py-0.5 rounded-full inline-block ${sc.badge}`}>
                  {vd.upsides[sc.upKey]}
                </div>
              </div>
            ))}
          </div>

          {/* 서브탭 패널 */}
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
            <div className="flex border-b border-slate-100 dark:border-slate-700 overflow-x-auto">
              {([
                ['dcf','DCF 분석'],['wacc','WACC'],['multiples','멀티플'],
                ['sensitivity','민감도'],['tornado','토네이도'],['peers','피어 비교'],
              ] as [ValTab,string][]).map(([t,label]) => (
                <button key={t} onClick={() => setValTab(t)}
                  className={`px-5 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${valTab===t
                    ? 'border-indigo-600 text-indigo-700 font-bold bg-indigo-50 dark:bg-indigo-900/30 dark:text-indigo-300'
                    : 'border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700'}`}>
                  {label}
                </button>
              ))}
            </div>

            <div className="p-5">

              {/* ── DCF 분석 ── */}
              {valTab === 'dcf' && (
                <div className="space-y-4">
                  {valData && !valData.is_mock && valData.dcf_valid === false && (
                    <div className="flex items-start gap-2 bg-yellow-50 border border-yellow-300 rounded-lg px-4 py-3">
                      <span className="text-yellow-500 text-base mt-0.5">⚠️</span>
                      <div>
                        <div className="text-sm font-bold text-yellow-800">DCF 유효성 검증 미통과</div>
                        <div className="text-xs text-yellow-700 mt-0.5">
                          {valData.dcf_invalid_reason || 'DCF 계산 신뢰도 낮음'} — 멀티플 탭의 역산 적정가를 함께 참고하세요.
                        </div>
                      </div>
                    </div>
                  )}
                  <p className="text-xs text-slate-400">단위: 억원 · FCFF 기반 DCF · WACC {vd.wacc.wacc}% · g {vd.wacc.terminalG}%</p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-slate-50 dark:bg-slate-700 border-b border-slate-200 dark:border-slate-600">
                          <th className="text-left py-2 px-3 text-slate-500 font-semibold w-48">항목</th>
                          {vd.dcfYears.map((y:string) => (
                            <th key={y} className="text-right py-2 px-3 text-slate-500 font-semibold">{y}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {vd.dcfRows.map((row:any, i:number) => (
                          <tr key={i} className={`border-b border-slate-50 dark:border-slate-700 ${row.bold ? 'bg-indigo-50 dark:bg-indigo-900/20' : ''}`}>
                            <td className={`py-2 px-3 ${row.bold ? 'font-bold text-slate-800 dark:text-slate-200' : 'text-slate-600 dark:text-slate-400'}`}>{row.label}</td>
                            {row.values.map((v:number, j:number) => (
                              <td key={j} className={`text-right py-2 px-3 font-mono ${row.bold ? 'font-bold text-slate-800 dark:text-slate-200' : 'text-slate-600 dark:text-slate-400'}`}>
                                {row.fmt === 'pct' ? v.toFixed(1)+'%'
                                  : row.fmt === 'decimal3' ? v.toFixed(3)
                                  : v.toLocaleString()}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {([
                      ['PV(FCFF) 합계',  vd.dcfSummary.pvFCFF.toLocaleString()+'억'],
                      ['PV(터미널가치)', vd.dcfSummary.pvTerminalValue.toLocaleString()+'억'],
                      ['기업가치 (EV)', vd.dcfSummary.enterpriseValue.toLocaleString()+'억'],
                      ['자기자본가치',  vd.dcfSummary.equityValue.toLocaleString()+'억'],
                    ] as [string,string][]).map(([l,v]) => (
                      <div key={l} className="bg-slate-50 dark:bg-slate-700 rounded-xl p-3 text-center">
                        <div className="text-xs text-slate-400 mb-1">{l}</div>
                        <div className="text-sm font-bold text-slate-800 dark:text-slate-200 font-mono">{v}</div>
                      </div>
                    ))}
                  </div>
                  <div className="bg-indigo-50 dark:bg-indigo-900/30 rounded-xl p-4 flex items-center justify-between">
                    <div>
                      <div className="text-xs text-indigo-500 mb-0.5">주당 적정가 (Base)</div>
                      <div className="text-2xl font-extrabold text-indigo-700 dark:text-indigo-400 font-mono">{fmtPrice(vd.fairPrices.base)}</div>
                    </div>
                    <div className="text-right text-xs text-slate-500 space-y-0.5">
                      <div>발행주식수 <span className="font-mono font-bold text-slate-700 dark:text-slate-300">{vd.dcfSummary.shares.toLocaleString()}만주</span></div>
                      <div>순부채 <span className="font-mono font-bold text-slate-700 dark:text-slate-300">{vd.dcfSummary.netDebt.toLocaleString()}억</span></div>
                    </div>
                  </div>
                  {(!valData || valData.is_mock) && (
                    <p className="text-xs text-slate-300 text-center">* Mock 데이터 — 밸류에이션팀 JSON 도착 시 자동 전환</p>
                  )}
                </div>
              )}

              {/* ── WACC ── */}
              {valTab === 'wacc' && (
                <div className="space-y-4">
                  <p className="text-xs text-slate-400">CAPM 기반 자기자본비용 + 세후 타인자본비용 가중평균</p>
                  <div className="bg-indigo-600 text-white rounded-xl p-5 text-center">
                    <div className="text-xs opacity-80 mb-1">WACC</div>
                    <div className="text-4xl font-extrabold">{vd.wacc.wacc}%</div>
                    <div className="text-sm opacity-70 mt-1">E% {vd.wacc.eWeight}% · D% {vd.wacc.dWeight}% · 법인세율 {vd.wacc.tax}%</div>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {([
                      { label:'무위험수익률 (Rf)', value:vd.wacc.rf+'%',   note:'국고채 10년',       cls:'' },
                      { label:'베타 (β)',           value:vd.wacc.beta,    note:'산업 평균 조정',    cls:'' },
                      { label:'ERP',                value:vd.wacc.erp+'%', note:'Damodaran 기준',    cls:'' },
                      { label:'자기자본비용 (Ke)',   value:vd.wacc.ke+'%',  note:'Rf + β × ERP',     cls:'border-indigo-200 bg-indigo-50 dark:bg-indigo-900/30 dark:border-indigo-700' },
                      { label:'타인자본비용 (Kd)',   value:vd.wacc.kd+'%',  note:'세전 · 회사채',    cls:'' },
                      { label:'세후 Kd',            value:(vd.wacc.kd*(1-vd.wacc.tax/100)).toFixed(2)+'%', note:'Kd × (1−t)', cls:'' },
                    ] as any[]).map((item:any) => (
                      <div key={item.label} className={`border rounded-xl p-4 dark:border-slate-700 ${item.cls || 'border-slate-200'}`}>
                        <div className="text-xs text-slate-400 mb-1">{item.label}</div>
                        <div className="text-xl font-bold text-slate-800 dark:text-slate-200 font-mono">{item.value}</div>
                        <div className="text-xs text-slate-400 mt-1">{item.note}</div>
                      </div>
                    ))}
                  </div>
                  <div className="bg-slate-50 dark:bg-slate-700 rounded-xl p-4">
                    <div className="text-xs text-slate-500 font-semibold mb-2">산출식</div>
                    <div className="text-sm font-mono text-slate-700 dark:text-slate-300">WACC = Ke × E/(E+D) + Kd×(1−t) × D/(E+D)</div>
                    <div className="text-sm font-mono text-indigo-700 dark:text-indigo-400 mt-1">
                      = {vd.wacc.ke}% × {vd.wacc.eWeight}% + {(vd.wacc.kd*(1-vd.wacc.tax/100)).toFixed(2)}% × {vd.wacc.dWeight}% = <strong>{vd.wacc.wacc}%</strong>
                    </div>
                  </div>
                  {(!valData || valData.is_mock) && (
                    <p className="text-xs text-slate-300 text-center">* Mock 데이터 — 밸류에이션팀 JSON 도착 시 자동 전환</p>
                  )}
                </div>
              )}

              {/* ── 멀티플 역산 ── */}
              {valTab === 'multiples' && (
                <div className="space-y-4">
                  <p className="text-xs text-slate-400">업종 피어그룹 평균 멀티플 적용 역산 적정주가</p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-slate-50 dark:bg-slate-700 border-b border-slate-200 dark:border-slate-600">
                          {['멀티플','피어 평균','역산 적정가','현재 멀티플','상승여력'].map(h => (
                            <th key={h} className={`py-2.5 px-4 text-slate-500 font-semibold ${h==='멀티플'?'text-left':'text-right'}`}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {vd.multiples.map((m:any, i:number) => (
                          <tr key={i} className="border-b border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700">
                            <td className="py-2.5 px-4 font-semibold text-slate-800 dark:text-slate-200">{m.metric}</td>
                            <td className="text-right py-2.5 px-4 font-mono text-slate-600 dark:text-slate-400">{m.peerAvg}</td>
                            <td className="text-right py-2.5 px-4 font-mono font-bold text-slate-800 dark:text-slate-200">{m.implied}</td>
                            <td className="text-right py-2.5 px-4 font-mono text-slate-500 dark:text-slate-400">{m.current}</td>
                            <td className={`text-right py-2.5 px-4 font-mono font-semibold ${m.premium.startsWith('+')?'text-emerald-600':'text-red-600'}`}>{m.premium}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="bg-indigo-50 dark:bg-indigo-900/30 rounded-xl p-4 flex items-center justify-between">
                    <div>
                      <div className="text-xs text-slate-400 mb-1">멀티플 역산 단순평균</div>
                      <div className="text-lg font-bold text-slate-800 dark:text-slate-200 font-mono">
                        {fmtPrice(Math.round(vd.multiples.reduce((s:number,m:any)=>s+m.impliedAmt,0)/vd.multiples.length/1000)*1000)}
                      </div>
                    </div>
                    <div className="text-xs text-slate-400 text-right">DCF Base {fmtPrice(vd.fairPrices.base)}<br/>대비 검증용 참고치</div>
                  </div>
                  {(!valData || valData.is_mock) && (
                    <p className="text-xs text-slate-300 text-center">* Mock 데이터 — 밸류에이션팀 JSON 도착 시 자동 전환</p>
                  )}
                </div>
              )}

              {/* ── 민감도 히트맵 ── */}
              {valTab === 'sensitivity' && (
                <div className="space-y-4">
                  <p className="text-xs text-slate-400">WACC (행) × 터미널 성장률 g (열) 조합별 주당 적정가 · ◀ = Base case</p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs border-separate border-spacing-1">
                      <thead>
                        <tr>
                          <th className="py-1.5 px-3 text-slate-400 font-medium text-left w-20">WACC ↓ / g →</th>
                          {vd.sensitivityG.map((g:number) => (
                            <th key={g} className="py-1.5 px-2 text-center text-slate-500 font-semibold">{g.toFixed(1)}%</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {vd.sensitivityWacc.map((w:number, wi:number) => {
                          const baseWi = Math.floor(vd.sensitivityWacc.length / 2);
                          const baseGi = Math.floor(vd.sensitivityG.length / 2);
                          return (
                            <tr key={w}>
                              <td className={`py-1.5 px-3 font-semibold text-slate-600 dark:text-slate-400 ${wi===baseWi?'text-indigo-700 dark:text-indigo-400':''}`}>
                                {w.toFixed(1)}%{wi===baseWi?' ◀':''}
                              </td>
                              {vd.sensitivityPrices[wi].map((price:number, gi:number) => {
                                const cur = hdr.current_price || vd.fairPrices.base * 0.65;
                                const up = (price - cur) / cur;
                                const bg = up > 0.5  ? 'bg-emerald-600 text-white'
                                  : up > 0.3  ? 'bg-emerald-500 text-white'
                                  : up > 0.1  ? 'bg-emerald-300 text-emerald-900'
                                  : up > 0    ? 'bg-emerald-100 text-emerald-800'
                                  : up > -0.1 ? 'bg-yellow-100 text-yellow-800'
                                  : up > -0.3 ? 'bg-orange-200 text-orange-900'
                                  : 'bg-red-300 text-red-900';
                                const isBase = wi===baseWi && gi===baseGi;
                                return (
                                  <td key={gi} className={`py-2 px-2 text-center font-mono rounded ${bg} ${isBase?'ring-2 ring-indigo-500':''}`}>
                                    {(price/10000).toFixed(0)}만
                                    {isBase && <div className="text-xs opacity-70 leading-none">Base</div>}
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="flex gap-3 flex-wrap text-xs">
                    {[
                      ['bg-emerald-600','text-white','>+50%'],
                      ['bg-emerald-300','text-emerald-900','+10~50%'],
                      ['bg-emerald-100','text-emerald-800','0~+10%'],
                      ['bg-yellow-100','text-yellow-800','-10~0%'],
                      ['bg-orange-200','text-orange-900','-30~-10%'],
                      ['bg-red-300','text-red-900','<-30%'],
                    ].map(([bg,tc,label]) => (
                      <span key={label} className="flex items-center gap-1">
                        <span className={`w-4 h-4 rounded ${bg} inline-block`}/>
                        <span className="text-slate-500">{label}</span>
                      </span>
                    ))}
                  </div>
                  {(!valData || valData.is_mock) && (
                    <p className="text-xs text-slate-300 text-center">* Mock 데이터 — 밸류에이션팀 JSON 도착 시 자동 전환</p>
                  )}
                </div>
              )}

              {/* ── 토네이도 차트 ── */}
              {valTab === 'tornado' && (
                <div className="space-y-4">
                  <p className="text-xs text-slate-400">주요 가정 변동이 적정주가에 미치는 영향 (Base: {fmtPrice(vd.fairPrices.base)})</p>
                  <div className="space-y-2">
                    {vd.tornado.map((t:any) => {
                      const maxAbs = Math.max(...vd.tornado.map((x:any) => Math.max(Math.abs(x.low), x.high)));
                      const lowPct  = Math.abs(t.low) / maxAbs * 44;
                      const highPct = t.high / maxAbs * 44;
                      return (
                        <div key={t.variable} className="flex items-center gap-2 text-xs">
                          <span className="w-40 text-slate-500 dark:text-slate-400 text-right flex-shrink-0 truncate">{t.variable}</span>
                          <div className="flex flex-1 items-center">
                            <div className="flex-1 flex justify-end">
                              <div className="h-6 bg-red-300 rounded-l flex items-center justify-end pr-1.5 text-red-800 font-mono text-xs overflow-hidden"
                                style={{width:`${lowPct}%`, minWidth:40}}>
                                {t.low.toLocaleString()}
                              </div>
                            </div>
                            <div className="w-px h-7 bg-slate-400 flex-shrink-0"/>
                            <div className="flex-1 flex justify-start">
                              <div className="h-6 bg-emerald-300 rounded-r flex items-center justify-start pl-1.5 text-emerald-800 font-mono text-xs overflow-hidden"
                                style={{width:`${highPct}%`, minWidth:48}}>
                                +{t.high.toLocaleString()}
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex gap-6 text-xs justify-center mt-2">
                    <span className="flex items-center gap-1.5"><span className="w-4 h-3 bg-red-300 rounded inline-block"/> 하방 변동</span>
                    <span className="flex items-center gap-1.5"><span className="w-4 h-3 bg-emerald-300 rounded inline-block"/> 상방 변동</span>
                  </div>
                  {(!valData || valData.is_mock) && (
                    <p className="text-xs text-slate-300 text-center">* Mock 데이터 — 밸류에이션팀 JSON 도착 시 자동 전환</p>
                  )}
                </div>
              )}

              {/* ── 피어 비교 ── */}
              {valTab === 'peers' && (
                <div className="space-y-4">
                  <p className="text-xs text-slate-400">업종 피어그룹 {vd.peers.length}개사 멀티플 비교 · FY2024 기준</p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-slate-50 dark:bg-slate-700 border-b border-slate-200 dark:border-slate-600">
                          {['기업','β','EV/EBITDA','P/E','P/B','ROE'].map(h => (
                            <th key={h} className={`py-2.5 px-4 text-slate-500 font-semibold ${h==='기업'?'text-left':'text-right'}`}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {vd.peers.map((p:any, i:number) => (
                          <tr key={i} className={`border-b border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 ${p.isSelf?'bg-indigo-50 dark:bg-indigo-900/20':''}`}>
                            <td className="py-2.5 px-4">
                              <span className={`font-semibold ${p.isSelf?'text-indigo-700 dark:text-indigo-400':'text-slate-800 dark:text-slate-200'}`}>{p.name}</span>
                              <span className="font-mono text-xs text-slate-400 ml-2">{p.ticker}</span>
                              {p.isSelf && <span className="ml-2 text-xs bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 px-1.5 py-0.5 rounded-full">현재 종목</span>}
                            </td>
                            <td className="text-right py-2.5 px-4 font-mono text-slate-600 dark:text-slate-400">{p.beta}</td>
                            <td className="text-right py-2.5 px-4 font-mono text-slate-600 dark:text-slate-400">{p.evEbitda}</td>
                            <td className="text-right py-2.5 px-4 font-mono text-slate-600 dark:text-slate-400">{p.pe}</td>
                            <td className="text-right py-2.5 px-4 font-mono text-slate-600 dark:text-slate-400">{p.pb}</td>
                            <td className="text-right py-2.5 px-4 font-mono text-slate-600 dark:text-slate-400">{p.roe}</td>
                          </tr>
                        ))}
                        <tr className="bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 font-semibold text-xs">
                          <td className="py-2 px-4 text-slate-500">피어 평균</td>
                          <td className="text-right py-2 px-4 font-mono">
                            {(vd.peers.filter((p:any)=>!p.isSelf).reduce((s:number,p:any)=>s+p.beta,0)/vd.peers.filter((p:any)=>!p.isSelf).length).toFixed(2)}
                          </td>
                          <td className="text-right py-2 px-4 font-mono">{vd.multiples[0]?.peerAvg}</td>
                          <td className="text-right py-2 px-4 font-mono">{vd.multiples[1]?.peerAvg}</td>
                          <td className="text-right py-2 px-4 font-mono">{vd.multiples[2]?.peerAvg}</td>
                          <td className="text-right py-2 px-4 text-slate-400">—</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  {(!valData || valData.is_mock) && (
                    <p className="text-xs text-slate-300 text-center">* Mock 데이터 — 밸류에이션팀 JSON 도착 시 자동 전환</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ═══ TAB3: AI 챗봇 (탭 아래 전체 검은 배경 · 챗봇 화면 풀블리드) ═══ */}
      {!loadingMain && mainTab === 'ai' && (
        <div className="bg-[#0f1115]">
          <AIChatbotTab />
        </div>
      )}

      {/* 페이지 하단 회사 크레딧 (AI 챗봇 탭은 풀스크린이라 숨김) */}
      {mainTab !== 'ai' && (
        <footer className="text-center py-4 border-t border-slate-200 dark:border-white/5 mt-2">
          <div className="text-sm font-bold text-slate-900 dark:text-slate-100 tracking-[0.18em]">FILMN9&nbsp;Inc.</div>
        </footer>
      )}
    </div>
  );
}
