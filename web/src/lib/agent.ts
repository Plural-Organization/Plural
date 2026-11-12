import { ask } from "./daemon";

// The agent a computer runs, as the Plural program on it reports it (`GET /v1/agent`). The page keeps
// no list of providers: this is the list.

export interface AgentChoice {
  preset: string;
  model: string;
  baseUrl: string;
  contextWindow: string;
  fastModel: string;
}

export type ReadinessState = "ready" | "needs_key" | "needs_install" | "needs_sdk" | "needs_sign_in" | "needs_server";

export interface Readiness {
  state: ReadinessState;
  detail: string;
  /** What to run in a terminal to fix it. */
  command: string | null;
}

export interface KeyFacts {
  set: boolean;
  source: "saved" | "environment" | null;
  /** Only for a saved key long enough to show its end safely. */
  last4: string | null;
}

export interface Provider {
  id: string;
  label: string;
  provider: string;
  baseUrl: string;
  needsKey: boolean;
  editableUrl: boolean;
  contextWindow: boolean;
  models: string[];
  hint: string;
  connection: "api_key" | "oauth" | "local";
  keyEnv: string[];
  extra: string | null;
  tool: "claude" | "codex" | null;
  readiness: Readiness;
  key: KeyFacts;
  saved: AgentChoice | null;
}

export interface LocalServer {
  name: string;
  preset: string;
  baseUrl: string;
  models: string[];
}

export interface AgentCatalog {
  presets: Provider[];
  current: AgentChoice;
  local: LocalServer[];
}

export type Tool = "claude" | "codex";

export function agentCatalog(): Promise<AgentCatalog> {
  return ask<AgentCatalog>("/v1/agent");
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

// Makes a complete choice this computer's agent.
export function saveAgent(agent: AgentChoice): Promise<void> {
  return ask<void>("/v1/agent", json("PUT", { agent }));
}

// The key goes to the program on this computer and is never sent back.
export function saveKey(preset: string, key: string): Promise<void> {
  return ask<void>("/v1/agent/key", json("PUT", { preset, key }));
}

export function forgetKey(preset: string): Promise<void> {
  return ask<void>(`/v1/agent/key/${encodeURIComponent(preset)}`, { method: "DELETE" });
}

export function testAgent(choice: AgentChoice, key?: string): Promise<{ message: string }> {
  return ask<{ message: string }>("/v1/agent/test", json("POST", { choice, ...(key === undefined || key === "" ? {} : { key }) }));
}

export function installTool(tool: Tool): Promise<void> {
  return ask<void>("/v1/agent/install", json("POST", { tool }));
}

export function installExtra(extra: string): Promise<void> {
  return ask<void>("/v1/agent/install", json("POST", { extra }));
}

// Opens a terminal on that computer running the CLI's own sign-in.
export function signIn(tool: Tool): Promise<{ command: string }> {
  return ask<{ command: string }>("/v1/agent/sign-in", json("POST", { tool }));
}

// Switches a room the program on this computer is running.
export function setRoomAgent(room: string, agent: AgentChoice): Promise<{ agent: string }> {
  return ask<{ agent: string }>(`/v1/rooms/${encodeURIComponent(room)}/agent`, json("PUT", { agent }));
}

export function runningRooms(): Promise<{ rooms: { room: string; agent: string }[] }> {
  return ask<{ rooms: { room: string; agent: string }[] }>("/v1/rooms");
}
