import { useEffect, useReducer, useRef, useState } from "react";
import {
  absorb,
  CommandRejected,
  emptyFeed,
  Projection,
  SessionClient,
  withNotice,
  type Command,
  type ConnectionStatus,
  type Feed,
  type JoinLink,
  type Tone,
} from "@plural/client";
import { forgetRoom, rememberRoom } from "./saved";

const CLIENT = { kind: "web", version: "0.2.0" };

export interface Invite {
  link: string;
  role: string;
  expiresAt: string;
}

export interface SessionHandle {
  projection: Projection;
  feed: Feed;
  connection: ConnectionStatus;
  invite: Invite | null;
  clearInvite: () => void;
  send: (command: Command) => void;
  notify: (tone: Tone, text: string) => void;
  close: () => void;
}

export function useSession(link: JoinLink, name: string, onFatal: (reason: string) => void): SessionHandle {
  const token = useRef(link.token);
  const client = useRef<SessionClient | null>(null);
  const [projection, setProjection] = useState(() => new Projection());
  const [feed, setFeed] = useState<Feed>(emptyFeed);
  const feedRef = useRef<Feed>(feed);
  const [connection, setConnection] = useState<ConnectionStatus>("connecting");
  const [invite, setInvite] = useState<Invite | null>(null);
  const [, bump] = useReducer((value: number) => value + 1, 0);

  const commit = (next: Feed): void => {
    feedRef.current = next;
    setFeed(next);
  };
  const notify = (tone: Tone, text: string): void => commit(withNotice(feedRef.current, tone, text));

  useEffect(() => {
    const current = new SessionClient(
      { ...link, token: token.current, invite: token.current === null ? link.invite : null },
      { name, client: CLIENT },
    );
    client.current = current;
    setProjection(current.projection);
    commit(emptyFeed());
    const off = current.onStatus(setConnection);
    let alive = true;
    (async () => {
      try {
        for await (const event of current.events()) {
          if (!alive) {
            return;
          }
          if (event.type === "session.welcome") {
            token.current = event.token;
            rememberRoom(link, event.token, name);
          }
          if (event.type === "invite.created") {
            setInvite({ link: event.link, role: event.role, expiresAt: event.expires_at });
          }
          commit(
            event.type === "skills.found"
              ? withNotice(
                  feedRef.current,
                  "accent",
                  event.hits.length === 0
                    ? `skills.sh has nothing for "${event.query}"`
                    : [`skills.sh results for "${event.query}"`, ...event.hits.map((hit) => `  ${hit.package}  ${hit.installs} installs`), "add one with /skills add <package> [--global]"].join("\n"),
                )
              : absorb(feedRef.current, event, current.projection),
          );
          bump();
        }
      } catch (error) {
        if (!alive) {
          return;
        }
        if (error instanceof CommandRejected) {
          if (error.error.code === "unauthorized" || error.error.code === "forbidden") {
            forgetRoom(link.room);
          }
          onFatal(describe(error));
        } else {
          onFatal(error instanceof Error ? error.message : String(error));
        }
      }
    })();
    return () => {
      alive = false;
      off();
      current.close();
    };
  }, []);

  const send = (command: Command): void => {
    const current = client.current;
    if (current === null) {
      notify("warn", "not connected yet");
      return;
    }
    current.send(command).catch((error: unknown) => {
      notify("danger", error instanceof CommandRejected ? error.error.message : error instanceof Error ? error.message : String(error));
    });
  };

  return {
    projection,
    feed,
    connection,
    invite,
    clearInvite: () => setInvite(null),
    send,
    notify,
    close: () => client.current?.close(),
  };
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
