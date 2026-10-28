import { useEffect, useRef } from "react";
import type { Command, ConnectionStatus, TextSelection } from "@plural/client";
import { readSelection, sameSelection } from "../lib/selection";

const DELAY_MS = 120;

// Tells the room what this person has selected, at most every DELAY_MS and only when it changes.
export function useShareSelection(enabled: boolean, connection: ConnectionStatus, send: (command: Command) => boolean): void {
  const last = useRef<TextSelection | null>(null);

  useEffect(() => {
    // A reconnect starts over: the host dropped the selection when the connection did.
    last.current = null;
    if (!enabled || connection !== "online") {
      return;
    }
    let timer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      timer = null;
      const next = readSelection(window.getSelection());
      if (!sameSelection(next, last.current) && send({ type: "presence.select", selection: next })) {
        last.current = next;
      }
    };
    const change = () => {
      timer ??= setTimeout(flush, DELAY_MS);
    };
    document.addEventListener("selectionchange", change);
    flush();
    return () => {
      document.removeEventListener("selectionchange", change);
      if (timer !== null) {
        clearTimeout(timer);
      }
      if (last.current !== null) {
        last.current = null;
        send({ type: "presence.select", selection: null });
      }
    };
  }, [enabled, connection, send]);
}
