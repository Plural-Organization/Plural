import {
  createTeamInvite as inviteOnRelay,
  createTeamOnRelay,
  disbandTeamOnRelay,
  fetchMembers as membersOnRelay,
  fetchSessions as sessionsOnRelay,
  handOverTeam,
  joinTeamOnRelay,
  leaveTeamOnRelay,
  myTeamsOnRelay,
  removeMemberOnRelay,
  renewCertificate,
  renewalDue,
  teamProof as proveJoin,
  type SessionCard,
  type Stamp,
  type TeamInvite,
  type TeamPlatform,
  type TeamProfile,
  type TeamProof,
  type AccountProof,
  type MemberView,
} from "@plural/client";
import { accountsEnabled, createTicket } from "./accounts";
import { sha256 } from "./sha256";

// A team in the browser works as in the terminal (ADR 0007): this browser has its own ed25519 key, the
// team's directory on the relay signs it a member certificate, and every request and team join is
// signed with the key. The private key never leaves the browser: it is made non-extractable and kept
// in IndexedDB, next to the profiles of the teams it is in.
//
// Signed in, the browser is the account's member and not only this key (ADR 0016): it proves the
// account with a ticket for "teams", and the relay gives it every team of the account.

export interface Team {
  profile: TeamProfile;
  key: CryptoKeyPair;
}

const DATABASE = "plural";
const STORE = "keys";
const IDENTITY = "identity";
// One profile per team; "team" is where the single team of older versions was kept.
const PROFILE_PREFIX = "team:";
const LEGACY_PROFILE = "team";
const CURRENT = "current-team";

// The relay a team is made on when the person does not name one.
export const TEAM_RELAY: string = ((import.meta.env.VITE_TEAM_RELAY as string | undefined) ?? "wss://relay.plrl.host").replace(/\/+$/, "");
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

const isProfile = (value: unknown): value is TeamProfile => {
  const profile = value as TeamProfile | undefined;
  return profile !== undefined && profile !== null && typeof profile.team_id === "string" && typeof profile.certificate === "string" && typeof profile.relay === "string";
};

async function storedKeys(): Promise<string[]> {
  const keys = await keyStore<IDBValidKey[]>("readonly", (store) => store.getAllKeys()).catch((): IDBValidKey[] => []);
  const names: string[] = [];
  for (const key of keys) {
    if (typeof key === "string") names.push(key);
  }
  return names;
}

async function storedProfile(key: string): Promise<TeamProfile | null> {
  const value = await keyStore<unknown>("readonly", (store) => store.get(key)).catch(() => undefined);
  return isProfile(value) ? value : null;
}

export async function saveProfile(profile: TeamProfile): Promise<void> {
  await keyStore<unknown>("readwrite", (store) => store.put(profile, PROFILE_PREFIX + profile.team_id) as IDBRequest<unknown>);
}

async function dropProfile(teamId: string): Promise<void> {
  await keyStore<unknown>("readwrite", (store) => store.delete(PROFILE_PREFIX + teamId) as IDBRequest<unknown>);
}

// The team the rail shows; null is the rooms joined by link.
export async function currentTeam(): Promise<string | null> {
  const value = await keyStore<unknown>("readonly", (store) => store.get(CURRENT)).catch(() => undefined);
  return typeof value === "string" ? value : null;
}

export async function rememberCurrent(teamId: string | null): Promise<void> {
  await keyStore<unknown>("readwrite", (store) => (teamId === null ? store.delete(CURRENT) : store.put(teamId, CURRENT)) as IDBRequest<unknown>).catch(() => undefined);
}

