import { ask } from "./daemon";

// The chat apps this computer can connect (`GET /v1/bridges`). The page keeps no list of services or of the
// fields each needs: this is the list, so a new service shows up here without a change to the page.

export type BridgeState = "off" | "starting" | "running" | "failed" | "idle";

export interface BridgeField {
  id: string;
  label: string;
  secret: boolean;
  required: boolean;
  help: string;
  placeholder: string;
}

export interface BridgeOwner {
  id: string;
  name: string;
}

export interface BridgeLinks {
  /** Opens a private chat with the bot. With `autopair` it carries the pairing code: one tap makes the person its owner. */
  open: string;
  /** Adds the bot to a group or a server. */
  invite: string;
  autopair: boolean;
}

export interface BridgeProvider {
  id: string;
  label: string;
  summary: string;
  /** What to do in the service itself before the token exists. */
  steps: string[];
  fields: BridgeField[];
  configured: boolean;
  enabled: boolean;
  state: BridgeState;
  /** How people find the bot, once it is connected. */
  identity: string;
  error: string;
  /** Saved values, except secrets, which are never sent back. */
  values: Record<string, string>;
  /** The fields that have a value, secrets included. */
  set: string[];
  owners: BridgeOwner[];
  /** The code that makes a person the owner; null once someone is. */
  pairing: string | null;
  chats: number;
  links: BridgeLinks;
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });
const path = (id: string): string => `/v1/bridges/${encodeURIComponent(id)}`;

export async function bridges(): Promise<BridgeProvider[]> {
  return (await ask<{ providers: BridgeProvider[] }>("/v1/bridges")).providers;
}

// Values go to the program on this computer. A blank secret keeps the one already saved.
export function saveBridge(id: string, values: Record<string, string>, enabled?: boolean): Promise<void> {
  return ask<void>(path(id), json("PUT", { values, ...(enabled === undefined ? {} : { enabled }) }));
}

export function removeBridge(id: string): Promise<void> {
  return ask<void>(path(id), { method: "DELETE" });
}

// Connects once with what is saved and what is typed, and says who the bot is. Nothing is saved.
export async function testBridge(id: string, values: Record<string, string>): Promise<string> {
  return (await ask<{ identity: string }>(`${path(id)}/test`, json("POST", { values }))).identity;
}

export async function renewPairing(id: string): Promise<string> {
  return (await ask<{ pairing: string }>(`${path(id)}/pairing`, { method: "POST" })).pairing;
}

export function removeOwner(id: string, person: string): Promise<void> {
  return ask<void>(`${path(id)}/owners/${encodeURIComponent(person)}`, { method: "DELETE" });
}
