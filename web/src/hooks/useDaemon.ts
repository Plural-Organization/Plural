import { useCallback, useEffect, useRef, useState } from "react";
import { type DaemonStatus, daemonStatus } from "../lib/daemon";

export type DaemonPhase = "checking" | "absent" | "unlinked" | "ready";

const POLL_MS = 2500;
// A computer that is there answers at once. No answer after this long means the browser is holding the request,
// most likely asking whether this page may reach the local network.
const STUCK_MS = 3000;

// Looks for the Plural program on this computer while the page needs it, and says what it found.
export function useDaemon(active: boolean): { phase: DaemonPhase; status: DaemonStatus | null; stuck: boolean; check: () => void } {
  const [status, setStatus] = useState<DaemonStatus | null>(null);
  const [phase, setPhase] = useState<DaemonPhase>("checking");
  const [stuck, setStuck] = useState(false);
  const pending = useRef(0);

  const check = useCallback(() => {
    // One question at a time: a held request is not asked again every few seconds.
    if (pending.current > 0) return;
    pending.current += 1;
    const slow = setTimeout(() => setStuck(true), STUCK_MS);
    void daemonStatus().then((found) => {
      clearTimeout(slow);
      pending.current -= 1;
      if (pending.current === 0) setStuck(false);
      setStatus(found);
      setPhase(found === null ? "absent" : found.linked ? "ready" : "unlinked");
    });
  }, []);

  useEffect(() => {
    if (!active) {
      return;
    }
    check();
    const timer = setInterval(check, POLL_MS);
    return () => clearInterval(timer);
  }, [active, check]);

  return { phase, status, stuck, check };
}
