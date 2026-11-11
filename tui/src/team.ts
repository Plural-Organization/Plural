import { createHash, createPrivateKey, sign, type KeyObject } from "node:crypto";
import {
  createTeamInvite as inviteOnRelay,
  disbandTeamOnRelay,
  fetchSessions as sessionsOnRelay,
  httpBase,
  isTunnelHost,
  leaveTeamOnRelay,
  RelayError,
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

const TEAM_ID = /^[A-Za-z0-9_-]{1,64}$/;

// The current team's file: `current-team` names one of the teams under `teams/` (ADR 0016); without it,
// the single team of older versions in team.json. `plural team use` changes it.
export function currentTeamPath(directory: string = dataDir()): string {
  try {
    const chosen = readFileSync(join(directory, "current-team"), "utf8").trim();
    const path = join(directory, "teams", `${chosen}.json`);
    if (TEAM_ID.test(chosen) && existsSync(path)) {
      return path;
    }
  } catch {
    // No current team named: the older single team, if any.
  }
  return join(directory, "team.json");
}

export function loadTeam(directory: string = dataDir()): Team | null {
  const profilePath = currentTeamPath(directory);
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
  const path = currentTeamPath(directory);
  rmSync(path, { force: true });
  if (path !== join(directory, "team.json")) {
    rmSync(join(directory, "current-team"), { force: true });
  }
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

// Leaves the team, or deletes it for everyone when this is its owner (the relay refuses an owner who only leaves).
// A relay that no longer knows this member (401, 404: the team is gone, the member was removed, the certificate
// ran out) leaves nothing to undo there, so the profile is cleared all the same.
export async function leaveTeam(team: Team, directory: string = dataDir(), fetcher: typeof fetch = fetch): Promise<void> {
  const platform = platformOf(team, fetcher);
  try {
    await (team.profile.member.role === "owner" ? disbandTeamOnRelay(team.profile, platform) : leaveTeamOnRelay(team.profile, platform));
  } catch (error) {
    if (!(error instanceof RelayError && (error.status === 401 || error.status === 404))) {
      throw error;
    }
  }
  clearTeam(directory);
}
