import { label } from "./presenter";
import type { CommandOf, Participant, SessionState } from "./protocol";
import { SlashError } from "./slash";

export const CHAT_USAGE = "usage: /team <message> for the room · @name <message> for one person";
export const TEAM_COMMANDS = ["team", "to-team", "chat"] as const;
export const MAX_CHAT_CHARS = 2000;

/** The agent's handle: in mention mode it answers only messages that tag it. */
export const AGENT_HANDLE = "plrl";

export interface Mentionable {
  id: string;
  label: string;
  role: Participant["role"];
  connected: boolean;
  /** The agent itself rather than a person. */
  agent?: boolean;
}

export const AGENT_MENTION: Mentionable = { id: "agent", label: AGENT_HANDLE, role: "participant", connected: true, agent: true };

const ROOM_NOTE = `everyone sees it, the agent reads it but answers only @${AGENT_HANDLE}`;
const AGENT_TAG = new RegExp(`(^|[\\s(])@${AGENT_HANDLE}(?=$|[\\s,:;.!?)])`, "i");

/** Whether the text tags the agent with @plrl where a word begins. */
export function mentionsAgent(text: string): boolean {
  return AGENT_TAG.test(text);
}

/** The text as a prompt the agent answers in either mode: tagged @plrl in mention mode. */
export function forAgent(text: string, state: SessionState): string {
  return inMentionMode(state) && !mentionsAgent(text) && !text.startsWith("/") ? `@${AGENT_HANDLE} ${text}` : text;
}

/** Mention mode: a plain message is chat the agent reads, and it answers only @plrl. */
export function inMentionMode(state: SessionState): boolean {
  return state.chat_mode === "mention";
}

export interface ChatIntent {
  command: CommandOf<"chat.send">;
  to: Mentionable | null;
}

const BOUNDARY = /^[\s,:;.!?)]|^$/;

export function mentionable(state: SessionState, meId: string | null): Mentionable[] {
  return Object.values(state.participants)
    .filter((participant) => participant.id !== meId)
    .map((participant) => ({
      id: participant.id,
      label: label(state, participant),
      role: participant.role,
      connected: participant.connected,
    }))
    .sort((a, b) => Number(b.connected) - Number(a.connected) || a.label.localeCompare(b.label));
}

export function findPerson(name: string, people: Mentionable[]): Mentionable | null {
  const wanted = name.trim().toLowerCase().replace(/^@/, "");
  return wanted === "" ? null : (people.find((person) => person.label.toLowerCase() === wanted) ?? null);
}

export function matchMention(rest: string, people: Mentionable[]): Mentionable | null {
  const lower = rest.toLowerCase();
  let best: Mentionable | null = null;
  for (const person of people) {
    const name = person.label.toLowerCase();
    if (lower.startsWith(name) && BOUNDARY.test(rest.slice(name.length)) && (best === null || name.length > best.label.length)) {
      best = person;
    }
  }
  return best;
}

export interface MentionCompletion {
  person: Mentionable;
  insert: string;
}

export function mentionCompletions(value: string, people: Mentionable[]): MentionCompletion[] {
  const tail = /(^|\s)@([^\s@]*)$/.exec(value);
  if (tail === null) {
    return [];
  }
  const start = tail.index + (tail[1]?.length ?? 0);
  const query = (tail[2] ?? "").toLowerCase();
  return [AGENT_MENTION, ...people]
    .filter((person) => person.label.toLowerCase().startsWith(query))
    .map((person) => ({ person, insert: `${value.slice(0, start)}@${person.label} ` }));
}

export function mentionNote(person: Mentionable): string {
  if (person.agent === true) {
    return "the agent · answers this message";
  }
  return `${person.role}${person.connected ? "" : " · offline"}${person.role === "viewer" ? " · cannot get private messages" : ""}`;
}

