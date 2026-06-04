'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// 모닝루틴 — 기존 지표 / 추가 지표 (기본 표시 순서)
const M_EXISTING   = ['ES=F','NQ=F','^VIX','DX-Y.NYB','KRW=X','^TNX','^KS11','^KQ11','^N225','^HSI'];
const M_ADDITIONAL = ['KRX_GOLD','IRR_GOVT03Y','IRR_CORP03Y','IRR_CD91','^SOX','NVDA','TSM','MU','US_10Y_3M','ZQ=F','BZ=F','SI=F','LIT','URA','BDRY','SLX','ZW=F','ZC=F','ZS=F','TLT','EURUSD=X','BTC-USD'];
const M_DEFAULT_ORDER = [...M_EXISTING, ...M_ADDITIONAL];

interface SearchResult {
  stock_code: string;
  corp_name: string;
  market: string;
  has_data: boolean;
}

const DEMO_STOCKS = [
  { code: '090430', name: '아모레퍼시픽', market: 'KOSPI', tag: '화장품' },
  { code: '009150', name: '삼성전기',     market: 'KOSPI', tag: '전자부품' },
  { code: '035420', name: 'NAVER',        market: 'KOSPI', tag: '인터넷' },
];

// 슬라이드 캐러셀 첫 화면(고정 3종목) — 이후 랜덤 풀이 이어 붙음
const FIXED3 = [
  { stock_code: '090430', corp_name: '아모레퍼시픽', tag: '화장품' },
  { stock_code: '009150', corp_name: '삼성전기',     tag: '전자부품' },
  { stock_code: '035420', corp_name: 'NAVER',        tag: '인터넷' },
];
const SLIDE_STEP = 204;   // 카드폭 192 + gap 12 (px)


