import type { TeamProof } from "../protocol";
import { authorizationHeader, freshNonce, httpBase, joinMessage, keyProofMessage, nowSeconds, requestMessage } from "./protocol";
import { closedTunnel, isTunnelHost, TUNNEL_GONE } from "./tunnel";
import type { AccountProof, MemberView, SessionCard, TeamGrant, TeamProfile } from "./types";

// What differs between the terminal (node:crypto, node's fetch) and the browser (WebCrypto, the page's
// fetch). Everything else a team client does is written once, here.
export interface TeamPlatform {
  // The ed25519 signature of the text, base64url.
  sign(message: string): Promise<string>;
  // The SHA-256 of the bytes, hex.
  sha256(body: Uint8Array): Promise<string>;
  fetch(url: string, init: RequestInit): Promise<Response>;
}

export interface Stamp {
  timestamp?: number;
  nonce?: string;
}

export async function authorization(
  profile: TeamProfile,
  platform: TeamPlatform,
  method: string,
  path: string,
  body: Uint8Array = new Uint8Array(),
  stamp: Stamp = {},
): Promise<string> {
  const timestamp = stamp.timestamp ?? nowSeconds();
  const nonce = stamp.nonce ?? freshNonce();
  const signature = await platform.sign(requestMessage(method, path, await platform.sha256(body), timestamp, nonce));
  return authorizationHeader(profile.certificate, timestamp, nonce, signature);
}

export async function teamProof(profile: TeamProfile, platform: TeamPlatform, url: string, room: string, stamp: Stamp = {}): Promise<TeamProof> {
  const timestamp = stamp.timestamp ?? nowSeconds();
  const nonce = stamp.nonce ?? freshNonce();
  return { certificate: profile.certificate, url, ts: timestamp, nonce, proof: await platform.sign(joinMessage(url, room, timestamp, nonce)) };
}

// The relay refused, with the status it answered: a caller may treat 401 or 404 as "already gone".
export class RelayError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "RelayError";
  }
}

export async function answer<T>(response: Response, relay: string): Promise<T> {
  if (response.status === 204) {
    return undefined as T;
  }
  if (response.ok) {
    return (await response.json()) as T;
  }
  const detail = (await response.json().catch(() => null)) as { error?: string } | null;
  const host = new URL(httpBase(relay)).host;
  if (detail?.error === undefined && isTunnelHost(host) && TUNNEL_GONE.has(response.status)) {
    throw new RelayError(closedTunnel(host), response.status);
  }
  throw new RelayError(detail?.error ?? `the relay answered ${response.status}`, response.status);
}

const isTimeout = (error: unknown): boolean => error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError");

// A request that never reached the relay is made once more, with a fresh signature: the relay refuses a nonce it has
// seen. A timeout is not repeated, it may have arrived.
async function signed<T>(profile: TeamProfile, platform: TeamPlatform, method: string, path: string, json?: unknown): Promise<T> {
  const body = json === undefined ? undefined : new TextEncoder().encode(JSON.stringify(json));
  for (let attempt = 0; ; attempt += 1) {
    const headers: Record<string, string> = { authorization: await authorization(profile, platform, method, path, body) };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
    }
    let response: Response;
    try {
      response = await platform.fetch(`${httpBase(profile.relay)}${path}`, { method, headers, ...(body === undefined ? {} : { body }) });
    } catch (error) {
      if (attempt === 0 && !isTimeout(error)) {
        continue;
      }
      throw new Error(`the relay at ${new URL(httpBase(profile.relay)).host} did not answer, try again in a moment`, { cause: error });
    }
    return answer<T>(response, profile.relay);
  }
}

