import { findPerson, mentionable } from "./chat";
import type { Tone } from "./feed";
import type { Projection } from "./projection";
import type { Command } from "./protocol";
import type { Surface } from "./commands";

export type LocalAction = "briefings" | "access-requests" | "brief-give";

export type LocalEffect =
  | { kind: "send"; command: Command }
  | { kind: "notify"; tone: Tone; text: string; topic: string }
  | { kind: "ui"; action: LocalAction };

const send = (command: Command): LocalEffect => ({ kind: "send", command });
const notify = (topic: string, tone: Tone, text: string): LocalEffect => ({ kind: "notify", tone, text, topic });
const ui = (action: LocalAction): LocalEffect => ({ kind: "ui", action });

type Seen = Pick<Projection, "state" | "meId" | "me">;

const SHARING = ["off", "ask", "team"] as const;

/**
 * What a command that changes the session does, the same in every client. `null` means the command is not
 * one of these (a client's own commands, or one that only shows something), so the caller goes on.
 */
export function localCommand(surface: Surface, text: string, seen: Seen): LocalEffect[] | null {
  const [name = "", ...rest] = text.slice(1).split(/\s+/);
  const isHost = seen.me?.role === "host";
  const state = seen.state;
  switch (name) {
    case "invite":
      return invite(rest[0]);
    case "cancel": {
      const entry = state.queue[Number(rest[0]) - 1];
      if (entry === undefined) {
        return [notify("cancel", "warn", state.queue.length === 0 ? "the queue is empty" : "usage: /cancel <number from the queue>")];
      }
      return [send({ type: "queue.cancel", prompt_id: entry.prompt_id })];
    }
    case "kick": {
      const person = findPerson(rest.join(" "), mentionable(state, seen.meId));
      if (person === null) {
        return [notify("kick", "warn", "usage: /kick <name> (see /who)")];
      }
      return [send({ type: "participant.revoke", participant_id: person.id }), notify("kick", "dim", `${person.label} was removed from the session`)];
    }
    case "access":
      return access(rest, seen, isHost);
    case "brief":
      return brief(surface, rest, seen, isHost);
    default:
      return null;
  }
}

function invite(kind: string | undefined): LocalEffect[] {
  switch (kind) {
    case undefined:
    case "link":
      return [send({ type: "invite.create", role: "participant", ttl_s: 3600, reusable: true })];
    case "once":
      return [send({ type: "invite.create", role: "participant", ttl_s: 3600 })];
    case "viewer":
      return [send({ type: "invite.create", role: "viewer", ttl_s: 3600 })];
    case "revoke":
      return [send({ type: "link.revoke" })];
    case "open":
    case "approve":
      return [
        send({ type: "link.set_admission", mode: kind }),
        notify("invite", "accent", kind === "open" ? "the room link lets people in at once" : "you will be asked to let each person in"),
      ];
    default:
      return [notify("invite", "warn", "usage: /invite [link | once | viewer | revoke | open | approve]")];
  }
}

function access(rest: string[], seen: Seen, isHost: boolean): LocalEffect[] {
  const [verb, ...names] = rest;
  if (seen.me?.role === "viewer") {
    return [send({ type: "access.request", note: rest.join(" ").trim() || null })];
  }
  if (!isHost) {
    return [notify("access", "warn", "you can already write")];
  }
  if (verb === undefined) {
    return [ui("access-requests")];
  }
  const person = findPerson(names.join(" "), mentionable(seen.state, seen.meId));
  if (person === null || !["allow", "deny", "revoke"].includes(verb)) {
    return [notify("access", "warn", "usage: /access [allow|deny|revoke <name>]")];
  }
  if (verb === "revoke") {
    return [send({ type: "participant.set_role", participant_id: person.id, role: "viewer" })];
  }
  return [send({ type: "access.decide", participant_id: person.id, decision: verb as "allow" | "deny" })];
}

function brief(surface: Surface, rest: string[], seen: Seen, isHost: boolean): LocalEffect[] {
  const [verb, ...more] = rest;
  if (isHost) {
    const mode = SHARING.find((candidate) => candidate === more[0]);
    return verb === "share" && mode !== undefined ? [send({ type: "session.set_briefing_sharing", mode })] : [ui("briefings")];
  }
  if (surface === "browser") {
    return [notify("brief", "warn", "ask for a briefing from the terminal client, plural join @name, then /brief")];
  }
  if (verb === "give") {
    return [ui("brief-give")];
  }
  const update = verb === "update";
  const focus = (update ? more : rest).join(" ").trim();
  return [send({ type: "briefing.request", focus: focus === "" ? null : focus, update })];
}
