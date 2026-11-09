import { useState } from "react";

// Below this the side panels slide over the room instead of standing beside it.
export const NARROW = "(max-width: 980px)";

export const isNarrow = (): boolean => window.matchMedia(NARROW).matches;

// Whether a side panel is tucked away on a wide screen, remembered in this browser only.
export function useTucked(key: string): [boolean, (tucked: boolean) => void] {
  const [tucked, setTucked] = useState(() => {
    try {
      return localStorage.getItem(key) === "1";
    } catch {
      return false;
    }
  });
  const set = (next: boolean) => {
    setTucked(next);
    try {
      localStorage.setItem(key, next ? "1" : "0");
    } catch {
      // Private windows may refuse; the choice then lasts until the page reloads.
    }
  };
  return [tucked, set];
}

// A side panel's width on a wide screen, kept within its bounds and remembered in this browser only.
export const RAIL_WIDTH = { min: 220, max: 440 };
export const SIDE_WIDTH = { min: 240, max: 480 };

export function useWidth(key: string, initial: number, { min, max }: { min: number; max: number }): [number, (width: number) => void] {
  const clamp = (value: number) => Math.round(Math.min(max, Math.max(min, value)));
  const [width, setWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem(key));
      return saved > 0 ? clamp(saved) : initial;
    } catch {
      return initial;
    }
  });
  const set = (next: number) => {
    const kept = clamp(next);
    setWidth(kept);
    try {
      localStorage.setItem(key, String(kept));
    } catch {
      // Kept until the page reloads.
    }
  };
  return [width, set];
}
