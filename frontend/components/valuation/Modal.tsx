"use client";

import * as React from "react";
import { C } from "@/lib/valuation";

/** 설명 모달 다이얼로그(원본 .modal 재현). ESC·배경클릭으로 닫힘. */
export function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
}) {
  React.useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", h);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", h);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,.55)", backdropFilter: "blur(2px)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
    >
      <div className="max-h-[86vh] w-full max-w-[580px] overflow-y-auto rounded-2xl bg-white shadow-2xl">
        <div className="sticky top-0 flex items-start justify-between gap-3 rounded-t-2xl border-b bg-white px-6 pb-3.5 pt-5">
          <h3 className="text-lg font-extrabold leading-snug" style={{ color: C.navy }}>
            {title}
          </h3>
          <button
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[17px] text-slate-500 hover:bg-slate-200"
            aria-label="닫기"
          >
            ✕
          </button>
        </div>
        <div className="px-6 pb-6 pt-4 text-sm leading-7 text-slate-700">{children}</div>
      </div>
    </div>
  );
}
