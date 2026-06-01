'use client';

import { useEffect, useRef } from 'react';

interface OhlcvRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface Props {
  data: OhlcvRow[];
  height?: number;
}

export default function CandlestickChart({ data, height = 240 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current || !data.length) return;

    let chart: any;

    const init = async () => {
      try {
        const { createChart, CandlestickSeries } = await import('lightweight-charts');
        const el = containerRef.current!;

        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }

        chart = createChart(el, {
          width: el.clientWidth,
          height,
          layout: {
            background: { color: 'transparent' },
            textColor: '#64748b',
            fontSize: 11,
          },
          grid: {
            vertLines: { color: '#f1f5f9' },
            horzLines: { color: '#f1f5f9' },
          },
          crosshair: { mode: 1 },
          rightPriceScale: { borderVisible: false },
          timeScale: { borderVisible: false, timeVisible: false },
          handleScroll: { mouseWheel: false, pressedMouseMove: true },
          handleScale: { mouseWheel: false, pinch: false },
        });

        const series = chart.addSeries(CandlestickSeries, {
          upColor: '#ef4444',
          downColor: '#3b82f6',
          borderVisible: false,
          wickUpColor: '#ef4444',
          wickDownColor: '#3b82f6',
        });

        const sorted = [...data].sort((a, b) => a.date.localeCompare(b.date));
        series.setData(
          sorted.map(d => ({
            time: d.date as any,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
          }))
        );
        chart.timeScale().fitContent();
        chartRef.current = chart;
      } catch (e) {
        console.error('CandlestickChart init error', e);
      }
    };

    init();

    const ro = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    if (containerRef.current) ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [data, height]);

  if (!data.length) {
    return (
      <div className="flex items-center justify-center bg-slate-50 rounded-lg text-slate-300 text-sm"
        style={{ height }}>
        주가 데이터 없음
      </div>
    );
  }

  return <div ref={containerRef} style={{ height }} className="w-full" />;
}
