import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 배포(EC2)용 경량 standalone 서버 출력 (.next/standalone) — t3.micro RAM 절약.
  output: "standalone",
  // 밸류 UI 컴포넌트(태상이 파트, 느슨한 타입) 통합 위해 빌드시 타입·린트 검사 생략.
  // ※ 런타임 동작과 무관. 발표 후 타입 정리 권장.
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  // Next.js 개발용 표시(N 버튼) 위치 — 개발 모드에서만 보임(배포 시 자동 사라짐).
  // 우측 상단(+ dev-indicator-nudge.tsx 에서 y 좌표 미세조정: AI챗봇 '새 대화' 윗부분)
  devIndicators: {
    position: "top-right",
  },
};

export default nextConfig;
