"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";

const ToastContext = createContext<(message: string) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [message, setMessage] = useState<{ text: string; key: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const show = useCallback((text: string) => {
    if (timer.current) clearTimeout(timer.current);
    setMessage({ text, key: Date.now() });
    timer.current = setTimeout(() => setMessage(null), 2400);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 z-[60]" style={{ bottom: "calc(var(--nav-h) + var(--safe-bottom) + 16px)" }}>
        {message && (
          <div
            key={message.key}
            role="status"
            className="toast absolute left-1/2 max-w-[90vw] -translate-x-1/2 rounded-full bg-white px-4 py-2 text-sm font-medium text-black shadow-lg"
          >
            {message.text}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
