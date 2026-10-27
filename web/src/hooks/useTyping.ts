import { useEffect, useRef } from "react";
import type { Command } from "@plural/client";

const REFRESH_MS = 3000;
const IDLE_MS = 2500;

export function useTyping(enabled: boolean, send: (command: Command) => void) {
  const on = useRef(false);
  const sentAt = useRef(0);
  const idle = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stop = () => {
    if (idle.current) {
      clearTimeout(idle.current);
      idle.current = null;
    }
    if (on.current) {
      on.current = false;
      send({ type: "presence.typing", typing: false });
    }
  };

  const activity = (text: string) => {
    if (!enabled) {
      return;
    }
    if (text.trim() === "" || text.startsWith("/")) {
      stop();
      return;
    }
    const now = Date.now();
    if (!on.current || now - sentAt.current > REFRESH_MS) {
      on.current = true;
      sentAt.current = now;
      send({ type: "presence.typing", typing: true });
    }
    if (idle.current) {
      clearTimeout(idle.current);
    }
    idle.current = setTimeout(stop, IDLE_MS);
  };

  useEffect(
    () => () => {
      if (idle.current) {
        clearTimeout(idle.current);
      }
    },
    [],
  );

  return { activity, stop };
}
