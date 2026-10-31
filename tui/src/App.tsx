import { createHash } from "node:crypto";
import type { ScrollBoxRenderable } from "@opentui/core";
import { useKeyboard, useRenderer, useSelectionHandler, useTerminalDimensions } from "@opentui/react";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  label,
  mentionable,
  mentionsMe,
  findInFeed,
  findPerson,
  matchPreview,
  nextPermissionMode,
  parseChat,
  parseSlash,
  routeOf,
  SlashError,
  stepMatch,
  status,
  type Command,
  type ConnectionStatus,
  type PermissionMode,
  type Session,
} from "@plural/client";
import { COMMANDS, pluginHints } from "./commands";
import { feedId, FeedItemView, PinnedPrompt, pinId } from "./components/Cards";
import { onCodeCopy } from "./code";
import { Composer, type Delivery } from "./components/Composer";
import { SearchBar } from "./components/SearchBar";
import { Inbox, inboxItems, type InboxItem } from "./components/Inbox";
import { ExtrasDialog } from "./components/ExtrasDialog";
import { SettingsDialog } from "./components/SettingsDialog";
import { SetupDialog } from "./components/SetupDialog";
import { type ExtraStatus } from "./extras";
import { Splash } from "./components/Splash";
import { Sidebar, SIDEBAR_WIDTH } from "./components/Sidebar";
import { preview, Toast, TOAST_MS, type ToastMessage } from "./components/Toast";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { SCOPES, TrayView, type Form, type McpWizard, type Row, type Tray } from "./components/Tray";
import { addCommand, MCP_CATALOG, wizardFields } from "./mcpCatalog";
import { Compacting, ModeLine, Working } from "./components/Working";
import { helpRows, pluginRows, policyRows, skillRows, usageRows, whoRows } from "./trays";
import type { Alerts } from "./alerts";
import type { UpdateState, Updater } from "./update";
import { describeConflict, type SpaceRow, type Summary } from "./spaces";
import type { Conflict } from "./team";
import { explain } from "./failure";
import { absorb, emptyFeed, lastReply, withBanner, withNotice, type Feed, type Tone } from "./feed";
import type { AgentControl } from "./control";
import type { Keys } from "./credentials";
import type { AgentChoice, PresetId } from "./presets";
import type { Tab } from "./settingsModel";
import { copyToClipboard, IMAGE_LIMIT_BYTES, pasteImage } from "./lib/clipboard";
import { createSyntaxStyle } from "./syntax";
import { DEFAULT_SETTINGS, type Settings } from "./settings";
import { setTheme, theme } from "./theme";
import * as sound from "./lib/sound";

export interface AppProps {
  client: Session;
  room: string;
  version: string;
  guestLink: string | null;
  teamLink?: string | null;
  settings?: Settings;
  onSettings?: (settings: Settings) => void;
  control?: AgentControl | null;
  keys?: Keys;
  onKeys?: (preset: PresetId, key: string, remember: boolean) => void;
  startupNote?: string | null;
  startup?: Command[];
  initialPrompt?: string | null;
  alerts?: Alerts;
  updater?: Updater;
  active?: boolean;
  viewing?: string | null;
  spaces?: SpaceRow[];
  teamName?: string | null;
  teamError?: string | null;
  onOpenSpace?: (id: string) => void;
  onCycleSpace?: (direction: 1 | -1) => void;
  onClose?: () => void;
  onSummary?: (summary: Summary) => void;
  onGiveBriefing?: (briefing: { source: string; as_of_seq: number; text: string }) => Promise<void>;
  conflicts?: Conflict[];
  splash?: boolean;
  onQuit: () => void;
}

type Focus = "composer" | "inbox" | "search";

const GUARD_MS = 400;
const FRAME_MS = 33;
const MIN_WIDTH_FOR_PANEL = 90;
const TYPING_REFRESH_MS = 3000;
const TYPING_IDLE_MS = 2500;
const PLAN_APPROVED = "The host approved the plan. Implement it now.";
const UPLOAD_WAIT_MS = 10_000;
const LONG_RUN_MS = 15_000;
const DELIVERED_MS = 1500;
const FAILED_MS = 8000;

interface PastedImage {
  name: string;
  sha256: string;
}

