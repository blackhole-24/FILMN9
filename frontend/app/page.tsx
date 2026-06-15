'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// 모닝루틴 — 기존 지표 / 추가 지표 (추가지표 표시용 ● 마킹)
const M_ADDITIONAL = ['FEAR_GREED','KRX_GOLD','IRR_GOVT03Y','IRR_CORP03Y','IRR_CD91','^SOX','NVDA','TSM','MU','US_10Y_3M','ZQ=F','BZ=F','SI=F','LIT','URA','BDRY','SLX','ZW=F','ZC=F','ZS=F','TLT','EURUSD=X','BTC-USD'];

// 마켓 시그널 카테고리 (접기/펴기) — 각 카테고리에 속한 티커 순서대로 표시
const SIGNAL_CATS: { id: string; name: string; tickers: string[] }[] = [
  { id: 'index',     name: '지수 · 선물', tickers: ['^KS11','^KQ11','ES=F','NQ=F','YM=F','^GSPC','^IXIC','^DJI','^N225','^HSI','000001.SS','EWY'] },
  { id: 'fxrate',    name: '환율 · 금리', tickers: ['KRW=X','DX-Y.NYB','JPY=X','EURUSD=X','^TNX','^IRX','US_10Y_3M','IRR_GOVT03Y','IRR_CORP03Y','IRR_CD91','ZQ=F','TLT'] },
  { id: 'commodity', name: '원자재',      tickers: ['CL=F','BZ=F','GC=F','KRX_GOLD','SI=F','HG=F','NG=F','URA','LIT','SLX','BDRY','ZW=F','ZC=F','ZS=F'] },
  { id: 'sentiment', name: '심리 · 테마',  tickers: ['^VIX','FEAR_GREED','BTC-USD','^SOX','NVDA','TSM','MU','XLK','XLF','XLV','XLE','XLY','XLI'] },
];

interface SearchResult { stock_code: string; corp_name: string; market: string; has_data: boolean; }
interface WatchItem { code: string; name: string; market: string; }
interface FeatStock { stock_code: string; corp_name: string; market?: string; tag?: string; }

const WATCH_KEY = 'finsight_watchlist';
const CATS_KEY  = 'finsight_signal_cats';
const SLIDE_STEP = 204;   // 카드폭 192 + gap 12 (px)

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

