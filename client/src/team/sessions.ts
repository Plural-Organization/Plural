import type { SessionCard, SessionStatus } from "./types";

// Where a teammate's session can be reached from here: an https page reaches only wss.
export function reachable(card: SessionCard, protocol: string): string | null {
  const urls = card.endpoints.map((endpoint) => endpoint.url).filter((url) => url.startsWith("ws"));
  return (protocol === "https:" ? urls.find((url) => url.startsWith("wss:")) : urls[0]) ?? null;
}

const BUSIEST: Record<SessionStatus, number> = { running: 0, waiting: 1, idle: 2 };

// The session to open right after joining: someone else's that this page can reach, the busiest first,
// then the freshest.
export function firstSession(cards: SessionCard[], memberId: string, protocol: string): { card: SessionCard; url: string } | null {
  const open = cards
    .filter((card) => card.owner_id !== memberId)
    .map((card) => ({ card, url: reachable(card, protocol) }))
    .filter((item): item is { card: SessionCard; url: string } => item.url !== null);
  open.sort((a, b) => BUSIEST[a.card.status] - BUSIEST[b.card.status] || b.card.updated_at.localeCompare(a.card.updated_at));
  return open[0] ?? null;
}

export function pickTeamSession(sessions: SessionCard[], me: string, spec: string): SessionCard {
  const [rawName = "", repo] = spec.replace(/^@/, "").split(":");
  const name = rawName.toLowerCase();
  if (name === "") {
    throw new Error("usage: plural join @name[:repo]");
  }
  const theirs = sessions.filter((card) => card.owner.toLowerCase() === name);
  if (theirs.length === 0) {
    throw new Error(`${rawName} is not sharing a session right now. plural ls shows who is`);
  }
  if (theirs.every((card) => card.owner_id === me)) {
    throw new Error("that is your own session");
  }
  const chosen = repo === undefined ? theirs : theirs.filter((card) => card.repo.toLowerCase() === repo.toLowerCase());
  if (chosen.length === 0) {
    throw new Error(`${rawName} has no session in ${repo}: ${theirs.map((card) => card.repo).join(", ")}`);
  }
  if (chosen.length > 1) {
    throw new Error(`${rawName} shares ${chosen.length} sessions, say which: ${chosen.map((card) => `@${card.owner}:${card.repo}`).join(", ")}`);
  }
  return chosen[0] as SessionCard;
}
