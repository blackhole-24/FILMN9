'use client';
import { useEffect, useRef, useState, useCallback } from 'react';

interface OhlcvRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface Props {
  data: OhlcvRow[];
}

type PeriodKey = '1M' | '3M' | '6M' | '1Y' | '3Y' | '전체';

interface InfoState {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  ma5: number | null;
  ma20: number | null;
  ma60: number | null;
  volume: number | null;
}

function calcMA(data: OhlcvRow[], n: number): { time: string; value: number }[] {
  const result: { time: string; value: number }[] = [];
  for (let i = n - 1; i < data.length; i++) {
    let sum = 0;
    for (let j = i - n + 1; j <= i; j++) sum += data[j].close;
    result.push({ time: data[i].date, value: sum / n });
  }
  return result;
}

function calcBB(data: OhlcvRow[], n = 20, k = 2) {
  const upper: { time: string; value: number }[] = [];
  const mid: { time: string; value: number }[] = [];
  const lower: { time: string; value: number }[] = [];
  for (let i = n - 1; i < data.length; i++) {
    const slice = data.slice(i - n + 1, i + 1);
    const avg = slice.reduce((s, x) => s + x.close, 0) / n;
    const std = Math.sqrt(slice.reduce((s, x) => s + (x.close - avg) ** 2, 0) / n);
    upper.push({ time: data[i].date, value: avg + k * std });
    mid.push({ time: data[i].date, value: avg });
    lower.push({ time: data[i].date, value: avg - k * std });
  }
  return { upper, mid, lower };
}

function buildMaCache(data: OhlcvRow[]) {
  const ma5: (number | null)[] = [];
  const ma20: (number | null)[] = [];
  const ma60: (number | null)[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i < 4) { ma5.push(null); } else {
      let s = 0; for (let j = i - 4; j <= i; j++) s += data[j].close;
      ma5.push(s / 5);
    }
    if (i < 19) { ma20.push(null); } else {
      let s = 0; for (let j = i - 19; j <= i; j++) s += data[j].close;
      ma20.push(s / 20);
    }
    if (i < 59) { ma60.push(null); } else {
      let s = 0; for (let j = i - 59; j <= i; j++) s += data[j].close;
      ma60.push(s / 60);
    }
  }
  return { ma5, ma20, ma60 };
}

function filterByPeriod(data: OhlcvRow[], period: PeriodKey): OhlcvRow[] {
  if (!data.length) return [];
  if (period === '전체') return data;
  const months: Record<PeriodKey, number> = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12, '3Y': 36, '전체': 0 };
  const m = months[period];
  const last = new Date(data[data.length - 1].date);
  last.setMonth(last.getMonth() - m);
  const cutStr = last.toISOString().slice(0, 10);
  return data.filter(d => d.date >= cutStr);
}

function fmt(v: number | null): string {
  if (v == null) return '—';
  return Math.round(v).toLocaleString('ko-KR');
}

function fmtVol(v: number | null): string {
  if (v == null) return '—';
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '억';
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '만';
  return v.toLocaleString('ko-KR');
}

function ts2key(t: any): string | null {
  if (t == null) return null;
  if (typeof t === 'object' && typeof t.year === 'number') {
    return `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`;
  }
  if (typeof t === 'string') return t;
  if (typeof t === 'number') {
    const d = new Date(t * 1000);
    if (isNaN(d.getTime())) return null;
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
  }
  return null;
}

function dateFmtDisplay(t: any): string {
  let year: number, month: number, day: number;
  if (t && typeof t === 'object' && 'year' in t) {
    year = t.year; month = t.month; day = t.day;
  } else if (typeof t === 'number') {
    const d = new Date(t * 1000);
    year = d.getUTCFullYear(); month = d.getUTCMonth() + 1; day = d.getUTCDate();
  } else if (typeof t === 'string') {
    const parts = t.split('-').map(Number);
    year = parts[0]; month = parts[1]; day = parts[2];
  } else {
    return '';
  }
  const yy = String(year).slice(2);
  const mm = String(month).padStart(2, '0');
  const dd = String(day).padStart(2, '0');
  return `'${yy}/${mm}/${dd}`;
}

