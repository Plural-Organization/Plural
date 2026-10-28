import { useEffect, useState, useSyncExternalStore } from "react";
import {
  absorb,
  CommandRejected,
  emptyFeed,
  label,
  mentionsMe,
  Projection,
  SessionClient,
  withNotice,
  type Command,
  type ConnectionStatus,
  type Feed,
  type JoinLink,
  type Tone,
} from "@plural/client";
import { alertMention } from "../lib/alert";
import { forgetRoom, rememberRoom } from "../lib/saved";

const CLIENT = { kind: "web", version: "0.2.0" };

export interface Invite {
  link: string;
  role: string;
  expiresAt: string;
}

export interface SessionView {
  projection: Projection;
  feed: Feed;
  connection: ConnectionStatus;
  invite: Invite | null;
}

export interface Session extends SessionView {
  send: (command: Command) => void;
  notify: (tone: Tone, text: string) => void;
  clearInvite: () => void;
  close: () => void;
}

class SessionStore {
  private view: SessionView = { projection: new Projection(), feed: emptyFeed(), connection: "connecting", invite: null };
  private readonly listeners = new Set<() => void>();
  private client: SessionClient | null = null;
  private token: string | null;

  constructor(
    private readonly link: JoinLink,
    private readonly name: string,
    private readonly onFatal: (reason: string) => void,
  ) {
    this.token = link.token;
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly snapshot = (): SessionView => this.view;

  start(): () => void {
    const link = { ...this.link, token: this.token, invite: this.token === null ? this.link.invite : null };
    const client = new SessionClient(link, { name: this.name, client: CLIENT });
    this.client = client;
    this.update({ projection: client.projection, feed: emptyFeed(), connection: client.status, invite: null });
    const off = client.onStatus((connection) => this.update({ connection }));
    let alive = true;
    void (async () => {
      try {
        for await (const event of client.events()) {
          if (!alive) {
            return;
          }
          if (event.type === "session.welcome") {
            this.token = event.token;
            rememberRoom(this.link, event.token, this.name);
          }
          if (event.type === "chat.posted" && mentionsMe(event, client.projection.meId)) {
            const author = client.projection.state.participants[event.author_id];
            alertMention(author ? label(client.projection.state, author) : "someone", event.to !== null);
          }
          if (event.type === "invite.created") {
            this.update({ invite: { link: event.link, role: event.role, expiresAt: event.expires_at } });
          }
          this.update({
            feed:
              event.type === "skills.found"
                ? withNotice(
                    this.view.feed,
                    "accent",
                    event.hits.length === 0
                      ? `skills.sh has nothing for "${event.query}"`
                      : [`skills.sh results for "${event.query}"`, ...event.hits.map((hit) => `  ${hit.package}  ${hit.installs} installs`), "add one with /skills add <package> [--global]"].join("\n"),
                  )
                : absorb(this.view.feed, event, client.projection),
          });
        }
      } catch (error) {
        if (alive) {
          this.fail(error);
        }
      }
    })();
    return () => {
      alive = false;
      off();
      client.close();
    };
  }

  readonly send = (command: Command): void => {
    if (this.client === null) {
      this.notify("warn", "not connected yet");
      return;
    }
    this.client.send(command).catch((error: unknown) => this.notify("danger", messageOf(error)));
  };

  readonly notify = (tone: Tone, text: string): void => this.update({ feed: withNotice(this.view.feed, tone, text) });

  readonly clearInvite = (): void => this.update({ invite: null });

  readonly close = (): void => this.client?.close();

  private update(changes: Partial<SessionView>): void {
    this.view = { ...this.view, ...changes };
    this.listeners.forEach((listener) => listener());
  }

  private fail(error: unknown): void {
    if (error instanceof CommandRejected && (error.error.code === "unauthorized" || error.error.code === "forbidden")) {
      forgetRoom(this.link.room);
    }
    this.onFatal(error instanceof CommandRejected ? describe(error) : messageOf(error));
  }
}

export function useSession(link: JoinLink, name: string, onFatal: (reason: string) => void): Session {
  const [store] = useState(() => new SessionStore(link, name, onFatal));
  const view = useSyncExternalStore(store.subscribe, store.snapshot);
  useEffect(() => store.start(), [store]);
  return { ...view, send: store.send, notify: store.notify, clearInvite: store.clearInvite, close: store.close };
}

function messageOf(error: unknown): string {
  if (error instanceof CommandRejected) {
    return error.error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

function describe(error: CommandRejected): string {
  switch (error.error.code) {
    case "unauthorized":
      return "This link no longer works. Invites are single-use and expire after an hour, so ask the host for a new one.";
    case "forbidden":
      return "The host removed you from this room.";
    case "version_mismatch":
      return "The host runs a different version of Plural. Update one side and try again.";
    default:
      return error.error.message;
  }
}