export default function HomePage() {
  const router = useRouter();
  const [query, setQuery]       = useState('');
  const [results, setResults]   = useState<SearchResult[]>([]);
  const [loading, setLoading]   = useState(false);
  const [open, setOpen]         = useState(false);
  const [dark, setDark]         = useState(false);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  const wrapRef     = useRef<HTMLDivElement>(null);
  const [morning, setMorning] = useState<any>(null);

  // 모닝루틴 — 글로벌 야간시장 신호등 (yfinance 실데이터)
  useEffect(() => {
    fetch(`${API}/api/morning`).then(r=>r.json()).then(setMorning).catch(()=>{});
  }, []);

  // 추천 종목 슬라이드 캐러셀 (3개 노출 · 4초마다 한 칸씩 왼쪽으로)
  const [rotation, setRotation] = useState<any[]>(FIXED3);
  const [slidePos, setSlidePos] = useState(0);
  const [sliding,  setSliding]  = useState(false);
  const slidePausedRef = useRef(false);
  useEffect(() => {   // 고정 3개 + 랜덤 60개 풀 로드
    fetch(`${API}/api/featured?n=60`).then(r=>r.json()).then(d=>{
      const pool = (d.stocks || []);
      if (pool.length) setRotation([...FIXED3, ...pool]);
    }).catch(()=>{});
  }, []);
  useEffect(() => {   // 4초마다 한 칸 슬라이드 트리거
    if (rotation.length < 4) return;
    const id = setInterval(() => { if (!slidePausedRef.current) setSliding(true); }, 4000);
    return () => clearInterval(id);
  }, [rotation.length]);
  const onSlideEnd = (e: any) => {   // 슬라이드(transform) 끝 → 한 칸 전진 + 즉시 원위치
    if (e.propertyName !== 'transform' || e.target !== e.currentTarget) return;
    setSliding(false);
    setSlidePos(p => (p + 1) % rotation.length);
  };

  // 모닝루틴 지표 순서(드래그 편집·localStorage 저장)
  const [mOrder, setMOrder] = useState<string[]>(M_DEFAULT_ORDER);
  const [mDrag,  setMDrag]  = useState<string | null>(null);
  useEffect(() => {
    try {
      const saved = localStorage.getItem('filmn9_morning_order');
      if (saved) {
        const arr = JSON.parse(saved) as string[];
        const merged = [...arr.filter(t=>M_DEFAULT_ORDER.includes(t)), ...M_DEFAULT_ORDER.filter(t=>!arr.includes(t))];
        setMOrder(merged);
      }
    } catch {}
  }, []);
  const mSaveOrder = (arr: string[]) => {
    setMOrder(arr);
    try { localStorage.setItem('filmn9_morning_order', JSON.stringify(arr)); } catch {}
  };
  const mOnDrop = (target: string) => {
    if (!mDrag || mDrag === target) { setMDrag(null); return; }
    const arr = [...mOrder];
    const from = arr.indexOf(mDrag), to = arr.indexOf(target);
    if (from < 0 || to < 0) { setMDrag(null); return; }
    arr.splice(from, 1); arr.splice(to, 0, mDrag);
    mSaveOrder(arr); setMDrag(null);
  };

  // 다크모드
  const toggleDark = () => {
    document.documentElement.classList.toggle('dark');
    setDark(d => !d);
  };

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const search = async (q: string) => {
    if (!q.trim()) { setOpen(false); return; }
    setLoading(true); setOpen(true);
    try {
      const res  = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}&limit=10`);
      const data = await res.json();
      setResults(data.results || []);
    } catch { setResults([]); }
    finally { setLoading(false); }
  };

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(v), 200);
  };

  const goTo = (code: string) => router.push(`/stock/${code}`);

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 flex flex-col">

      {/* 상단 바 */}
      <header className="flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-2">
          <span className="text-2xl font-extrabold text-white tracking-tight">FILMN9</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/30 text-indigo-300 font-medium border border-indigo-500/40">PoC</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400 hidden sm:block">KPMG AI Lab · 2026-05-26</span>
          <button onClick={toggleDark}
            className="w-8 h-8 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center text-white transition-colors"
            title="다크모드 토글">
            {dark ? '☀️' : '🌙'}
          </button>
        </div>
      </header>

      {/* Hero 섹션 */}
      <div className="flex-1 flex flex-col items-center justify-center px-4 pb-16 pt-8">
        {/* 타이틀 */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 text-xs font-medium mb-6">
            🤖 AI 기반 기업 분석 자동화
          </div>
          <h1 className="text-5xl sm:text-6xl font-extrabold text-white tracking-tight mb-4">
            기업 분석, 이제<br/>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-purple-400">5분 만에</span>
          </h1>
          <p className="text-slate-400 text-base sm:text-lg max-w-md mx-auto">
            DART 공시 데이터 + LLM + DCF 모델링으로<br/>개인 투자자도 기관 수준의 분석을
          </p>
        </div>

        {/* 검색창 */}
        <div className="relative w-full max-w-lg mb-6" ref={wrapRef}>
          <div className="flex items-center bg-white rounded-2xl px-4 py-3.5 shadow-2xl shadow-indigo-900/40 border-2 transition-all"
            style={{ borderColor: open ? '#6366F1' : 'transparent' }}>
            <svg className="w-5 h-5 text-slate-400 mr-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
            </svg>
            <input
              value={query}
              onChange={handleInput}
              onKeyDown={e => { if (e.key === 'Enter' && results[0]) goTo(results[0].stock_code); }}
              placeholder="기업명 또는 종목코드 (예: 삼성전자, 005930)"
              className="flex-1 outline-none text-slate-800 placeholder-slate-400 bg-transparent text-sm"
              autoComplete="off"
            />
            {loading && (
              <div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin ml-2" />
            )}
          </div>

          {open && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-white border border-slate-200 rounded-xl shadow-2xl z-50 overflow-hidden">
              {results.length === 0 && !loading ? (
                <div className="px-4 py-3 text-sm text-slate-400 text-center">검색 결과 없음</div>
              ) : results.map(r => (
                <button key={r.stock_code} onClick={() => goTo(r.stock_code)}
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-indigo-50 transition-colors text-left">
                  <span className="font-mono text-xs text-slate-400 w-14">{r.stock_code}</span>
                  <span className="flex-1 text-sm font-semibold text-slate-800">{r.corp_name}</span>
                  <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white"
                    style={{ background: r.market === 'KOSPI' ? '#2563EB' : '#7C3AED' }}>
                    {r.market}
                  </span>
                  {r.has_data && <span className="text-xs text-emerald-500 font-medium">● 데이터 있음</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 추천 종목 — 4초마다 왼쪽으로 한 칸씩 슬라이드 (3개 노출, 3000개 중 랜덤) */}
        <div className="mb-2 overflow-hidden mx-auto" style={{ width: '600px', maxWidth: '90vw' }}>
          <div
            className="flex gap-3"
            onTransitionEnd={onSlideEnd}
            onMouseEnter={() => { slidePausedRef.current = true; }}
            onMouseLeave={() => { slidePausedRef.current = false; }}
            style={{
              transform: sliding ? `translateX(-${SLIDE_STEP}px)` : 'translateX(0)',
              transition: sliding ? 'transform 0.8s ease-in-out' : 'none',
            }}>
            {[0, 1, 2, 3].map(i => {
              const s = rotation[(slidePos + i) % rotation.length];
              if (!s) return null;
              return (
                <button key={`${slidePos}-${i}`} onClick={() => goTo(s.stock_code)}
                  className="group flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 hover:border-indigo-400/60 text-white transition-colors flex-shrink-0"
                  style={{ width: '192px' }}>
                  <div className="text-left overflow-hidden">
                    <div className="text-sm font-semibold truncate">{s.corp_name}</div>
                    <div className="text-xs text-slate-400 font-mono truncate">{s.stock_code} · {s.tag}</div>
                  </div>
                  <svg className="w-4 h-4 text-slate-400 group-hover:text-indigo-300 ml-auto transition-colors flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
                  </svg>
                </button>
              );
            })}
          </div>
        </div>
        <div className="text-[11px] text-slate-500 mb-6">🔀 3,000개 기업 중 랜덤 추천 · 4초마다 자동 전환 · 마우스 올리면 멈춤 · 클릭하면 상세분석</div>

        {/* 산업 분류 입구 */}
        <button onClick={() => router.push('/sectors')}
          className="group inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/5 hover:bg-white/15 border border-white/15 hover:border-indigo-400/60 text-slate-300 hover:text-white text-sm transition-all">
          🏭 산업(업종)별로 탐색하기
          <svg className="w-4 h-4 text-slate-500 group-hover:text-indigo-300 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
          </svg>
        </button>

        {/* 🌅 모닝루틴 위젯 — 좌측 빈공간 가운데 세로 패널 (fixed 라 중앙 검색란 영향 없음) */}
        {morning?.overall && (
          <div className="hidden lg:block fixed left-[9%] top-1/2 -translate-y-1/2 w-80 max-h-[90vh] z-30 bg-white/5 border border-white/10 rounded-2xl p-5 backdrop-blur text-left">
            <div className="text-lg font-bold text-white">📡 글로벌 마켓 시그널</div>
            <div className="text-[11px] text-slate-500 mb-3">개장 전 글로벌 시황 → 한국장 방향 · {morning.as_of}</div>

            {/* 종합 판정 */}
            <div className="flex items-center gap-3 mb-4 p-3 rounded-xl bg-white/5 border border-white/10">
              <span className="text-3xl">{morning.overall.icon}</span>
              <div className="flex-1">
                <div className="text-sm font-semibold text-white leading-snug flex items-center gap-1.5">
                  {morning.overall.text}
                  {/* (i) 종합판정 해석 */}
                  <span className="group relative inline-flex flex-shrink-0">
                    <span className="w-4 h-4 inline-flex items-center justify-center rounded-full bg-white/10 hover:bg-indigo-500/50 text-slate-200 text-[10px] font-serif italic cursor-help">i</span>
                    <span className="pointer-events-none absolute left-6 top-0 z-50 hidden group-hover:block w-64 p-3 rounded-lg bg-slate-900 border border-slate-600 text-[12px] text-slate-200 leading-relaxed shadow-2xl font-normal">
                      <b className="text-white block mb-1">오늘 한국장 종합 판정</b>
                      <span className="block">6개 글로벌 지표(미국선물·VIX·원/달러·미금리·닛케이·항셍)의 KOSPI 상관 신호를 합산해 오늘 한국 증시 분위기를 추정합니다.</span>
                      <span className="block mt-1.5">🟢 4개↑ = 상승 우호 · 🔴 4개↑ = 하락 위험</span>
                      <span className="block">🟢&gt;🔴 = 소폭 상승 · 엇비슷 = <b className="text-white">혼조세(방향 불분명)</b></span>
                      <span className="block mt-1.5 text-slate-400">※ 미래 예측이 아닌 참고용. 지금: 🟢{morning.overall.green} 🟡{morning.overall.yellow} 🔴{morning.overall.red}</span>
                    </span>
                  </span>
                </div>
                <div className="text-[11px] text-slate-400 mt-1">🟢{morning.overall.green} 🟡{morning.overall.yellow} 🔴{morning.overall.red}</div>
              </div>
            </div>

            {/* 지표 목록 — 드래그 순서편집 + 스크롤 */}
            <div className="flex items-center justify-between mb-1.5">
              <div className="text-[11px] text-slate-400">지표 <span className="text-slate-600">⠿드래그로 순서편집</span></div>
              <button onClick={()=>mSaveOrder(M_DEFAULT_ORDER)} className="text-[10px] text-slate-500 hover:text-indigo-300 underline">기본순서</button>
            </div>
            <div className="max-h-[44vh] overflow-y-auto pr-1 -mr-1 space-y-0.5">
              {(() => {
                const flat:any = {};
                (Object.values(morning.sections||{}) as any[]).flat().forEach((e:any)=>{ flat[e.ticker]=e; });
                return mOrder.map(tk=>flat[tk]).filter(Boolean).map((e:any)=>{
                  const tip = `${e.label}\n${e.desc||''}\n📊 ${e.range_str||''}`;
                  const isAdd = M_ADDITIONAL.includes(e.ticker);
                  return (
                    <div key={e.ticker} draggable
                      onDragStart={()=>setMDrag(e.ticker)}
                      onDragOver={(ev)=>ev.preventDefault()}
                      onDrop={()=>mOnDrop(e.ticker)}
                      className={`flex items-center gap-1.5 py-1.5 px-1 rounded border-b border-white/5 last:border-0 cursor-grab active:cursor-grabbing hover:bg-white/5 ${mDrag===e.ticker?'opacity-40':''}`}>
                      <span className="text-slate-600 text-[12px] select-none flex-shrink-0">⠿</span>
                      {isAdd && <span className="text-[8px] text-amber-400 flex-shrink-0" title="추가지표">●</span>}
                      <span className="flex-1 text-[12px] text-slate-100 truncate" title={tip}>{e.label}</span>
                      <span className="w-4 h-4 inline-flex items-center justify-center rounded-full bg-white/10 hover:bg-indigo-500/50 text-slate-300 text-[9px] font-serif italic flex-shrink-0 cursor-help" title={tip}>i</span>
                      <span className="text-[12px] font-mono text-white text-right w-14 truncate" title={tip}>{e.price_str}</span>
                      <span className={`text-[11px] font-mono w-11 text-right flex-shrink-0 ${e.change_pct>=0?'text-emerald-400':'text-rose-400'}`}>{e.delta_str}</span>
                    </div>
                  );
                });
              })()}
            </div>
            <div className="text-[10px] text-slate-500 mt-2"><span className="text-amber-400">●</span> 추가지표 · ⓘ/이름 위 마우스=설명·한달범위 · 투자 참고용</div>
          </div>
        )}

      </div>

      <footer className="text-center py-4 text-xs text-slate-600 border-t border-white/5">
        FILMN9 PoC &nbsp;·&nbsp; KPMG AI Lab &nbsp;·&nbsp; 2026-05-26 데모
      </footer>
    </main>
  );
}
