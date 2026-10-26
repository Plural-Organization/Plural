import type { ScrollBoxRenderable } from "@opentui/core";
import { useKeyboard, useRenderer, useSelectionHandler, useTerminalDimensions } from "@opentui/react";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
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
import { cycleTheme, settingsRows, SettingsDialog, type RowId } from "./components/SettingsDialog";
import { Sidebar, SIDEBAR_WIDTH } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { absorb, emptyFeed, lastReply, withBanner, withNotice, type Feed, type Tone } from "./feed";
import { copyToClipboard } from "./lib/clipboard";
import { createSyntaxStyle } from "./syntax";
import { DEFAULT_SETTINGS, type Settings } from "./settings";
import { setTheme, theme } from "./theme";

export interface AppProps {
  client: Session;
  room: string;
  version: string;
  guestLink: string | null;
  settings?: Settings;
  onSettings?: (settings: Settings) => void;
  onQuit: () => void;
}

type Focus = "composer" | "inbox";

const GUARD_MS = 400;
const MIN_WIDTH_FOR_PANEL = 90;
const TYPING_REFRESH_MS = 3000;
const TYPING_IDLE_MS = 2500;

export function App({ client, room, version, guestLink, settings: initialSettings, onSettings, onQuit }: AppProps) {
  const renderer = useRenderer();
  const [settings, setSettings] = useState<Settings>(initialSettings ?? DEFAULT_SETTINGS);
  setTheme(settings.theme);
  const syntax = useMemo(() => createSyntaxStyle(renderer), [renderer, settings.theme]);
  const [dialog, setDialog] = useState(false);
  const [row, setRow] = useState(0);
  const rowRef = useRef(0);
  const selectRow = (index: number): void => {
    rowRef.current = index;
    setRow(index);
  };
  const { width, height } = useTerminalDimensions();
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
  const [, bump] = useReducer((value: number) => value + 1, 0);
  const scroll = useRef<ScrollBoxRenderable>(null);
  const armed = useRef(false);
  const dirty = useRef(false);
  const guardUntil = useRef(0);
  const copying = useRef<ReturnType<typeof setTimeout> | null>(null);
  const typingOn = useRef(false);
  const typingSent = useRef(0);
  const typingIdle = useRef<ReturnType<typeof setTimeout> | null>(null);

  const change = (next: Settings): void => {
    setSettings(next);
    onSettings?.(next);
  };
  const commit = (next: Feed): void => {
    feedRef.current = next;
    setFeed(next);
  };
  const notify = (tone: Tone, text: string): void => commit(withNotice(feedRef.current, tone, text));
  const copy = (text: string, done: string): void => {
    void copyToClipboard(text, (value) => renderer.copyToClipboardOSC52(value)).then(() => flash(done));
  };

  useEffect(() => {
    const off = client.onStatus(setConnection);
    (async () => {
      try {
        for await (const event of client.events()) {
          commit(absorb(feedRef.current, event, client.projection));
          bump();
          if (event.type === "invite.created") {
            copy(event.link, "invite link copied to the clipboard");
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
  const typers = [...projection.typing]
    .filter((id) => id !== projection.meId)
    .map((id) => state.participants[id])
    .filter((participant): participant is NonNullable<typeof participant> => participant !== undefined)
    .map((participant) => label(state, participant));
  const runStatus = feed.items.some((item) => item.kind === "assistant" && item.streaming) ? "… writing" : status(projection);

  useEffect(() => {
    if (items.length === 0) {
      setFocus("composer");
      setSelected(0);
    } else if (approvals > 0 && !dirty.current) {
      guardUntil.current = Date.now() + GUARD_MS;
      setFocus("inbox");
    }
  }, [items.length, approvals]);

  const seenInbox = useRef(0);
  useEffect(() => {
    if (settings.bell && isHost && items.length > seenInbox.current) {
      process.stdout.write("\u0007");
    }
    seenInbox.current = items.length;
  }, [items.length]);

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

  const canType = me !== undefined && me.role !== "viewer" && settings.announceTyping;

  const stopTyping = (): void => {
    if (typingIdle.current) {
      clearTimeout(typingIdle.current);
      typingIdle.current = null;
    }
    if (typingOn.current) {
      typingOn.current = false;
      send({ type: "presence.typing", typing: false });
    }
  };

  const announceTyping = (text: string): void => {
    if (!canType) {
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

  const flash = (text: string): void => {
    setHint(text);
    setTimeout(() => setHint((current) => (current === text ? null : current)), 2000);
  };

  const interrupt = (): void => {
    if (armed.current) {
      onQuit();
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
    copy(text, "copied the last reply");
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
      case "settings":
        setDialog(true);
        return true;
      case "copy":
        copyReply();
        return true;
      case "cancel": {
        const entry = state.queue[Number(rest[0]) - 1];
        if (!entry) {
          notify("warn", state.queue.length === 0 ? "the queue is empty" : "usage: /cancel <number from the queue>");
        } else {
          send({ type: "queue.cancel", prompt_id: entry.prompt_id });
        }
        return true;
      }
      case "quit":
        onQuit();
        return true;
      default:
        return false;
    }
  };

  const submit = (text: string): void => {
    stopTyping();
    scroll.current?.scrollTo(Number.MAX_SAFE_INTEGER);
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

  const rows = settingsRows(settings, state.prompt_mode, me?.role);

  const apply = (index: number, direction: 1 | -1): void => {
    const target = rows[index];
    if (!target || !target.enabled) {
      return;
    }
    const id: RowId = target.id;
    switch (id) {
      case "theme":
        change({ ...settings, theme: cycleTheme(settings.theme, direction) });
        break;
      case "prompts":
        send({ type: "session.set_prompt_mode", mode: state.prompt_mode === "open" ? "review" : "open" });
        break;
      case "panel":
        change({ ...settings, panel: !settings.panel });
        break;
      case "copy":
        change({ ...settings, copyOnSelect: !settings.copyOnSelect });
        break;
      case "bell":
        change({ ...settings, bell: !settings.bell });
        break;
      case "typing":
        if (settings.announceTyping) {
          stopTyping();
        }
        change({ ...settings, announceTyping: !settings.announceTyping });
        break;
      case "invite":
        send({ type: "invite.create", role: "participant", ttl_s: 3600 });
        break;
      case "reply":
        copyReply();
        break;
    }
  };

  useKeyboard((key) => {
    if (key.name === "f2" || (dialog && key.name === "q")) {
      key.preventDefault();
      setDialog((open) => !open);
      return;
    }
    if (dialog) {
      key.preventDefault();
      if (key.name === "escape") {
        setDialog(false);
      } else if (key.name === "up") {
        selectRow((rowRef.current + rows.length - 1) % rows.length);
      } else if (key.name === "down") {
        selectRow((rowRef.current + 1) % rows.length);
      } else if (key.name === "left") {
        apply(rowRef.current, -1);
      } else if (key.name === "right" || key.name === "return" || key.name === "space") {
        apply(rowRef.current, 1);
      }
      return;
    }
    if (key.ctrl && key.name === "b") {
      key.preventDefault();
      change({ ...settings, panel: !settings.panel });
      return;
    }
    if (key.name === "pageup" || key.name === "pagedown") {
      key.preventDefault();
      scroll.current?.scrollBy((key.name === "pageup" ? -1 : 1) * Math.max(3, height - 8));
      return;
    }
    if (focus !== "inbox" || !isHost || Date.now() < guardUntil.current) {
      return;
    }
    const item = items[Math.min(selected, items.length - 1)];
    key.preventDefault();
    if (key.name === "tab" || key.name === "escape") {
      setFocus("composer");
    } else if (key.name === "up" || key.name === "k") {
      setSelected((value) => Math.max(0, value - 1));
    } else if (key.name === "down" || key.name === "j") {
      setSelected((value) => Math.min(items.length - 1, value + 1));
    } else if (item?.kind === "approval") {
      const decisions: Record<string, "once" | "always" | "reject" | "block"> = { y: "once", a: "always", n: "reject", b: "block" };
      const decision = key.name === "return" ? "once" : decisions[key.name];
      if (decision) {
        send({ type: "approval.respond", approval_id: item.id, decision });
      }
    } else if (item?.kind === "proposal") {
      if (key.name === "return" || key.name === "y") {
        send({ type: "proposal.decide", proposal_id: item.id, decision: "approve" });
      } else if (key.name === "n" || key.name === "x") {
        send({ type: "proposal.decide", proposal_id: item.id, decision: "reject" });
      } else if (key.name === "e") {
        setEditing(item.id);
        setSeed({ text: item.proposal.text, key: Date.now() });
        setFocus("composer");
      }
    }
  });

  useSelectionHandler((selection) => {
    const text = selection.getSelectedText();
    if (!text || !settings.copyOnSelect) {
      return;
    }
    if (copying.current) {
      clearTimeout(copying.current);
    }
    copying.current = setTimeout(() => copy(text, `copied ${text.length} characters`), 250);
  });

  const placeholder =
    me?.role === "participant" && state.prompt_mode === "review"
      ? "Propose a prompt, the host approves it"
      : "Message the agent, / for commands";
  const disabled = me?.role === "viewer" ? "viewers can only watch the session" : null;
  const showPanel = settings.panel && width >= MIN_WIDTH_FOR_PANEL;

  return (
    <box flexDirection="row" width={width} height={height} backgroundColor={theme.bg}>
      <box flexDirection="column" flexGrow={1} minWidth={0}>
        <TopBar room={room} state={state} onSettings={() => setDialog(true)} />
        <scrollbox
          ref={scroll}
          stickyScroll
          stickyStart="bottom"
          flexGrow={1}
          paddingX={2}
          paddingTop={1}
          scrollbarOptions={{ showArrows: false, trackOptions: { foregroundColor: theme.line, backgroundColor: theme.bg } }}
        >
          {feed.items.map((item) => (
            <FeedItemView key={`${item.id}:${settings.theme}`} item={item} syntax={syntax} />
          ))}
        </scrollbox>
        {items.length > 0 ? <Inbox items={items} state={state} selected={selected} focused={focus === "inbox"} now={now} /> : null}
        {typers.length > 0 ? (
          <box paddingX={2} height={1} flexShrink={0}>
            <text fg={theme.dim}>
              <span fg={theme.accent}>✎ </span>
              {typers.length <= 2 ? `${typers.join(" and ")} ${typers.length === 1 ? "is" : "are"} typing…` : `${typers.length} people are typing…`}
            </text>
          </box>
        ) : null}
        <Composer
          focused={focus === "composer" && !dialog}
          disabled={disabled}
          placeholder={placeholder}
          role={me?.role}
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
          onInterrupt={interrupt}
          onCopy={copyReply}
          onDirty={(value) => {
            dirty.current = value;
          }}
          onActivity={announceTyping}
        />
        <StatusBar me={me} state={state} connection={connection} inbox={items.length} focused={focus === "inbox"} hint={hint} />
      </box>
      {dialog ? (
        <SettingsDialog
          rows={rows}
          selected={row}
          width={width}
          height={height}
          agent={projection.agent}
          room={room}
          onSelect={selectRow}
          onChange={apply}
          onClose={() => setDialog(false)}
        />
      ) : null}
      {showPanel ? <Sidebar projection={projection} room={room} inbox={items} running={running} status={runStatus} onSettings={() => setDialog(true)} /> : null}
    </box>
  );
}

export { SIDEBAR_WIDTH };
