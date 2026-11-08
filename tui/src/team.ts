import { createHash, createPrivateKey, sign, type KeyObject } from "node:crypto";
import {
  createTeamInvite as inviteOnRelay,
  fetchSessions as sessionsOnRelay,
  httpBase,
  isTunnelHost,
  teamProof as proveJoin,
  USER_AGENT,
  type SessionCard,
  type Stamp,
  type TeamPlatform,
  type TeamProfile,
  type TeamProof,
} from "@plural/client";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { dataDir } from "./paths";

const TIMEOUT_MS = 8000;

export interface Team {
  profile: TeamProfile;
  key: KeyObject;
}

export function loadTeam(directory: string = dataDir()): Team | null {
  const profilePath = join(directory, "team.json");
  const keyPath = join(directory, "identity.pem");
  if (!existsSync(profilePath) || !existsSync(keyPath)) {
    return null;
  }
  try {
    return { profile: JSON.parse(readFileSync(profilePath, "utf8")) as TeamProfile, key: createPrivateKey(readFileSync(keyPath)) };
  } catch {
    return null;
  }
}

export function platformOf(team: Team, fetcher: typeof fetch = fetch): TeamPlatform {
  return {
    sign: async (message) => sign(null, Buffer.from(message), team.key).toString("base64url"),
    sha256: async (body) => createHash("sha256").update(body).digest("hex"),
    fetch: (url, init) =>
      fetcher(url, { ...init, headers: { ...(init.headers as Record<string, string>), "user-agent": USER_AGENT }, signal: AbortSignal.timeout(TIMEOUT_MS) }),
  };
}

export function fetchSessions(team: Team, fetcher: typeof fetch = fetch): Promise<SessionCard[]> {
  return sessionsOnRelay(team.profile, platformOf(team, fetcher));
}

export function createTeamInvite(team: Team, fetcher: typeof fetch = fetch): Promise<{ code: string; expires_at: string | null }> {
  return inviteOnRelay(team.profile, platformOf(team, fetcher));
}

export function teamProof(team: Team, url: string, room: string, stamp: Stamp = {}): Promise<TeamProof> {
  return proveJoin(team.profile, platformOf(team), url, room, stamp);
}

export type RelayState = "alive" | "dead" | "unknown";

// Only an answer that is not ours means the relay is gone: a timeout or a refused connection may be this
// machine being offline, so those stay unknown.
export async function relayState(relay: string, fetcher: typeof fetch = fetch): Promise<RelayState> {
  try {
    const response = await fetcher(`${httpBase(relay)}/healthz`, { headers: { "user-agent": USER_AGENT }, signal: AbortSignal.timeout(4000) });
    return response.ok ? "alive" : "dead";
  } catch {
    return "unknown";
  }
}

export function clearTeam(directory: string = dataDir()): void {
  rmSync(join(directory, "team.json"), { force: true });
}

// A team made on a tunnel ends with it. Leaves it when the tunnel is closed, and says so.
export async function leaveClosedTunnel(directory: string = dataDir(), fetcher: typeof fetch = fetch): Promise<string | null> {
  const team = loadTeam(directory);
  if (team === null || !isTunnelHost(new URL(httpBase(team.profile.relay)).host)) {
    return null;
  }
  if ((await relayState(team.profile.relay, fetcher)) !== "dead") {
    return null;
  }
  clearTeam(directory);
  return `you left ${team.profile.team_name}: its tunnel is closed, and a team on a tunnel ends with it`;
}