export function App({
  client,
  room,
  version,
  guestLink,
  teamLink = null,
  settings: initialSettings,
  onSettings,
  control = null,
  keys = {},
  onKeys,
  startupNote = null,
  startup = [],
  initialPrompt = null,
  alerts,
  updater,
  active = true,
  viewing = null,
  spaces,
  teamName = null,
  teamError = null,
  onOpenSpace,
  onCycleSpace,
  onClose,
  onSummary,
  onGiveBriefing,
  conflicts = [],
  splash = false,
  onQuit,
}: AppProps) {
  const renderer = useRenderer();
  const [settings, setSettings] = useState<Settings>(initialSettings ?? DEFAULT_SETTINGS);
  const liveSettings = useRef(settings);
  liveSettings.current = settings;
  setTheme(settings.theme);
  const syntax = useMemo(() => createSyntaxStyle(renderer), [renderer, settings.theme]);
  const [dialog, setDialog] = useState(false);
  const [setup, setSetup] = useState<{ first: boolean; back: boolean } | null>(null);
  const [extrasPrompt, setExtrasPrompt] = useState<{ preselect: string | null; reason: string | null; back: boolean } | null>(null);
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
  const initial = useMemo(() => withBanner(emptyFeed(), { kind: "banner", id: "banner", room, version, guestLink, teamLink }), []);
  const [feed, setFeed] = useState<Feed>(initial);
  const feedRef = useRef(initial);
  const [connection, setConnection] = useState<ConnectionStatus>(client.status);
  const [focus, setFocus] = useState<Focus>("composer");
  const [selected, setSelected] = useState(0);
  const [approvalChoice, setApprovalChoice] = useState<{ id: string; index: number } | null>(null);
  const [seed, setSeed] = useState<{ text: string; key: number } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const toasts = useRef({ count: 0, timer: null as ReturnType<typeof setTimeout> | null });
  const [now, setNow] = useState(Date.now());
  const [planReady, setPlanReady] = useState(false);
  const [intro, setIntro] = useState(splash);
  const [failure, setFailure] = useState<string | null>(null);
  const reached = useRef(client.status === "online");
  if (connection === "online") {
    reached.current = true;
  }
  const [tray, setTrayState] = useState<Tray | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<string | null>(null);
  const [delivery, setDelivery] = useState<Delivery | null>(null);
  const [update, setUpdate] = useState<UpdateState | null>(updater?.state ?? null);
  useEffect(() => updater?.subscribe(setUpdate), [updater]);
  const [behind, setBehind] = useState({ away: false, fresh: 0, chat: 0 });
  const anchor = useRef(0);
  const [finished, setFinished] = useState(false);
  const runStart = useRef<number | null>(null);
  const deliveryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [images, setImages] = useState<PastedImage[]>([]);
  const pastes = useRef(0);
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
  const frames = useRef({ last: 0, timer: null as ReturnType<typeof setTimeout> | null });
  const publish = (): void => {
    const state = frames.current;
    const wait = FRAME_MS - (Date.now() - state.last);
    if (wait > 0) {
      state.timer ??= setTimeout(publish, wait);
      return;
    }
    if (state.timer !== null) {
      clearTimeout(state.timer);
      state.timer = null;
    }
    state.last = Date.now();
    setFeed(feedRef.current);
    bump();
  };
  useEffect(
    () => () => {
      if (frames.current.timer !== null) {
        clearTimeout(frames.current.timer);
      }
    },
    [],
  );
  const commit = (next: Feed): void => {
    feedRef.current = next;
    publish();
  };
  const notify = (tone: Tone, text: string): void => commit(withNotice(feedRef.current, tone, text));
  const showToast = (title: string, detail: string | null = null, tone: "ok" | "accent" = "ok", icon = "✓"): void => {
    toasts.current.count += 1;
    const id = toasts.current.count;
    if (toasts.current.timer !== null) {
      clearTimeout(toasts.current.timer);
    }
    setToast({ id, title, detail, tone, icon });
    toasts.current.timer = setTimeout(() => setToast((current) => (current?.id === id ? null : current)), TOAST_MS);
  };
  const copy = (text: string, title: string, detail: string | null = null): void => {
    void copyToClipboard(text, (value) => renderer.copyToClipboardOSC52(value)).then(() => showToast(title, detail));
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
          publish();
          if (event.type === "chat.posted" && mentionsMe(event, client.projection.meId)) {
            const author = client.projection.state.participants[event.author_id];
            const who = author ? label(client.projection.state, author) : "someone";
            if (liveSettings.current.mentionBell) {
              sound.ring();
            }
            showToast(event.to === null ? `${who} mentioned you` : `${who} wrote to you`, preview(event.text, 60), "accent", "✉");
          }
          if (event.type === "participant.joined" && client.projection.me?.role === "host" && event.participant.id !== client.projection.meId) {
            if (liveSettings.current.joinBell) {
              sound.ring();
            }
            showToast(`${label(client.projection.state, event.participant)} joined`, `as ${event.participant.role}`, "accent", "+");
          }
          if (event.type === "invite.created") {
            if (event.reusable) {
              copy(
                event.link,
                "Room link copied",
                client.projection.state.admission === "open" ? "anyone with it joins at once" : "you will be asked to let each person in",
              );
            } else {
              copy(event.link, "Invite link copied", "send it to one person, it works once");
            }
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
          } else if (pending && event.type === "plugins.changed") {
            setTray({ kind: "text", title: `plugins · ${event.plugins.length}`, tone: "accent", rows: pluginRows(client.projection) });
          } else if (pending && event.type === "error") {
            const title = trayRef.current?.kind === "busy" ? trayRef.current.title : "skills";
            setTray({ kind: "text", title, tone: "danger", rows: [[{ text: event.message, fg: theme.danger }]] });
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
        const reason = explain(error);
        setFailure(reason);
        notify("danger", reason);
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
  const pluginCommands = useMemo(() => pluginHints(state.commands), [state.commands]);
  const isHost = me?.role === "host";
  const mode = state.permission_mode;
  const running = state.run !== null;
  const items = useMemo(
    (): InboxItem[] => (isHost ? [...inboxItems(state), ...(planReady ? [{ kind: "plan", id: "plan" } as const] : [])] : []),
    [isHost, state.approvals, state.proposals, state.join_requests, state.access_requests, state.briefing_requests, planReady],
  );
  const approvals = Object.keys(state.approvals).length;
  const queuedIds = useMemo(
    () => new Map(state.queue.map((entry) => [entry.prompt_id, entry.delivery === "follow_up" ? ("follow_up" as const) : ("steer" as const)])),
    [state.queue],
  );
  const searching = focus === "search";
  const hits = useMemo(() => (searching ? findInFeed(feed.items, query).reverse() : []), [feed.items, query, searching]);
  const hitSet = useMemo(() => new Set(hits), [hits]);
  const hitIndex = Math.max(0, found === null ? 0 : hits.indexOf(found));
  const current = hits[hitIndex] ?? null;

  const matchedItem = current === null ? undefined : feed.items.find((item) => item.id === current);
  const matched = matchedItem ? matchPreview(matchedItem, query, Math.max(20, width - 60)) : "";

  const reveal = (id: string | null): void => {
    setFound(id);
    const box = scroll.current;
    const card = id === null ? undefined : box?.findDescendantById(feedId(id));
    if (box && card) {
      box.scrollBy(card.y - box.y - 1);
    }
  };

  const search = (next: string): void => {
    setQuery(next);
    const first = findInFeed(feedRef.current.items, next).at(-1) ?? null;
    reveal(first);
  };

  const step = (direction: 1 | -1): void => {
    if (hits.length > 0) {
      reveal(hits[stepMatch(hits.length, hitIndex, direction)] ?? null);
    }
  };

  const closeSearch = (): void => {
    setFound(null);
    setFocus("composer");
  };

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
      const entries = feedRef.current.items;
      const atBottom = box.scrollTop + box.viewport.height >= box.scrollHeight - 1;
      if (atBottom) {
        anchor.current = entries.length;
      }
      const fresh = entries.slice(anchor.current);
      const next = { away: !atBottom, fresh: fresh.length, chat: fresh.filter((entry) => entry.kind === "chat" && !entry.mine).length };
      setBehind((current) => (current.away === next.away && current.fresh === next.fresh && current.chat === next.chat ? current : next));
    }, 100);
    return () => clearInterval(timer);
  }, []);
  const pinnedItem = pinned ? feed.items.find((item): item is Extract<typeof item, { kind: "user" }> => item.kind === "user" && item.id === pinned) : undefined;

  const latest = (): void => {
    scroll.current?.scrollTo(Number.MAX_SAFE_INTEGER);
  };

  const jumpPrompt = (direction: 1 | -1): void => {
    const box = scroll.current;
    if (!box) {
      return;
    }
    const cards = feedRef.current.items
      .filter((item) => item.kind === "user")
      .map((item) => box.findDescendantById(feedId(item.id)))
      .filter((card) => card !== undefined);
    const target = direction === -1 ? cards.filter((card) => card.y < box.y).at(-1) : cards.find((card) => card.y > box.y + 1);
    if (target) {
      box.scrollBy(target.y - box.y - 1);
    } else if (direction === 1) {
      latest();
    }
  };

  useEffect(() => onCodeCopy((text) => copy(text, "Copied", `${text.length} characters`)), []);

  const phase = isHost && items.length > 0 ? "waiting" : running ? "running" : finished ? "done" : "idle";
  useEffect(() => onSummary?.({ phase }), [phase]);

  const knownConflicts = useRef<ReadonlySet<string>>(new Set());
  useEffect(() => {
    const keys = new Set(conflicts.map((conflict) => `${conflict.room}:${conflict.paths.join(",")}`));
    for (const conflict of conflicts) {
      if (!knownConflicts.current.has(`${conflict.room}:${conflict.paths.join(",")}`)) {
        notify("warn", `${describeConflict(conflict)}${conflict.same_branch ? "" : ` on ${conflict.branch ?? "another branch"}`}`);
        showToast("Same file", describeConflict(conflict), "accent", "⚠");
      }
    }
    knownConflicts.current = keys;
  }, [conflicts]);

  useEffect(() => {
    if (!active) {
      setDialog(false);
      setFocus((current) => (current === "search" ? "composer" : current));
      setFound(null);
    }
  }, [active]);

  useEffect(() => {
    if (initialSettings) {
      setSettings(initialSettings);
    }
  }, [initialSettings]);

  useEffect(() => {
    if (running) {
      runStart.current = Date.now();
      setFinished(false);
    } else if (runStart.current !== null) {
      const long = Date.now() - runStart.current >= LONG_RUN_MS;
      runStart.current = null;
      setFinished(true);
      if (long && settings.bell) {
        sound.ring();
      }
    }
  }, [running]);

  const seenInbox = useRef<ReadonlySet<string>>(new Set());
  useEffect(() => {
    const ids = new Set(items.map((item) => `${item.kind}:${item.id}`));
    if (settings.bell && isHost && [...ids].some((id) => !seenInbox.current.has(id))) {
      sound.ring();
    }
    seenInbox.current = ids;
  }, [items, settings.bell, isHost]);

  useEffect(() => {
    if (approvals === 0) {
      return;
    }
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [approvals]);

  const closeSettings = (): void => {
    setDialog(false);
  };

  useEffect(() => {
    if (control && isHost && !settings.setupSeen && settings.agent.preset === "demo" && state.agent.startsWith("demo")) {
      setSetup({ first: true, back: false });
    }
  }, [isHost, state.agent]);

  const chooseProvider = (): void => {
    setDialog(false);
    setSetup({ first: false, back: true });
  };

  const closeSetup = (): void => {
    const back = setup?.back ?? false;
    setSetup(null);
    if (!settings.setupSeen) {
      change({ ...settings, setupSeen: true });
    }
    if (back) {
      setDialog(true);
    }
  };

  const applyProvider = (choice: AgentChoice, key: string, label: string): void => {
    change({ ...settings, agent: choice, agentChoices: { ...settings.agentChoices, [choice.preset]: choice }, setupSeen: true });
    onKeys?.(choice.preset, key, settings.rememberKey);
    setSetup(null);
    notify("ok", `Now using ${label}`);
  };

  const finishInSettings = (preset: string): void => {
    change({ ...settings, agent: { preset, model: "", baseUrl: "", contextWindow: "" }, setupSeen: true });
    setSetup(null);
    setDialog(true);
  };

  const askForExtra = (extra: ExtraStatus): void => {
    setDialog(false);
    setExtrasPrompt({ preselect: extra.id, reason: `This provider needs the ${extra.label}.`, back: true });
  };

  const closeExtras = (installed: boolean): void => {
    const back = extrasPrompt?.back ?? false;
    setExtrasPrompt(null);
    if (!settings.extrasSeen) {
      change({ ...settings, extrasSeen: true });
    }
    if (back) {
      setDialog(true);
      if (installed) {
        notify("ok", "SDK installed: choose Save and use");
      }
    }
  };

  useEffect(() => {
    if (startupNote) {
      notify("warn", startupNote);
    }
  }, []);

  useEffect(() => alerts?.subscribe((tone, text) => notify(tone, text)), [alerts]);

  const started = useRef(false);
  useEffect(() => {
    if (started.current || connection !== "online" || me === undefined) {
      return;
    }
    started.current = true;
    startup.forEach((command) => send(command));
    if (initialPrompt !== null && initialPrompt.trim() !== "") {
      submit(initialPrompt.trim());
    }
  }, [connection, me?.id]);

  const send = (command: Command): void => {
    client.send(command).catch((error: unknown) => {
      const text = error instanceof Error ? error.message : String(error);
      if (command.type.startsWith("skills.") || command.type.startsWith("mcp.") || command.type.startsWith("plugins.") || command.type === "context.compact") {
        show(command.type.split(".")[0] === "context" ? "compact" : command.type.split(".")[0]!, [[{ text, fg: theme.warn }]], "warn");
      } else {
        notify("danger", text);
      }
    });
  };

  const fade = (ms: number): void => {
    if (deliveryTimer.current !== null) {
      clearTimeout(deliveryTimer.current);
    }
    deliveryTimer.current = setTimeout(() => setDelivery(null), ms);
  };

  const deliver = (command: Command, text: string, retry?: () => void): void => {
    if (deliveryTimer.current !== null) {
      clearTimeout(deliveryTimer.current);
    }
    setDelivery({ state: "sending" });
    client.send(command).then(
      () => {
        setDelivery((current) => (current?.state === "failed" ? current : { state: "sent" }));
        fade(DELIVERED_MS);
      },
      (error: unknown) => {
        const reason = error instanceof Error ? error.message : String(error);
        const restored = !dirty.current;
        if (restored) {
          retry?.();
          setSeed({ text, key: Date.now() });
        }
        setDelivery({ state: "failed", reason, restored });
        fade(FAILED_MS);
      },
    );
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

  const pasteFromClipboard = async (): Promise<void> => {
    const data = await pasteImage();
    if (data === null) {
      flash("no image in the clipboard");
      return;
    }
    if (data.length > IMAGE_LIMIT_BYTES) {
      notify("warn", `the image is ${(data.length / 1e6).toFixed(1)} MB, more than ${IMAGE_LIMIT_BYTES / 1e6} MB`);
      return;
    }
    pastes.current += 1;
    const image = {
      name: `image-${pastes.current}.${data[0] === 0xff ? "jpg" : "png"}`,
      sha256: createHash("sha256").update(data).digest("hex"),
    };
    setImages((current) => [...current, image]);
    send({ type: "file.attach", name: image.name, content_b64: data.toString("base64"), sha256: image.sha256 });
  };

  // An upload is confirmed by its attachment.added event, which carries the id a prompt refers to.
  const uploaded = async (pending: PastedImage[]): Promise<string[] | null> => {
    const deadline = Date.now() + UPLOAD_WAIT_MS;
    while (Date.now() < deadline) {
      const added = Object.values(client.projection.state.attachments);
      const ids = pending.map(
        (image) => added.find((meta) => meta.sha256 === image.sha256 && meta.owner_id === client.projection.meId)?.id,
      );
      if (ids.every((id) => id !== undefined)) {
        return ids as string[];
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    return null;
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
    copy(text, "Last reply copied", `${text.length} characters`);
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
        show("help", helpRows(me?.role, pluginCommands));
        return true;
      case "who":
        show(`who · ${Object.values(state.participants).filter((person) => person.connected).length} here`, whoRows(projection));
        return true;
      case "invite":
        switch (rest[0]) {
          case undefined:
          case "link":
            send({ type: "invite.create", role: "participant", ttl_s: 3600, reusable: true });
            break;
          case "once":
            send({ type: "invite.create", role: "participant", ttl_s: 3600 });
            break;
          case "viewer":
            send({ type: "invite.create", role: "viewer", ttl_s: 3600 });
            break;
          case "revoke":
            send({ type: "link.revoke" });
            break;
          case "open":
          case "approve":
            send({ type: "link.set_admission", mode: rest[0] });
            notify("accent", rest[0] === "open" ? "the room link lets people in at once" : "you will be asked to let each person in");
            break;
          default:
            warn("invite", "usage: /invite [link | once | viewer | revoke | open | approve]");
        }
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
      case "brief": {
        const [verb, ...more] = rest;
        if (isHost) {
          if (verb === "share" && ["off", "ask", "team"].includes(more[0] ?? "")) {
            send({ type: "session.set_briefing_sharing", mode: more[0] as "off" | "ask" | "team" });
          } else {
            const waiting = Object.values(state.briefing_requests);
            show("briefings", [
              [{ text: `this session shares briefings: ${state.briefing_sharing}`, bold: true }, { text: "  (/brief share off|ask|team)", fg: theme.dim }],
              ...waiting.map((ask): Row => [{ text: ask.name }, { text: ask.focus ? `  ${ask.focus}` : "", fg: theme.dim }]),
            ]);
          }
        } else if (verb === "give") {
          const last = feedRef.current.items.filter((entry) => entry.kind === "briefing").at(-1);
          if (last === undefined || last.kind !== "briefing") {
            warn("brief", "there is no briefing here yet, /brief asks for one");
          } else if (!onGiveBriefing) {
            warn("brief", "a briefing goes to your own agent, ask for it from a teammate's session");
          } else {
            onGiveBriefing({ source: last.from, as_of_seq: last.asOf, text: last.text }).then(
              () => notify("ok", `${last.from}'s briefing is in your agent's notes, it reads it at its next prompt. Click “you” to go back`),
              (error: unknown) => notify("warn", error instanceof Error ? error.message : String(error)),
            );
          }
        } else {
          const update = verb === "update";
          const focus = (update ? more : rest).join(" ").trim();
          send({ type: "briefing.request", focus: focus === "" ? null : focus, update });
        }
        return true;
      }
      case "access": {
        const people = mentionable(state, projection.meId);
        const [verb, ...names] = rest;
        if (me?.role === "viewer") {
          send({ type: "access.request", note: rest.join(" ").trim() || null });
        } else if (!isHost) {
          warn("access", "you can already write");
        } else if (verb === undefined) {
          const waiting = Object.values(state.access_requests);
          show("access", waiting.length === 0 ? [[{ text: "nobody is asking to write", fg: theme.dim }]] : waiting.map((ask): Row => [{ text: ask.name, bold: true }, { text: ask.note ? `  ${ask.note}` : "", fg: theme.dim }]));
        } else {
          const person = findPerson(names.join(" "), people);
          if (person === null || !["allow", "deny", "revoke"].includes(verb)) {
            warn("access", "usage: /access [allow|deny|revoke <name>]");
          } else if (verb === "revoke") {
            send({ type: "participant.set_role", participant_id: person.id, role: "viewer" });
          } else {
            send({ type: "access.decide", participant_id: person.id, decision: verb as "allow" | "deny" });
          }
        }
        return true;
      }
      case "kick": {
        const person = findPerson(rest.join(" "), mentionable(state, projection.meId));
        if (person === null) {
          warn("kick", "usage: /kick <name> (see /who)");
        } else {
          send({ type: "participant.revoke", participant_id: person.id });
          notify("dim", `${person.label} was removed from the session`);
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
    if (text === "" && (images.length === 0 || editing || wizard?.kind === "mcp-add")) {
      return;
    }
    if (wizard?.kind === "mcp-add" && wizard.step === "field") {
      advance(wizard, text);
      return;
    }
    if (routeOf(text, projection.state, projection.meId).label === "watching") {
      warn("watching", "you are only watching. /access asks the host for the right to write");
      return;
    }
    stopTyping();
    setTray(null);
    setPlanReady(false);
    scroll.current?.scrollTo(Number.MAX_SAFE_INTEGER);
    if (editing) {
      const proposal = editing;
      deliver({ type: "proposal.decide", proposal_id: proposal, decision: "approve", edited_text: text }, text, () => setEditing(proposal));
      setEditing(null);
      return;
    }
    try {
      const chat = parseChat(text, projection.state, projection.meId);
      if (chat !== null) {
        deliver(chat.command, text);
        return;
      }
    } catch (error) {
      warn(text.split(/\s+/)[0] ?? "chat", error instanceof SlashError ? error.message : String(error));
      return;
    }
    if (text.startsWith("/")) {
      const name = text.slice(1).split(/\s+/)[0] ?? "";
      const known = [...COMMANDS, ...pluginCommands].find((command) => command.name === name);
      if (known?.hostOnly && !isHost) {
        warn(`/${name}`, `/${name} is for the host`);
        return;
      }
      if (local(text)) {
        return;
      }
      try {
        const parsed = parseSlash(text, new Set(state.commands.map((command) => command.name)));
        if (parsed === null) {
          return;
        }
        if (parsed.type === "show.plugins") {
          show(`plugins · ${state.plugins.length}`, pluginRows(projection));
          return;
        }
        if (parsed.type === "plugins.create") {
          setTray({ kind: "busy", title: "plugins", text: `creating ~/.plural/plugins/${parsed.name}.py`, key: Date.now() });
        } else if (parsed.type === "plugins.reload") {
          setTray({ kind: "busy", title: "plugins", text: "reloading plugins", key: Date.now() });
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
    if (images.length === 0) {
      deliver({ type: "prompt.submit", text, delivery: "now" }, text);
      return;
    }
    const pending = images;
    setImages([]);
    void uploaded(pending).then((ids) => {
      if (ids === null) {
        setImages(pending);
        setSeed({ text, key: Date.now() });
        notify("danger", "the image did not reach the host; try sending again");
        return;
      }
      deliver({ type: "prompt.submit", text: text || "(image)", delivery: "now", attachments: ids }, text, () => setImages(pending));
    });
  };

  useKeyboard((key) => {
    if (!active || dialog || intro || extrasPrompt !== null || setup !== null) {
      return;
    }
    if (key.meta && (key.name === "left" || key.name === "right") && onCycleSpace) {
      key.preventDefault();
      onCycleSpace(key.name === "left" ? -1 : 1);
      return;
    }
    if (key.ctrl && key.name === "w" && viewing !== null && onClose) {
      key.preventDefault();
      onClose();
      return;
    }
    if (key.name === "f2") {
      key.preventDefault();
      setDialog(true);
      return;
    }
    if (finished) {
      setFinished(false);
    }
    if (key.name === "end" && !dirty.current) {
      key.preventDefault();
      latest();
      return;
    }
    if (key.meta && (key.name === "up" || key.name === "down")) {
      key.preventDefault();
      jumpPrompt(key.name === "up" ? -1 : 1);
      return;
    }
    if (key.ctrl && key.name === "f") {
      key.preventDefault();
      setFocus("search");
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
    } else if (item?.kind === "approval" && (key.name === "up" || key.name === "down")) {
      const direction = key.name === "up" ? -1 : 1;
      setApprovalChoice((current) => ({
        id: item.id,
        index: Math.max(0, Math.min(3, (current?.id === item.id ? current.index : 0) + direction)),
      }));
    } else if (key.name === "up" || key.name === "k" || key.name === "left") {
      setApprovalChoice(null);
      setSelected(Math.max(0, Math.min(selected, items.length - 1) - 1));
    } else if (key.name === "down" || key.name === "j" || key.name === "right") {
      setApprovalChoice(null);
      setSelected(Math.min(items.length - 1, selected + 1));
    } else if (item?.kind === "join") {
      const choices: Record<string, "allow" | "viewer" | "deny"> = { y: "allow", return: "allow", v: "viewer", n: "deny", x: "deny" };
      const choice = choices[key.name];
      if (choice) {
        send({ type: "join.decide", request_id: item.id, decision: choice });
      }
    } else if (item?.kind === "briefing") {
      if (key.name === "y" || key.name === "return") {
        send({ type: "briefing.decide", request_id: item.id, decision: "allow" });
      } else if (key.name === "n" || key.name === "x") {
        send({ type: "briefing.decide", request_id: item.id, decision: "deny" });
      }
    } else if (item?.kind === "access") {
      if (key.name === "y" || key.name === "return") {
        send({ type: "access.decide", participant_id: item.id, decision: "allow" });
      } else if (key.name === "n" || key.name === "x") {
        send({ type: "access.decide", participant_id: item.id, decision: "deny" });
      }
    } else if (item?.kind === "approval") {
      const decisions: Record<string, "once" | "always" | "reject" | "block"> = { y: "once", a: "always", n: "reject", b: "block" };
      const options = ["once", "always", "reject", "block"] as const;
      const index = approvalChoice?.id === item.id ? approvalChoice.index : 0;
      const decision = key.name === "return" ? options[index] : decisions[key.name];
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
    if (!active || !text || !settings.copyOnSelect) {
      return;
    }
    if (copying.current) {
      clearTimeout(copying.current);
    }
    copying.current = setTimeout(() => copy(text, "Copied", `${text.length} characters · “${preview(text)}”`), 250);
  });

  const formAsk = tray?.kind === "form" ? tray.steps[tray.index] : undefined;
  const asking =
    tray?.kind === "mcp-add" && tray.step === "field"
      ? tray.fields[tray.index]
      : formAsk?.kind === "text"
        ? { label: formAsk.label, hint: formAsk.hint, secret: false }
        : undefined;
  const placeholder =
    me?.role === "viewer"
      ? me.id in state.access_requests
        ? "You asked to write, waiting for the host…"
        : "You are watching · /access asks the host for the right to write"
      : me?.role === "participant" && state.prompt_mode === "review"
        ? "Propose a prompt, the host approves it"
        : "Message the agent, / for commands";
  const disabled = null;
  const showPanel = settings.panel && width >= MIN_WIDTH_FOR_PANEL;

  if (intro) {
    return (
      <Splash
        width={width}
        height={height}
        version={version}
        ready={connection === "online" && me !== undefined}
        status={
          connection === "online"
            ? projection.waiting
              ? "waiting for the host to let you in…"
              : "joining the session…"
            : connection === "connecting"
              ? "connecting to the session…"
              : reached.current
                ? "connection lost, reconnecting…"
                : "cannot reach the host yet, still trying…"
        }
        failure={failure}
        onDone={() => setIntro(false)}
        onQuit={onQuit}
      />
    );
  }

  return (
    <box flexDirection="row" width={width} height={height} backgroundColor={theme.bg} visible={active}>
      <box flexDirection="column" flexGrow={1} minWidth={0}>
        <TopBar state={state} update={update} team={teamName ?? null} onSettings={() => setDialog(true)} />
        {viewing !== null ? (
          <box flexShrink={0} height={1} paddingX={2} backgroundColor={theme.panel}>
            <text fg={theme.info} wrapMode="none">
              viewing {viewing}
              <span fg={theme.dim}> · alt+←/→ switch · ctrl+w closes</span>
            </text>
          </box>
        ) : null}
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
          paddingLeft={1}
          paddingRight={2}
          paddingTop={1}
          scrollbarOptions={{ showArrows: false, trackOptions: { foregroundColor: theme.line, backgroundColor: theme.bg } }}
        >
          {feed.items.map((item) => {
            const active = item.id === current;
            const marked = active || hitSet.has(item.id);
            return (
              <box
                key={`${item.id}:${settings.theme}`}
                id={feedId(item.id)}
                flexDirection="column"
                flexShrink={0}
                paddingLeft={marked ? 0 : 1}
                {...(marked ? { border: ["left"] as ["left"], borderStyle: active ? ("heavy" as const) : ("single" as const), borderColor: active ? theme.warn : theme.line } : {})}
              >
                <FeedItemView
                  item={item}
                  syntax={syntax}
                  width={width - (showPanel ? SIDEBAR_WIDTH : 0) - 9}
                  expanded={allOpen || opened.has(item.id)}
                  queued={queuedIds.get(item.id) ?? null}
                  onToggle={toggle}
                  onCopy={(text) => copy(text, "Copied", `${text.length} characters`)}
                />
              </box>
            );
          })}
        </scrollbox>
        {behind.away ? (
          <box flexShrink={0} height={1} paddingX={2} onMouseDown={latest}>
            <text fg={theme.accent}>
              ↓ {behind.fresh > 0 ? `${behind.fresh} new` : "latest"}
              {behind.chat > 0 ? ` · ✉ ${behind.chat}` : ""}
              <span fg={theme.dim}>  click or end to jump down · alt+↑/↓ between prompts</span>
            </text>
          </box>
        ) : null}
        {items.length > 0 ? <Inbox items={items} state={state} selected={selected} focused={focus === "inbox"} now={now} approvalChoice={approvalChoice} /> : null}
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
        {searching ? (
          <SearchBar query={query} count={hits.length} position={hitIndex} preview={matched} onQuery={search} onStep={step} onClose={closeSearch} />
        ) : null}
        <Composer
          focused={active && focus === "composer" && !dialog && extrasPrompt === null && setup === null}
          disabled={disabled}
          placeholder={asking ? `${asking.label}${asking.hint ? ` · ${asking.hint}` : ""}` : placeholder}
          remember={!asking?.secret}
          tips={!asking}
          role={me?.role}
          people={mentionable(state, projection.meId)}
          commands={pluginCommands}
          seed={seed}
          label={editing ? "editing the proposal: enter approves it, esc cancels" : null}
          route={asking || editing || disabled ? () => null : (text) => routeOf(text, state, projection.meId)}
          delivery={delivery}
          onSubmit={submit}
          images={images.map((image) => image.name)}
          onPasteImage={() => void pasteFromClipboard()}
          onDropImage={() => setImages((current) => current.slice(0, -1))}
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
      {toast ? <Toast message={toast} right={(showPanel ? SIDEBAR_WIDTH : 0) + 2} /> : null}
      {dialog ? (
        <SettingsDialog
          width={width}
          height={height}
          settings={settings}
          mode={state.prompt_mode}
          role={me?.role}
          agent={projection.agentLabel}
          room={room}
          control={isHost ? control : null}
          keys={keys}
          initialTab="model"
          onChooseProvider={chooseProvider}
          onSettings={change}
          onKeys={(preset, key, remember) => onKeys?.(preset, key, remember)}
          onMode={(mode) => send({ type: "session.set_prompt_mode", mode })}
          onInvite={() => send({ type: "invite.create", role: "participant", ttl_s: 3600, reusable: true })}
          admission={state.admission}
          onAdmission={(mode) => send({ type: "link.set_admission", mode })}
          onCopyReply={copyReply}
          onNeedExtra={askForExtra}
          update={update}
          version={version}
          onUpdate={() => void updater?.install()}
          onClose={closeSettings}
        />
      ) : null}
      {setup !== null && control ? (
        <SetupDialog
          width={width}
          height={height}
          control={control}
          settings={settings}
          keys={keys}
          first={setup.first}
          current={settings.agent.preset}
          onApplied={applyProvider}
          onSettings={finishInSettings}
          onClose={closeSetup}
        />
      ) : null}
      {extrasPrompt !== null && control ? (
        <ExtrasDialog width={width} height={height} control={control} preselect={extrasPrompt.preselect} reason={extrasPrompt.reason} onClose={closeExtras} />
      ) : null}
      {showPanel ? <Sidebar projection={projection} room={room} spaces={spaces} teamName={teamName} teamError={teamError} onOpenSpace={onOpenSpace} inbox={items} running={running} status={runStatus} onSettings={() => setDialog(true)} onInvite={() => send({ type: "invite.create", role: "participant", ttl_s: 3600, reusable: true })} update={update} /> : null}
    </box>
  );
}

export { SIDEBAR_WIDTH };
