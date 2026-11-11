import { createTicket } from "./accounts";
import type { AgentChoice } from "./agent";

// The Plural program on this computer, which starts rooms for this page (`plural daemon`).
export const DAEMON_URL: string = ((import.meta.env.VITE_DAEMON_URL as string | undefined) ?? "http://127.0.0.1:47831").replace(/\/+$/, "");

export interface DaemonStatus {
  version: string;
  linked: boolean;
}

export interface StartedRoom {
  room: string;
  guest_link: string;
  host_link: string;
  folder: string;
  title: string | null;
  agent: string;
}

export interface PickedFolder {
  folder: string;
  name: string;
}

export class DaemonError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly linkedEmail: string | null = null,
    readonly reason: string | null = null,
  ) {
    super(message);
  }
}

// Whether a daemon answers. A page the browser keeps from reaching it looks the same as no daemon,
// so the caller says both in one sentence.
export async function daemonStatus(base: string = DAEMON_URL): Promise<DaemonStatus | null> {
  try {
    const response = await fetch(`${base}/v1/status`);
    if (!response.ok) {
      return null;
    }
    const body = (await response.json()) as { daemon?: boolean; version?: string; linked?: boolean };
    return body.daemon === true ? { version: body.version ?? "", linked: body.linked === true } : null;
  } catch {
    return null;
  }
}

const REASONS: Record<string, string> = {
  no_ticket: "Sign in again, then retry.",
  ticket_used: "Try again.",
  not_linked: "Plural on this computer is not signed in. Run plural login.",
  no_folder_dialog: "This computer cannot show a folder dialog. Start the room from the terminal instead.",
  too_many_rooms: "Too many rooms are open on this computer. Close one first.",
  unknown_folder: "Choose the folder again.",
  bad_relay: "That relay address is not valid.",
  agent_not_ready: "That agent is not ready yet. Finish its setup first.",
};

export function daemonMessage(error: DaemonError, signedInAs: string | null = null): string {
  if (error.code === "bad_ticket") {
    // A ticket the computer cannot verify was signed by another accounts service than the one it is
    // linked to; that is not an expired sign-in and signing in again does not help.
    return error.reason === "expired" ? "Your sign-in expired. Try again." : "Plural on this computer is linked through a different Plural accounts service than this page uses. Run plural login again against the same one.";
  }
  if (error.code === "wrong_account") {
    const linked = error.linkedEmail ?? "another account";
    return signedInAs === null ? `Plural on this computer belongs to ${linked}.` : `Plural on this computer belongs to ${linked}, and you are signed in as ${signedInAs}.`;
  }
  return REASONS[error.code] ?? error.message;
}

// Every call carries its own ticket: the daemon accepts each one once.
export async function ask<T>(path: string, init: RequestInit = {}, base: string = DAEMON_URL): Promise<T> {
  const { ticket } = await createTicket();
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      ...init,
      headers: { ...(init.body === undefined ? {} : { "content-type": "application/json" }), authorization: `Bearer ${ticket}` },
    });
  } catch {
    throw new DaemonError(0, "unreachable", "Plural on this computer cannot be reached.");
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const body = (await response.json().catch(() => ({}))) as { error?: { code?: string; message?: string; linked_email?: string; reason?: string } } & Record<string, unknown>;
  if (!response.ok) {
    throw new DaemonError(response.status, body.error?.code ?? "failed", body.error?.message ?? "Something went wrong.", body.error?.linked_email ?? null, body.error?.reason ?? null);
  }
  return body as T;
}

// The person chooses in the operating system's own dialog; null when they close it.
export async function pickFolder(base?: string): Promise<PickedFolder | null> {
  const picked = await ask<{ folder: string | null; name?: string }>("/v1/folders/pick", { method: "POST" }, base);
  return picked.folder === null ? null : { folder: picked.folder, name: picked.name ?? "" };
}

export interface RoomOptions {
  /** The provider and model the person chose; the key is never sent, the daemon holds it. */
  agent?: AgentChoice;
  /** The relay to go through: empty for the Plural relay. Left out: the one this computer uses. */
  relay?: string;
}

export function startRoom(folder: string, title: string, options: RoomOptions = {}, base?: string): Promise<StartedRoom> {
  const body = { folder, title: title.trim() === "" ? null : title.trim(), ...(options.agent === undefined ? {} : { agent: options.agent }), ...(options.relay === undefined ? {} : { relay: options.relay.trim() }) };
  return ask<StartedRoom>("/v1/rooms", { method: "POST", body: JSON.stringify(body) }, base);
}

// What this computer starts rooms with when the page says nothing.
export async function roomDefaults(base?: string): Promise<{ relay: string }> {
  const found = await ask<{ relay: string | null }>("/v1/settings", {}, base);
  return { relay: found.relay ?? "" };
}

// Why an address cannot be a relay, or null. Empty means the Plural relay.
export function relayProblem(value: string): string | null {
  const text = value.trim();
  if (text === "") return null;
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return "That is not an address. Use wss://relay.example.com";
  }
  if (url.protocol !== "wss:" && url.protocol !== "ws:") return "A relay address starts with wss:// (or ws:// on a private network)";
  if (url.hostname === "" || url.username !== "" || url.password !== "") return "A relay address needs a host and no password";
  return null;
}
