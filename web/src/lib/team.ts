import {
  answer,
  createTeamInvite as inviteOnRelay,
  fetchSessions as sessionsOnRelay,
  httpBase,
  leaveTeamOnRelay,
  renewCertificate,
  renewalDue,
  teamProof as proveJoin,
  type SessionCard,
  type Stamp,
  type TeamInvite,
  type TeamPlatform,
  type TeamProfile,
  type TeamProof,
} from "@plural/client";
import { sha256 } from "./sha256";

// A team in the browser works as in the terminal (ADR 0007): this browser has its own ed25519 key, the
// team's directory on the relay signs it a member certificate, and every request and team join is
// signed with the key. The private key never leaves the browser: it is made non-extractable and kept
// in IndexedDB, next to the team's profile.

export interface Team {
  profile: TeamProfile;
  key: CryptoKeyPair;
}

const DATABASE = "plural";
const STORE = "keys";
const IDENTITY = "identity";
const PROFILE = "team";
const TIMEOUT_MS = 8000;

export function base64url(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function signText(key: CryptoKeyPair, text: string): Promise<string> {
  return base64url(new Uint8Array(await crypto.subtle.sign("Ed25519", key.privateKey, new TextEncoder().encode(text))));
}

export async function publicKey(key: CryptoKeyPair): Promise<string> {
  return base64url(new Uint8Array(await crypto.subtle.exportKey("raw", key.publicKey)));
}

function openKeys(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("this browser keeps no keys"));
  });
}

function keyStore<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openKeys().then(
    (database) =>
      new Promise<T>((resolve, reject) => {
        const request = run(database.transaction(STORE, mode).objectStore(STORE));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error ?? new Error("this browser keeps no keys"));
      }).finally(() => database.close()),
  );
}

function savedKey(): Promise<CryptoKeyPair | undefined> {
  return keyStore<CryptoKeyPair | undefined>("readonly", (store) => store.get(IDENTITY) as IDBRequest<CryptoKeyPair | undefined>);
}

// This browser's key, made once.
export async function identity(): Promise<CryptoKeyPair> {
  const saved = await savedKey();
  if (saved) {
    return saved;
  }
  let made: CryptoKeyPair;
  try {
    made = (await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign", "verify"])) as CryptoKeyPair;
  } catch {
    throw new Error("this browser cannot make an ed25519 key; teams need a recent Chrome, Edge, Safari or Firefox over https");
  }
  await keyStore("readwrite", (store) => store.put(made, IDENTITY));
  return made;
}

async function savedProfile(): Promise<TeamProfile | null> {
  const profile = await keyStore<TeamProfile | undefined>("readonly", (store) => store.get(PROFILE) as IDBRequest<TeamProfile | undefined>).catch(() => undefined);
  return profile && typeof profile.team_id === "string" && typeof profile.certificate === "string" ? profile : null;
}

async function saveProfile(profile: TeamProfile | null): Promise<void> {
  await keyStore<unknown>("readwrite", (store) => (profile === null ? store.delete(PROFILE) : store.put(profile, PROFILE)) as IDBRequest<unknown>);
}

// A profile without its key is no use: the certificate names a key this browser no longer has.
export async function loadTeam(): Promise<Team | null> {
  const profile = await savedProfile();
  if (profile === null) {
    return null;
  }
  const key = await savedKey();
  if (key === undefined) {
    await saveProfile(null);
    throw new Error(`this browser lost its key for ${profile.team_name}; ask the owner for a new invite`);
  }
  return { profile, key };
}

const NGROK_SKIP = "ngrok-skip-browser-warning";

export async function reach(url: string, init: RequestInit): Promise<Response> {
  const ask = (headers: HeadersInit): Promise<Response> => fetch(url, { ...init, headers, signal: AbortSignal.timeout(TIMEOUT_MS) });
  const headers = (init.headers ?? {}) as Record<string, string>;
  try {
    return await ask(headers);
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new Error(`could not reach the team's relay at ${new URL(url).host}`);
    }
  }
  try {
    return await ask({ ...headers, [NGROK_SKIP]: "1" });
  } catch {
    throw new Error(`could not reach the team's relay at ${new URL(url).host}`);
  }
}


export function platformOf(team: Team): TeamPlatform {
  return { sign: (message) => signText(team.key, message), sha256, fetch: reach };
}

interface Grant {
  team_id: string;
  team_name: string;
  team_key: string;
  certificate: string;
  member: { id: string; name: string; role: string };
}

export async function joinTeam(invite: TeamInvite, name: string): Promise<Team> {
  const key = await identity();
  const body = JSON.stringify({ code: invite.code, name, key: await publicKey(key) });
  const response = await reach(`${httpBase(invite.relay)}/teams/join`, { method: "POST", headers: { "content-type": "application/json" }, body });
  const grant = await answer<Grant>(response, invite.relay);
  const profile: TeamProfile = {
    relay: invite.relay,
    team_id: grant.team_id,
    team_name: grant.team_name,
    team_key: grant.team_key,
    certificate: grant.certificate,
    member: { id: grant.member.id, name: grant.member.name, role: grant.member.role },
  };
  await saveProfile(profile);
  return { profile, key };
}

export function teamProof(team: Team, url: string, room: string, stamp?: Stamp): Promise<TeamProof> {
  return proveJoin(team.profile, platformOf(team), url, room, stamp);
}

export function fetchSessions(team: Team): Promise<SessionCard[]> {
  return sessionsOnRelay(team.profile, platformOf(team));
}

export function createTeamInvite(team: Team): Promise<{ code: string; expires_at: string | null }> {
  return inviteOnRelay(team.profile, platformOf(team));
}

// A certificate close to its end is swapped for a fresh one; a failure leaves the old one to try again.
export async function renewIfDue(team: Team, now = Date.now()): Promise<Team> {
  if (!renewalDue(team.profile.certificate, now)) {
    return team;
  }
  const profile = { ...team.profile, certificate: await renewCertificate(team.profile, platformOf(team)) };
  await saveProfile(profile);
  return { ...team, profile };
}

// Leaving takes this browser out of the team on the relay too, then forgets the team here.
export async function leaveTeam(team: Team): Promise<void> {
  await leaveTeamOnRelay(team.profile, platformOf(team));
  await saveProfile(null);
}

export function forgetTeam(): Promise<void> {
  return saveProfile(null);
}
