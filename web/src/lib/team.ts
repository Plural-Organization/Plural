import type { TeamProof } from "@plural/client";
import { sha256 } from "./sha256";

// A team in the browser works as in the terminal (ADR 0007): this browser has its own ed25519 key, the
// team's directory on the relay signs it a member certificate, and every request and team join is
// signed with the key. The private key never leaves the browser: it is made non-extractable and kept
// in IndexedDB; the profile, which holds nothing secret, sits in localStorage.

export type SessionStatus = "idle" | "running" | "waiting";

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
  key: CryptoKeyPair;
}

export interface TeamInvite {
  code: string;
  relay: string;
}

const PROFILE_KEY = "plural.team";
const DATABASE = "plural";
const STORE = "keys";
const IDENTITY = "identity";
const TIMEOUT_MS = 8000;
// A certificate lasts 30 days; past this much of it left, the browser asks for a fresh one.
const RENEW_BEFORE_MS = 7 * 24 * 3600 * 1000;

export function base64url(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64url(text: string): Uint8Array {
  const plain = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4));
  return Uint8Array.from(plain, (char) => char.charCodeAt(0));
}

export function httpBase(relay: string): string {
  const url = new URL(relay.trim());
  const scheme = ({ "ws:": "http:", "wss:": "https:", "http:": "http:", "https:": "https:" } as Record<string, string>)[url.protocol];
  if (scheme === undefined) {
    throw new Error(`${relay} is not a relay address`);
  }
  return `${scheme}//${url.host}`;
}

export function requestMessage(method: string, path: string, bodyHash: string, timestamp: number, nonce: string): string {
  return `${method.toUpperCase()}\n${path}\n${timestamp}\n${nonce}\n${bodyHash}`;
}

export function joinMessage(url: string, room: string, timestamp: number, nonce: string): string {
  return `plural-team-join\n${url}\n${room}\n${timestamp}\n${nonce}`;
}

// What a teammate pastes: the command `plural team join <code> --relay <url>`, or this page's link
// with ?team=<code>&relay=<url>.
export function parseTeamInvite(text: string): TeamInvite | null {
  const trimmed = text.trim();
  const command = /team\s+join\s+(\S+)\s+--relay[\s=]+(\S+)/.exec(trimmed) ?? /--relay[\s=]+(\S+)\s.*?team\s+join\s+(\S+)/.exec(trimmed);
  if (command) {
    const [code, relay] = command[0].startsWith("--relay") ? [command[2]!, command[1]!] : [command[1]!, command[2]!];
    return { code, relay };
  }
  try {
    const url = new URL(trimmed);
    const code = url.searchParams.get("team");
    const relay = url.searchParams.get("relay");
    return code && relay ? { code, relay } : null;
  } catch {
    return null;
  }
}

export function teamJoinCommand(profile: TeamProfile, code: string): string {
  return `plural team join ${code} --relay ${profile.relay}`;
}

export function teamJoinLink(profile: TeamProfile, code: string, location: Pick<Location, "origin" | "pathname">): string {
  return `${location.origin}${location.pathname}?team=${encodeURIComponent(code)}&relay=${encodeURIComponent(profile.relay)}`;
}

// When the certificate was made and runs out, read from its signed claims.
export function certificateWindow(certificate: string): { issued: number; expiry: number } | null {
  try {
    const claims = JSON.parse(new TextDecoder().decode(fromBase64url(certificate.split(".")[0]!))) as { iat?: string; exp?: string };
    const issued = claims.iat ? Date.parse(claims.iat) : NaN;
    const expiry = claims.exp ? Date.parse(claims.exp) : NaN;
    return Number.isNaN(issued) || Number.isNaN(expiry) ? null : { issued, expiry };
  } catch {
    return null;
  }
}

// Due once less than a week, or less than half its life, is left; a fresh certificate is never due.
export function renewalDue(certificate: string, now: number): boolean {
  const window = certificateWindow(certificate);
  return window !== null && window.expiry - now <= Math.min(RENEW_BEFORE_MS, (window.expiry - window.issued) / 2);
}

