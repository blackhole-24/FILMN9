'use client';

import { useState, useEffect, useRef, useMemo } from 'react';
import { useRouter } from 'next/navigation';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Sector { sector_name: string; count: number; }

export default function SectorsPage() {
  const router = useRouter();
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [total, setTotal]     = useState(0);
  const [loading, setLoading] = useState(true);
  const [term, setTerm]       = useState('');
  const [synMatches, setSynMatches] = useState<string[]>([]);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);

  // 전체 섹터 목록 1회 로드
  useEffect(() => {
    (async () => {
      try {
        const res  = await fetch(`${API}/api/sectors`);
        const data = await res.json();
        setSectors(data.sectors || []);
        setTotal(data.total_stocks || 0);
      } catch { setSectors([]); }
      finally { setLoading(false); }
    })();
  }, []);

  // 유사어 검색 (방산 → 우주항공과국방 등) — 백엔드 wics_keywords 사전
  const onTerm = (v: string) => {
    setTerm(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!v.trim()) { setSynMatches([]); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const res  = await fetch(`${API}/api/sectors/search?q=${encodeURIComponent(v)}`);
        const data = await res.json();
        setSynMatches(data.matched_sectors || []);
      } catch { setSynMatches([]); }
    }, 200);
  };

  // 표시 목록: 이름 부분일치 ∪ 유사어 매칭
  const shown = useMemo(() => {
    const t = term.trim();
    if (!t) return sectors;
    const set = new Set(synMatches);
    return sectors.filter(s => s.sector_name.includes(t) || set.has(s.sector_name));
  }, [sectors, term, synMatches]);

  const goSector = (name: string) => router.push(`/sectors/${encodeURIComponent(name)}`);

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900">
      {/* 좌우 빈 공간 전체 클릭 = 뒤로 / 앞으로 가기 (큰 화살표, 콘텐츠 옆 빈 공간 전부) */}
      <button onClick={() => router.back()} aria-label="뒤로 가기"
        className="hidden lg:flex fixed left-0 top-16 bottom-0 w-[calc((100vw-64rem)/2)] items-center justify-center group z-20 hover:bg-white/[0.04] transition-colors cursor-pointer">
        <span className="flex flex-col items-center gap-1 text-slate-600 group-hover:text-indigo-300 transition-colors">
          <span className="text-8xl leading-none font-light">‹</span>
          <span className="text-base font-semibold opacity-60 group-hover:opacity-100 transition-opacity">뒤로</span>
        </span>
      </button>
      <button onClick={() => router.forward()} aria-label="앞으로 가기"
        className="hidden lg:flex fixed right-0 top-16 bottom-0 w-[calc((100vw-64rem)/2)] items-center justify-center group z-20 hover:bg-white/[0.04] transition-colors cursor-pointer">
        <span className="flex flex-col items-center gap-1 text-slate-600 group-hover:text-indigo-300 transition-colors">
          <span className="text-8xl leading-none font-light">›</span>
          <span className="text-base font-semibold opacity-60 group-hover:opacity-100 transition-opacity">앞으로</span>
        </span>
      </button>

      {/* 상단 바 — FILMN9 중앙(홈 버튼) */}
      <header className="relative flex items-center justify-center px-6 py-4 z-30">
        <button onClick={() => router.push('/')} aria-label="홈으로"
          className="flex items-center gap-2 text-white hover:opacity-80 transition">
          <span className="text-2xl font-extrabold tracking-tight">FINSIGHT</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/30 text-indigo-300 font-medium border border-indigo-500/40">PoC</span>
        </button>
        <span className="absolute right-6 text-xs text-slate-400 hidden sm:block">산업 분류 (WICS)</span>
      </header>

      <div className="max-w-5xl mx-auto px-4 pb-16">
        {/* 브레드크럼 (홈 › 산업지도) */}
        <nav className="flex items-center gap-1.5 text-[13px] text-slate-500 mt-2">
          <button onClick={() => router.push('/')} className="hover:text-slate-200 transition-colors">홈</button>
          <span className="opacity-50">›</span>
          <span className="text-slate-200 font-semibold">산업지도</span>
        </nav>
        {/* 타이틀 */}
        <div className="text-center mt-4 mb-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 text-xs font-medium mb-4">
            🏭 산업(업종)별 탐색
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight mb-2">산업 분류로 종목 찾기</h1>
          <p className="text-slate-400 text-sm">총 {total.toLocaleString()} 종목 · {sectors.length} 업종 (WICS) · 업종을 누르면 해당 종목 목록</p>
        </div>

        {/* 검색 */}
        <div className="max-w-lg mx-auto mb-8">
          <div className="flex items-center bg-white rounded-2xl px-4 py-3 shadow-2xl shadow-indigo-900/40">
            <svg className="w-5 h-5 text-slate-400 mr-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
            </svg>
            <input value={term} onChange={e => onTerm(e.target.value)}
              placeholder="업종 검색 (예: 반도체, 방산, 이차전지, 제약)"
              className="flex-1 outline-none text-slate-800 placeholder-slate-400 bg-transparent text-sm" autoComplete="off" />
          </div>
          {term.trim() && (
            <div className="text-center text-xs text-slate-400 mt-2">
              {shown.length}개 업종 일치 {synMatches.length > 0 && `· 유사어 매칭 포함`}
            </div>
          )}
        </div>

        {/* 섹터 카드 그리드 */}
        {loading ? (
          <div className="text-center text-slate-400 py-20">불러오는 중…</div>
        ) : shown.length === 0 ? (
          <div className="text-center text-slate-400 py-20">일치하는 업종이 없습니다.</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {shown.map(s => (
              <button key={s.sector_name} onClick={() => goSector(s.sector_name)}
                className="group flex items-center justify-between gap-2 px-4 py-3.5 rounded-xl bg-white/10 hover:bg-white/20 border border-white/15 hover:border-indigo-400/60 text-white transition-all text-left">
                <span className="text-sm font-semibold truncate">{s.sector_name}</span>
                <span className="flex items-center gap-2 flex-shrink-0">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/30 text-indigo-200 font-medium">{s.count}</span>
                  <svg className="w-4 h-4 text-slate-400 group-hover:text-indigo-300 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
                  </svg>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <footer className="text-center py-5 border-t border-white/5">
        <div className="text-xs text-slate-600">FINSIGHT · 산업 분류(WICS) · 데이터: ticker_universe (SPAC·우선주 제외)</div>
        <div className="text-sm font-bold text-slate-100 tracking-[0.18em] mt-2">FILMN9&nbsp;Inc.</div>
      </footer>
    </main>
  );
}