const PERIODS: PeriodKey[] = ['1M', '3M', '6M', '1Y', '3Y', '전체'];
const C_UP = '#ef4444';
const C_DOWN = '#3b82f6';
const C_FLAT = '#9ca3af';

export default function FullChart({ data }: Props) {
  const candleRef = useRef<HTMLDivElement>(null);
  const volumeRef = useRef<HTMLDivElement>(null);
  const chartAreaRef = useRef<HTMLDivElement>(null);  // Y축 휠 감지용
  const candleChartRef = useRef<any>(null);
  const volumeChartRef = useRef<any>(null);
  const seriesMapRef = useRef<Record<string, any>>({});
  const displayedRef = useRef<OhlcvRow[]>([]);
  const maCacheRef = useRef<{ ma5: (number | null)[]; ma20: (number | null)[]; ma60: (number | null)[] }>({ ma5: [], ma20: [], ma60: [] });

  const [chartReady, setChartReady] = useState(false);  // ← race condition 방지
  const [period, setPeriod] = useState<PeriodKey>('1Y');
  const [showMa5, setShowMa5] = useState(true);
  const [showMa20, setShowMa20] = useState(true);
  const [showMa60, setShowMa60] = useState(true);
  const [showBB, setShowBB] = useState(false);
  const [info, setInfo] = useState<InfoState>({
    date: '', open: null, high: null, low: null, close: null,
    ma5: null, ma20: null, ma60: null, volume: null,
  });

  const showLatestInfo = useCallback(() => {
    const d = displayedRef.current;
    if (!d.length) return;
    const i = d.length - 1;
    const bar = d[i];
    const cache = maCacheRef.current;
    setInfo({
      date: dateFmtDisplay(bar.date),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      ma5: cache.ma5[i] ?? null,
      ma20: cache.ma20[i] ?? null,
      ma60: cache.ma60[i] ?? null,
      volume: bar.volume ?? null,
    });
  }, []);

  // Chart init — runs once
  useEffect(() => {
    if (!candleRef.current || !volumeRef.current) return;
    let cancelled = false;

    const init = async () => {
      const lc = await import('lightweight-charts');
      if (cancelled) return;

      const { createChart, CandlestickSeries, LineSeries, HistogramSeries } = lc as any;

      const dateFmt = (t: any) => dateFmtDisplay(t);

      const _tsOpts = {
        borderColor: '#d1d5db',
        timeVisible: false,
        tickMarkFormatter: dateFmt,
        fixLeftEdge: true,
        fixRightEdge: true,
        lockVisibleTimeRangeOnResize: true,
        rightBarStaysOnScroll: true,
      };
      const commonOpts = {
        layout: { background: { color: '#ffffff' }, textColor: '#374151' },
        grid: { vertLines: { color: '#f3f4f6' }, horzLines: { color: '#f3f4f6' } },
        crosshair: {
          mode: 1,
          vertLine: { color: '#6b7280', labelBackgroundColor: '#374151' },
          horzLine: { color: '#6b7280', labelBackgroundColor: '#374151' },
        },
        leftPriceScale: { visible: false },
        rightPriceScale: { visible: true, borderColor: '#d1d5db' },
        timeScale: _tsOpts,
        localization: {
          timeFormatter: dateFmt,
          priceFormatter: (p: number) => Math.round(p).toLocaleString('ko-KR'),
        },
        handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
        handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
      };

      const candleEl = candleRef.current!;
      const volEl = volumeRef.current!;

      const candleChart = createChart(candleEl, { ...commonOpts, height: 420, timeScale: { ..._tsOpts, barSpacing: 8 } });
      const volumeChart = createChart(volEl, {
        ...commonOpts,
        height: 90,
        rightPriceScale: { visible: true, borderColor: '#d1d5db', scaleMargins: { top: 0.1, bottom: 0 } },
        timeScale: { ..._tsOpts, visible: true, barSpacing: 8 },
        handleScroll: false,
        handleScale: false,
      });

      candleChartRef.current = candleChart;
      volumeChartRef.current = volumeChart;

      const candleSeries = candleChart.addSeries(CandlestickSeries, {
        upColor: C_UP, wickUpColor: C_UP,
        downColor: C_DOWN, wickDownColor: C_DOWN,
        borderVisible: false,
        priceScaleId: 'right',
        priceFormat: { type: 'price', precision: 0, minMove: 1 },
      });
      const volumeSeries = volumeChart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'right',
      });

      const _lineOpts = { lineWidth: 1, priceLineVisible: false, lastValueVisible: false, priceScaleId: 'right' };
      const ma5Series = candleChart.addSeries(LineSeries, { ..._lineOpts, color: '#d97706' });
      const ma20Series = candleChart.addSeries(LineSeries, { ..._lineOpts, color: '#7c3aed' });
      const ma60Series = candleChart.addSeries(LineSeries, { ..._lineOpts, color: '#059669' });
      const bbUpperSeries = candleChart.addSeries(LineSeries, { ..._lineOpts, color: '#db2777', lineWidth: 2, visible: false });
      const bbMidSeries = candleChart.addSeries(LineSeries, { ..._lineOpts, color: '#9d174d', lineWidth: 1, lineStyle: 2, visible: false });
      const bbLowerSeries = candleChart.addSeries(LineSeries, { ..._lineOpts, color: '#db2777', lineWidth: 2, visible: false });

      seriesMapRef.current = {
        candle: candleSeries,
        volume: volumeSeries,
        ma5: ma5Series, ma20: ma20Series, ma60: ma60Series,
        bbUpper: bbUpperSeries, bbMid: bbMidSeries, bbLower: bbLowerSeries,
      };

      // Sync candle → volume
      candleChart.timeScale().subscribeVisibleLogicalRangeChange((range: any) => {
        if (range) volumeChart.timeScale().setVisibleLogicalRange(range);
      });

      // Crosshair
      candleChart.subscribeCrosshairMove((param: any) => {
        const d = displayedRef.current;
        if (!param || !param.time || !d.length) {
          showLatestInfo();
          return;
        }
        const dateKey = ts2key(param.time);
        if (!dateKey) { showLatestInfo(); return; }
        const idx = d.findIndex(x => x.date === dateKey);
        if (idx < 0) { showLatestInfo(); return; }
        const bar = d[idx];
        const cache = maCacheRef.current;
        setInfo({
          date: dateFmtDisplay(param.time),
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
          ma5: cache.ma5[idx] ?? null,
          ma20: cache.ma20[idx] ?? null,
          ma60: cache.ma60[idx] ?? null,
          volume: bar.volume ?? null,
        });
      });

      // ResizeObserver
      const ro = new ResizeObserver(() => {
        if (candleChartRef.current && candleEl) {
          candleChartRef.current.applyOptions({ width: candleEl.clientWidth });
        }
        if (volumeChartRef.current && volEl) {
          volumeChartRef.current.applyOptions({ width: volEl.clientWidth });
        }
      });
      ro.observe(candleEl);

      (candleChartRef as any)._ro = ro;

      // ← 차트 초기화 완료 신호 (race condition 방지)
      setChartReady(true);
    };

    init();

    return () => {
      cancelled = true;
      const ro = (candleChartRef as any)._ro;
      if (ro) ro.disconnect();
      if (candleChartRef.current) { candleChartRef.current.remove(); candleChartRef.current = null; }
      if (volumeChartRef.current) { volumeChartRef.current.remove(); volumeChartRef.current = null; }
      setChartReady(false);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Y축 위에서 휠 → 페이지 스크롤, 차트 내부에서 휠 → 줌인/줌아웃 ──────────
  useEffect(() => {
    const area = chartAreaRef.current;
    if (!area || !chartReady) return;
    const YAXIS_WIDTH = 72;  // lightweight-charts Y축 폭 근사치 (px)
    const handler = (e: WheelEvent) => {
      const rect = area.getBoundingClientRect();
      const overYAxis = e.clientX >= rect.right - YAXIS_WIDTH;
      if (overYAxis) {
        // Y축 영역: 페이지 위아래 스크롤
        e.preventDefault();
        e.stopImmediatePropagation();
        window.scrollBy({ top: e.deltaY });
      }
      // 차트 영역: 기본 줌인/줌아웃 동작 허용 (chart 내부 listener가 처리)
    };
    area.addEventListener('wheel', handler, { passive: false, capture: true });
    return () => area.removeEventListener('wheel', handler, { capture: true } as any);
  }, [chartReady]);

  // Apply data when data or period changes — chartReady 가 true 가 된 후에도 재실행
  useEffect(() => {
    const sm = seriesMapRef.current;
    if (!chartReady || !sm.candle || !data.length) return;

    const sorted = [...data].sort((a, b) => a.date.localeCompare(b.date));
    const filtered = filterByPeriod(sorted, period);
    if (!filtered.length) return;

    displayedRef.current = filtered;
    maCacheRef.current = buildMaCache(filtered);

    const candles = filtered.map(d => ({ time: d.date, open: d.open, high: d.high, low: d.low, close: d.close }));
    const volumes = filtered.map((d, i) => {
      const prev = i > 0 ? filtered[i - 1].close : d.open;
      const color = d.close > prev ? C_UP : (d.close < prev ? C_DOWN : C_FLAT);
      return { time: d.date, value: d.volume ?? 0, color };
    });

    sm.candle.setData(candles);
    sm.volume.setData(volumes);
    sm.ma5.setData(calcMA(filtered, 5));
    sm.ma20.setData(calcMA(filtered, 20));
    sm.ma60.setData(calcMA(filtered, 60));

    const bb = calcBB(filtered, 20, 2);
    sm.bbUpper.setData(bb.upper);
    sm.bbMid.setData(bb.mid);
    sm.bbLower.setData(bb.lower);

    candleChartRef.current?.timeScale().fitContent();
    volumeChartRef.current?.timeScale().fitContent();

    const range = candleChartRef.current?.timeScale().getVisibleLogicalRange();
    if (range) volumeChartRef.current?.timeScale().setVisibleLogicalRange(range);

    showLatestInfo();
  }, [data, period, showLatestInfo, chartReady]);  // chartReady 의존성 추가

  // Toggle MA5
  useEffect(() => {
    seriesMapRef.current.ma5?.applyOptions({ visible: showMa5 });
  }, [showMa5]);

  // Toggle MA20
  useEffect(() => {
    seriesMapRef.current.ma20?.applyOptions({ visible: showMa20 });
  }, [showMa20]);

  // Toggle MA60
  useEffect(() => {
    seriesMapRef.current.ma60?.applyOptions({ visible: showMa60 });
  }, [showMa60]);

  // Toggle BB
  useEffect(() => {
    seriesMapRef.current.bbUpper?.applyOptions({ visible: showBB });
    seriesMapRef.current.bbMid?.applyOptions({ visible: showBB });
    seriesMapRef.current.bbLower?.applyOptions({ visible: showBB });
  }, [showBB]);

  if (!data.length) {
    return (
      <div className="flex items-center justify-center bg-slate-50 rounded-lg text-slate-300 text-sm" style={{ height: 510 }}>
        주가 데이터 없음
      </div>
    );
  }

  return (
    <div style={{ width: '100%' }}>
      {/* 기간 버튼 + 지표 토글 */}
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2 px-1">
        <div className="flex gap-1">
          {PERIODS.map(p => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`px-3 py-1 text-xs rounded-full font-medium transition-colors ${period === p
                ? 'bg-indigo-600 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
              {p}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          {/* ── [i] 실시간 차트 한계 안내 ── */}
          <span style={{ position: 'relative', display: 'inline-block' }} className="group">
            <span style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 16, height: 16, borderRadius: '50%',
              border: '1.5px solid #94a3b8', color: '#94a3b8',
              fontSize: 10, fontWeight: 700, cursor: 'help', userSelect: 'none',
            }}>i</span>
            {/* 툴팁 */}
            <span style={{
              display: 'none', position: 'absolute', right: 0, top: '100%', marginTop: 6,
              width: 300, background: '#1e293b', color: '#e2e8f0',
              borderRadius: 8, padding: '10px 12px', fontSize: 11, lineHeight: 1.6,
              zIndex: 100, boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
            }} className="group-hover:!block">
              <div style={{ fontWeight: 700, marginBottom: 6, color: '#93c5fd' }}>📡 실시간 차트 반영의 한계</div>
              <div>• <b>KRX WebSocket</b>: 한국거래소 Level 2 실시간 데이터피드 계약 필요 (유료, 연간 수천만원~)</div>
              <div style={{ marginTop: 4 }}>• <b>증권사 HTS API</b>: KIS Open API 등 개인/법인 계좌 인증 + API 키 발급 필요</div>
              <div style={{ marginTop: 4 }}>• <b>yfinance / Yahoo Finance</b>: KRX 종목 15~20분 지연, 과도한 호출 시 IP 차단</div>
              <div style={{ marginTop: 4 }}>• <b>현재 구현</b>: yfinance 60초 폴링 → 헤더 현재가 표시; 차트는 전일까지 일봉</div>
              <div style={{ marginTop: 4 }}>• <b>개선 방안</b>: KIS Open API 연동 시 장중 1분봉 실시간 차트 구현 가능</div>
            </span>
          </span>
          <label className="flex items-center gap-1 cursor-pointer select-none">
            <input type="checkbox" checked={showMa5} onChange={e => setShowMa5(e.target.checked)} className="cursor-pointer" />
            <span style={{ width: 10, height: 2, background: '#d97706', display: 'inline-block' }} />
            MA5
          </label>
          <label className="flex items-center gap-1 cursor-pointer select-none">
            <input type="checkbox" checked={showMa20} onChange={e => setShowMa20(e.target.checked)} className="cursor-pointer" />
            <span style={{ width: 10, height: 2, background: '#7c3aed', display: 'inline-block' }} />
            MA20
          </label>
          <label className="flex items-center gap-1 cursor-pointer select-none">
            <input type="checkbox" checked={showMa60} onChange={e => setShowMa60(e.target.checked)} className="cursor-pointer" />
            <span style={{ width: 10, height: 2, background: '#059669', display: 'inline-block' }} />
            MA60
          </label>
          <label className="flex items-center gap-1 cursor-pointer select-none">
            <input type="checkbox" checked={showBB} onChange={e => setShowBB(e.target.checked)} className="cursor-pointer" />
            <span style={{ width: 10, height: 4, background: '#db2777', display: 'inline-block' }} />
            볼린저밴드
          </label>
          {/* ⓘ 볼린저밴드 해석 툴팁 */}
          <span className="group" style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
            <span style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 16, height: 16, borderRadius: '50%',
              border: '1.5px solid #94a3b8', color: '#94a3b8',
              fontSize: 10, fontWeight: 700, cursor: 'help', userSelect: 'none',
            }}>i</span>
            <span style={{
              display: 'none', position: 'absolute', right: 0, top: '100%', marginTop: 6,
              width: 320, background: '#1e293b', color: '#e2e8f0',
              borderRadius: 8, padding: '10px 12px', fontSize: 11, lineHeight: 1.6,
              zIndex: 100, boxShadow: '0 8px 24px rgba(0,0,0,0.3)', textAlign: 'left', whiteSpace: 'normal',
            }} className="group-hover:!block">
              <div style={{ fontWeight: 700, marginBottom: 6, color: '#93c5fd' }}>📊 볼린저밴드</div>
              <div>20일 이동평균(중심선) 위·아래에 표준편차 2배(±2σ) 폭의 밴드. 주가가 약 95% 확률로 밴드 안에서 움직입니다.</div>
              <div style={{ marginTop: 5 }}><b>구성</b> · 중심선=MA20 / 상단=+2σ / 하단=−2σ</div>
              <div style={{ marginTop: 5, fontWeight: 700, color: '#cbd5e1' }}>해석</div>
              <div>🔴 상단밴드 접근·돌파 → 단기 과열(과매수)</div>
              <div>🔵 하단밴드 접근·돌파 → 단기 침체(과매도)</div>
              <div>🔶 밴드 폭 좁아짐(스퀴즈) → 변동성 축소·큰 변동 예고</div>
              <div>🔷 밴드 폭 넓어짐 → 변동성 확대 국면</div>
              <div>📈 상단밴드 타고 상승 → 강한 상승추세</div>
              <div style={{ marginTop: 5, fontSize: 10, color: '#94a3b8' }}>※ 단독 매매신호 아님 · 추세·거래량과 함께 판단</div>
            </span>
          </span>
        </div>
      </div>

      {/* 차트 영역 */}
      <div ref={chartAreaRef} style={{ position: 'relative' }}>
        {/* 정보 패널 overlay */}
        <div style={{
          position: 'absolute', top: 8, left: 8, zIndex: 15,
          background: 'rgba(255,255,255,0.93)',
          border: '1px solid #e5e7eb', borderRadius: 6,
          padding: '4px 10px', fontSize: 12,
          pointerEvents: 'none', color: '#1f2937', lineHeight: 1.6,
        }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ color: '#6b7280', fontSize: 11 }}>{info.date}</span>
            <span style={{ color: '#6b7280', fontSize: 11 }}>시</span>
            <span style={{ fontWeight: 600 }}>{fmt(info.open)}</span>
            <span style={{ color: '#6b7280', fontSize: 11 }}>고</span>
            <span style={{ fontWeight: 600 }}>{fmt(info.high)}</span>
            <span style={{ color: '#6b7280', fontSize: 11 }}>저</span>
            <span style={{ fontWeight: 600 }}>{fmt(info.low)}</span>
            <span style={{ color: '#6b7280', fontSize: 11 }}>종</span>
            <span style={{ fontWeight: 600 }}>{fmt(info.close)}</span>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 2 }}>
            <span style={{ color: '#6b7280', fontSize: 11 }}>이평선</span>
            <span style={{ color: '#d97706', fontWeight: 700, fontSize: 11 }}>5</span>
            <span style={{ fontWeight: 600 }}>{fmt(info.ma5)}</span>
            <span style={{ color: '#7c3aed', fontWeight: 700, fontSize: 11 }}>20</span>
            <span style={{ fontWeight: 600 }}>{fmt(info.ma20)}</span>
            <span style={{ color: '#059669', fontWeight: 700, fontSize: 11 }}>60</span>
            <span style={{ fontWeight: 600 }}>{fmt(info.ma60)}</span>
            <span style={{ color: '#6b7280', fontSize: 11, marginLeft: 8 }}>거래량</span>
            <span style={{ fontWeight: 600 }}>{fmtVol(info.volume)}</span>
          </div>
        </div>

        {/* 캔들차트 */}
        <div ref={candleRef} style={{ width: '100%', height: 420 }} />
        {/* 거래량 차트 */}
        <div ref={volumeRef} style={{ width: '100%', height: 90, marginTop: 2 }} />
      </div>
      {/* 조작 안내 */}
      <div style={{ fontSize: 10, color: '#9ca3af', textAlign: 'right', marginTop: 4, paddingRight: 4 }}>
        차트 내 휠: 줌인·줌아웃 | Y축 위 휠: 페이지 스크롤 | 시간축 드래그: 이동
      </div>
    </div>
  );
}
