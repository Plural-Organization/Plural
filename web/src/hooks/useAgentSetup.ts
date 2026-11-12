import { useCallback, useEffect, useMemo, useState } from "react";
import { type AgentCatalog, type AgentChoice, type Provider, agentCatalog, saveKey } from "../lib/agent";
import { blockerFor, choiceFor } from "../lib/agentSetup";
import { DaemonError, daemonMessage } from "../lib/daemon";

export interface AgentSetupState {
  catalog: AgentCatalog | null;
  /** Why the catalog could not be read. */
  error: string | null;
  /** The program on this computer is older than agent setup: rooms start with its own agent. */
  outdated: boolean;
  provider: Provider | null;
  choice: AgentChoice | null;
  typedKey: string;
  /** Why the choice cannot run yet, or null. */
  blocker: string | null;
  pick: (id: string) => void;
  edit: (change: Partial<AgentChoice>) => void;
  setTypedKey: (key: string) => void;
  refresh: () => void;
  /** Saves a typed key on the computer and returns the choice to run. Throws what is missing. */
  commit: () => Promise<AgentChoice>;
}

const clean = (choice: AgentChoice): AgentChoice => ({
  ...choice,
  model: choice.model.trim(),
  baseUrl: choice.baseUrl.trim(),
  contextWindow: choice.contextWindow.trim(),
  fastModel: choice.fastModel.trim(),
});

// The agent screen's state: what this computer offers, what is chosen, and a key being typed.
// `active` is false while the page cannot reach the program on the computer.
export function useAgentSetup(active: boolean): AgentSetupState {
  const [catalog, setCatalog] = useState<AgentCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [choice, setChoice] = useState<AgentChoice | null>(null);
  const [typedKey, setTypedKey] = useState("");
  const [outdated, setOutdated] = useState(false);

  const refresh = useCallback(() => {
    agentCatalog()
      .then((found) => {
        setCatalog(found);
        setError(null);
        setChoice((before) => {
          if (before !== null) return before;
          const first = found.presets.find((entry) => entry.id === found.current.preset);
          return first === undefined ? found.current : choiceFor(first, found.current);
        });
      })
      .catch((failure: unknown) => {
        // A daemon from before agent setup has no /v1/agent: it answers 404.
        if (failure instanceof DaemonError && failure.status === 404) {
          setOutdated(true);
          setError("Update Plural on this computer to choose the agent here: run plural update, then start plural daemon again.");
          return;
        }
        setError(failure instanceof DaemonError ? daemonMessage(failure) : "Could not read the agents on this computer.");
      });
  }, []);

  useEffect(() => {
    if (active) refresh();
  }, [active, refresh]);

  const provider = useMemo(() => catalog?.presets.find((entry) => entry.id === choice?.preset) ?? null, [catalog, choice?.preset]);

  const pick = useCallback(
    (id: string) => {
      const next = catalog?.presets.find((entry) => entry.id === id);
      if (catalog === undefined || catalog === null || next === undefined) return;
      setChoice(choiceFor(next, catalog.current));
      setTypedKey("");
    },
    [catalog],
  );

  const edit = useCallback((change: Partial<AgentChoice>) => setChoice((before) => (before === null ? before : { ...before, ...change })), []);

  const blocker = provider !== null && choice !== null ? blockerFor(provider, choice, typedKey) : null;

  const commit = useCallback(async () => {
    if (provider === null || choice === null) throw new Error("Choose an agent first.");
    const why = blockerFor(provider, choice, typedKey);
    if (why !== null) throw new Error(why);
    if (typedKey.trim() !== "") {
      await saveKey(provider.id, typedKey.trim());
      setTypedKey("");
      refresh();
    }
    return clean(choice);
  }, [provider, choice, typedKey, refresh]);

  return { catalog, error, outdated, provider, choice, typedKey, blocker, pick, edit, setTypedKey, refresh, commit };
}
