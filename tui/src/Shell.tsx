import { useRenderer } from "@opentui/react";
import type { Session } from "@plural/client";
import { useEffect, useMemo, useState } from "react";
import { App, type AppProps } from "./App";
import { buildSpaces, neighbour, OWN, ownConflicts, type Phase, type Summary, type Visit } from "./spaces";
import { DEFAULT_SETTINGS, type Settings } from "./settings";
import type { SessionCard, Team, TeamView, TeamWatcher } from "./team";

export interface ShellProps {
  app: AppProps;
  team: Team | null;
  watcher?: TeamWatcher;
  home: string;
  connect: (card: SessionCard, team: Team) => Session;
}

interface Open extends Visit {
  client: Session;
}

const TITLES: Record<Phase, string> = {
  waiting: "plural · ⚠ waiting for you",
  running: "plural · ● working",
  done: "plural · ✓ done",
  idle: "plural",
};

export function Shell({ app, team, watcher, home, connect }: ShellProps) {
  const renderer = useRenderer();
  const [settings, setSettings] = useState<Settings>(app.settings ?? DEFAULT_SETTINGS);
  const [view, setView] = useState<TeamView | null>(watcher?.view ?? null);
  const [visits, setVisits] = useState<Open[]>([]);
  const [active, setActive] = useState(OWN);
  const [summaries, setSummaries] = useState<Record<string, Summary | undefined>>({});

  useEffect(() => watcher?.subscribe(setView), [watcher]);

  const rows = useMemo(() => buildSpaces({ home, team: view, visits, active, summaries }), [home, view, visits, active, summaries]);

  const own = summaries[OWN]?.phase ?? "idle";
  useEffect(() => {
    try {
      renderer.setTerminalTitle(TITLES[own]);
    } catch {
      return;
    }
  }, [own]);

  const open = (id: string): void => {
    if (id === OWN || visits.some((visit) => visit.id === id)) {
      setActive(id);
      return;
    }
    const card = view?.sessions.find((entry) => entry.room === id);
    if (card === undefined || team === null) {
      return;
    }
    setVisits((current) => [...current, { id, card, client: connect(card, team) }]);
    setActive(id);
  };

  const close = (id: string): void => {
    setVisits((current) => current.filter((visit) => visit.id !== id));
    setActive((current) => (current === id ? OWN : current));
  };

  const summary = (id: string) => (next: Summary) => setSummaries((current) => (current[id]?.phase === next.phase ? current : { ...current, [id]: next }));

  const conflicts = useMemo(() => ownConflicts(view), [view]);
  const shared = {
    spaces: rows,
    teamName: view?.name ?? null,
    teamError: view?.error ?? null,
    onOpenSpace: open,
    onCycleSpace: (direction: 1 | -1) => open(neighbour(rows, active, direction)),
  };
  const change = (next: Settings): void => {
    setSettings(next);
    app.onSettings?.(next);
  };

  return (
    <>
      <App {...app} {...shared} conflicts={conflicts} settings={settings} onSettings={change} active={active === OWN} onSummary={summary(OWN)} />
      {visits.map((visit) => (
        <App
          key={visit.id}
          {...shared}
          client={visit.client}
          room={visit.id}
          version={app.version}
          guestLink={null}
          settings={settings}
          onSettings={change}
          viewing={visit.card.owner}
          onGiveBriefing={(briefing) => app.client.send({ type: "briefing.import", ...briefing })}
          active={active === visit.id}
          onSummary={summary(visit.id)}
          onClose={() => close(visit.id)}
          onQuit={() => close(visit.id)}
        />
      ))}
    </>
  );
}
