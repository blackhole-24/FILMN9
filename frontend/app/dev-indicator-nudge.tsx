'use client';

import { useEffect } from 'react';

/**
 * 개발 모드 전용 — Next.js 개발용 표시(N 버튼)를 좌하단에서 살짝 위로(58px≈1cm) 올림.
 * 그 버튼은 <nextjs-portal> 의 open shadow root 안 #devtools-indicator (position:fixed; bottom:20px)라
 * 바깥 CSS가 안 닿음 → shadow root 에 직접 <style> 주입.
 * production 빌드에선 dev 버튼 자체가 없으므로 아무 동작 안 함.
 */
export default function DevIndicatorNudge() {
  useEffect(() => {
    if (process.env.NODE_ENV === 'production') return;

    // 우측 상단 배치: 헤더(56px) 아래·탭바(~100px) 안쪽 = AI챗봇 '새 대화' 버튼 바로 윗부분
    const TOP_PX = 64;
    const RIGHT_PX = 16;
    const apply = (): boolean => {
      const portal = document.querySelector('nextjs-portal') as (Element & { shadowRoot?: ShadowRoot | null }) | null;
      const sr = portal?.shadowRoot;
      if (!sr) return false;
      if (!sr.getElementById?.('devtools-indicator')) return false;    // 아직 버튼 미생성
      let style = sr.getElementById?.('dev-indicator-nudge') as HTMLStyleElement | null;
      if (!style) {
        style = document.createElement('style');
        style.id = 'dev-indicator-nudge';
        sr.appendChild(style);
      }
      // 우측 상단으로 강제 (bottom/left 해제) — 존재해도 값 갱신
      style.textContent = `#devtools-indicator{top:${TOP_PX}px !important;right:${RIGHT_PX}px !important;bottom:auto !important;left:auto !important;}`;
      return true;
    };

    if (apply()) return;
    // dev 버튼이 늦게 붙으므로 관찰
    const obs = new MutationObserver(() => { if (apply()) obs.disconnect(); });
    obs.observe(document.documentElement, { childList: true, subtree: true });
    const t = setTimeout(() => obs.disconnect(), 15000);  // 안전망
    return () => { obs.disconnect(); clearTimeout(t); };
  }, []);

  return null;
}
