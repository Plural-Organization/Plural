import { useEffect, useMemo, useRef, useState } from "react";
import {
  label,
  lastReply,
  parseSlash,
  ruleLine,
  SlashError,
  status,
  type JoinLink,
  type ProposalView,
} from "@plural/client";
import { Composer, COMMANDS, helpText } from "./Composer";
import { FeedItemView } from "./FeedView";
import { Inbox, inboxItems } from "./Inbox";
import { InviteDialog } from "./InviteDialog";
import { Logo } from "./Logo";
import { Sidebar } from "./Sidebar";
import { copyText } from "./clipboard";
import { useSession } from "./useSession";

const TYPING_REFRESH_MS = 3000;
const TYPING_IDLE_MS = 2500;
const DECISIONS = { y: "once", a: "always", n: "reject", b: "block" } as const;

interface RoomProps {
  link: JoinLink;
  name: string;
  onLeave: (reason: string | null) => void;
}

export function Room({ link, name, onLeave }: RoomProps) {
  const session = useSession(link, name, (reason) => onLeave(reason));
  const { projection, feed, connection, invite, send, notify } = session;
  const state = projection.state;
  const me = projection.me;
  const isHost = me?.role === "host";
  const items = useMemo(() => (isHost ? inboxItems(state) : []), [isHost, state.approvals, state.proposals]);
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const [editing, setEditing] = useState<ProposalView | null>(null);
  const [panel, setPanel] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const [behind, setBehind] = useState(false);
  const typingOn = useRef(false);
  const typingSent = useRef(0);
  const typingIdle = useRef<ReturnType<typeof setTimeout> | null>(null);

  const writing = feed.items.some((item) => item.kind === "assistant" && item.streaming);
  const runStatus = writing ? "writing…" : status(projection).replace(/^… /, "");
  const typers = [...projection.typing]
    .filter((id) => id !== projection.meId)
    .map((id) => state.participants[id])
    .filter((person): person is NonNullable<typeof person> => person !== undefined)
    .map((person) => label(state, person));

  useEffect(
    () => () => {
      if (typingIdle.current) {
        clearTimeout(typingIdle.current);
      }
    },
    [],
  );

  useEffect(() => {
    const element = scroller.current;
    if (element && pinned.current) {
      element.scrollTop = element.scrollHeight;
    }
  }, [feed, items.length]);

  const flash = (text: string) => {
    setToast(text);
    setTimeout(() => setToast((current) => (current === text ? null : current)), 2000);
  };

  const stopTyping = () => {
    if (typingIdle.current) {
      clearTimeout(typingIdle.current);
      typingIdle.current = null;
    }
    if (typingOn.current) {
      typingOn.current = false;
      send({ type: "presence.typing", typing: false });
    }
  };

  const announceTyping = (text: string) => {
    if (me === undefined || me.role === "viewer") {
      return;
    }
    if (text.trim() === "" || text.startsWith("/")) {
      stopTyping();
      return;
    }
    const now = Date.now();
    if (!typingOn.current || now - typingSent.current > TYPING_REFRESH_MS) {
      typingOn.current = true;
      typingSent.current = now;
      send({ type: "presence.typing", typing: true });
    }
    if (typingIdle.current) {
      clearTimeout(typingIdle.current);
    }
    typingIdle.current = setTimeout(stopTyping, TYPING_IDLE_MS);
  };

  const leave = () => {
    session.close();
    onLeave(null);
  };

  const local = (text: string): boolean => {
    const [command = "", ...rest] = text.slice(1).split(/\s+/);
    switch (command) {
      case "help":
        notify("accent", helpText(me?.role));
        return true;
      case "who":
        notify(
          "accent",
          Object.values(state.participants)
            .map((person) => `${person.connected ? "●" : "○"} ${label(state, person)} (${person.role})`)
            .join("\n"),
        );
        return true;
      case "invite":
        send({ type: "invite.create", role: rest[0] === "viewer" ? "viewer" : "participant", ttl_s: 3600 });
        return true;
      case "copy": {
        const reply = lastReply(feed);
        if (reply === "") {
          flash("nothing to copy yet");
        } else {
          void copyText(reply).then((ok) => flash(ok ? "copied the last reply" : "your browser blocked the clipboard"));
        }
        return true;
      }
      case "cancel": {
        const entry = state.queue[Number(rest[0]) - 1];
        if (entry === undefined) {
          notify("warn", state.queue.length === 0 ? "the queue is empty" : "usage: /cancel <number from the queue>");
        } else {
          send({ type: "queue.cancel", prompt_id: entry.prompt_id });
        }
        return true;
      }
      case "leave":
        leave();
        return true;
      default:
        return false;
    }
  };

  const submit = (text: string) => {
    stopTyping();
    pinned.current = true;
    if (editing) {
      send({ type: "proposal.decide", proposal_id: editing.id, decision: "approve", edited_text: text });
      setEditing(null);
      return;
    }
    if (text.startsWith("/")) {
      const command = text.slice(1).split(/\s+/)[0] ?? "";
      if (COMMANDS.find((hint) => hint.name === command)?.hostOnly && !isHost) {
        notify("warn", `/${command} is for the host`);
        return;
      }
      if (local(text)) {
        return;
      }
      try {
        const parsed = parseSlash(text);
        if (parsed === null) {
          return;
        }
        if (parsed.type === "show.policy") {
          const rules = state.policy.length > 0 ? state.policy.map((rule) => `${ruleLine(rule)}  [${rule.id}]`) : ["no session rules"];
          notify("accent", [`built-in rules: ${projection.basePolicy.length}`, ...rules].join("\n"));
          return;
        }
        send(parsed);
        if (parsed.type === "context.compact") {
          notify("dim", "the context will be compacted before the next prompt");
        }
      } catch (error) {
        notify("warn", error instanceof SlashError ? error.message : String(error));
      }
      return;
    }
    send({ type: "prompt.submit", text, delivery: "now" });
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      const typing = target instanceof Element && target.closest("input, textarea, select, [contenteditable]") !== null;
      if (event.key === "Escape" && !typing && isHost && state.run !== null && !editing && !invite) {
        send({ type: "run.abort" });
        return;
      }
      if (typing || event.metaKey || event.ctrlKey || event.altKey || invite) {
        return;
      }
      const item = items[0];
      if (item?.kind === "approval" && event.key in DECISIONS) {
        event.preventDefault();
        send({ type: "approval.respond", approval_id: item.id, decision: DECISIONS[event.key as keyof typeof DECISIONS] });
      } else if (item?.kind === "proposal" && (event.key === "y" || event.key === "n")) {
        event.preventDefault();
        send({ type: "proposal.decide", proposal_id: item.id, decision: event.key === "y" ? "approve" : "reject" });
      } else if (item?.kind === "proposal" && event.key === "e") {
        event.preventDefault();
        setEditing(item.proposal);
      } else if (event.key === "/" || (event.key.length === 1 && /\S/.test(event.key) && items.length === 0)) {
        document.getElementById("composer")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, isHost, state.run, editing, invite]);

  const placeholder =
    me?.role === "participant" && state.prompt_mode === "review"
      ? "Propose a prompt, the host approves it"
      : "Message the agent, / for commands";
  const ready = projection.ready;

  return (
    <div className={`room${panel ? " with-panel" : ""}`}>
      <header className="topbar">
        <div className="brand">
          <Logo size={22} />
          <span>plural</span>
        </div>
        <button
          className="room-id mono"
          type="button"
          title="Copy the room id"
          onClick={() => void copyText(link.room).then((ok) => ok && flash("room id copied"))}
        >
          {link.room}
        </button>
        <span className={`pill ${state.prompt_mode}`}>{state.prompt_mode} mode</span>
        <span className="grow" />
        <span className="agent mono">{state.agent || projection.agent}</span>
        <span className={`conn ${connection}`} title={connection}>
          <span className="dot" />
          {connection === "online" ? `${Object.values(state.participants).filter((person) => person.connected).length} in the room` : connection === "connecting" ? "connecting…" : "reconnecting…"}
        </span>
        <button className="button small ghost panel-toggle" type="button" onClick={() => setPanel((open) => !open)} aria-expanded={panel}>
          room
        </button>
        <button className="button small ghost" type="button" onClick={leave}>
          leave
        </button>
      </header>

      <main className="stage">
        <div
          className="feed"
          ref={scroller}
          onScroll={(event) => {
            const element = event.currentTarget;
            const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
            pinned.current = atBottom;
            setBehind(!atBottom);
          }}
        >
          <div className="feed-inner">
            <div className="welcome">
              <span className="mono muted">
                room {link.room} · you are {me ? `${me.name}, ${me.role}` : name}
              </span>
            </div>
            {!ready ? <div className="notice dim">{connection === "online" ? "loading the session…" : "connecting to the host…"}</div> : null}
            {feed.items.map((item) => (
              <FeedItemView
                key={item.id}
                item={item}
                expanded={opened.has(item.id)}
                onToggle={(id) =>
                  setOpened((current) => {
                    const next = new Set(current);
                    if (next.has(id)) {
                      next.delete(id);
                    } else {
                      next.add(id);
                    }
                    return next;
                  })
                }
              />
            ))}
          </div>
        </div>
        <div className="dock">
          {behind ? (
            <button
              className="jump"
              type="button"
              onClick={() => {
                pinned.current = true;
                scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
              }}
            >
              ↓ latest
            </button>
          ) : null}

          {connection === "offline" ? <div className="banner warn">The connection dropped. Reconnecting…</div> : null}
          <Inbox items={items} state={state} send={send} onEdit={(proposal) => setEditing(proposal)} />
          <div className="presence">
            {typers.length > 0 ? (
              <span>
                {typers.length <= 2 ? `${typers.join(" and ")} ${typers.length === 1 ? "is" : "are"} typing…` : `${typers.length} people are typing…`}
              </span>
            ) : state.run ? (
              <span className="running">{runStatus || "working"}</span>
            ) : null}
            {toast ? <span className="toast">{toast}</span> : null}
          </div>
          <Composer
            role={me?.role}
            placeholder={placeholder}
            disabled={me?.role === "viewer" ? "Viewers watch the session and can't prompt" : null}
            editing={editing}
            onSubmit={submit}
            onCancelEdit={() => setEditing(null)}
            onEscape={() => {
              if (isHost && state.run !== null) {
                send({ type: "run.abort" });
              }
            }}
            onActivity={announceTyping}
          />
        </div>
      </main>

      <Sidebar
        projection={projection}
        status={runStatus}
        waiting={items.length}
        send={send}
        onInvite={(role) => send({ type: "invite.create", role, ttl_s: 3600 })}
      />

      {invite ? <InviteDialog invite={invite} onClose={session.clearInvite} /> : null}
    </div>
  );
}
