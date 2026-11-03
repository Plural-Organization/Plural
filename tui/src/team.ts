import { createHash, createPrivateKey, randomBytes, sign, type KeyObject } from "node:crypto";
import { USER_AGENT, type TeamProof } from "@plural/client";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { dataDir } from "./paths";

export type SessionStatus = "idle" | "running" | "waiting";

export interface Conflict {
  owner: string;
  room: string;
  branch: string | null;
  paths: string[];
  same_branch: boolean;
  latest: string;
}

export interface SessionCard {
  room: string;
  repo: string;
  branch: string | null;
  title: string | null;
  status: SessionStatus;
  viewers: number;
  endpoints: { kind: "relay" | "direct"; url: string }[];
  owner: string;
  owner_id: string;
  updated_at: string;
  repo_id?: string | null;
  conflicts?: Conflict[];
}

export interface TeamProfile {
  relay: string;
  team_id: string;
  team_name: string;
  team_key: string;
  certificate: string;
  member: { id: string; name: string; role: string };
}

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

// Hosts of tunnels that open for one session. Their address changes at every start and a team made on one
// ends with it. A tunnel of your own, on a domain of yours, is not on this list. The host command keeps
// the same list (src/plural/host/team.py).
const TUNNEL_SUFFIXES = [".trycloudflare.com", ".ngrok-free.app", ".ngrok-free.dev", ".ngrok.app", ".ngrok.dev", ".ngrok.io", ".loca.lt"];
// What a tunnel provider answers for an address nothing listens on any more.
const TUNNEL_GONE = new Set([404, 502, 503, 504, 530]);

export function isTunnelHost(host: string): boolean {
  const name = (host.toLowerCase().split(":")[0] ?? "");
  return TUNNEL_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

export function closedTunnel(host: string): string {
  return `the tunnel ${host} is closed, and the team on it ended with it. Ask the team owner to start it again and send a new invite`;
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

async function refusal(response: Response, relay: string): Promise<Error> {
  const detail = (await response.json().catch(() => null)) as { error?: string } | null;
  const host = new URL(httpBase(relay)).host;
  if (detail?.error === undefined && isTunnelHost(host) && TUNNEL_GONE.has(response.status)) {
    return new Error(closedTunnel(host));
  }
  return new Error(detail?.error ?? `the relay answered ${response.status}`);
}

export function httpBase(relay: string): string {
  const url = new URL(relay.trim());
  const scheme = { "ws:": "http:", "wss:": "https:", "http:": "http:", "https:": "https:" }[url.protocol];
  if (scheme === undefined) {
    throw new Error(`${relay} is not a relay address`);
  }
  return `${scheme}//${url.host}`;
}

export function requestMessage(method: string, path: string, body: Uint8Array, timestamp: number, nonce: string): string {
  return `${method.toUpperCase()}\n${path}\n${timestamp}\n${nonce}\n${createHash("sha256").update(body).digest("hex")}`;
}

export function joinMessage(url: string, room: string, timestamp: number, nonce: string): string {
  return `plural-team-join\n${url}\n${room}\n${timestamp}\n${nonce}`;
}

export function teamProof(team: Team, url: string, room: string, timestamp = Math.floor(Date.now() / 1000), nonce = randomBytes(8).toString("hex")): TeamProof {
  return {
    certificate: team.profile.certificate,
    url,
    ts: timestamp,
    nonce,
    proof: sign(null, Buffer.from(joinMessage(url, room, timestamp, nonce)), team.key).toString("base64url"),
  };
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

export function authorization(team: Team, method: string, path: string, body: Uint8Array = new Uint8Array(), timestamp = Math.floor(Date.now() / 1000), nonce = randomBytes(8).toString("hex")): string {
  const signature = sign(null, Buffer.from(requestMessage(method, path, body, timestamp, nonce)), team.key).toString("base64url");
  return `Plural cert=${team.profile.certificate} ts=${timestamp} nonce=${nonce} sig=${signature}`;
}

export async function fetchSessions(team: Team, fetcher: typeof fetch = fetch): Promise<SessionCard[]> {
  const path = `/teams/${team.profile.team_id}/sessions`;
  const response = await fetcher(`${httpBase(team.profile.relay)}${path}`, {
    headers: { authorization: authorization(team, "GET", path), "user-agent": USER_AGENT },
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) {
    throw await refusal(response, team.profile.relay);
  }
  return ((await response.json()) as { sessions: SessionCard[] }).sessions;
}

export function teamJoinCommand(team: Team, code: string): string {
  return `plural team join ${code} --relay ${team.profile.relay}`;
}

export async function createTeamInvite(team: Team, fetcher: typeof fetch = fetch): Promise<{ code: string; expires_at: string | null }> {
  const path = `/teams/${team.profile.team_id}/invites`;
  const response = await fetcher(`${httpBase(team.profile.relay)}${path}`, {
    method: "POST",
    headers: { authorization: authorization(team, "POST", path), "user-agent": USER_AGENT },
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) {
    throw await refusal(response, team.profile.relay);
  }
  return (await response.json()) as { code: string; expires_at: string | null };
}

export interface TeamView {
  name: string;
  me: string;
  member: string;
  sessions: SessionCard[];
  error: string | null;
}

export class TeamWatcher {
  private current: TeamView;
  private readonly listeners = new Set<(view: TeamView) => void>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private refreshing = false;

  constructor(
    private readonly team: Team,
    private readonly fetcher: typeof fetch = fetch,
    private readonly everyMs = 5000,
  ) {
    this.current = { name: team.profile.team_name, me: team.profile.member.id, member: team.profile.member.name, sessions: [], error: null };
  }

  get view(): TeamView {
    return this.current;
  }

  subscribe(listener: (view: TeamView) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  start(): void {
    if (this.timer !== null) {
      return;
    }
    void this.refresh();
    this.timer = setInterval(() => void this.refresh(), this.everyMs);
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  async refresh(): Promise<void> {
    if (this.refreshing) {
      return;
    }
    this.refreshing = true;
    try {
      this.set({ ...this.current, sessions: await fetchSessions(this.team, this.fetcher), error: null });
    } catch (error) {
      this.set({ ...this.current, error: error instanceof Error ? error.message : String(error) });
    } finally {
      this.refreshing = false;
    }
  }

  private set(view: TeamView): void {
    this.current = view;
    this.listeners.forEach((listener) => listener(view));
  }
}
