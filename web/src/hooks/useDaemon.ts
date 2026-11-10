import { useCallback, useEffect, useState } from "react";
import { type DaemonStatus, daemonStatus } from "../lib/daemon";

export type DaemonPhase = "checking" | "absent" | "unlinked" | "ready";

const POLL_MS = 2500;

// Looks for the Plural program on this computer while the page needs it, and says what it found.
export function useDaemon(active: boolean): { phase: DaemonPhase; status: DaemonStatus | null; check: () => void } {
  const [status, setStatus] = useState<DaemonStatus | null>(null);
  const [phase, setPhase] = useState<DaemonPhase>("checking");

  const check = useCallback(() => {
    void daemonStatus().then((found) => {
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

  return { phase, status, check };
}
