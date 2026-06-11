'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface VRow {
  stock_code: string; corp_name: string; market: string; industry: string;
  dcf_grade: string; dcf_confidence: string; peer_confidence_grade: string;
  fair_price: number | null; current_price: number | null; upside_pct: number | null;
  wacc: number | null; wacc_pct: number | null; as_of_date: string; model_version: string;
}

type SortKey = 'upside' | 'grade' | 'wacc' | 'name';

// DCF 신뢰도별 색상 (엔진 산출 dcf_confidence: 높음→평가불가) — NO-MOCK
const CONF_STYLE: Record<string, string> = {
  high:     'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  medium:   'bg-sky-500/20 text-sky-300 border-sky-500/40',
  low:      'bg-amber-500/20 text-amber-300 border-amber-500/40',
  very_low: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  invalid:  'bg-slate-500/20 text-slate-300 border-slate-500/40',
};
const CONF_LABEL: Record<string, string> = {
  high: '높음', medium: '보통', low: '낮음', very_low: '매우낮음', invalid: '평가불가',
};
const won = (v: number | null) => v == null ? '—' : '₩' + Math.round(v).toLocaleString();
const pct = (v: number | null) => v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
// 상승여력 ±500% 초과 = 적정가 이상치(엔진 산출 오류 의심) → "검증중" 표기 (NO-MOCK)
const isAnomaly = (u: number | null) => u != null && Math.abs(u) > 500;

