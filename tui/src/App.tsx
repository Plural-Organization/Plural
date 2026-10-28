import type { ScrollBoxRenderable } from "@opentui/core";
import { useKeyboard, useRenderer, useSelectionHandler, useTerminalDimensions } from "@opentui/react";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  label,
  nextPermissionMode,
  parseSlash,

  SlashError,
  status,
  type Command,
  type ConnectionStatus,
  type PermissionMode,
  type Session,
} from "@plural/client";
import { COMMANDS } from "./commands";
import { FeedItemView, PinnedPrompt, pinId } from "./components/Cards";
import { Composer } from "./components/Composer";
import { Inbox, inboxItems, type InboxItem } from "./components/Inbox";
import { SettingsDialog } from "./components/SettingsDialog";
import { Splash } from "./components/Splash";
import { Sidebar, SIDEBAR_WIDTH } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { SCOPES, TrayView, type Form, type McpWizard, type Row, type Tray } from "./components/Tray";
import { addCommand, MCP_CATALOG, wizardFields } from "./mcpCatalog";
import { Compacting, ModeLine, Working } from "./components/Working";
import { helpRows, policyRows, skillRows, usageRows, whoRows } from "./trays";
import { absorb, emptyFeed, lastReply, withBanner, withNotice, type Feed, type Tone } from "./feed";
import type { AgentControl } from "./control";
import type { Keys } from "./credentials";
import type { PresetId } from "./presets";
import type { Tab } from "./settingsModel";
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
  control?: AgentControl | null;
  keys?: Keys;
  onKeys?: (preset: PresetId, key: string, remember: boolean) => void;
  startupNote?: string | null;
  splash?: boolean;
  onQuit: () => void;
}

type Focus = "composer" | "inbox";

const GUARD_MS = 400;
const MIN_WIDTH_FOR_PANEL = 90;
const TYPING_REFRESH_MS = 3000;
const TYPING_IDLE_MS = 2500;
const PLAN_APPROVED = "The host approved the plan. Implement it now.";

