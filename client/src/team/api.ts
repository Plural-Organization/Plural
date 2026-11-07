import type { TeamProof } from "../protocol";
import { authorizationHeader, freshNonce, httpBase, joinMessage, nowSeconds, requestMessage } from "./protocol";
import { closedTunnel, isTunnelHost, TUNNEL_GONE } from "./tunnel";
import type { SessionCard, TeamProfile } from "./types";

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

export async function answer<T>(response: Response, relay: string): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }
  const detail = (await response.json().catch(() => null)) as { error?: string } | null;
  const host = new URL(httpBase(relay)).host;
  if (detail?.error === undefined && isTunnelHost(host) && TUNNEL_GONE.has(response.status)) {
    throw new Error(closedTunnel(host));
  }
  throw new Error(detail?.error ?? `the relay answered ${response.status}`);
}

const isTimeout = (error: unknown): boolean => error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError");

// A request that never reached the relay is made once more, with a fresh signature: the relay refuses a nonce it has
// seen. A timeout is not repeated, it may have arrived.
async function signed<T>(profile: TeamProfile, platform: TeamPlatform, method: string, path: string): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    const headers = { authorization: await authorization(profile, platform, method, path) };
    let response: Response;
    try {
      response = await platform.fetch(`${httpBase(profile.relay)}${path}`, { method, headers });
    } catch (error) {
      if (attempt === 0 && !isTimeout(error)) {
        continue;
      }
      throw new Error(`the relay at ${new URL(httpBase(profile.relay)).host} did not answer, try again in a moment`, { cause: error });
    }
    return answer<T>(response, profile.relay);
  }
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