export default function ValuationSummaryPage() {
  const router = useRouter();
  const [rows, setRows]   = useState<VRow[]>([]);
  const [meta, setMeta]   = useState<any>({});
  const [sort, setSort]   = useState<SortKey>('grade');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/api/valuation-summary?sort=${sort}`)
      .then(r => r.json())
      .then(d => { setRows(d.stocks || []); setMeta(d); })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [sort]);

  const goStock = (code: string) => router.push(`/stock/${code}`);

  const SORTS: { key: SortKey; label: string }[] = [
    { key: 'upside', label: '상승여력순' },
    { key: 'grade',  label: 'DCF신뢰도순' },
    { key: 'wacc',   label: 'WACC 낮은순' },
    { key: 'name',   label: '이름순' },
  ];

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900">
      {/* 상단 바 */}
      <header className="flex items-center justify-between px-6 py-4">
        <button onClick={() => router.push('/')} className="flex items-center gap-2 text-white hover:opacity-80 transition">
          <span className="text-2xl font-extrabold tracking-tight">FINSIGHT</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/30 text-indigo-300 font-medium border border-indigo-500/40">PoC</span>
        </button>
        <span className="text-xs text-slate-400 hidden sm:block">밸류에이션 요약</span>
      </header>

      <div className="max-w-6xl mx-auto px-4 pb-16">
        {/* 타이틀 */}
        <div className="text-center mt-6 mb-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 text-xs font-medium mb-4">
            💰 상장사 밸류에이션
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight mb-2">밸류에이션 요약 ({meta.count ?? 0}종)</h1>
          <p className="text-slate-400 text-sm">
            DCF 엔진 {meta.model_version || 'v8'} · 기준일 {meta.as_of || '—'} · 적정가 산출 {meta.valid_count ?? 0}/{meta.count ?? 0}종
            <span className="text-slate-500"> (사업보고서 보유 전 종목)</span>
          </p>
        </div>

        {/* 정렬 토글 */}
        <div className="flex flex-wrap justify-center gap-2 mb-5">
          {SORTS.map(s => (
            <button key={s.key} onClick={() => setSort(s.key)}
              className={`px-3.5 py-1.5 rounded-full text-xs font-medium border transition-all ${
                sort === s.key
                  ? 'bg-indigo-500 text-white border-indigo-400'
                  : 'bg-white/5 text-slate-300 border-white/15 hover:bg-white/10'}`}>
              {s.label}
            </button>
          ))}
        </div>

        {/* 표 */}
        {loading ? (
          <div className="text-center text-slate-400 py-20">불러오는 중…</div>
        ) : rows.length === 0 ? (
          <div className="text-center text-slate-400 py-20">
            데이터가 없습니다. <code className="text-indigo-300">python load_valuation_summary.py</code> 실행이 필요합니다.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-white/10 bg-white/[0.03]">
            <table className="w-full text-sm min-w-[760px]">
              <thead>
                <tr className="text-slate-400 text-xs border-b border-white/10">
                  <th className="px-3 py-3 text-left font-medium">#</th>
                  <th className="px-3 py-3 text-left font-medium">종목</th>
                  <th className="px-3 py-3 text-left font-medium">산업</th>
                  <th className="px-3 py-3 text-center font-medium">DCF 신뢰도</th>
                  <th className="px-3 py-3 text-right font-medium">적정가</th>
                  <th className="px-3 py-3 text-right font-medium">현재가</th>
                  <th className="px-3 py-3 text-right font-medium">상승여력</th>
                  <th className="px-3 py-3 text-right font-medium">WACC</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.stock_code} onClick={() => goStock(r.stock_code)}
                    className="border-b border-white/5 hover:bg-indigo-500/10 cursor-pointer transition-colors">
                    <td className="px-3 py-3 text-slate-500 font-mono text-xs">{i + 1}</td>
                    <td className="px-3 py-3">
                      <div className="text-white font-semibold whitespace-nowrap">{r.corp_name}</div>
                      <div className="text-[11px] text-slate-500 font-mono">{r.stock_code} · {r.market}</div>
                    </td>
                    <td className="px-3 py-3 text-slate-400 text-xs max-w-[180px] truncate">{r.industry || '—'}</td>
                    <td className="px-3 py-3 text-center">
                      <span className={`inline-block px-2 py-0.5 rounded-md text-xs font-bold border ${CONF_STYLE[r.dcf_confidence] || 'bg-slate-500/20 text-slate-300 border-slate-500/40'}`}>
                        {CONF_LABEL[r.dcf_confidence] || '—'}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right text-slate-200 font-medium whitespace-nowrap">
                      {isAnomaly(r.upside_pct) ? <span className="text-slate-500 text-[11px]">검증중</span> : won(r.fair_price)}
                    </td>
                    <td className="px-3 py-3 text-right text-slate-400 whitespace-nowrap">{won(r.current_price)}</td>
                    <td className={`px-3 py-3 text-right font-semibold whitespace-nowrap ${
                      isAnomaly(r.upside_pct) ? 'text-slate-500' : r.upside_pct == null ? 'text-slate-500' : r.upside_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {isAnomaly(r.upside_pct) ? <span className="text-[11px]">검증중</span> : pct(r.upside_pct)}
                    </td>
                    <td className="px-3 py-3 text-right text-slate-400 whitespace-nowrap">{r.wacc_pct != null ? r.wacc_pct + '%' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* 안내 (NO-MOCK 정직 표기) */}
        <div className="mt-5 text-[11px] text-slate-500 leading-relaxed space-y-1">
          <p>· <b className="text-slate-400">DCF 신뢰도</b>(엔진 산출): 높음·보통·낮음·매우낮음·평가불가. "평가불가"는 DCF 무효 → 적정가 "—" (멀티플 등 보조지표 참고).</p>
          <p>· <b className="text-slate-400">출처</b>: {meta.source || 'valuation_summary · DCF 엔진 v8 (사업보고서 보유 전 종목)'}. 종목 클릭 시 상세 분석으로 이동.</p>
          <p>· 적정가·상승여력은 엔진 산출 기준값입니다. (현재가는 산출시점 기준 — 실시간 시세와 차이 있을 수 있음)</p>
        </div>
      </div>

      <footer className="text-center py-5 border-t border-white/5">
        <div className="text-xs text-slate-600">FINSIGHT · 밸류에이션 요약 · DCF 엔진 v8 산출 · SQLite valuation_summary</div>
        <div className="text-sm font-bold text-slate-100 tracking-[0.18em] mt-2">FILMN9&nbsp;Inc.</div>
      </footer>
    </main>
  );
}