function nonce(): string {
  return [...crypto.getRandomValues(new Uint8Array(8))].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function signText(key: CryptoKeyPair, text: string): Promise<string> {
  return base64url(new Uint8Array(await crypto.subtle.sign("Ed25519", key.privateKey, new TextEncoder().encode(text))));
}

export async function publicKey(key: CryptoKeyPair): Promise<string> {
  return base64url(new Uint8Array(await crypto.subtle.exportKey("raw", key.publicKey)));
}

export async function authorization(team: Team, method: string, path: string, body = new Uint8Array(), timestamp = Math.floor(Date.now() / 1000)): Promise<string> {
  const once = nonce();
  const signature = await signText(team.key, requestMessage(method, path, await sha256(body), timestamp, once));
  return `Plural cert=${team.profile.certificate} ts=${timestamp} nonce=${once} sig=${signature}`;
}

export async function teamProof(team: Team, url: string, room: string, timestamp = Math.floor(Date.now() / 1000)): Promise<TeamProof> {
  const once = nonce();
  return { certificate: team.profile.certificate, url, ts: timestamp, nonce: once, proof: await signText(team.key, joinMessage(url, room, timestamp, once)) };
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

export function savedProfile(): TeamProfile | null {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    const profile = raw === null ? null : (JSON.parse(raw) as TeamProfile);
    return profile && typeof profile.team_id === "string" && typeof profile.certificate === "string" ? profile : null;
  } catch {
    return null;
  }
}

function saveProfile(profile: TeamProfile | null): void {
  try {
    if (profile === null) {
      localStorage.removeItem(PROFILE_KEY);
    } else {
      localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
    }
  } catch {
    return;
  }
}

// A profile without its key is no use: the certificate names a key this browser no longer has.
export async function loadTeam(): Promise<Team | null> {
  const profile = savedProfile();
  if (profile === null) {
    return null;
  }
  const key = await savedKey();
  if (key === undefined) {
    saveProfile(null);
    throw new Error(`this browser lost its key for ${profile.team_name}; ask the owner for a new invite`);
  }
  return { profile, key };
}

async function answer<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(detail.error ?? `the relay answered ${response.status}`);
  }
  return (await response.json()) as T;
}

async function reach(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch {
    throw new Error(`could not reach the team's relay at ${new URL(url).host}`);
  }
}

async function signed<T>(team: Team, method: string, path: string): Promise<T> {
  const response = await reach(`${httpBase(team.profile.relay)}${path}`, { method, headers: { authorization: await authorization(team, method, path) } });
  return answer<T>(response);
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
  const grant = await answer<Grant>(response);
  const profile: TeamProfile = {
    relay: invite.relay,
    team_id: grant.team_id,
    team_name: grant.team_name,
    team_key: grant.team_key,
    certificate: grant.certificate,
    member: { id: grant.member.id, name: grant.member.name, role: grant.member.role },
  };
  saveProfile(profile);
  return { profile, key };
}

export async function fetchSessions(team: Team): Promise<SessionCard[]> {
  return (await signed<{ sessions: SessionCard[] }>(team, "GET", `/teams/${team.profile.team_id}/sessions`)).sessions;
}

export async function createTeamInvite(team: Team): Promise<{ code: string; expires_at: string }> {
  return signed(team, "POST", `/teams/${team.profile.team_id}/invites`);
}

// A certificate close to its end is swapped for a fresh one; a failure leaves the old one to try again.
export async function renewIfDue(team: Team, now = Date.now()): Promise<Team> {
  if (!renewalDue(team.profile.certificate, now)) {
    return team;
  }
  const { certificate } = await signed<{ certificate: string }>(team, "POST", `/teams/${team.profile.team_id}/renew`);
  const profile = { ...team.profile, certificate };
  saveProfile(profile);
  return { ...team, profile };
}

// Leaving takes this browser out of the team on the relay too, then forgets the team here.
export async function leaveTeam(team: Team): Promise<void> {
  await signed(team, "DELETE", `/teams/${team.profile.team_id}/members/${team.profile.member.id}`);
  saveProfile(null);
}

export function forgetTeam(): void {
  saveProfile(null);
}

// Where a teammate's session can be reached from this page: an https page reaches only wss.
export function reachable(card: SessionCard, protocol: string): string | null {
  const urls = card.endpoints.map((endpoint) => endpoint.url).filter((url) => url.startsWith("ws"));
  return (protocol === "https:" ? urls.find((url) => url.startsWith("wss:")) : urls[0]) ?? null;
}