// Every team this browser is in, oldest version's single team moved to its own place first.
// A profile without the browser's key is no use: the certificate names a key this browser no longer has.
export async function loadTeams(): Promise<Team[]> {
  const legacy = await storedProfile(LEGACY_PROFILE);
  if (legacy !== null) {
    await saveProfile(legacy);
    await keyStore<unknown>("readwrite", (store) => store.delete(LEGACY_PROFILE) as IDBRequest<unknown>);
    if ((await currentTeam()) === null) {
      await rememberCurrent(legacy.team_id);
    }
  }
  const profiles = (await Promise.all((await storedKeys()).filter((key) => key.startsWith(PROFILE_PREFIX)).map(storedProfile))).filter(isProfile);
  if (profiles.length === 0) {
    return [];
  }
  const key = await savedKey();
  if (key === undefined) {
    await Promise.all(profiles.map((profile) => dropProfile(profile.team_id)));
    throw new Error("this browser lost its team key; sign in or ask for a new invite");
  }
  return profiles.sort((one, two) => one.team_name.localeCompare(two.team_name)).map((profile) => ({ profile, key }));
}

// The account's proof for a team directory, when the person is signed in.
async function accountProof(signedIn: boolean): Promise<AccountProof | undefined> {
  if (!signedIn || !accountsEnabled) {
    return undefined;
  }
  return { ticket: (await createTicket("teams")).ticket };
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


function browserPlatform(key: CryptoKeyPair): TeamPlatform {
  return { sign: (message) => signText(key, message), sha256, fetch: reach };
}

export function platformOf(team: Team): TeamPlatform {
  return browserPlatform(team.key);
}

export async function createTeam(relay: string, name: string, memberName: string, signedIn: boolean): Promise<{ team: Team; invite: string | null }> {
  const key = await identity();
  const made = await createTeamOnRelay(relay, browserPlatform(key), { name, memberName, key: await publicKey(key), proof: await accountProof(signedIn) });
  await saveProfile(made.profile);
  return { team: { profile: made.profile, key }, invite: made.invite };
}

// Signed in, joining also takes over a key-only member this browser already was (ADR 0016).
export async function joinTeam(invite: TeamInvite, name: string, signedIn: boolean): Promise<Team> {
  const key = await identity();
  const proof = await accountProof(signedIn);
  const profile = await joinTeamOnRelay(invite.relay, browserPlatform(key), {
    code: invite.code,
    name,
    key: await publicKey(key),
    ...(proof === undefined ? {} : { proof, claim: true }),
  });
  await saveProfile(profile);
  return { profile, key };
}

// Every team of the signed-in account on these relays, with certificates for this browser. A relay that
// cannot answer (an older one, or one without accounts) is passed over and its error kept.
export async function accountTeams(relays: readonly string[]): Promise<{ teams: Team[]; errors: string[] }> {
  const key = await identity();
  const found: Team[] = [];
  const errors: string[] = [];
  for (const relay of new Set(relays)) {
    try {
      const proof = await accountProof(true);
      if (proof === undefined) {
        break;
      }
      for (const profile of await myTeamsOnRelay(relay, browserPlatform(key), await publicKey(key), proof)) {
        await saveProfile(profile);
        found.push({ profile, key });
      }
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }
  return { teams: found, errors };
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

export function fetchMembers(team: Team): Promise<MemberView[]> {
  return membersOnRelay(team.profile, platformOf(team));
}

export function removeMember(team: Team, member: string): Promise<void> {
  return removeMemberOnRelay(team.profile, platformOf(team), member);
}

export async function handOver(team: Team, member: string): Promise<void> {
  await handOverTeam(team.profile, platformOf(team), member);
}

// Leaving takes this browser out of the team on the relay too, then forgets the team here.
export async function leaveTeam(team: Team): Promise<void> {
  await leaveTeamOnRelay(team.profile, platformOf(team));
  await dropProfile(team.profile.team_id);
}

// Owner only: the team is gone for everyone.
export async function disbandTeam(team: Team): Promise<void> {
  await disbandTeamOnRelay(team.profile, platformOf(team));
  await dropProfile(team.profile.team_id);
}

export function forgetTeam(teamId: string): Promise<void> {
  return dropProfile(teamId);
}

// Newer profiles (fresh certificates from the relay) win over what was stored, team by team, in name order.
export function mergeTeams(stored: readonly Team[], fresh: readonly Team[]): Team[] {
  const byId = new Map(stored.map((team) => [team.profile.team_id, team]));
  for (const team of fresh) byId.set(team.profile.team_id, team);
  return [...byId.values()].sort((one, two) => one.profile.team_name.localeCompare(two.profile.team_name));
}
