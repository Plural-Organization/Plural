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
  type PluginAsked,
  type TraceFound,
  type Tone,
} from "@plural/client";
import { alertMention, alertNotice } from "../lib/alert";
import { forgetRoom, rememberRoom } from "../lib/saved";
import { teamProof, type Team } from "../lib/team";

const CLIENT = { kind: "web", version: "0.2.0" };

export interface Invite {
  link: string;
  role: string;
  expiresAt: string | null;
  reusable: boolean;
}

export interface SessionView {
  projection: Projection;
  feed: Feed;
  connection: ConnectionStatus;
  invite: Invite | null;
  // Pictures on the board, as object URLs, by attachment id.
  pictures: Record<string, string>;
  // Questions plugin commands asked this person, oldest first.
  asks: PluginAsked[];
  // The trace on screen, null while it is closed: one run's spans, and the whole session's.
  trace: Trace | null;
}

export interface Trace {
  run: TraceFound | null;
  session: TraceFound | null;
  // Asked and not answered yet: the panel is open and shows that it is loading.
  waiting: boolean;
  // What the panel opened on.
  tab: TraceTab;
}

export type TraceTab = "run" | "session";

export interface Session extends SessionView {
  send: (command: Command) => void;
  fetchPicture: (attachmentId: string) => void;
  // This participant's own address of the server the host shares, which the host hands out.
  openPreview: (previewId: string) => Promise<string>;
  // Presence that may fail quietly: a host from an older release does not know it.
  sendPresence: (command: Command) => boolean;
  notify: (tone: Tone, text: string) => void;
  clearInvite: () => void;
  openTrace: (tab?: TraceTab) => void;
  closeTrace: () => void;
  answer: (askId: string, value: string | null) => void;
  close: () => void;
}