export function mentionsIn(text: string, people: Mentionable[]): string[] {
  const found: string[] = [];
  for (let index = text.indexOf("@"); index !== -1; index = text.indexOf("@", index + 1)) {
    if (index > 0 && !/\s|[(]/.test(text[index - 1]!)) {
      continue;
    }
    const person = matchMention(text.slice(index + 1), people);
    if (person !== null && !found.includes(person.id)) {
      found.push(person.id);
    }
  }
  return found;
}

export function parseChat(text: string, state: SessionState, meId: string | null): ChatIntent | null {
  const people = mentionable(state, meId);
  if (text.startsWith("/")) {
    const space = text.search(/\s/);
    const name = text.slice(1, space === -1 ? undefined : space);
    if (!(TEAM_COMMANDS as readonly string[]).includes(name)) {
      return null;
    }
    const body = space === -1 ? "" : text.slice(space).trim();
    if (body === "") {
      throw new SlashError(CHAT_USAGE);
    }
    return { command: { type: "chat.send", text: body, to: null, mentions: mentionsIn(body, people) }, to: null };
  }
  const person = text.startsWith("@") ? matchMention(text.slice(1), people) : null;
  if (person === null && mentionsAgent(text)) {
    return null;
  }
  if (person !== null) {
    if (person.role === "viewer") {
      throw new SlashError(`${person.label} watches the session and cannot get private messages`);
    }
    const body = text.slice(1 + person.label.length).replace(/^[,:;]/, "").trim();
    if (body === "") {
      throw new SlashError(`write something after @${person.label}`);
    }
    return { command: { type: "chat.send", text: body, to: person.id, mentions: [] }, to: person };
  }
  if (!inMentionMode(state) || text.trim() === "") {
    return null;
  }
  const body = text.trim();
  if (body.length > MAX_CHAT_CHARS) {
    throw new SlashError(`a chat message holds ${MAX_CHAT_CHARS} characters; tag @${AGENT_HANDLE} to give the agent a longer one`);
  }
  return { command: { type: "chat.send", text: body, to: null, mentions: mentionsIn(body, people) }, to: null };
}

export function mentionsMe(
  entry: { author_id: string; to: string | null; mentions: string[] },
  meId: string | null,
): boolean {
  if (meId === null || entry.author_id === meId) {
    return false;
  }
  return entry.to === meId || entry.mentions.includes(meId);
}

export interface Route {
  kind: "agent" | "room" | "person" | "command";
  label: string;
  note: string;
  blocked: boolean;
}

export function routeOf(text: string, state: SessionState, meId: string | null): Route {
  const me = meId === null ? undefined : state.participants[meId];
  const first = text.startsWith("/") ? (text.slice(1).split(/\s/)[0] ?? "") : "";
  if (me?.role === "viewer" && (!text.startsWith("/") || (TEAM_COMMANDS as readonly string[]).includes(first))) {
    return { kind: "command", label: "watching", note: "you cannot write here, /access asks the host for the right", blocked: true };
  }
  if (text.startsWith("/")) {
    const space = text.search(/\s/);
    const name = text.slice(1, space === -1 ? undefined : space);
    if ((TEAM_COMMANDS as readonly string[]).includes(name)) {
      return { kind: "room", label: "room", note: inMentionMode(state) ? ROOM_NOTE : "everyone sees it, the agent does not", blocked: false };
    }
    return { kind: "command", label: `/${name}`, note: "a command, not a prompt", blocked: false };
  }
  if (text.startsWith("@")) {
    const person = matchMention(text.slice(1), mentionable(state, meId));
    if (person !== null) {
      if (person.role === "viewer") {
        return { kind: "person", label: `@${person.label}`, note: "watches the session, cannot get private messages", blocked: true };
      }
      return {
        kind: "person",
        label: `@${person.label}`,
        note: `private, the agent does not see it${person.connected ? "" : " · offline, reads it when back"}`,
        blocked: false,
      };
    }
  }
  if (inMentionMode(state) && !mentionsAgent(text)) {
    return { kind: "room", label: "room", note: ROOM_NOTE, blocked: false };
  }
  const reviewed = me?.role === "participant" && state.prompt_mode === "review";
  return { kind: "agent", label: "agent", note: reviewed ? "the host approves it first" : "everyone in the room sees it", blocked: false };
}
