import * as React from "react";

/** ⓘ 툴팁 — 어려운 용어에 쉬운 설명. 호버/포커스 시 표시(원본 .tip 재현). */
export function Tip({ text }: { text: React.ReactNode }) {
  return (
    <span
      className="group/tip relative ml-1 inline-block align-middle"
      tabIndex={0}
    >
      <span className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-slate-400 text-[10px] font-bold leading-none text-white">
        i
      </span>
      <span className="invisible absolute bottom-[150%] left-1/2 z-[60] w-60 max-w-[78vw] -translate-x-1/2 rounded-lg bg-slate-800 px-3 py-2.5 text-left text-[12.5px] font-normal leading-relaxed text-slate-100 opacity-0 shadow-2xl transition-opacity group-hover/tip:visible group-hover/tip:opacity-100 group-focus/tip:visible group-focus/tip:opacity-100">
        {text}
      </span>
    </span>
  );
}