export class SessionStore {
  private view: SessionView = { projection: new Projection(), feed: emptyFeed(), connection: "connecting", invite: null, pictures: {}, asks: [], trace: null };
  private readonly asked = new Set<string>();
  private readonly listeners = new Set<() => void>();
  private client: SessionClient | null = null;
  private token: string | null;
  private readonly previewRequests = new Map<string, { resolve: (url: string) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();

  private clearPreviewRequests(): void {
    for (const request of this.previewRequests.values()) {
      clearTimeout(request.timer);
      request.reject(new Error("preview connection closed or changed"));
    }
    this.previewRequests.clear();
  }

  constructor(
    private readonly link: JoinLink,
    private readonly name: string,
    private readonly onFatal: (reason: string) => void,
    // Given, the first join proves team membership and the host lets this person watch.
    private readonly team: Team | null = null,
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
    const team = this.team;
    const client = new SessionClient(link, { name: this.name, client: CLIENT, team: team ? (room, url) => teamProof(team, url, room) : undefined });
    this.client = client;
    this.update({ projection: client.projection, feed: emptyFeed(), connection: client.status, invite: null, asks: [] });
    const off = client.onStatus((connection) => {
      if (connection !== "online") this.clearPreviewRequests();
      this.update({ connection });
    });
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
          if (client.projection.me?.role === "host") {
            if (event.type === "participant.joined" && event.participant.id !== client.projection.meId) {
              alertNotice(`${label(client.projection.state, event.participant)} joined`);
            } else if (event.type === "join.requested" || event.type === "access.requested" || event.type === "briefing.requested" || event.type === "approval.requested" || event.type === "proposal.created") {
              alertNotice("A request needs your attention");
            }
          }
          if (event.type === "plugin.asked") {
            this.update({ asks: [...this.view.asks, event] });
            continue;
          }
          if (event.type === "trace.found") {
            // An answer opens the trace; a run's answer and the session's each keep their place.
            // An answer that comes after the panel was closed stays closed.
            const shown = this.view.trace;
            if (shown !== null) this.update({ trace: event.run_id === null ? { ...shown, session: event, waiting: false } : { ...shown, run: event, waiting: false } });
            continue;
          }
          if (event.type === "plugin.notified") {
            this.notify("accent", `/${event.command}: ${event.text}`);
            continue;
          }
          if (event.type === "preview.changed") this.clearPreviewRequests();
          if (event.type === "preview.opened") {
            const request = this.previewRequests.get(event.preview_id);
            if (request) {
              clearTimeout(request.timer);
              this.previewRequests.delete(event.preview_id);
              request.resolve(previewUrl(this.link.url, event.path));
            }
            continue;
          }
          if (event.type === "attachment.data") {
            const bytes = Uint8Array.from(atob(event.content_b64), (char) => char.charCodeAt(0));
            const url = URL.createObjectURL(new Blob([bytes], { type: event.media_type }));
            this.update({ pictures: { ...this.view.pictures, [event.attachment_id]: url } });
            continue;
          }
          if (event.type === "invite.created") {
            this.update({ invite: { link: event.link, role: event.role, expiresAt: event.expires_at, reusable: event.reusable } });
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
      this.clearPreviewRequests();
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

  private presence = true;

  readonly sendPresence = (command: Command): boolean => {
    if (this.client === null || !this.presence || this.view.connection !== "online") {
      return false;
    }
    this.client.send(command).catch((error: unknown) => {
      // Commands are checked before they leave, so "invalid" here means the host does not know the command.
      if (error instanceof CommandRejected && error.error.code === "invalid") {
        this.presence = false;
      }
    });
    return true;
  };

  // Each picture is asked for once; a failed ask may be retried after a reconnect.
  readonly fetchPicture = (attachmentId: string): void => {
    if (this.client === null || this.asked.has(attachmentId) || this.view.pictures[attachmentId] || this.view.connection !== "online") {
      return;
    }
    this.asked.add(attachmentId);
    this.client.send({ type: "attachment.fetch", attachment_id: attachmentId }).catch(() => this.asked.delete(attachmentId));
  };

  readonly openPreview = (previewId: string): Promise<string> => {
    const client = this.client;
    if (!client || this.view.connection !== "online") return Promise.reject(new Error("preview is offline"));
    this.previewRequests.get(previewId)?.reject(new Error("preview asked again"));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.previewRequests.delete(previewId);
        reject(new Error("the host did not answer about the preview"));
      }, 15000);
      this.previewRequests.set(previewId, { resolve, reject, timer });
      client.send({ type: "preview.open", preview_id: previewId }).catch((error: unknown) => {
        clearTimeout(timer);
        this.previewRequests.delete(previewId);
        reject(error instanceof Error ? error : new Error(String(error)));
      });
    });
  };

  readonly notify = (tone: Tone, text: string): void => this.update({ feed: withNotice(this.view.feed, tone, text) });

  readonly clearInvite = (): void => this.update({ invite: null });

  // The panel opens at once and fills in when the host answers.
  readonly openTrace = (tab: TraceTab = "run"): void => {
    this.update({ trace: { run: null, session: null, waiting: true, tab } });
    this.send({ type: "trace.get", run_id: null, everything: tab === "session" });
  };

  readonly closeTrace = (): void => this.update({ trace: null });

  readonly answer = (askId: string, value: string | null): void => {
    this.update({ asks: this.view.asks.filter((ask) => ask.ask_id !== askId) });
    this.client?.send({ type: "plugin.answer", ask_id: askId, value }).catch(() => undefined);
  };

  readonly close = (): void => this.client?.close();

  private update(changes: Partial<SessionView>): void {
    this.view = { ...this.view, ...changes };
    this.listeners.forEach((listener) => listener());
  }

  private fail(error: unknown): void {
    if (error instanceof CommandRejected && (error.error.code === "unauthorized" || error.error.code === "forbidden")) {
      forgetRoom(this.link.room);
    }
    this.onFatal(error instanceof CommandRejected ? describe(error, this.team !== null) : messageOf(error));
  }
}

// The host answers with a path on the relay the session runs on, next to the room's own address.
export function previewUrl(roomUrl: string, path: string): string {
  const base = new URL(roomUrl.replace(/[^/]*$/, ""));
  base.protocol = base.protocol === "wss:" ? "https:" : "http:";
  return new URL(path, base).toString();
}

export function useSession(link: JoinLink, name: string, onFatal: (reason: string) => void, team: Team | null = null): Session {
  const [store] = useState(() => new SessionStore(link, name, onFatal, team));
  const view = useSyncExternalStore(store.subscribe, store.snapshot);
  useEffect(() => store.start(), [store]);
  return { ...view, send: store.send, fetchPicture: store.fetchPicture, openPreview: store.openPreview, sendPresence: store.sendPresence, notify: store.notify, clearInvite: store.clearInvite, openTrace: store.openTrace, closeTrace: store.closeTrace, answer: store.answer, close: store.close };
}

function messageOf(error: unknown): string {
  if (error instanceof CommandRejected) {
    // An older host does not know a newer command and answers with its validation dump.
    if (error.error.code === "invalid" && error.error.message.includes("does not match any of the expected tags")) {
      return "The host runs an older Plural that does not have this yet. Run the host from a newer version.";
    }
    return error.error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

function describe(error: CommandRejected, viaTeam: boolean): string {
  // Someone joining through a team holds no invite; the host says what is really wrong.
  if (viaTeam && (error.error.code === "unauthorized" || error.error.code === "forbidden")) {
    return error.error.message;
  }
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
