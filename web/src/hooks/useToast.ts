import { useEffect, useRef, useState } from "react";

const TOAST_MS = 2000;

export function useToast() {
  const [toast, setToast] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) {
        clearTimeout(timer.current);
      }
    },
    [],
  );

  const flash = (text: string) => {
    if (timer.current) {
      clearTimeout(timer.current);
    }
    setToast(text);
    timer.current = setTimeout(() => setToast(null), TOAST_MS);
  };

  return { toast, flash };
}