export function App({
  client,
  room,
  version,
  guestLink,
  settings: initialSettings,
  onSettings,
  control = null,
  keys = {},
  onKeys,
  startupNote = null,
  splash = false,
  onQuit,
}: AppProps) {
  const renderer = useRenderer();
  const [settings, setSettings] = useState<Settings>(initialSettings ?? DEFAULT_SETTINGS);
  setTheme(settings.theme);
  const syntax = useMemo(() => createSyntaxStyle(renderer), [renderer, settings.theme]);
  const [dialog, setDialog] = useState(false);
  const [welcome, setWelcome] = useState(false);
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const [allOpen, setAllOpen] = useState(false);
  const toggle = (id: string): void =>
    setOpened((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
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
  const [planReady, setPlanReady] = useState(false);
  const [intro, setIntro] = useState(splash);
  const [tray, setTrayState] = useState<Tray | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const trayRef = useRef<Tray | null>(null);
  const setTray = (next: Tray | null | ((current: Tray | null) => Tray | null)): void => {
    trayRef.current = typeof next === "function" ? next(trayRef.current) : next;
    setTrayState(trayRef.current);
  };
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
          const pending = trayRef.current?.kind === "busy";
          if (!(pending && event.type === "error")) {
            commit(absorb(feedRef.current, event, client.projection));
          }
          bump();
          if (event.type === "invite.created") {
            copy(event.link, "invite link copied to the clipboard");
          }
          if (event.type === "skills.found") {
            const host = client.projection.me?.role === "host";
            setTray({ kind: "pick", title: `skills.sh · ${event.query}`, hits: [...event.hits], selected: 0, canInstall: host });
          } else if (pending && event.type === "skills.changed") {
            setTray({
              kind: "text",
              title: "skills",
              tone: "accent",
              rows: [
                ...event.added.map((name): Row => [{ text: "✓ ", fg: theme.ok }, { text: name, bold: true }, { text: " installed · the agent sees it from the next prompt", fg: theme.dim }]),
                ...event.removed.map((name): Row => [{ text: "✕ ", fg: theme.warn }, { text: name, bold: true }, { text: " removed", fg: theme.dim }]),
              ],
            });
          } else if (pending && event.type === "error") {
            setTray({ kind: "text", title: "skills", tone: "danger", rows: [[{ text: event.message, fg: theme.danger }]] });
          }
          if (event.type === "run.started" || event.type === "session.permission_mode_changed") {
            setPlanReady(false);
          }
          const { state: after, me: self } = client.projection;
          if (event.type === "run.ended" && event.reason === "stop" && after.permission_mode === "plan" && self?.role === "host") {
            setPlanReady(lastReply(feedRef.current) !== "");
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
  const mode = state.permission_mode;
  const running = state.run !== null;
  const items = useMemo(
    (): InboxItem[] => (isHost ? [...inboxItems(state), ...(planReady ? [{ kind: "plan", id: "plan" } as const] : [])] : []),
    [isHost, state.approvals, state.proposals, planReady],
  );
  const approvals = Object.keys(state.approvals).length;
  const queuedIds = useMemo(
    () => new Map(state.queue.map((entry) => [entry.prompt_id, entry.delivery === "follow_up" ? ("follow_up" as const) : ("steer" as const)])),
    [state.queue],
  );
  const typers = [...projection.typing]
    .filter((id) => id !== projection.meId)
    .map((id) => state.participants[id])
    .filter((participant): participant is NonNullable<typeof participant> => participant !== undefined)
    .map((participant) => label(state, participant));
  const runStatus = feed.items.some((item) => item.kind === "assistant" && item.streaming && item.text !== "") ? "… writing" : status(projection);

  useEffect(() => {
    if (items.length === 0) {
      setFocus("composer");
      setSelected(0);
    } else if ((approvals > 0 || planReady) && !dirty.current) {
      guardUntil.current = Date.now() + GUARD_MS;
      setFocus("inbox");
    }
  }, [items.length, approvals, planReady]);

  useEffect(() => {
    const timer = setInterval(() => {
      const box = scroll.current;
      if (!box) {
        return;
      }
      let above: string | null = null;
      for (const item of feedRef.current.items) {
        if (item.kind !== "user") {
          continue;
        }
        const card = box.findDescendantById(pinId(item.id));
        if (card && card.y + card.height <= box.y) {
          above = item.id;
        } else if (card && card.y >= box.y) {
          break;
        }
      }
      setPinned((current) => (current === above ? current : above));
    }, 100);
    return () => clearInterval(timer);
  }, []);
  const pinnedItem = pinned ? feed.items.find((item): item is Extract<typeof item, { kind: "user" }> => item.kind === "user" && item.id === pinned) : undefined;

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

  const closeSettings = (): void => {
    if (welcome) {
      change({ ...settings, setupSeen: true });
      setWelcome(false);
    }
    setDialog(false);
  };

  useEffect(() => {
    if (control && isHost && !settings.setupSeen && settings.agent.preset === "demo" && state.agent.startsWith("demo")) {
      setWelcome(true);
      setDialog(true);
    }
  }, [isHost, state.agent]);

  useEffect(() => {
    if (startupNote) {
      notify("warn", startupNote);
    }
  }, []);

  const send = (command: Command): void => {
    client.send(command).catch((error: unknown) => {
      const text = error instanceof Error ? error.message : String(error);
      if (command.type.startsWith("skills.") || command.type.startsWith("mcp.") || command.type === "context.compact") {
        show(command.type.split(".")[0] === "context" ? "compact" : command.type.split(".")[0]!, [[{ text, fg: theme.warn }]], "warn");
      } else {
        notify("danger", text);
      }
    });
  };

  const show = (title: string, rows: Row[], tone: "accent" | "warn" | "danger" = "accent"): void => setTray({ kind: "text", title, tone, rows });
  const warn = (title: string, text: string): void => show(title, [[{ text, fg: theme.warn }]], "warn");

  const install = (global: boolean): void => {
    const current = trayRef.current;
    if (current?.kind !== "pick" || !current.canInstall) {
      return;
    }
    const hit = current.hits[current.selected];
    if (!hit) {
      return;
    }
    setTray({ kind: "busy", title: "skills", text: `installing ${hit.package}${global ? " for every project" : ""}`, key: Date.now() });
    send({ type: "skills.install", package: hit.package, scope: global ? "global" : "project" });
  };

  const agentForm = (): Form => ({
    kind: "form",
    title: "create an agent",
    index: 0,
    values: {},
    selected: 0,
    warning: null,
    steps: [
      { kind: "text", key: "name", label: "Name", hint: "letters, digits, - and _, for example reviewer" },
      { kind: "text", key: "description", label: "When to use it", hint: "one line the main agent reads to decide when to call it" },
      { kind: "text", key: "prompt", label: "Instructions", hint: "what it does and what its report should look like", multiline: true },
      {
        kind: "choice",
        key: "tools",
        label: "What it may touch",
        options: [
          { value: "read, grep, glob, ls, web_search, web_fetch, skill", title: "Read only", detail: "search the code and the web; nothing asks the host" },
          { value: "read, grep, glob, ls, bash", title: "Read and run commands", detail: "also bash, for tests and builds; commands ask the host" },
          { value: "read, grep, glob, ls, edit, multi_edit, write, bash", title: "Read, edit and run", detail: "can change files; every change asks the host" },
        ],
      },
      {
        kind: "choice",
        key: "model",
        label: "Model",
        options: [
          { value: "fast", title: "Fast", detail: state.fast_agent ? `runs on ${state.fast_agent}` : "the cheaper model, or the main one when there is none" },
          { value: "main", title: "Main", detail: `runs on ${state.agent || "the main model"}` },
        ],
      },
      {
        kind: "choice",
        key: "scope",
        label: "Save for",
        options: [
          { value: "project", title: "This project", detail: ".agents/agents in the workspace · commit it to share it" },
          { value: "global", title: "Every project", detail: "~/.agents/agents on this machine" },
        ],
      },
    ],
  });

  const finishForm = (form: Form): void => {
    const values = form.values;
    send({
      type: "agents.create",
      name: values.name ?? "",
      description: values.description ?? "",
      prompt: values.prompt ?? "",
      tools: (values.tools ?? "").split(",").map((tool) => tool.trim()).filter(Boolean),
      model: values.model === "main" ? "main" : "fast",
      scope: values.scope === "global" ? "global" : "project",
    });
    setTray({ kind: "agents", selected: 0, canManage: true });
  };

  const formStep = (form: Form, typed: string | null): void => {
    const step = form.steps[form.index];
    if (!step) {
      return;
    }
    let value: string;
    if (step.kind === "choice") {
      value = step.options[form.selected]?.value ?? "";
    } else {
      value = (typed ?? "").trim();
      const taken = client.projection.state.agents.map((agent) => agent.name);
      const warning =
        !value && !step.optional
          ? `${step.label.toLowerCase()} is needed`
          : step.key === "name" && !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value)
            ? "use letters, digits, ., - and _"
            : step.key === "name" && taken.includes(value)
              ? `${value} is taken, pick another name`
              : null;
      if (warning) {
        setTray({ ...form, warning });
        return;
      }
    }
    const next = { ...form, values: { ...form.values, [step.key]: value }, index: form.index + 1, selected: 0, warning: null };
    if (next.index >= form.steps.length) {
      finishForm(next);
    } else {
      setTray(next);
    }
  };

  const advance = (wizard: McpWizard, typed: string): void => {
    const field = wizard.fields[wizard.index];
    if (!field) {
      return;
    }
    const value = typed.trim() || field.fallback || "";
    const taken = client.projection.state.mcp.map((server) => server.name);
    const warning =
      !value && !field.optional
        ? `${field.label.toLowerCase()} is needed`
        : field.key === "name" && !/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/.test(value)
          ? "use letters, digits, - and _ (up to 32)"
          : field.key === "name" && taken.includes(value)
            ? `${value} is taken, pick another name`
            : null;
    if (warning) {
      setTray({ ...wizard, warning });
      return;
    }
    const values = { ...wizard.values, [field.key]: value };
    const last = wizard.index + 1 >= wizard.fields.length;
    setTray({ ...wizard, values, warning: null, index: last ? wizard.index : wizard.index + 1, step: last ? "scope" : "field", selected: 0 });
  };

  const wizardKey = (wizard: McpWizard, name: string): boolean => {
    const count = wizard.step === "pick" ? MCP_CATALOG.length : wizard.step === "scope" ? SCOPES.length : 0;
    if ((name === "up" || name === "down") && count > 0) {
      setTray({ ...wizard, selected: (wizard.selected + (name === "up" ? -1 : 1) + count) % count });
      return true;
    }
    if (name !== "return") {
      return false;
    }
    if (wizard.step === "pick") {
      const preset = MCP_CATALOG[wizard.selected]!;
      const taken = client.projection.state.mcp.map((server) => server.name);
      setTray({ ...wizard, step: "field", preset: wizard.selected, fields: wizardFields(preset, taken), index: 0, values: {}, warning: null });
    } else if (wizard.step === "field") {
      advance(wizard, "");
    } else {
      send(addCommand(MCP_CATALOG[wizard.preset]!, wizard.values, SCOPES[wizard.selected]!.scope));
      setTray({ kind: "mcp", selected: 0, canManage: true });
    }
    return true;
  };

  const idleKey = (name: string): boolean => {
    const current = trayRef.current;
    if (current?.kind === "form") {
      const step = current.steps[current.index];
      if (step?.kind === "choice" && (name === "up" || name === "down")) {
        const count = step.options.length;
        setTray({ ...current, selected: (current.selected + (name === "up" ? -1 : 1) + count) % count });
        return true;
      }
      if (name === "return") {
        formStep(current, step?.kind === "text" ? "" : null);
        return true;
      }
      return false;
    }
    if (current?.kind === "agents") {
      const agents = client.projection.state.agents;
      const total = agents.length + (isHost ? 1 : 0);
      if (name === "up" || name === "down") {
        setTray({ ...current, selected: (current.selected + (name === "up" ? -1 : 1) + total) % total });
        return true;
      }
      if (name === "return" && isHost && current.selected === agents.length) {
        setTray(agentForm());
        return true;
      }
      return false;
    }
    if (current?.kind === "mcp-add") {
      return wizardKey(current, name);
    }
    if (current?.kind === "mcp") {
      const servers = client.projection.state.mcp;
      const total = servers.length + (isHost ? 2 : 0);
      if (total === 0) {
        return false;
      }
      if (name === "up" || name === "down") {
        const step = name === "up" ? -1 : 1;
        setTray({ ...current, selected: (current.selected + step + total) % total });
        return true;
      }
      const server = servers[current.selected];
      if (!isHost) {
        return false;
      }
      if (name === "return" && current.selected === servers.length) {
        setTray({ kind: "mcp-add", step: "pick", selected: 0, preset: 0, fields: [], index: 0, values: {}, warning: null });
        return true;
      }
      if (name === "return" && current.selected === servers.length + 1) {
        send({ type: "mcp.import" });
        return true;
      }
      if (!server) {
        return false;
      }
      if (name === "return") {
        send({ type: "mcp.toggle", name: server.name, enabled: server.status === "off" });
        return true;
      }
      if (name === "ctrl+r") {
        send({ type: "mcp.restart", name: server.name });
        return true;
      }
      return false;
    }
    if (current?.kind !== "pick" || current.hits.length === 0) {
      return false;
    }
    if (name === "up" || name === "down") {
      const step = name === "up" ? -1 : 1;
      setTray({ ...current, selected: (current.selected + step + current.hits.length) % current.hits.length });
      return true;
    }
    if (name === "return" || name === "ctrl+g") {
      install(name === "ctrl+g");
      return current.canInstall;
    }
    return false;
  };

  const setMode = (next: PermissionMode): void => {
    if (next !== mode) {
      send({ type: "session.set_permission_mode", mode: next });
    }
  };

  const cycleMode = (): void => {
    if (isHost) {
      setMode(nextPermissionMode(mode));
    }
  };

  const startPlan = (next: PermissionMode): void => {
    setPlanReady(false);
    setMode(next);
    send({ type: "prompt.submit", text: PLAN_APPROVED, delivery: "now" });
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
    if (trayRef.current) {
      setTray(null);
    } else if (editing) {
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
        show("help", helpRows(me?.role));
        return true;
      case "who":
        show(`who · ${Object.values(state.participants).filter((person) => person.connected).length} here`, whoRows(projection));
        return true;
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
          warn("cancel", state.queue.length === 0 ? "the queue is empty" : "usage: /cancel <number from the queue>");
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
    const wizard = trayRef.current;
    if (wizard?.kind === "form") {
      formStep(wizard, wizard.steps[wizard.index]?.kind === "text" ? text : null);
      return;
    }
    if (wizard?.kind === "mcp-add" && wizard.step === "field") {
      advance(wizard, text);
      return;
    }
    stopTyping();
    setTray(null);
    setPlanReady(false);
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
        warn(`/${name}`, `/${name} is for the host`);
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
        if (parsed.type === "show.skills") {
          show(`skills · ${state.skills.length}`, skillRows(projection, width - (showPanel ? SIDEBAR_WIDTH : 0) - 10));
          return;
        }
        if (parsed.type === "show.usage") {
          show("usage · this session", usageRows(projection));
          return;
        }
        if (parsed.type === "show.agents") {
          setTray({ kind: "agents", selected: 0, canManage: isHost });
          return;
        }
        if (parsed.type === "show.mcp") {
          setTray({ kind: "mcp", selected: 0, canManage: isHost });
          return;
        }
        if (parsed.type === "show.policy") {
          show("policy", policyRows(projection));
          return;
        }
        if (parsed.type === "skills.search") {
          setTray({ kind: "busy", title: "skills.sh", text: `searching for "${parsed.query}"`, key: Date.now() });
        } else if (parsed.type === "skills.install") {
          setTray({ kind: "busy", title: "skills", text: `installing ${parsed.package}${parsed.scope === "global" ? " for every project" : ""}`, key: Date.now() });
        } else if (parsed.type === "skills.remove") {
          setTray({ kind: "busy", title: "skills", text: `removing ${parsed.name}`, key: Date.now() });
        }
        send(parsed);
        if (parsed.type.startsWith("mcp.")) {
          setTray({ kind: "mcp", selected: 0, canManage: isHost });
        }
        if (parsed.type === "context.compact" && running) {
          show("compact", [[{ text: "the agent compacts the context before its next step", fg: theme.dim }]]);
        }
      } catch (error) {
        warn(text.split(/\s+/)[0] ?? "command", error instanceof SlashError ? error.message : String(error));
      }
      return;
    }
    send({ type: "prompt.submit", text, delivery: "now" });
  };

  useKeyboard((key) => {
    if (dialog || intro) {
      return;
    }
    if (key.name === "f2") {
      key.preventDefault();
      setDialog(true);
      return;
    }
    if (key.ctrl && key.name === "o") {
      key.preventDefault();
      setAllOpen((value) => !value);
      flash(allOpen ? "tool details collapsed" : "tool details expanded");
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
    } else if (item?.kind === "plan") {
      const choices: Record<string, PermissionMode> = { a: "auto", e: "accept_edits", y: "default", return: "default" };
      const choice = choices[key.name];
      if (choice) {
        startPlan(choice);
      } else if (key.name === "n") {
        setPlanReady(false);
        flash("tell the agent what to change in the plan");
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

  const formAsk = tray?.kind === "form" ? tray.steps[tray.index] : undefined;
  const asking =
    tray?.kind === "mcp-add" && tray.step === "field"
      ? tray.fields[tray.index]
      : formAsk?.kind === "text"
        ? { label: formAsk.label, hint: formAsk.hint, secret: false }
        : undefined;
  const placeholder =
    me?.role === "participant" && state.prompt_mode === "review"
      ? "Propose a prompt, the host approves it"
      : "Message the agent, / for commands";
  const disabled = me?.role === "viewer" ? "viewers can only watch the session" : null;
  const showPanel = settings.panel && width >= MIN_WIDTH_FOR_PANEL;

  if (intro) {
    return (
      <Splash
        width={width}
        height={height}
        version={version}
        ready={connection === "online" && me !== undefined}
        status={connection === "online" ? "joining the session…" : connection === "connecting" ? "connecting to the session…" : "reconnecting…"}
        onDone={() => setIntro(false)}
        onQuit={onQuit}
      />
    );
  }

  return (
    <box flexDirection="row" width={width} height={height} backgroundColor={theme.bg}>
      <box flexDirection="column" flexGrow={1} minWidth={0}>
        <TopBar room={room} state={state} onSettings={() => setDialog(true)} />
        {pinnedItem ? (
          <PinnedPrompt
            item={pinnedItem}
            width={width - (showPanel ? SIDEBAR_WIDTH : 0) - 4}
            onJump={() => {
              const box = scroll.current;
              const card = box?.findDescendantById(pinId(pinnedItem.id));
              if (box && card) {
                box.scrollBy(card.y - box.y - 1);
              }
            }}
          />
        ) : null}
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
            <FeedItemView
              key={`${item.id}:${settings.theme}`}
              item={item}
              syntax={syntax}
              width={width - (showPanel ? SIDEBAR_WIDTH : 0) - 8}
              expanded={allOpen || opened.has(item.id)}
              queued={queuedIds.get(item.id) ?? null}
              onToggle={toggle}
            />
          ))}
        </scrollbox>
        {items.length > 0 ? <Inbox items={items} state={state} selected={selected} focused={focus === "inbox"} now={now} /> : null}
        {projection.compacting ? (
          <Compacting tokens={projection.compacting.tokens} />
        ) : running ? (
          <Working status={runStatus} canAbort={isHost} queued={state.queue.length} />
        ) : null}
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
          placeholder={asking ? `${asking.label}${asking.hint ? ` · ${asking.hint}` : ""}` : placeholder}
          remember={!asking?.secret}
          tips={!asking}
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
          onCycleMode={cycleMode}
          onInterrupt={interrupt}
          onCopy={copyReply}
          onDirty={(value) => {
            dirty.current = value;
          }}
          onActivity={announceTyping}
          onFocus={() => setFocus("composer")}
          onIdleKey={idleKey}
        />
        {tray ? (
          <TrayView
            tray={tray}
            servers={state.mcp}
            agents={state.agents}
            maxRows={Math.max(4, Math.floor(height * 0.55))}
            onClose={() => setTray(null)}
            onSelect={(index) => {
              setFocus("composer");
              setTray((current) => (current?.kind === "pick" || current?.kind === "mcp" || current?.kind === "mcp-add" || current?.kind === "agents" || current?.kind === "form" ? { ...current, selected: index } : current));
            }}
          />
        ) : null}
        <ModeLine mode={mode} canCycle={isHost} />
        <StatusBar me={me} state={state} connection={connection} inbox={items.length} focused={focus === "inbox"} hint={hint} />
      </box>
      {dialog ? (
        <SettingsDialog
          width={width}
          height={height}
          settings={settings}
          mode={state.prompt_mode}
          role={me?.role}
          agent={state.agent || projection.agent}
          room={room}
          control={isHost ? control : null}
          keys={keys}
          initialTab="model"
          welcome={welcome}
          onSettings={change}
          onKeys={(preset, key, remember) => onKeys?.(preset, key, remember)}
          onMode={(mode) => send({ type: "session.set_prompt_mode", mode })}
          onInvite={() => send({ type: "invite.create", role: "participant", ttl_s: 3600 })}
          onCopyReply={copyReply}
          onClose={closeSettings}
        />
      ) : null}
      {showPanel ? <Sidebar projection={projection} room={room} inbox={items} running={running} status={runStatus} onSettings={() => setDialog(true)} /> : null}
    </box>
  );
}

export { SIDEBAR_WIDTH };
