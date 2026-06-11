'use client';

import { useState, useEffect, useMemo } from 'react';
import { useRouter, useParams } from 'next/navigation';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Stock { stock_code: string; corp_name: string; market: string; }

export default function SectorStocksPage() {
  const router = useRouter();
  const params = useParams();
  const sectorName = decodeURIComponent(
    Array.isArray(params.sector) ? params.sector[0] : (params.sector as string) || ''
  );

  const [stocks, setStocks]   = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr]         = useState('');
  const [term, setTerm]       = useState('');

  useEffect(() => {
    if (!sectorName) return;
    (async () => {
      setLoading(true); setErr('');
      try {
        const res  = await fetch(`${API}/api/sectors/${encodeURIComponent(sectorName)}/stocks`);
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        setStocks(data.stocks || []);
      } catch { setErr('종목 목록을 불러오지 못했습니다.'); setStocks([]); }
      finally { setLoading(false); }
    })();
  }, [sectorName]);

  const shown = useMemo(() => {
    const t = term.trim();
    if (!t) return stocks;
    return stocks.filter(s => s.corp_name.includes(t) || s.stock_code.startsWith(t));
  }, [stocks, term]);

  const goStock = (code: string) => router.push(`/stock/${code}`);

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900">
      {/* 좌측 빈 공간 전체 클릭 = 뒤로 가기 (큰 화살표) — 종목 리스트는 앞으로가기 없음 */}
      <button onClick={() => router.back()} aria-label="뒤로 가기"
        className="hidden lg:flex fixed left-0 top-16 bottom-0 w-[calc((100vw-48rem)/2)] items-center justify-center group z-20 hover:bg-white/[0.04] transition-colors cursor-pointer">
        <span className="flex flex-col items-center gap-1 text-slate-600 group-hover:text-indigo-300 transition-colors">
          <span className="text-8xl leading-none font-light">‹</span>
          <span className="text-base font-semibold opacity-60 group-hover:opacity-100 transition-opacity">뒤로</span>
        </span>
      </button>

      {/* 상단 바 — FILMN9 중앙(홈 버튼) */}
      <header className="relative flex items-center justify-center px-6 py-4 z-30">
        <button onClick={() => router.push('/')} aria-label="홈으로"
          className="flex items-center gap-2 text-white hover:opacity-80 transition">
          <span className="text-2xl font-extrabold tracking-tight">FINSIGHT</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/30 text-indigo-300 font-medium border border-indigo-500/40">PoC</span>
        </button>
        <button onClick={() => router.push('/sectors')}
          className="absolute right-6 text-xs text-slate-400 hover:text-white transition hidden sm:block">산업 분류 ↑</button>
      </header>

      <div className="max-w-3xl mx-auto px-4 pb-16">
        <div className="mt-6 mb-6">
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">{sectorName}</h1>
          <p className="text-slate-400 text-sm mt-1">{loading ? '…' : `${stocks.length} 종목`} · 종목을 누르면 상세 분석으로 이동</p>
        </div>

        {/* 종목 내 검색 */}
        {stocks.length > 0 && (
          <div className="mb-5">
            <div className="flex items-center bg-white rounded-xl px-4 py-2.5 shadow-lg">
              <svg className="w-4 h-4 text-slate-400 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
              </svg>
              <input value={term} onChange={e => setTerm(e.target.value)}
                placeholder="이 업종 내 종목 검색"
                className="flex-1 outline-none text-slate-800 placeholder-slate-400 bg-transparent text-sm" autoComplete="off" />
            </div>
          </div>
        )}

        {loading ? (
          <div className="text-center text-slate-400 py-20">불러오는 중…</div>
        ) : err ? (
          <div className="text-center text-rose-300 py-20">{err}</div>
        ) : shown.length === 0 ? (
          <div className="text-center text-slate-400 py-20">종목이 없습니다.</div>
        ) : (
          <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden divide-y divide-white/5">
            {shown.map(s => (
              <button key={s.stock_code} onClick={() => goStock(s.stock_code)}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/10 transition-colors text-left">
                <span className="font-mono text-xs text-slate-400 w-14 flex-shrink-0">{s.stock_code}</span>
                <span className="flex-1 text-sm font-semibold text-white truncate">{s.corp_name}</span>
                <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white flex-shrink-0"
                  style={{ background: s.market === 'KOSPI' ? '#2563EB' : '#7C3AED' }}>{s.market}</span>
                <svg className="w-4 h-4 text-slate-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
                </svg>
              </button>
            ))}
          </div>
        )}
      </div>

      <footer className="text-center py-5 border-t border-white/5">
        <div className="text-xs text-slate-600">FINSIGHT · 산업 분류(WICS)</div>
        <div className="text-sm font-bold text-slate-100 tracking-[0.18em] mt-2">FILMN9&nbsp;Inc.</div>
      </footer>
    </main>
  );
}
