import { Box, Static, Text, useApp, useInput, useWindowSize } from "ink";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  label,
  parseSlash,
  ruleLine,
  SlashError,
  status,
  type Command,
  type ConnectionStatus,
  type Session,
} from "@plural/client";
import { COMMANDS, helpText } from "./commands";
import { FeedItemView } from "./components/Cards";
import { Composer } from "./components/Composer";
import { Inbox, inboxItems } from "./components/Inbox";
import { Live } from "./components/Live";
import { StatusBar } from "./components/StatusBar";
import { absorb, emptyFeed, lastReply, withBanner, withNotice, type Feed, type Tone } from "./feed";
import { copyToClipboard } from "./lib/clipboard";
import { theme } from "./theme";

export interface AppProps {
  client: Session;
  room: string;
  version: string;
  guestLink: string | null;
}

type Focus = "composer" | "inbox";

const GUARD_MS = 400;

export function App({ client, room, version, guestLink }: AppProps) {
  const { exit } = useApp();
  const { columns, rows } = useWindowSize();
  const initial = useMemo(() => withBanner(emptyFeed(), { kind: "banner", id: "banner", room, version, guestLink }), []);
  const [feed, setFeed] = useState<Feed>(initial);
  const feedRef = useRef(initial);
  const [connection, setConnection] = useState<ConnectionStatus>(client.status);
  const [focus, setFocus] = useState<Focus>("composer");
  const [selected, setSelected] = useState(0);
  const [seed, setSeed] = useState<{ text: string; key: number } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const armed = useRef(false);
  const dirty = useRef(false);
  const guardUntil = useRef(0);

  const commit = (next: Feed): void => {
    feedRef.current = next;
    setFeed(next);
  };
  const notify = (tone: Tone, text: string): void => commit(withNotice(feedRef.current, tone, text));
  const write = (data: string): void => {
    process.stdout.write(data);
  };

  useEffect(() => {
    const off = client.onStatus(setConnection);
    (async () => {
      try {
        for await (const event of client.events()) {
          commit(absorb(feedRef.current, event, client.projection));
          if (event.type === "invite.created") {
            void copyToClipboard(event.link, write).then(() => notify("dim", "invite link copied to the clipboard"));
          }
        }
      } catch (error) {
        notify("danger", error instanceof Error ? error.message : String(error));
      }
    })();
    return () => {
      off();
      client.close();
    };
  }, []);

  const projection = client.projection;
  const state = projection.state;
  const me = projection.me;
  const isHost = me?.role === "host";
  const items = useMemo(() => (isHost ? inboxItems(state) : []), [isHost, state.approvals, state.proposals]);
  const approvals = Object.keys(state.approvals).length;
  const running = state.run !== null;

  useEffect(() => {
    if (items.length === 0) {
      setFocus("composer");
      setSelected(0);
    } else if (approvals > 0 && !dirty.current) {
      guardUntil.current = Date.now() + GUARD_MS;
      setFocus("inbox");
    }
  }, [items.length, approvals]);

  useEffect(() => {
    if (approvals === 0) {
      return;
    }
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [approvals]);

  const send = (command: Command): void => {
    client.send(command).catch((error: unknown) => notify("danger", error instanceof Error ? error.message : String(error)));
  };

  const flash = (text: string): void => {
    setHint(text);
    setTimeout(() => setHint((current) => (current === text ? null : current)), 2000);
  };

  const interrupt = (): void => {
    if (armed.current) {
      exit();
      return;
    }
    armed.current = true;
    flash("press ctrl+c again to quit");
    setTimeout(() => {
      armed.current = false;
    }, 2000);
  };

  const copyReply = (): void => {
    const text = lastReply(feedRef.current);
    if (text === "") {
      flash("nothing to copy yet");
      return;
    }
    void copyToClipboard(text, write).then(() => flash("copied the last reply"));
  };

  const escape = (): void => {
    if (editing) {
      setEditing(null);
      setSeed({ text: "", key: Date.now() });
    } else if (isHost && running) {
      send({ type: "run.abort" });
    }
  };

  const local = (text: string): boolean => {
    const [name = "", ...rest] = text.slice(1).split(/\s+/);
    switch (name) {
      case "help":
        notify("accent", helpText(me?.role));
        return true;
      case "who": {
        const lines = Object.values(state.participants).map(
          (participant) => `${participant.connected ? "●" : "○"} ${label(state, participant)} (${participant.role})`,
        );
        notify("accent", lines.join("\n"));
        return true;
      }
      case "invite":
        send({ type: "invite.create", role: rest[0] === "viewer" ? "viewer" : "participant", ttl_s: 3600 });
        return true;
      case "copy":
        copyReply();
        return true;
      case "quit":
        exit();
        return true;
      default:
        return false;
    }
  };

  const submit = (text: string): void => {
    if (editing) {
      send({ type: "proposal.decide", proposal_id: editing, decision: "approve", edited_text: text });
      setEditing(null);
      return;
    }
    if (text.startsWith("/")) {
      const name = text.slice(1).split(/\s+/)[0] ?? "";
      const known = COMMANDS.find((command) => command.name === name);
      if (known?.hostOnly && !isHost) {
        notify("warn", `/${name} is for the host`);
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

  useInput(
    (input, key) => {
      const item = items[Math.min(selected, items.length - 1)];
      if (Date.now() < guardUntil.current) {
        return;
      }
      if (key.tab || key.escape) {
        setFocus("composer");
      } else if (key.upArrow || input === "k") {
        setSelected((value) => Math.max(0, value - 1));
      } else if (key.downArrow || input === "j") {
        setSelected((value) => Math.min(items.length - 1, value + 1));
      } else if (item?.kind === "approval") {
        const decisions: Record<string, "once" | "always" | "reject" | "block"> = { y: "once", a: "always", n: "reject", b: "block" };
        const decision = key.return ? "once" : decisions[input];
        if (decision) {
          send({ type: "approval.respond", approval_id: item.id, decision });
        }
      } else if (item?.kind === "proposal") {
        if (key.return || input === "y") {
          send({ type: "proposal.decide", proposal_id: item.id, decision: "approve" });
        } else if (input === "n" || input === "x") {
          send({ type: "proposal.decide", proposal_id: item.id, decision: "reject" });
        } else if (input === "e") {
          setEditing(item.id);
          setSeed({ text: item.proposal.text, key: Date.now() });
          setFocus("composer");
        }
      }
    },
    { isActive: focus === "inbox" && isHost },
  );

  const placeholder =
    me?.role === "participant" && state.prompt_mode === "review"
      ? "Propose a prompt, the host approves it"
      : "Message the agent, / for commands";
  const disabled = me?.role === "viewer" ? "viewers can only watch the session" : null;

  return (
    <>
      <Static items={feed.items}>{(item) => <FeedItemView key={item.id} item={item} width={columns} />}</Static>
      <Live
        feed={feed}
        status={feed.pending && feed.pending.text !== "" ? "… writing" : status(projection)}
        running={running}
        columns={columns}
        maxLines={Math.max(4, rows - 16)}
        interruptible={isHost}
      />
      {items.length > 0 ? <Inbox items={items} state={state} selected={selected} focused={focus === "inbox"} now={now} /> : null}
      <Composer
        active={focus === "composer"}
        disabled={disabled}
        placeholder={placeholder}
        role={me?.role}
        columns={columns}
        seed={seed}
        label={editing ? "editing the proposal: enter approves it, esc cancels" : null}
        onSubmit={submit}
        onEscape={escape}
        onTab={() => {
          if (items.length > 0) {
            guardUntil.current = 0;
            setFocus("inbox");
          }
        }}
        onDirty={(value) => {
          dirty.current = value;
        }}
        onInterrupt={interrupt}
        onCopy={copyReply}
      />
      <StatusBar me={me} state={state} connection={connection} inbox={items.length} focused={focus === "inbox"} hint={hint} />
      {columns < 40 ? <Text color={theme.warn}>terminal is very narrow</Text> : null}
    </>
  );
}
