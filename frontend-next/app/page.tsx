'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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


export default function HomePage() {
  const router = useRouter();
  const [query, setQuery]       = useState('');
  const [results, setResults]   = useState<SearchResult[]>([]);
  const [loading, setLoading]   = useState(false);
  const [open, setOpen]         = useState(false);
  const [dark, setDark]         = useState(false);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  const wrapRef     = useRef<HTMLDivElement>(null);

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

        {/* PoC 종목 바로가기 */}
        <div className="flex gap-3 flex-wrap justify-center mb-6">
          {DEMO_STOCKS.map(s => (
            <button key={s.code} onClick={() => goTo(s.code)}
              className="group flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 hover:border-indigo-400/60 text-white transition-all hover:scale-105">
              <div className="text-left">
                <div className="text-sm font-semibold">{s.name}</div>
                <div className="text-xs text-slate-400 font-mono">{s.code} · {s.tag}</div>
              </div>
              <svg className="w-4 h-4 text-slate-400 group-hover:text-indigo-300 ml-1 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
              </svg>
            </button>
          ))}
        </div>

      </div>

      <footer className="text-center py-4 text-xs text-slate-600 border-t border-white/5">
        FILMN9 PoC &nbsp;·&nbsp; KPMG AI Lab &nbsp;·&nbsp; 2026-05-26 데모
      </footer>
    </main>
  );
}