// A request anyone may make: creating or joining a team, or asking for an account's teams.
async function open<T>(relay: string, platform: TeamPlatform, path: string, json: unknown): Promise<T> {
  let response: Response;
  try {
    response = await platform.fetch(`${httpBase(relay)}${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(json) });
  } catch (error) {
    throw new Error(`could not reach the team's relay at ${new URL(httpBase(relay)).host}`, { cause: error });
  }
  return answer<T>(response, relay);
}

// The profile a device keeps for a team, from what the relay granted it.
export function profileFrom(relay: string, grant: TeamGrant): TeamProfile {
  return {
    relay,
    team_id: grant.team_id,
    team_name: grant.team_name,
    team_key: grant.team_key,
    certificate: grant.certificate,
    member: { id: grant.member.id, name: grant.member.name, role: grant.member.role },
  };
}

export interface NewTeam {
  name: string;
  memberName: string;
  // This device's public key, base64url.
  key: string;
  // Given, the creator is an account and not only this key (ADR 0016).
  proof?: AccountProof;
}

// Creates a team; the creator owns it. The invite code comes back once, to share.
export async function createTeamOnRelay(relay: string, platform: TeamPlatform, team: NewTeam): Promise<{ profile: TeamProfile; invite: string | null }> {
  const body = { name: team.name, member_name: team.memberName, key: team.key, ...(team.proof === undefined ? {} : { proof: team.proof }) };
  const grant = await open<TeamGrant>(relay, platform, "/teams", body);
  return { profile: profileFrom(relay, grant), invite: grant.invite ?? null };
}

export interface Joining {
  code: string;
  name: string;
  key: string;
  proof?: AccountProof;
  // With an account, sign the code with this device's key, so a key-only member it already is gets claimed.
  claim?: boolean;
}

export async function joinTeamOnRelay(relay: string, platform: TeamPlatform, joining: Joining): Promise<TeamProfile> {
  const body = {
    code: joining.code,
    name: joining.name,
    key: joining.key,
    ...(joining.proof === undefined ? {} : { proof: joining.proof }),
    ...(joining.proof !== undefined && joining.claim === true ? { key_proof: await platform.sign(keyProofMessage(joining.code)) } : {}),
  };
  return profileFrom(relay, await open<TeamGrant>(relay, platform, "/teams/join", body));
}

// Every team of the signed-in account on this relay, each with a certificate for this device's key.
export async function myTeamsOnRelay(relay: string, platform: TeamPlatform, key: string, proof: AccountProof): Promise<TeamProfile[]> {
  const found = await open<{ teams: TeamGrant[] }>(relay, platform, "/teams/mine", { key, proof });
  return found.teams.map((grant) => profileFrom(relay, grant));
}

export async function fetchMembers(profile: TeamProfile, platform: TeamPlatform): Promise<MemberView[]> {
  return (await signed<{ members: MemberView[] }>(profile, platform, "GET", `/teams/${profile.team_id}/members`)).members;
}

// Owner only, except for oneself (that is leaving).
export async function removeMemberOnRelay(profile: TeamProfile, platform: TeamPlatform, member: string): Promise<void> {
  await signed(profile, platform, "DELETE", `/teams/${profile.team_id}/members/${encodeURIComponent(member)}`);
}

// Owner only: another member owns the team from now on, and the old owner may leave.
export function handOverTeam(profile: TeamProfile, platform: TeamPlatform, member: string): Promise<MemberView> {
  return signed<MemberView>(profile, platform, "POST", `/teams/${profile.team_id}/owner`, { member });
}

export async function fetchSessions(profile: TeamProfile, platform: TeamPlatform): Promise<SessionCard[]> {
  return (await signed<{ sessions: SessionCard[] }>(profile, platform, "GET", `/teams/${profile.team_id}/sessions`)).sessions;
}

export function createTeamInvite(profile: TeamProfile, platform: TeamPlatform): Promise<{ code: string; expires_at: string | null }> {
  return signed(profile, platform, "POST", `/teams/${profile.team_id}/invites`);
}

export async function renewCertificate(profile: TeamProfile, platform: TeamPlatform): Promise<string> {
  return (await signed<{ certificate: string }>(profile, platform, "POST", `/teams/${profile.team_id}/renew`)).certificate;
}

export async function leaveTeamOnRelay(profile: TeamProfile, platform: TeamPlatform): Promise<void> {
  await signed(profile, platform, "DELETE", `/teams/${profile.team_id}/members/${profile.member.id}`);
}

// Owner only: deletes the team for everyone.
export async function disbandTeamOnRelay(profile: TeamProfile, platform: TeamPlatform): Promise<void> {
  await signed(profile, platform, "DELETE", `/teams/${profile.team_id}`);
}
