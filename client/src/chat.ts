import { label } from "./presenter";
import type { CommandOf, Participant, SessionState } from "./protocol";
import { SlashError } from "./slash";

export const CHAT_USAGE = "usage: /team <message> for the room · @name <message> for one person";
export const TEAM_COMMANDS = ["team", "to-team", "chat"] as const;

export interface Mentionable {
  id: string;
  label: string;
  role: Participant["role"];
  connected: boolean;
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
  return people
    .filter((person) => person.label.toLowerCase().startsWith(query))
    .map((person) => ({ person, insert: `${value.slice(0, start)}@${person.label} ` }));
}

export function mentionNote(person: Mentionable): string {
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
  if (!text.startsWith("@")) {
    return null;
  }
  const person = matchMention(text.slice(1), people);
  if (person === null) {
    return null;
  }
  if (person.role === "viewer") {
    throw new SlashError(`${person.label} watches the session and cannot get private messages`);
  }
  const body = text.slice(1 + person.label.length).replace(/^[,:;]/, "").trim();
  if (body === "") {
    throw new SlashError(`write something after @${person.label}`);
  }
  return { command: { type: "chat.send", text: body, to: person.id, mentions: [] }, to: person };
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
  if (text.startsWith("/")) {
    const space = text.search(/\s/);
    const name = text.slice(1, space === -1 ? undefined : space);
    if ((TEAM_COMMANDS as readonly string[]).includes(name)) {
      return { kind: "room", label: "room", note: "everyone sees it, the agent does not", blocked: false };
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
  const me = meId === null ? undefined : state.participants[meId];
  const reviewed = me?.role === "participant" && state.prompt_mode === "review";
  return { kind: "agent", label: "agent", note: reviewed ? "the host approves it first" : "everyone in the room sees it", blocked: false };
}
