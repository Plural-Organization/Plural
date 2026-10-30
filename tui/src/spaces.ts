import type { Conflict, SessionCard, SessionStatus, TeamView } from "./team";

export type Phase = "idle" | "running" | "waiting" | "done";

export interface Summary {
  phase: Phase;
}

export interface Visit {
  id: string;
  card: SessionCard;
}

export interface SpaceRow {
  id: string;
  title: string;
  detail: string;
  status: SessionStatus;
  viewers: number;
  mine: boolean;
  active: boolean;
  offline: boolean;
  clash: boolean;
  warning: string | null;
}

export const OWN = "own";

function statusOf(phase: Phase | undefined, fallback: SessionStatus): SessionStatus {
  if (phase === undefined) {
    return fallback;
  }
  return phase === "waiting" || phase === "running" ? phase : "idle";
}

function where(card: SessionCard): string {
  return card.branch ? `${card.repo} · ${card.branch}` : card.repo;
}

export interface SpacesInput {
  home: string;
  team: TeamView | null;
  visits: Visit[];
  active: string;
  summaries: Record<string, Summary | undefined>;
}

export function describeConflict(conflict: Conflict): string {
  const files = conflict.paths.slice(0, 2).join(", ") + (conflict.paths.length > 2 ? " …" : "");
  return `${conflict.owner} also changed ${files}`;
}

export function ownConflicts(team: TeamView | null): Conflict[] {
  return team?.sessions.find((card) => card.owner_id === team.me)?.conflicts ?? [];
}

export function buildSpaces({ home, team, visits, active, summaries }: SpacesInput): SpaceRow[] {
  const cards = team?.sessions ?? [];
  const mine = cards.find((card) => card.owner_id === team?.me);
  const clashing = new Set((mine?.conflicts ?? []).map((conflict) => conflict.room));
  const rows: SpaceRow[] = [
    {
      id: OWN,
      title: "you",
      detail: mine ? where(mine) : home,
      status: statusOf(summaries[OWN]?.phase, mine?.status ?? "idle"),
      viewers: mine?.viewers ?? 0,
      mine: true,
      active: active === OWN,
      offline: false,
      clash: false,
      warning: mine?.conflicts?.[0] ? describeConflict(mine.conflicts[0]) : null,
    },
  ];
  const seen = new Set<string>();
  for (const card of cards.filter((entry) => entry.owner_id !== team?.me)) {
    seen.add(card.room);
    rows.push({
      id: card.room,
      title: card.owner,
      detail: where(card),
      status: statusOf(summaries[card.room]?.phase, card.status),
      viewers: card.viewers,
      mine: false,
      active: active === card.room,
      offline: false,
      clash: clashing.has(card.room),
      warning: null,
    });
  }
  for (const visit of visits.filter((entry) => !seen.has(entry.id))) {
    rows.push({
      id: visit.id,
      title: visit.card.owner,
      detail: where(visit.card),
      status: "idle",
      viewers: 0,
      mine: false,
      active: active === visit.id,
      offline: true,
      clash: clashing.has(visit.id),
      warning: null,
    });
  }
  return rows;
}

export function neighbour(rows: SpaceRow[], active: string, direction: 1 | -1): string {
  const index = rows.findIndex((row) => row.id === active);
  const next = rows[(Math.max(0, index) + direction + rows.length) % rows.length];
  return next?.id ?? OWN;
}
