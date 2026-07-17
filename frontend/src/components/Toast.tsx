import { useCallback, useEffect, useRef, useState } from "react";

import { CheckIcon } from "./icons";

/** Bottom-center auto-dismissing toast (design: ~3s, re-trigger resets). */
export function useToast(initial: string | null = null) {
  const [message, setMessage] = useState<string | null>(initial);
  const timer = useRef<number | undefined>(undefined);

  const show = useCallback((msg: string) => {
    setMessage(msg);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(null), 3000);
  }, []);

  useEffect(() => {
    if (initial !== null) {
      timer.current = window.setTimeout(() => setMessage(null), 3000);
    }
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { message, show };
}

export function Toast({ message }: { message: string | null }) {
  if (message === null) {
    return null;
  }
  return (
    <div className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-[11px] bg-ink px-[18px] py-[11px] text-[13px] text-white shadow-[0_8px_24px_rgba(0,0,0,0.18)]">
      <CheckIcon size={15} className="text-up" />
      {message}
    </div>
  );
}
