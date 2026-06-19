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
// 지표 기본 순서(드래그 순서변경의 기준) — localStorage에 사용자 순서 저장
const M_DEFAULT_ORDER: string[] = SIGNAL_CATS.flatMap(c => c.tickers);
const MORDER_KEY = 'finsight_morning_order';

interface SearchResult { stock_code: string; corp_name: string; market: string; has_data: boolean; }
interface WatchItem { code: string; name: string; market: string; }
interface FeatStock { stock_code: string; corp_name: string; market?: string; tag?: string; }

const WATCH_KEY = 'finsight_watchlist';
const CATS_KEY  = 'finsight_signal_cats';
const SIGFAV_KEY = 'finsight_signal_fav';   // 시그널 즐겨찾기(카테고리 무관 내가 고른 지수)

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

// 시총(원) → '조/억' 축약
function fmtCap(won?: number | null): string {
  if (!won) return '—';
  const jo = won / 1e12;
  if (jo >= 1) return jo.toFixed(jo >= 10 ? 0 : 1) + '조';
  return Math.round(won / 1e8).toLocaleString() + '억';
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
  const [wQuotes, setWQuotes] = useState<Record<string, any>>({});   // 관심종목 시세(시총·등락·PER·PBR)

  // 업종 — 회전 표시(랜덤 순서로 6개씩 돌아감) + 업종→종목수 매핑(드롭다운)
  const [allSectors, setAllSectors] = useState<{name:string;count:number}[]>([]);
  const [secWin, setSecWin] = useState(0);
  const [sectorCount, setSectorCount] = useState<Record<string, number>>({});

  // 추천 종목 캐러셀 (밸류·DCF 충실 종목만) — 검색란 바로 밑, 4초마다 한 칸 슬라이드
  const [rotation, setRotation] = useState<FeatStock[]>([]);
  const [slidePos, setSlidePos] = useState(0);
  const slidePausedRef = useRef(false);

  // 관심종목 (localStorage)
  const [watch, setWatch] = useState<WatchItem[]>([]);
  // 시그널 카테고리 열림 상태
  const [catOpen, setCatOpen] = useState<Record<string, boolean>>({ fav: true, index: true, fxrate: false, commodity: false, sentiment: false });
  const [sigFav, setSigFav] = useState<string[]>([]);   // 시그널 즐겨찾기 ticker 목록
  const [wDrag, setWDrag] = useState<string | null>(null);   // 관심종목 드래그 순서변경
  // 지표 드래그 순서변경 (localStorage 저장)
  const [mOrder, setMOrder] = useState<string[]>(M_DEFAULT_ORDER);
  const [mDrag,  setMDrag]  = useState<string | null>(null);

  // ── 초기 로드 ──
  useEffect(() => {
    fetch(`${API}/api/morning`).then(r=>r.json()).then(setMorning).catch(()=>{});
    fetch(`${API}/api/sectors`).then(r=>r.json()).then(d=>{
      const arr = (d.sectors || []) as {sector_name:string;count:number}[];
      setAllSectors(arr.map(s => ({ name: s.sector_name, count: s.count })));   // 백엔드 시총순 유지
      const m: Record<string, number> = {};
      arr.forEach(s => { m[s.sector_name] = s.count; });
      setSectorCount(m);
    }).catch(()=>{});
    // 캐러셀 풀 — 밸류 충실 종목(source=val). 매 방문마다 업종이 골고루 섞여 '다른 3개씩'
    // 보이도록: 전체 셔플 + 업종(tag) 라운드로빈(연속 카드가 서로 다른 업종이 되게).
    fetch(`${API}/api/featured?n=40&source=val`).then(r=>r.json()).then(d=>{
      const arr = (d.stocks || []) as FeatStock[];
      const shuffle = <T,>(a:T[]):T[] => { for (let i=a.length-1;i>0;i--){ const j=Math.floor(Math.random()*(i+1)); [a[i],a[j]]=[a[j],a[i]]; } return a; };
      const groups: Record<string, FeatStock[]> = {};
      for (const s of arr) { const k = s.tag || '기타'; (groups[k] ||= []).push(s); }
      Object.values(groups).forEach(g => shuffle(g));
      const keys = shuffle(Object.keys(groups));
      const out: FeatStock[] = []; let added = true;
      while (added) { added = false; for (const k of keys) { const g = groups[k]; if (g.length) { out.push(g.shift()!); added = true; } } }
      setRotation(out);
    }).catch(()=>{});
    try { const s = localStorage.getItem(WATCH_KEY); if (s) setWatch(JSON.parse(s)); } catch {}
    try { const c = localStorage.getItem(CATS_KEY); if (c) setCatOpen({ fav: true, ...JSON.parse(c) }); } catch {}
    try { const f = localStorage.getItem(SIGFAV_KEY); if (f) setSigFav(JSON.parse(f)); } catch {}
    try {
      const o = localStorage.getItem(MORDER_KEY);
      if (o) { const arr = JSON.parse(o) as string[];
        setMOrder([...arr.filter(t=>M_DEFAULT_ORDER.includes(t)), ...M_DEFAULT_ORDER.filter(t=>!arr.includes(t))]); }
    } catch {}
  }, []);

  // 업종 칩 회전 (3.5초마다 한 칸)
  useEffect(() => {
    if (allSectors.length < 7) return;
    const id = setInterval(() => setSecWin(p => (p + 1) % allSectors.length), 3500);
    return () => clearInterval(id);
  }, [allSectors.length]);

  // 추천 종목 자동 회전 — 5초마다 한 칸 콘텐츠 교체(슬라이드 클리핑 없음). 호버·화살표 조작 시 일시정지.
  useEffect(() => {
    if (rotation.length < 4) return;
    const id = setInterval(() => {
      if (slidePausedRef.current) return;
      setSlidePos(p => (p + 1) % rotation.length);
    }, 5000);
    return () => clearInterval(id);
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
  // 관심종목 드래그 순서변경 (지수처럼 내 마음대로 정렬)
  const wOnDrop = (targetCode: string) => {
    if (!wDrag || wDrag === targetCode) { setWDrag(null); return; }
    const arr = [...watch];
    const from = arr.findIndex(w => w.code === wDrag), to = arr.findIndex(w => w.code === targetCode);
    if (from < 0 || to < 0) { setWDrag(null); return; }
    const [moved] = arr.splice(from, 1); arr.splice(to, 0, moved);
    saveWatch(arr); setWDrag(null);
  };
  // 시그널 즐겨찾기 토글 (카테고리 무관 — 내가 고른 지수만 상단에 모아보기)
  const toggleSigFav = (tk: string) => {
    setSigFav(prev => {
      const next = prev.includes(tk) ? prev.filter(t => t !== tk) : [...prev, tk];
      try { localStorage.setItem(SIGFAV_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  };
  // 지표 드래그 순서변경
  const mSaveOrder = (arr: string[]) => { setMOrder(arr); try { localStorage.setItem(MORDER_KEY, JSON.stringify(arr)); } catch {} };
  const mOnDrop = (target: string) => {
    if (!mDrag || mDrag === target) { setMDrag(null); return; }
    const arr = [...mOrder];
    const from = arr.indexOf(mDrag), to = arr.indexOf(target);
    if (from < 0 || to < 0) { setMDrag(null); return; }
    arr.splice(from, 1); arr.splice(to, 0, mDrag);
    mSaveOrder(arr); setMDrag(null);
  };

  const toggleDark = () => { document.documentElement.classList.toggle('dark'); setDark(d => !d); };

  useEffect(() => {
    const handler = (e: MouseEvent) => { if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // 관심종목 시세(현재가·시총·등락·PER·PBR) 조회 — watch 변경 시
  const watchKey = watch.map(w => w.code).join(',');
  useEffect(() => {
    if (!watchKey) { setWQuotes({}); return; }
    fetch(`${API}/api/watchlist-quote?codes=${watchKey}`).then(r=>r.json()).then(d=>{
      const m: Record<string, any> = {};
      (d.items || []).forEach((it: any) => { m[it.stock_code] = it; });
      setWQuotes(m);
    }).catch(()=>{});
  }, [watchKey]);

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

  // ── 관심종목 패널 (좌측, 시그널 박스와 동일 스타일) ──
  const WatchlistPanel = () => (
    <div className="bg-white border border-slate-200 shadow-sm rounded-2xl p-5">
      <div className="flex items-center gap-2">
        <span className="text-base font-bold text-slate-900">★ 내 관심종목</span>
        <span className="text-[11px] font-bold text-slate-900 bg-amber-300 rounded-full px-1.5 min-w-[18px] text-center">{watch.length}</span>
      </div>
      <div className="text-[11px] text-slate-500 mb-3">로그인 없이 이 브라우저에 저장 · 시세 ~15분 지연</div>
      {watch.length === 0 ? (
        <div className="text-[12px] text-slate-500 py-10 text-center border border-dashed border-slate-200 rounded-xl leading-relaxed">
          검색에서 <span className="text-amber-500">☆</span> 를 눌러<br/>관심종목을 추가하세요
        </div>
      ) : (
        <div className="space-y-2">
          {watch.map(w => {
            const q = wQuotes[w.code];
            const up = q?.change_pct;
            return (
              <div key={w.code}
                onDragOver={(ev)=>ev.preventDefault()} onDrop={()=>wOnDrop(w.code)}
                className={`p-3 rounded-xl bg-slate-50 hover:bg-indigo-50 border border-slate-200 transition-colors ${wDrag===w.code?'opacity-40':''}`}>
                <div className="flex items-center gap-1.5">
                  <span draggable onDragStart={(ev)=>{ ev.stopPropagation(); setWDrag(w.code); }}
                    className="text-slate-600 text-[13px] cursor-grab active:cursor-grabbing select-none flex-shrink-0" title="드래그로 순서 변경">⠿</span>
                  <span onClick={()=>goStock(w.code)} className="text-[15px] font-bold text-slate-900 truncate cursor-pointer flex-1">{w.name}</span>
                  <button onClick={(e)=>{ e.stopPropagation(); toggleWatch(w); }} title="해제"
                    className="text-slate-600 hover:text-rose-600 text-[13px] flex-shrink-0">✕</button>
                </div>
                <div onClick={()=>goStock(w.code)} className="flex items-center justify-between mt-1 cursor-pointer">
                  <span className="font-mono text-[17px] font-bold text-slate-900">{q?.price ? '₩'+q.price.toLocaleString() : '—'}</span>
                  <span className={`font-mono text-[13.5px] font-semibold ${up==null?'text-slate-500':up>=0?'text-emerald-600':'text-rose-600'}`}>
                    {up==null ? '—' : (up>=0?'▲ +':'▼ ')+up+'%'}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-1.5 text-[12px] text-slate-400">
                  <span>시총 <b className="text-slate-700">{fmtCap(q?.market_cap)}</b></span>
                  <span>PER <b className="text-slate-700">{q?.per ?? '—'}</b></span>
                  <span>PBR <b className="text-slate-700">{q?.pbr ?? '—'}</b></span>
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="text-[10px] text-slate-500 mt-3 pt-2 border-t border-slate-200">시총·PER·PBR=최신 재무·시세 기준 · 적자 등은 — 표기</div>
    </div>
  );

  // ── 마켓 시그널 패널 (카테고리 접기/펴기) ──
  const SignalPanel = () => {
    if (!morning?.overall) {
      return (
        <div className="bg-white border border-slate-200 shadow-sm rounded-2xl p-5">
          <div className="text-base font-bold text-slate-900">📡 글로벌 마켓 시그널</div>
          <div className="text-[11px] text-slate-500 mb-3 flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 border-2 border-slate-500 border-t-transparent rounded-full animate-spin"></span>실시간 시황 불러오는 중…
          </div>
          <div className="h-16 rounded-xl bg-slate-200 animate-pulse mb-4"></div>
          <div className="space-y-2">{[0,1,2,3,4,5].map(i => <div key={i} className="h-9 rounded-lg bg-slate-200 animate-pulse"></div>)}</div>
        </div>
      );
    }
    const flat: any = {};
    (Object.values(morning.sections||{}) as any[]).flat().forEach((e:any)=>{ flat[e.ticker]=e; });
    const used = new Set(SIGNAL_CATS.flatMap(c => c.tickers));
    const leftover = Object.keys(flat).filter(tk => !used.has(tk));
    // ⭐ 즐겨찾기 — 카테고리 무관 사용자가 별표한 지수를 맨 위 한 곳에 모음
    const favTickers = sigFav.filter(tk => flat[tk]);
    const favCat = favTickers.length ? [{ id: 'fav', name: '⭐ 즐겨찾기', tickers: favTickers }] : [];
    const baseCats = leftover.length ? [...SIGNAL_CATS, { id: 'etc', name: '기타', tickers: leftover }] : [...SIGNAL_CATS];
    const cats = [...favCat, ...baseCats];
    const Row = (e: any) => {
      // (i) 툴팁: 설명 + 지난 한 달 범위·추세(오름세/내림세/보합세)
      const tip = [e.label, e.desc || '', e.range_str ? `📊 ${e.range_str}` : ''].filter(Boolean).join('\n');
      const isAdd = M_ADDITIONAL.includes(e.ticker);
      return (
        <div key={e.ticker}
          onDragOver={(ev)=>ev.preventDefault()} onDrop={()=>mOnDrop(e.ticker)}
          className={`flex items-center gap-1.5 py-1.5 px-1 border-t border-slate-100 first:border-t-0 hover:bg-slate-50 rounded ${mDrag===e.ticker?'opacity-40':''}`}>
          <span draggable onDragStart={(ev)=>{ ev.stopPropagation(); setMDrag(e.ticker); }}
            className="text-slate-600 text-[13px] cursor-grab active:cursor-grabbing select-none flex-shrink-0" title="드래그로 순서 변경">⠿</span>
          {isAdd && <span className="text-[8px] text-amber-400 flex-shrink-0" title="추가지표">●</span>}
          <span className="text-[13.5px] text-slate-800 truncate min-w-0" title={tip}>{e.label}</span>
          <span className="text-slate-500 hover:text-indigo-300 text-[12px] leading-none cursor-help flex-shrink-0" title={tip}>ⓘ</span>
          <button onClick={(ev)=>{ ev.stopPropagation(); toggleSigFav(e.ticker); }}
            title={sigFav.includes(e.ticker) ? '즐겨찾기 해제' : '즐겨찾기 추가'}
            className={`text-[12px] leading-none flex-shrink-0 ${sigFav.includes(e.ticker) ? 'text-amber-400' : 'text-slate-600 hover:text-amber-500'}`}>
            {sigFav.includes(e.ticker) ? '★' : '☆'}
          </button>
          <span className="flex-1" />
          <span className="text-[13.5px] font-mono font-semibold text-slate-900 text-right w-[88px] flex-shrink-0" title={tip}>{e.price_str}</span>
          <span className={`text-[12.5px] font-mono w-[58px] text-right flex-shrink-0 ${e.change_pct>=0?'text-emerald-600':'text-rose-600'}`}>{e.delta_str}</span>
        </div>
      );
    };
    const orderIdx = (tk: string) => { const i = mOrder.indexOf(tk); return i < 0 ? 999 : i; };
    return (
      <div className="bg-white border border-slate-200 shadow-sm rounded-2xl p-5">
        <div className="text-base font-bold text-slate-900">📡 글로벌 마켓 시그널</div>
        <div className="text-[11px] text-slate-500 mb-3">개장 전 글로벌 시황 → 한국장 방향 · {morning.as_of}</div>
        <div className="flex items-center gap-3 mb-4 p-3 rounded-xl bg-slate-50 border border-slate-200">
          <span className="text-3xl">{morning.overall.icon}</span>
          <div className="flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-[15px] font-semibold text-slate-900 leading-snug">{morning.overall.text}</span>
              <span className="text-slate-400 hover:text-indigo-300 text-[12px] leading-none cursor-help flex-shrink-0"
                title={`글로벌 23개 지표(미 선물·금리·환율·아시아 지수 등)의 간밤 등락을, 각 지표의 KOSPI와의 과거 상관관계로 신호등(🟢/🔴) 채점해 합산한 종합 판정입니다.\n규칙: 🟢4↑ "상승 우호" · 🔴4↑ "하락 위험" · 🟢>🔴 "소폭 상승 가능성" · 그 외 "혼조세".\n현재 🟢${morning.overall.green} 🟡${morning.overall.yellow} 🔴${morning.overall.red}.\n※ 정교한 예측 모델이 아니라 글로벌 지표 종합 신호등(참고용)입니다.`}>ⓘ</span>
            </div>
            <div className="text-[12px] text-slate-400 mt-1">🟢{morning.overall.green} 🟡{morning.overall.yellow} 🔴{morning.overall.red}</div>
          </div>
        </div>
        {/* 카테고리 접기/펴기 */}
        <div className="space-y-1">
          {cats.map(cat => {
            const rows = cat.tickers.slice().sort((a,b)=>orderIdx(a)-orderIdx(b)).map(tk => flat[tk]).filter(Boolean);
            if (!rows.length) return null;
            const isOpen = catOpen[cat.id] ?? false;
            return (
              <div key={cat.id} className="border-t border-slate-200 first:border-t-0">
                <button onClick={()=>toggleCat(cat.id)} className="w-full flex items-center gap-2 py-2.5 hover:bg-slate-50 rounded transition-colors">
                  <span className="text-[13px] font-bold text-slate-700 flex-1 text-left">{cat.name}</span>
                  <span className="text-[11px] text-slate-500">{rows.length}</span>
                  <span className={`text-slate-500 text-[12px] transition-transform ${isOpen?'':'-rotate-90'}`}>▾</span>
                </button>
                {isOpen && <div className="pb-2 pl-0.5">{rows.map(Row)}</div>}
              </div>
            );
          })}
        </div>
        <div className="text-[10px] text-slate-500 mt-3 pt-2 border-t border-slate-200"><span className="text-amber-400">●</span> 추가지표 · <span className="text-slate-400">⠿ 순서변경</span> · <span className="text-slate-400">ⓘ 추세·설명</span> · <span className="text-amber-400">★ 즐겨찾기</span> · 참고용</div>
      </div>
    );
  };

  const Star = ({ item, size=18 }: { item: WatchItem; size?: number }) => {
    const on = inWatch(item.code);
    return (
      <button onClick={(e)=>{ e.stopPropagation(); toggleWatch(item); }} title={on ? '관심종목 해제' : '관심종목 추가'} aria-label="관심종목"
        className={`flex-shrink-0 grid place-items-center rounded-md transition-colors ${on?'text-amber-400':'text-slate-500 hover:text-amber-500'}`} style={{ width: size+14, height: size+14 }}>
        <span style={{ fontSize: size }}>{on ? '★' : '☆'}</span>
      </button>
    );
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-indigo-50 via-white to-white flex flex-col">

      {/* ── 상단 고정 네비게이션 ── */}
      <header className="sticky top-0 z-40 flex items-center gap-5 px-6 h-16 border-b border-slate-200 bg-white/85 backdrop-blur-md">
        <button onClick={()=>router.push('/')} className="flex items-center gap-2 flex-shrink-0" title="홈으로">
          <span className="text-2xl font-extrabold text-indigo-700 tracking-tight">FINSIGHT</span>
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-semibold border border-indigo-200">PoC</span>
        </button>
        <div className="flex items-center gap-3 flex-shrink-0 ml-auto">
          <span className="text-[13px] text-slate-500 hidden lg:block">KPMG AI Lab · 2026-06-20</span>
        </div>
      </header>

      {/* ── 본문: (좌 스페이서) 중앙 메인 + 우측 시그널 — 메인을 화면 정중앙에 ── */}
      <div className="flex-1 w-full max-w-[1820px] mx-auto grid grid-cols-1 lg:grid-cols-[420px_minmax(0,1fr)_420px] gap-12 px-5 py-8">

        {/* 좌측 관심종목 패널 (우측 시그널과 대칭 · 화면 정가운데 유지) */}
        <aside className="hidden lg:block lg:sticky lg:top-20 lg:self-start">
          {WatchlistPanel()}
        </aside>

        {/* 중앙 메인 */}
        <div className="flex flex-col items-center">
          <div className="mt-8 mb-6 text-6xl sm:text-7xl font-black tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-indigo-700 via-indigo-600 to-purple-600 select-none">
            FINSIGHT
          </div>
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-indigo-100 border border-indigo-200 text-indigo-700 text-sm font-semibold mb-7">
            🤖 AI 기반 기업 분석 자동화
          </div>
          <h1 className="text-4xl sm:text-5xl font-extrabold text-slate-900 tracking-tight text-center mb-6 leading-snug">
            기업 분석, 이제 <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-purple-600">5분 만에</span>
          </h1>
          <p className="text-slate-600 text-lg sm:text-xl text-center max-w-xl mb-10">
            <b className="text-slate-900 font-bold">DART 공시 + LLM + DCF 모델링</b>으로<br/>개인 투자자도 기관 수준의 분석을 한 화면에서
          </p>

          {/* 통합 스마트 검색 */}
          <div className="relative w-full max-w-2xl mb-14" ref={wrapRef}>
            <div className="flex items-center bg-white border-2 rounded-2xl px-5 h-[68px] shadow-xl shadow-indigo-200/60 transition-all" style={{ borderColor: open ? '#6366f1' : '#cbd5e1' }}>
              <svg className="w-6 h-6 text-indigo-500 mr-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"/></svg>
              <input ref={inputRef} value={query} onChange={handleInput} onFocus={()=>{ if(query) setOpen(true); }} onKeyDown={e => { if (e.key === 'Enter') onEnter(); }}
                placeholder="기업명 · 종목코드 · 업종을 한 번에  (예: 삼성전자, 005930, 방산)" className="flex-1 outline-none text-slate-900 placeholder-slate-400 bg-transparent text-[16px] font-medium" autoComplete="off"/>
              {loading && <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin ml-2"/>}
            </div>

            {open && (
              <div className="absolute top-full left-0 right-0 mt-3 bg-white border border-slate-200 rounded-2xl shadow-2xl shadow-slate-400/30 z-50 overflow-hidden">
                {sectorHits.length > 0 && (
                  <>
                    <div className="flex items-center gap-2 px-5 pt-3.5 pb-2 text-[12px] font-bold tracking-wide uppercase text-slate-500">
                      산업 <span className="text-[11px] font-bold tracking-normal normal-case px-2 py-0.5 rounded-full text-indigo-300 bg-indigo-500/15 border border-indigo-500/40">업종 {sectorHits.length}건</span>
                    </div>
                    {sectorHits.map(name => (
                      <button key={name} onClick={()=>goSector(name)} className="w-full flex items-center gap-3 px-5 py-3 hover:bg-indigo-50 transition-colors text-left">
                        <span className="w-9 h-9 rounded-lg grid place-items-center bg-indigo-50 border border-indigo-200 text-indigo-600 flex-shrink-0">🏭</span>
                        <span className="flex-1 text-[15px] font-bold text-slate-900">{name}</span>
                        {sectorCount[name] != null && <span className="text-[11px] font-bold px-2 py-0.5 rounded-full text-purple-700 bg-purple-50 border border-purple-200">{sectorCount[name]}종목</span>}
                        <span className="text-slate-400">›</span>
                      </button>
                    ))}
                    {results.length > 0 && <div className="h-px bg-slate-100 mx-2 my-1"/>}
                  </>
                )}
                {results.length > 0 && (
                  <div className="flex items-center gap-2 px-5 pt-3 pb-2 text-[12px] font-bold tracking-wide uppercase text-slate-500">
                    기업 <span className="text-[11px] font-bold tracking-normal normal-case px-2 py-0.5 rounded-full text-emerald-300 bg-emerald-500/10 border border-emerald-500/30">종목 {results.length}건</span>
                  </div>
                )}
                {results.map(r => (
                  <button key={r.stock_code} onClick={()=>goStock(r.stock_code)} className="w-full flex items-center gap-3 px-5 py-3 hover:bg-indigo-50 transition-colors text-left">
                    <span className="w-9 h-9 rounded-lg grid place-items-center bg-slate-100 border border-slate-200 text-slate-600 font-bold flex-shrink-0">{r.corp_name.slice(0,1)}</span>
                    <span className="flex-1 text-[15px] font-bold text-slate-900 truncate">{r.corp_name}</span>
                    <span className="font-mono text-[13px] text-slate-500">{r.stock_code}</span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full font-bold" style={{ color: r.market==='KOSPI'?'#cfe0ff':'#e3d4ff', background: r.market==='KOSPI'?'rgba(79,140,247,.18)':'rgba(155,108,240,.18)', border: `1px solid ${r.market==='KOSPI'?'rgba(79,140,247,.4)':'rgba(155,108,240,.4)'}` }}>{r.market}</span>
                    <Star item={{ code: r.stock_code, name: r.corp_name, market: r.market }} size={17}/>
                  </button>
                ))}
                {!loading && results.length === 0 && sectorHits.length === 0 && (
                  <div className="px-5 py-4 text-sm text-slate-400 text-center">검색 결과 없음</div>
                )}
                <div className="flex items-center gap-4 px-5 py-2.5 text-[12px] text-slate-500 border-t border-slate-100 bg-slate-50">
                  <span><kbd className="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-slate-600">Enter</kbd> 열기</span>
                  <span><kbd className="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-slate-600">★</kbd> 관심종목</span>
                  {sectorHits[0] && <button onClick={()=>goSector(sectorHits[0])} className="ml-auto text-indigo-600 font-semibold hover:underline">'{sectorHits[0]}' 업종 전체 보기 →</button>}
                </div>
              </div>
            )}
          </div>

          {/* 추천 종목 캐러셀 — 정확히 3개 표시(잘림 없음) + 좌우 화살표로 왔다갔다 */}
          {rotation.length >= 4 && (
            <div className="w-full flex flex-col items-center mb-16">
              <div className="text-lg font-bold text-slate-800 mb-3">✨ 추천 종목 <span className="text-[14px] font-normal text-slate-500">· 거래대금 상위 인기 종목</span></div>
              <div className="flex items-center gap-2.5"
                onMouseEnter={()=>{ slidePausedRef.current = true; }} onMouseLeave={()=>{ slidePausedRef.current = false; }}>
                {/* 이전 */}
                <button onClick={()=>setSlidePos(p => (p - 1 + rotation.length) % rotation.length)} aria-label="이전 추천 종목"
                  className="flex-shrink-0 w-9 h-9 grid place-items-center rounded-full bg-white hover:bg-indigo-50 border border-slate-200 hover:border-indigo-400 text-slate-500 hover:text-indigo-600 shadow-sm transition-colors">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/></svg>
                </button>
                {/* 카드 3개 (잘림 없음) */}
                <div className="flex gap-3 transition-opacity duration-300" style={{ maxWidth: '90vw' }}>
                  {[0,1,2].map(i => {
                    const s = rotation[(slidePos + i) % rotation.length];
                    if (!s) return null;
                    return (
                      <button key={`${slidePos}-${i}`} onClick={()=>goStock(s.stock_code)}
                        className="group flex items-center gap-2 px-4 py-3.5 rounded-xl bg-white hover:bg-indigo-50 border border-slate-200 hover:border-indigo-400 text-slate-900 shadow-sm transition-colors flex-shrink-0" style={{ width: '230px' }}>
                        <div className="text-left overflow-hidden">
                          <div className="text-[15px] font-bold truncate">{s.corp_name}</div>
                          <div className="text-xs text-slate-500 font-mono truncate">{s.stock_code} · {s.tag}</div>
                        </div>
                        <svg className="w-4 h-4 text-slate-400 group-hover:text-indigo-500 ml-auto transition-colors flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/></svg>
                      </button>
                    );
                  })}
                </div>
                {/* 다음 */}
                <button onClick={()=>setSlidePos(p => (p + 1) % rotation.length)} aria-label="다음 추천 종목"
                  className="flex-shrink-0 w-9 h-9 grid place-items-center rounded-full bg-white hover:bg-indigo-50 border border-slate-200 hover:border-indigo-400 text-slate-500 hover:text-indigo-600 shadow-sm transition-colors">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/></svg>
                </button>
              </div>
            </div>
          )}

          {/* 업종 둘러보기 (랜덤 회전) + 전체 78업종 */}
          <div className="w-full flex flex-col items-center gap-3">
            <div className="flex items-center justify-center gap-3">
              <span className="text-lg font-bold text-slate-800">🏭 업종 둘러보기</span>
              <button onClick={()=>router.push('/sectors')}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-[14px] font-semibold text-indigo-700 border border-indigo-200 bg-indigo-50 hover:bg-indigo-100 transition-colors">
                전체 78업종 ›
              </button>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2">
              {sectorWindow.map(s => s && (
                <button key={s.name} onClick={()=>goSector(s.name)}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-full text-[15px] font-semibold text-slate-700 border border-slate-200 bg-white shadow-sm hover:text-indigo-700 hover:border-indigo-400 hover:bg-indigo-50 transition-colors">
                  {s.name}<span className="text-[12.5px] font-bold text-slate-400">{s.count}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 내 관심종목 (모바일 전용 — 데스크톱은 좌측 패널에 표시) */}
          <div className="w-full mt-16 lg:hidden">
            <div className="flex items-center justify-center gap-2 mb-3">
              <span className="text-amber-400">★</span>
              <span className="text-[14px] font-bold text-slate-700">내 관심종목</span>
              <span className="text-[12px] text-slate-500">· 로그인 없이 이 브라우저에 저장</span>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2.5">
              {watch.map(w => (
                <div key={w.code} onClick={()=>goStock(w.code)} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-200 cursor-pointer transition-colors">
                  <span className="text-amber-400 text-[13px]">★</span>
                  <span className="text-[14px] font-bold text-slate-900">{w.name}</span>
                  <span className="font-mono text-[11px] text-slate-500">{w.code}</span>
                  <button onClick={(e)=>{ e.stopPropagation(); toggleWatch(w); }} className="text-slate-600 hover:text-rose-600 text-[13px] ml-0.5" title="해제">✕</button>
                </div>
              ))}
              <span className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-dashed border-slate-300 text-[13px] text-slate-500">
                {watch.length === 0 ? '검색에서 ☆ 눌러 관심종목을 추가하세요' : '+ 검색에서 ☆ 추가'}
              </span>
            </div>
          </div>
        </div>

        {/* 우측 시그널 사이드 (오른쪽 끝) */}
        <aside ref={signalRef} className="lg:sticky lg:top-20 lg:self-start">
          {SignalPanel()}
        </aside>
      </div>

      <footer className="text-center py-6 border-t border-slate-200">
        <div className="text-xs text-slate-500">FINSIGHT · KPMG AI Lab · 2026-06-20 데모 · NO-MOCK: 추정하지 않는다, 출처(DART 공시)로 말한다</div>
        <div className="text-sm font-bold text-slate-600 tracking-[0.18em] mt-2">FILMN9&nbsp;Inc.</div>
      </footer>
    </main>
  );
}