export default function HomePage() {
  const router = useRouter();
  const [query, setQuery]       = useState('');
  const [results, setResults]   = useState<SearchResult[]>([]);   // 기업
  const [sectorHits, setSectorHits] = useState<string[]>([]);     // 산업(업종)
  const [loading, setLoading]   = useState(false);
  const [open, setOpen]         = useState(false);
  const [dark, setDark]         = useState(false);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  const wrapRef     = useRef<HTMLDivElement>(null);
  const inputRef    = useRef<HTMLInputElement>(null);
  const signalRef   = useRef<HTMLDivElement>(null);
  const [morning, setMorning] = useState<any>(null);

  // 업종 — 회전 표시(랜덤 순서로 6개씩 돌아감) + 업종→종목수 매핑(드롭다운)
  const [allSectors, setAllSectors] = useState<{name:string;count:number}[]>([]);
  const [secWin, setSecWin] = useState(0);
  const [sectorCount, setSectorCount] = useState<Record<string, number>>({});

  // 추천 종목 캐러셀 (밸류·DCF 충실 종목만) — 검색란 바로 밑, 4초마다 한 칸 슬라이드
  const [rotation, setRotation] = useState<FeatStock[]>([]);
  const [slidePos, setSlidePos] = useState(0);
  const [sliding,  setSliding]  = useState(false);
  const slidePausedRef = useRef(false);

  // 관심종목 (localStorage)
  const [watch, setWatch] = useState<WatchItem[]>([]);
  // 시그널 카테고리 열림 상태
  const [catOpen, setCatOpen] = useState<Record<string, boolean>>({ index: true, fxrate: false, commodity: false, sentiment: false });

  // ── 초기 로드 ──
  useEffect(() => {
    fetch(`${API}/api/morning`).then(r=>r.json()).then(setMorning).catch(()=>{});
    fetch(`${API}/api/sectors`).then(r=>r.json()).then(d=>{
      const arr = (d.sectors || []) as {sector_name:string;count:number}[];
      setAllSectors(shuffle(arr.map(s => ({ name: s.sector_name, count: s.count }))));
      const m: Record<string, number> = {};
      arr.forEach(s => { m[s.sector_name] = s.count; });
      setSectorCount(m);
    }).catch(()=>{});
    // 캐러셀 풀 — 밸류 충실 종목(source=val) 랜덤
    fetch(`${API}/api/featured?n=120&source=val`).then(r=>r.json()).then(d=>{
      setRotation(shuffle(d.stocks || []));
    }).catch(()=>{});
    try { const s = localStorage.getItem(WATCH_KEY); if (s) setWatch(JSON.parse(s)); } catch {}
    try { const c = localStorage.getItem(CATS_KEY); if (c) setCatOpen(JSON.parse(c)); } catch {}
  }, []);

  // 업종 칩 회전 (3.5초마다 한 칸)
  useEffect(() => {
    if (allSectors.length < 7) return;
    const id = setInterval(() => setSecWin(p => (p + 1) % allSectors.length), 3500);
    return () => clearInterval(id);
  }, [allSectors.length]);

  // 캐러셀 슬라이드 — 타이머 기반(transitionend 불안정 회피).
  // 3.2초 대기 → 0.8초 애니메이션(왼쪽 한 칸) → 위치 전진 + 즉시 원위치 → 반복.
  useEffect(() => {
    if (rotation.length < 4) return;
    let alive = true; let tWait: any, tAnim: any;
    const cycle = () => {
      if (!alive) return;
      if (slidePausedRef.current) { tWait = setTimeout(cycle, 3200); return; }
      setSliding(true);                                  // 0.8초간 왼쪽으로 슬라이드
      tAnim = setTimeout(() => {
        if (!alive) return;
        setSliding(false);                               // 즉시 원위치
        setSlidePos(p => (p + 1) % rotation.length);     // 한 칸 전진(다음 종목)
        tWait = setTimeout(cycle, 3200);
      }, 820);
    };
    tWait = setTimeout(cycle, 3200);
    return () => { alive = false; clearTimeout(tWait); clearTimeout(tAnim); };
  }, [rotation.length]);

  // 관심종목
  const saveWatch = (arr: WatchItem[]) => { setWatch(arr); try { localStorage.setItem(WATCH_KEY, JSON.stringify(arr)); } catch {} };
  const inWatch = (code: string) => watch.some(w => w.code === code);
  const toggleWatch = (item: WatchItem) => { inWatch(item.code) ? saveWatch(watch.filter(w => w.code !== item.code)) : saveWatch([...watch, item]); };

  // 시그널 카테고리 토글
  const toggleCat = (id: string) => {
    const next = { ...catOpen, [id]: !catOpen[id] };
    setCatOpen(next);
    try { localStorage.setItem(CATS_KEY, JSON.stringify(next)); } catch {}
  };

  const toggleDark = () => { document.documentElement.classList.toggle('dark'); setDark(d => !d); };

  useEffect(() => {
    const handler = (e: MouseEvent) => { if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // 통합검색 — 기업 + 산업 동시
  const search = async (q: string) => {
    if (!q.trim()) { setOpen(false); setResults([]); setSectorHits([]); return; }
    setLoading(true); setOpen(true);
    try {
      const [sRes, secRes] = await Promise.all([
        fetch(`${API}/api/search?q=${encodeURIComponent(q)}&limit=8`).then(r=>r.json()).catch(()=>({results:[]})),
        fetch(`${API}/api/sectors/search?q=${encodeURIComponent(q)}`).then(r=>r.json()).catch(()=>({matched_sectors:[]})),
      ]);
      setResults(sRes.results || []);
      setSectorHits(secRes.matched_sectors || []);
    } catch { setResults([]); setSectorHits([]); }
    finally { setLoading(false); }
  };
  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value; setQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(v), 200);
  };
  const onEnter = () => {
    if (sectorHits[0] && results.length === 0) goSector(sectorHits[0]);
    else if (results[0]) goStock(results[0].stock_code);
  };

  const goStock  = (code: string) => router.push(`/stock/${code}`);
  const goSector = (name: string) => router.push(`/sectors/${encodeURIComponent(name)}`);

  // 회전 업종 6개 (현재 창)
  const sectorWindow = allSectors.length
    ? Array.from({ length: Math.min(6, allSectors.length) }, (_, i) => allSectors[(secWin + i) % allSectors.length])
    : [];

  // ── 마켓 시그널 패널 (카테고리 접기/펴기) ──
  const SignalPanel = () => {
    if (!morning?.overall) {
      return (
        <div className="bg-white/5 border border-white/10 rounded-2xl p-5">
          <div className="text-base font-bold text-white">📡 글로벌 마켓 시그널</div>
          <div className="text-[11px] text-slate-500 mb-3 flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 border-2 border-slate-500 border-t-transparent rounded-full animate-spin"></span>실시간 시황 불러오는 중…
          </div>
          <div className="h-16 rounded-xl bg-white/10 animate-pulse mb-4"></div>
          <div className="space-y-2">{[0,1,2,3,4,5].map(i => <div key={i} className="h-9 rounded-lg bg-white/10 animate-pulse"></div>)}</div>
        </div>
      );
    }
    const flat: any = {};
    (Object.values(morning.sections||{}) as any[]).flat().forEach((e:any)=>{ flat[e.ticker]=e; });
    const used = new Set(SIGNAL_CATS.flatMap(c => c.tickers));
    const leftover = Object.keys(flat).filter(tk => !used.has(tk));
    const cats = leftover.length ? [...SIGNAL_CATS, { id: 'etc', name: '기타', tickers: leftover }] : SIGNAL_CATS;
    const Row = (e: any) => {
      const tip = `${e.label}\n${e.desc||''}\n📊 ${e.range_str||''}`;
      const isAdd = M_ADDITIONAL.includes(e.ticker);
      return (
        <div key={e.ticker} className="flex items-center gap-1.5 py-1.5 px-1 border-t border-white/5 first:border-t-0">
          {isAdd && <span className="text-[8px] text-amber-400 flex-shrink-0" title="추가지표">●</span>}
          <span className="flex-1 text-[12px] text-slate-100 truncate" title={tip}>{e.label}</span>
          <span className="text-[12px] font-mono text-white text-right w-14 truncate" title={tip}>{e.price_str}</span>
          <span className={`text-[11px] font-mono w-11 text-right flex-shrink-0 ${e.change_pct>=0?'text-emerald-400':'text-rose-400'}`}>{e.delta_str}</span>
        </div>
      );
    };
    return (
      <div className="bg-white/5 border border-white/10 rounded-2xl p-5">
        <div className="text-base font-bold text-white">📡 글로벌 마켓 시그널</div>
        <div className="text-[11px] text-slate-500 mb-3">개장 전 글로벌 시황 → 한국장 방향 · {morning.as_of}</div>
        <div className="flex items-center gap-3 mb-4 p-3 rounded-xl bg-white/5 border border-white/10">
          <span className="text-3xl">{morning.overall.icon}</span>
          <div className="flex-1">
            <div className="text-sm font-semibold text-white leading-snug">{morning.overall.text}</div>
            <div className="text-[11px] text-slate-400 mt-1">🟢{morning.overall.green} 🟡{morning.overall.yellow} 🔴{morning.overall.red}</div>
          </div>
        </div>
        {/* 카테고리 접기/펴기 */}
        <div className="space-y-1">
          {cats.map(cat => {
            const rows = cat.tickers.map(tk => flat[tk]).filter(Boolean);
            if (!rows.length) return null;
            const isOpen = catOpen[cat.id] ?? false;
            return (
              <div key={cat.id} className="border-t border-white/10 first:border-t-0">
                <button onClick={()=>toggleCat(cat.id)} className="w-full flex items-center gap-2 py-2.5 hover:bg-white/[0.03] rounded transition-colors">
                  <span className="text-[13px] font-bold text-slate-200 flex-1 text-left">{cat.name}</span>
                  <span className="text-[11px] text-slate-500">{rows.length}</span>
                  <span className={`text-slate-500 text-[12px] transition-transform ${isOpen?'':'-rotate-90'}`}>▾</span>
                </button>
                {isOpen && <div className="pb-2 pl-0.5">{rows.map(Row)}</div>}
              </div>
            );
          })}
        </div>
        <div className="text-[10px] text-slate-500 mt-3 pt-2 border-t border-white/10"><span className="text-amber-400">●</span> 추가지표 · 이름 위 마우스=설명·한달범위 · 투자 참고용</div>
      </div>
    );
  };

  const Star = ({ item, size=18 }: { item: WatchItem; size?: number }) => {
    const on = inWatch(item.code);
    return (
      <button onClick={(e)=>{ e.stopPropagation(); toggleWatch(item); }} title={on ? '관심종목 해제' : '관심종목 추가'} aria-label="관심종목"
        className={`flex-shrink-0 grid place-items-center rounded-md transition-colors ${on?'text-amber-400':'text-slate-500 hover:text-amber-300'}`} style={{ width: size+14, height: size+14 }}>
        <span style={{ fontSize: size }}>{on ? '★' : '☆'}</span>
      </button>
    );
  };

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 flex flex-col">

      {/* ── 상단 고정 네비게이션 ── */}
      <header className="sticky top-0 z-40 flex items-center gap-5 px-6 h-16 border-b border-white/10 bg-slate-950/70 backdrop-blur-md">
        <button onClick={()=>router.push('/')} className="flex items-center gap-2 flex-shrink-0" title="홈으로">
          <span className="text-xl font-extrabold text-white tracking-tight">FINSIGHT</span>
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-500/30 text-indigo-300 font-medium border border-indigo-500/40">PoC</span>
        </button>
        <div className="flex items-center gap-3 flex-shrink-0 ml-auto">
          <button onClick={()=>signalRef.current?.scrollIntoView({behavior:'smooth'})} className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-semibold text-amber-300 border border-amber-400/30 bg-amber-400/5 hover:bg-amber-400/15 transition-colors" title="관심종목으로 이동">
            ★ 관심종목 <span className="text-[11px] font-bold text-slate-900 bg-amber-300 rounded-full px-1.5 min-w-[18px] text-center">{watch.length}</span>
          </button>
          <span className="text-[12px] text-slate-500 hidden lg:block">KPMG AI Lab · 2026-06-15</span>
          <button onClick={toggleDark} className="w-9 h-9 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center text-white transition-colors" title="다크모드">{dark ? '☀️' : '🌙'}</button>
        </div>
      </header>

      {/* ── 본문: (좌 스페이서) 중앙 메인 + 우측 시그널 — 메인을 화면 정중앙에 ── */}
      <div className="flex-1 w-full max-w-[1640px] mx-auto grid grid-cols-1 lg:grid-cols-[380px_minmax(0,1fr)_380px] gap-8 px-6 py-8">

        {/* 좌측 스페이서 (우측 시그널과 대칭 → 중앙 메인이 화면 정가운데) */}
        <div className="hidden lg:block" aria-hidden />

        {/* 중앙 메인 */}
        <div className="flex flex-col items-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 text-xs font-medium mt-2 mb-5">
            🤖 AI 기반 기업 분석 자동화 · NO-MOCK
          </div>
          <h1 className="text-4xl sm:text-5xl font-extrabold text-white tracking-tight text-center mb-4">
            기업 분석, 이제 <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-purple-400">5분 만에</span>
          </h1>
          <p className="text-slate-400 text-base sm:text-lg text-center max-w-lg mb-8">
            <b className="text-slate-200 font-bold">DART 공시 + LLM + DCF 모델링</b>으로<br/>개인 투자자도 기관 수준의 분석을 한 화면에서
          </p>

          {/* 통합 스마트 검색 */}
          <div className="relative w-full max-w-2xl mb-5" ref={wrapRef}>
            <div className="flex items-center bg-white/[0.06] border-2 rounded-2xl px-5 h-16 shadow-2xl shadow-indigo-900/40 transition-all" style={{ borderColor: open ? '#8b5cf6' : 'rgba(255,255,255,0.14)' }}>
              <svg className="w-5 h-5 text-indigo-400 mr-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"/></svg>
              <input ref={inputRef} value={query} onChange={handleInput} onFocus={()=>{ if(query) setOpen(true); }} onKeyDown={e => { if (e.key === 'Enter') onEnter(); }}
                placeholder="기업명 · 종목코드 · 업종을 한 번에  (예: 삼성전자, 005930, 방산)" className="flex-1 outline-none text-white placeholder-slate-500 bg-transparent text-[15px] font-medium" autoComplete="off"/>
              {loading && <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin ml-2"/>}
            </div>

            {open && (
              <div className="absolute top-full left-0 right-0 mt-3 bg-[#16132e] border border-white/15 rounded-2xl shadow-2xl shadow-black/60 z-50 overflow-hidden">
                {sectorHits.length > 0 && (
                  <>
                    <div className="flex items-center gap-2 px-5 pt-3.5 pb-2 text-[12px] font-bold tracking-wide uppercase text-slate-500">
                      산업 <span className="text-[11px] font-bold tracking-normal normal-case px-2 py-0.5 rounded-full text-indigo-300 bg-indigo-500/15 border border-indigo-500/40">업종 {sectorHits.length}건</span>
                    </div>
                    {sectorHits.map(name => (
                      <button key={name} onClick={()=>goSector(name)} className="w-full flex items-center gap-3 px-5 py-2.5 hover:bg-indigo-500/10 transition-colors text-left">
                        <span className="w-9 h-9 rounded-lg grid place-items-center bg-indigo-500/15 border border-indigo-500/40 text-indigo-300 flex-shrink-0">🏭</span>
                        <span className="flex-1 text-[15px] font-bold text-white">{name}</span>
                        {sectorCount[name] != null && <span className="text-[11px] font-bold px-2 py-0.5 rounded-full text-purple-200 bg-purple-500/15 border border-purple-500/40">{sectorCount[name]}종목</span>}
                        <span className="text-slate-500">›</span>
                      </button>
                    ))}
                    {results.length > 0 && <div className="h-px bg-white/10 mx-2 my-1"/>}
                  </>
                )}
                {results.length > 0 && (
                  <div className="flex items-center gap-2 px-5 pt-3 pb-2 text-[12px] font-bold tracking-wide uppercase text-slate-500">
                    기업 <span className="text-[11px] font-bold tracking-normal normal-case px-2 py-0.5 rounded-full text-emerald-300 bg-emerald-500/10 border border-emerald-500/30">종목 {results.length}건</span>
                  </div>
                )}
                {results.map(r => (
                  <button key={r.stock_code} onClick={()=>goStock(r.stock_code)} className="w-full flex items-center gap-3 px-5 py-2.5 hover:bg-indigo-500/10 transition-colors text-left">
                    <span className="w-9 h-9 rounded-lg grid place-items-center bg-white/5 border border-white/10 text-slate-300 font-bold flex-shrink-0">{r.corp_name.slice(0,1)}</span>
                    <span className="flex-1 text-[15px] font-bold text-white truncate">{r.corp_name}</span>
                    <span className="font-mono text-[13px] text-slate-400">{r.stock_code}</span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full font-bold" style={{ color: r.market==='KOSPI'?'#cfe0ff':'#e3d4ff', background: r.market==='KOSPI'?'rgba(79,140,247,.18)':'rgba(155,108,240,.18)', border: `1px solid ${r.market==='KOSPI'?'rgba(79,140,247,.4)':'rgba(155,108,240,.4)'}` }}>{r.market}</span>
                    <Star item={{ code: r.stock_code, name: r.corp_name, market: r.market }} size={17}/>
                  </button>
                ))}
                {!loading && results.length === 0 && sectorHits.length === 0 && (
                  <div className="px-5 py-4 text-sm text-slate-400 text-center">검색 결과 없음</div>
                )}
                <div className="flex items-center gap-4 px-5 py-2.5 text-[12px] text-slate-500 border-t border-white/10">
                  <span><kbd className="px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-slate-300">Enter</kbd> 열기</span>
                  <span><kbd className="px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-slate-300">★</kbd> 관심종목</span>
                  {sectorHits[0] && <button onClick={()=>goSector(sectorHits[0])} className="ml-auto text-indigo-300 font-semibold hover:underline">'{sectorHits[0]}' 업종 전체 보기 →</button>}
                </div>
              </div>
            )}
          </div>

          {/* 추천 종목 캐러셀 (검색란 바로 밑, 밸류·DCF 충실 종목만) */}
          {rotation.length >= 4 && (
            <div className="overflow-hidden mb-7" style={{ width: '624px', maxWidth: '92vw' }}>
              <div className="flex gap-3"
                onMouseEnter={()=>{ slidePausedRef.current = true; }} onMouseLeave={()=>{ slidePausedRef.current = false; }}
                style={{ transform: sliding ? `translateX(-${SLIDE_STEP}px)` : 'translateX(0)', transition: sliding ? 'transform 0.8s ease-in-out' : 'none' }}>
                {[0,1,2,3].map(i => {
                  const s = rotation[(slidePos + i) % rotation.length];
                  if (!s) return null;
                  return (
                    <button key={`${slidePos}-${i}`} onClick={()=>goStock(s.stock_code)}
                      className="group flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 hover:border-indigo-400/60 text-white transition-colors flex-shrink-0" style={{ width: '192px' }}>
                      <div className="text-left overflow-hidden">
                        <div className="text-sm font-semibold truncate">{s.corp_name}</div>
                        <div className="text-xs text-slate-400 font-mono truncate">{s.stock_code} · {s.tag}</div>
                      </div>
                      <svg className="w-4 h-4 text-slate-400 group-hover:text-indigo-300 ml-auto transition-colors flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/></svg>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* 업종 둘러보기 (랜덤 회전) + 전체 78업종 */}
          <div className="w-full flex flex-wrap items-center gap-2 mb-2">
            <span className="text-[13px] font-bold text-slate-500 mr-1">업종 둘러보기</span>
            {sectorWindow.map(s => s && (
              <button key={s.name} onClick={()=>goSector(s.name)}
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-full text-[13.5px] font-semibold text-slate-300 border border-white/10 bg-white/5 hover:text-white hover:border-indigo-400/50 hover:bg-indigo-500/10 transition-colors">
                {s.name}<span className="text-[12px] font-bold text-slate-500">{s.count}</span>
              </button>
            ))}
            <button onClick={()=>router.push('/sectors')}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full text-[13.5px] font-semibold text-indigo-300 border border-indigo-500/40 bg-indigo-500/15 hover:bg-indigo-500/25 transition-colors">
              전체 78업종 ›
            </button>
          </div>

          {/* 내 관심종목 */}
          <div className="w-full mt-8">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-amber-400">★</span>
              <span className="text-[14px] font-bold text-slate-300">내 관심종목</span>
              <span className="text-[12px] text-slate-500">· 로그인 없이 이 브라우저에 저장</span>
            </div>
            <div className="flex flex-wrap items-center gap-2.5">
              {watch.map(w => (
                <div key={w.code} onClick={()=>goStock(w.code)} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 cursor-pointer transition-colors">
                  <span className="text-amber-400 text-[13px]">★</span>
                  <span className="text-[14px] font-bold text-white">{w.name}</span>
                  <span className="font-mono text-[11px] text-slate-500">{w.code}</span>
                  <button onClick={(e)=>{ e.stopPropagation(); toggleWatch(w); }} className="text-slate-600 hover:text-rose-400 text-[13px] ml-0.5" title="해제">✕</button>
                </div>
              ))}
              <span className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-dashed border-white/15 text-[13px] text-slate-500">
                {watch.length === 0 ? '검색에서 ☆ 눌러 관심종목을 추가하세요' : '+ 검색에서 ☆ 추가'}
              </span>
            </div>
          </div>
        </div>

        {/* 우측 시그널 사이드 (오른쪽 끝) */}
        <aside ref={signalRef} className="lg:sticky lg:top-20 lg:self-start">
          <SignalPanel/>
        </aside>
      </div>

      <footer className="text-center py-6 border-t border-white/5">
        <div className="text-xs text-slate-600">FINSIGHT · KPMG AI Lab · 2026-06-15 데모 · NO-MOCK: 추정하지 않는다, 출처(DART 공시)로 말한다</div>
        <div className="text-sm font-bold text-slate-100 tracking-[0.18em] mt-2">FILMN9&nbsp;Inc.</div>
      </footer>
    </main>
  );
}
