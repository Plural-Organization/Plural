import { useCallback, useEffect, useState } from "react";
import { type BridgeProvider, bridges } from "../lib/bridges";
import { DaemonError, daemonMessage } from "../lib/daemon";

const POLL_MS = 3000;

export interface BridgesState {
  providers: BridgeProvider[] | null;
  /** Why the list could not be read. */
  error: string | null;
  /** The program on this computer is older than chat apps. */
  outdated: boolean;
  refresh: () => void;
}

// What chat apps this computer offers and how each is doing. It looks again every few seconds while the
// screen is open, because a bridge connects, fails or is paired after the person pressed Save.
export function useBridges(active: boolean): BridgesState {
  const [providers, setProviders] = useState<BridgeProvider[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outdated, setOutdated] = useState(false);

  const refresh = useCallback(() => {
    bridges()
      .then((found) => {
        setProviders(found);
        setError(null);
      })
      .catch((failure: unknown) => {
        if (failure instanceof DaemonError && failure.status === 404) {
          setOutdated(true);
          setError("Update Plural on this computer to connect chat apps: run plural update, then start plural daemon again.");
          return;
        }
        setError(failure instanceof DaemonError ? daemonMessage(failure) : "Could not read the chat apps on this computer.");
      });
  }, []);

  useEffect(() => {
    if (!active) return;
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [active, refresh]);

  return { providers, error, outdated, refresh };
}
