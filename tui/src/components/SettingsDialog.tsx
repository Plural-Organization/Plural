import { decodePasteBytes } from "@opentui/core";
import { useKeyboard, usePaste } from "@opentui/react";
import type { ScrollBoxRenderable } from "@opentui/core";
import { useEffect, useReducer, useRef } from "react";
import type { Role } from "@plural/client";
import { hostBridgeApi, type BridgeApi, type BridgeApp } from "../bridges";
import type { AgentControl } from "../control";
import { missingFor, type ExtraStatus } from "../extras";
import { beginOAuth, clearOAuth, exchangeCode, hasOAuth, openOAuth, saveOAuth, type OAuthAttempt } from "../anthropicOAuth";
import type { Keys } from "../credentials";
import { presetOf, problemWith, toConfig, type AgentChoice, type PresetId } from "../presets";
import type { Settings } from "../settings";
import { actionFor, stepFor } from "../setup";
import { relayProblem, type ShareMode } from "../share";
import {
  friendlyError,
  maskKey,
  nextFast,
  nextModel,
  draftKey,
  landing,
  rowsFor,
  switchConnection,
  switchPreset,
  TABS,
  type ModelState,
  type Row,
  type Tab,
} from "../settingsModel";
import { THEME_NAMES, theme, type ThemeName } from "../theme";
import type { UpdateState } from "../update";

export const DIALOG_WIDTH = 84;
// The explanation of a radio row sits under its label, this far in.
const DETAIL_INDENT = 6;
// Rows of the dialog that are not the list: frame, title, tabs, rule, status and the two lines of help.
const CHROME_ROWS = 12;

// How many screen rows a row of the list takes; a section title after the first has a blank line above it.
// A note that names the group of choices under it.
const isTitle = (row: Row): boolean => row.kind === "note" && row.id.endsWith("-title");

// Wrapped text is counted a little narrower than the row, because words do not break where characters would.
// `app:<service>:field:<field>` names a field of a chat app.
function fieldOf(id: string): { app: string; field: string } | null {
  const [head, app, kind, field] = id.split(":");
  return head === "app" && kind === "field" && app !== undefined && field !== undefined ? { app, field } : null;
}

function rowHeight(row: Row, first: boolean, inner: number): number {
  const lines = (text: string, width: number): number => Math.max(1, Math.ceil(text.length / Math.max(8, width - 2)));
  if (isTitle(row)) {
    return first ? 1 : 2;
  }
  if (row.kind === "radio") {
    return 1 + lines(row.description ?? "", inner - DETAIL_INDENT);
  }
  if (row.kind === "note") {
    return lines(row.label, inner);
  }
  return row.kind === "header" && !first ? 2 : 1;
}

type Tone = "ok" | "error" | "info";

interface Editing {
  id: string;
  buffer: string;
}

interface Local {
  tab: Tab;
  index: number;
  editing: Editing | null;
  choice: AgentChoice;
  savedChoices: Settings["agentChoices"];
  keys: Keys;
  status: { tone: Tone; text: string } | null;
  busy: boolean;
  oauthAttempt: OAuthAttempt | null;
  apps: BridgeApp[] | null;
  appsError: string | null;
  drafts: Record<string, string>;
}

export interface DialogProps {
  width: number;
  height: number;
  settings: Settings;
  mode: "open" | "review";
  replies?: "mention" | "all";
  role: Role | undefined;
  agent: string;
  room: string;
  control: AgentControl | null;
  keys: Keys;
  initialTab: Tab;
  onChooseProvider?: () => void;
  onSettings: (next: Settings) => void;
  onKeys: (preset: PresetId, key: string, remember: boolean) => void;
  onMode: (mode: "open" | "review") => void;
  onReplies?: (mode: "mention" | "all") => void;
  onInvite: () => void;
  admission?: "approve" | "open";
  onAdmission?: (mode: "approve" | "open") => void;
  onCopyReply: () => void;
  /** The chosen provider needs an SDK the host does not have yet: the app offers to install it. */
  onNeedExtra?: (extra: ExtraStatus) => void;
  update?: UpdateState | null;
  version?: string;
  onUpdate?: () => void;
  onClose: () => void;
  /** How chat apps are read and changed; the host's `bridge` commands unless a test brings its own. */
  bridgeApi?: BridgeApi;
}

// Read at draw time: the palette changes when the theme does.
const toneColor = (tone: Tone): string => ({ ok: theme.ok, error: theme.danger, info: theme.dim })[tone];

export function SettingsDialog(props: DialogProps) {
  const listBox = useRef<ScrollBoxRenderable>(null);
  const [, redraw] = useReducer((value: number) => value + 1, 0);
  const local = useRef<Local>({
    tab: props.initialTab,
    index: 0,
    editing: null,
    choice: props.settings.agent,
    savedChoices: { ...props.settings.agentChoices, [props.settings.agent.preset]: props.settings.agent },
    keys: { ...props.keys },
    status: null,
    busy: false,
    oauthAttempt: null,
    apps: null,
    appsError: null,
    drafts: {},
  });
  const bridgeApi = useRef<BridgeApi>(props.bridgeApi ?? hostBridgeApi());
  const live = useRef(props);
  live.current = props;

  const state = (): ModelState => ({
    settings: live.current.settings,
    choice: local.current.choice,
    keys: local.current.keys,
    mode: live.current.mode,
    replies: live.current.replies,
    admission: live.current.admission,
    role: live.current.role,
    canConfigure: live.current.control !== null && live.current.role === "host",
    oauthLoggedIn: hasOAuth(),
    update: live.current.update,
    version: live.current.version,
    apps: local.current.apps,
    appsError: local.current.appsError,
    drafts: local.current.drafts,
  });
  const rows = (): Row[] => rowsFor(local.current.tab, state());
  const set = (patch: Partial<Local>): void => {
    local.current = { ...local.current, ...patch };
    redraw();
  };
  const say = (tone: Tone, text: string): void => set({ status: { tone, text } });

  const currentKey = (): string => local.current.keys[local.current.choice.preset] ?? "";

  const run = async (kind: "test" | "save"): Promise<void> => {
    const { choice } = local.current;
    const key = currentKey();
    const problem = problemWith(choice, key);
    const control = live.current.control;
    if (problem !== null) {
      say("error", problem);
      return;
    }
    if (control === null || local.current.busy) {
      return;
    }
    const needed = missingFor(presetOf(choice.preset));
    if (needed !== null && live.current.onNeedExtra) {
      live.current.onNeedExtra(needed);
      return;
    }
    set({ busy: true, status: { tone: "info", text: kind === "test" ? "testing the connection…" : "switching the agent…" } });
    const result = kind === "test" ? await control.test(toConfig(choice, key)) : await control.configure(toConfig(choice, key));
    set({ busy: false });
    if (!result.ok) {
      say("error", friendlyError(result.error ?? "it did not work"));
      return;
    }
    if (kind === "test") {
      say("ok", `✓ connected, ${result.message ?? "the model answered"}`);
      return;
    }
    const current = live.current;
    const appliedChoice = { ...choice, model: choice.model || presetOf(choice.preset).models[0] || "" };
    current.onSettings({
      ...current.settings,
      agent: appliedChoice,
      agentChoices: { ...local.current.savedChoices, [choice.preset]: appliedChoice },
      setupSeen: true,
    });
    current.onKeys(choice.preset, key, current.settings.rememberKey);
    say("ok", `✓ now using ${result.agent ?? presetOf(choice.preset).label}`);
  };

  const commit = (editing: Editing): void => {
    const { choice, keys } = local.current;
    const value = editing.buffer.trim();
    const field = fieldOf(editing.id);
    if (field !== null) {
      set({ editing: null, drafts: { ...local.current.drafts, [draftKey(field.app, field.field)]: value }, status: null });
    } else if (editing.id === "oauth_code") {
      const attempt = local.current.oauthAttempt;
      if (!attempt) return;
      set({ editing: null, busy: true, status: { tone: "info", text: "finishing Claude sign in…" } });
      void exchangeCode(value, attempt.verifier).then((credentials) => {
        saveOAuth(credentials);
        set({ busy: false, oauthAttempt: null });
        say("ok", "✓ signed in to Claude; choose Save and use");
      }).catch((error: unknown) => {
        set({ busy: false, oauthAttempt: null });
        say("error", friendlyError(error instanceof Error ? error.message : String(error)));
      });
    } else if (editing.id === "key") {
      set({ editing: null, keys: { ...keys, [choice.preset]: value }, status: null });
    } else if (editing.id === "relay") {
      const problem = relayProblem(value);
      if (problem !== null) {
        say("error", problem);
        return;
      }
      live.current.onSettings({ ...live.current.settings, relayUrl: value });
      set({ editing: null, status: { tone: "ok", text: "✓ saved, it applies the next time you start plural" } });
    } else if (editing.id === "model") {
      set({ editing: null, choice: { ...choice, model: value }, status: null });
    } else if (editing.id === "url") {
      set({ editing: null, choice: { ...choice, baseUrl: value }, status: null });
    } else {
      set({ editing: null, choice: { ...choice, contextWindow: value }, status: null });
    }
  };

  const toggleSetting = (id: string): void => {
    const { settings, onSettings } = live.current;
    switch (id) {
      case "panel":
        onSettings({ ...settings, panel: !settings.panel });
        break;
      case "copy":
        onSettings({ ...settings, copyOnSelect: !settings.copyOnSelect });
        break;
      case "bell":
        onSettings({ ...settings, bell: !settings.bell });
        break;
      case "mention-bell":
        onSettings({ ...settings, mentionBell: !settings.mentionBell });
        break;
      case "join-bell":
        onSettings({ ...settings, joinBell: !settings.joinBell });
        break;
      case "typing":
        onSettings({ ...settings, announceTyping: !settings.announceTyping });
        break;
      case "remember":
        onSettings({ ...settings, rememberKey: !settings.rememberKey });
        break;
    }
  };

  const startEditing = (row: Row): void => {
    const field = fieldOf(row.id);
    if (field !== null) {
      const app = local.current.apps?.find((entry) => entry.id === field.app);
      const typed = local.current.drafts[draftKey(field.app, field.field)];
      set({ editing: { id: row.id, buffer: typed ?? (app?.fields.find((entry) => entry.id === field.field)?.secret ? "" : (app?.values[field.field] ?? "")) } });
      return;
    }
    const { choice } = local.current;
    const raw: Record<string, string> = {
      key: currentKey(),
      model: choice.model,
      url: choice.baseUrl,
      window: choice.contextWindow,
      relay: live.current.settings.relayUrl,
    };
    set({ editing: { id: row.id, buffer: raw[row.id] ?? "" } });
  };

  const change = (row: Row, direction: 1 | -1): void => {
    if (!row.enabled) {
      return;
    }
    const { choice } = local.current;
    if (row.id === "connection") {
      const switched = switchConnection(choice, local.current.savedChoices, direction);
      set({ choice: switched.choice, savedChoices: switched.saved, status: null });
    } else if (row.id === "preset") {
      const switched = switchPreset(choice, local.current.savedChoices, direction, false);
      set({ choice: switched.choice, savedChoices: switched.saved, status: null });
    } else if (row.id === "model") {
      set({ choice: { ...choice, model: nextModel(choice, direction) }, status: null });
    } else if (row.id === "fast") {
      set({ choice: { ...choice, fastModel: nextFast(choice, direction) }, status: null });
    } else if (row.id === "replies") {
      live.current.onReplies?.(live.current.replies === "mention" ? "all" : "mention");
    } else if (row.kind === "toggle") {
      toggleSetting(row.id);
    }
  };

  // What is typed for one chat app, keeping only what it asked for.
  const typedFor = (app: BridgeApp): Record<string, string> => {
    const values: Record<string, string> = {};
    for (const field of app.fields) {
      const typed = local.current.drafts[draftKey(app.id, field.id)];
      if (typed !== undefined) {
        values[field.id] = typed;
      }
    }
    return values;
  };

  const loadApps = async (): Promise<void> => {
    try {
      const apps = await bridgeApi.current.list();
      set({ apps, appsError: null });
    } catch (error) {
      set({ appsError: error instanceof Error ? error.message : "could not read the chat apps" });
    }
  };

  const appAction = async (id: string): Promise<void> => {
    const [, appId, what] = id.split(":");
    const app = local.current.apps?.find((entry) => entry.id === appId);
    if (app === undefined || what === undefined || local.current.busy) {
      return;
    }
    const api = bridgeApi.current;
    set({ busy: true, status: { tone: "info", text: what === "test" ? "connecting…" : "working…" } });
    const result =
      what === "save"
        ? await api.save(app.id, typedFor(app), true)
        : what === "test"
          ? await api.test(app.id, typedFor(app))
          : what === "toggle"
            ? await api.save(app.id, {}, !app.enabled)
            : what === "renew"
              ? await api.renew(app.id)
              : await api.remove(app.id);
    set({ busy: false });
    if (!result.ok) {
      say("error", result.error ?? "it did not work");
      return;
    }
    if (what === "save") {
      const drafts = { ...local.current.drafts };
      for (const field of app.fields) {
        delete drafts[draftKey(app.id, field.id)];
      }
      set({ drafts });
      say("ok", `✓ saved, ${app.label} is connecting`);
    } else if (what === "test") {
      say("ok", `✓ reached ${result.identity ?? app.label}`);
    } else if (what === "renew") {
      say("ok", "✓ a new pairing code is shown under the owners");
    } else {
      say("ok", what === "toggle" ? (app.enabled ? `✓ ${app.label} is off` : `✓ ${app.label} is on`) : `✓ ${app.label} removed`);
    }
    await loadApps();
  };

  // The chat apps are read when their tab opens and again every few seconds: a bridge connects, fails or is
  // paired some time after Save.
  useEffect(() => {
    if (local.current.tab !== "apps") {
      return;
    }
    void loadApps();
    const timer = setInterval(() => {
      if (!local.current.busy && local.current.editing === null) {
        void loadApps();
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [local.current.tab]);

  const activate = (row: Row): void => {
    if (!row.enabled) {
      return;
    }
    switch (row.kind) {
      case "text":
      case "secret":
        startEditing(row);
        break;
      case "toggle":
        toggleSetting(row.id);
        break;
      case "choice":
        if (row.id === "preset" && live.current.onChooseProvider) {
          live.current.onChooseProvider();
        } else {
          change(row, 1);
        }
        break;
      case "radio":
        if (row.id.startsWith("join-")) {
          live.current.onAdmission?.(row.id === "join-open" ? "open" : "approve");
        } else if (row.id.startsWith("share-")) {
          live.current.onSettings({ ...live.current.settings, share: row.id.slice("share-".length) as ShareMode });
        } else {
          live.current.onMode(row.id === "mode-open" ? "open" : "review");
        }
        break;
      case "swatch":
        live.current.onSettings({ ...live.current.settings, theme: row.id.slice("theme:".length) as ThemeName });
        break;
      case "action":
        if (row.id.startsWith("app:")) {
          void appAction(row.id);
        } else if (row.id === "update") {
          live.current.onUpdate?.();
        } else if (row.id === "test" || row.id === "save") {
          void run(row.id);
        } else if (row.id === "oauth-login") {
          const attempt = beginOAuth();
          set({ oauthAttempt: attempt, editing: { id: "oauth_code", buffer: "" }, status: { tone: "info", text: "Claude sign in opened; URL copied. Paste the code here." } });
          void openOAuth(attempt);
        } else if (row.id === "oauth-logout") {
          clearOAuth();
          say("ok", "Claude login removed from this machine");
        } else if (row.id === "reply") {
          live.current.onCopyReply();
        } else if (row.id === "invite") {
          live.current.onInvite();
        }
        break;
      case "note":
        break;
    }
  };

  const switchTab = (tab: Tab): void => set({ tab, index: landing(rowsFor(tab, state()), 0), editing: null, status: null });

  useKeyboard((key) => {
    key.preventDefault();
    const { editing, tab } = local.current;
    if (editing) {
      if (key.name === "escape") {
        set({ editing: null, oauthAttempt: editing.id === "oauth_code" ? null : local.current.oauthAttempt });
      } else if (key.name === "return") {
        commit(editing);
      } else if (key.name === "backspace") {
        set({ editing: { ...editing, buffer: editing.buffer.slice(0, -1) } });
      } else if (key.ctrl && key.name === "u") {
        set({ editing: { ...editing, buffer: "" } });
      } else if (!key.ctrl && !key.meta && key.sequence.length === 1 && key.sequence >= " ") {
        set({ editing: { ...editing, buffer: editing.buffer + key.sequence } });
      }
      return;
    }
    const list = rows();
    const index = landing(list, local.current.index);
    const row = list[index];
    if (key.name === "escape" || key.name === "f2") {
      live.current.onClose();
    } else if (key.name === "tab") {
      const at = TABS.findIndex((entry) => entry.id === tab);
      switchTab((TABS[(at + (key.shift ? TABS.length - 1 : 1)) % TABS.length] as { id: Tab }).id);
    } else if (key.name === "up") {
      set({ index: landing(list, index - 1, -1) });
    } else if (key.name === "down") {
      set({ index: landing(list, index + 1, 1) });
    } else if (key.name === "left" && row) {
      change(row, -1);
    } else if (key.name === "right" && row) {
      change(row, 1);
    } else if ((key.name === "return" || key.name === "space") && row) {
      activate(row);
    } else if (key.name === "e" && row?.id === "model") {
      startEditing(row);
    }
  });

  usePaste((event) => {
    const editing = local.current.editing;
    if (editing) {
      const text = decodePasteBytes(event.bytes).replace(/[\r\n]+/g, "").trim();
      set({ editing: { ...editing, buffer: editing.buffer + text } });
    }
  });

  const { width, height } = props;
  const boxWidth = Math.min(DIALOG_WIDTH, Math.max(34, width - 4));
  const list = rows();
  const { tab, editing, status } = local.current;
  const index = landing(list, local.current.index);
  const selected = list[index];
  const narrow = boxWidth < 70;
  // The list is as tall as its rows until the terminal runs out, then it scrolls and follows the selection.
  const heights = list.map((row, position) => rowHeight(row, position === 0, boxWidth - (narrow ? 5 : 7)));
  const total = heights.reduce((sum, value) => sum + value, 0);
  const listHeight = Math.max(3, Math.min(total, height - CHROME_ROWS));
  const top = heights.slice(0, index).reduce((sum, value) => sum + value, 0);
  const bottom = top + (heights[index] ?? 1);
  useEffect(() => {
    const box = listBox.current;
    if (!box) {
      return;
    }
    if (top < box.scrollTop) {
      box.scrollTo(index === list.findIndex((row) => row.kind !== "header") ? 0 : top);
    } else if (bottom > box.scrollTop + listHeight) {
      box.scrollTo(bottom - listHeight);
    }
  }, [tab, top, bottom, listHeight]);

  return (
    <box
      position="absolute"
      top={0}
      left={0}
      width={width}
      height={height}
      zIndex={20}
      onMouseDown={props.onClose}
      alignItems="center"
      justifyContent="center"
    >
      <box
        width={boxWidth}
        flexDirection="column"
        border
        borderStyle="rounded"
        borderColor={theme.dim}
        backgroundColor={theme.panel}
        paddingX={narrow ? 1 : 2}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <box flexDirection="row" justifyContent="space-between" flexShrink={0}>
          <text selectable={false} fg={theme.text}>
            <b>⚙ settings</b>
          </text>
          <box onMouseDown={props.onClose}>
            <text selectable={false} fg={theme.dim}>✕ esc</text>
          </box>
        </box>
        <box flexDirection="row" flexShrink={0} marginTop={1}>
          {TABS.map((entry) => (
            <box key={entry.id} marginRight={narrow ? 0 : 1} backgroundColor={entry.id === tab ? theme.bubble : undefined} paddingX={1} onMouseDown={() => switchTab(entry.id)}>
              <text selectable={false} fg={entry.id === tab ? theme.text : theme.dim} wrapMode="none">
                {entry.id === tab ? "● " : "○ "}
                {entry.id === tab ? <b>{entry.label}</b> : entry.label}
              </text>
            </box>
          ))}
        </box>
        <text selectable={false} fg={theme.line} flexShrink={0} wrapMode="none">
          {"─".repeat(Math.max(10, boxWidth - (narrow ? 4 : 6)))}
        </text>
        {tab === "model" && props.control !== null && props.role === "host" ? <ReadyLine choice={local.current.choice} apiKey={currentKey()} settings={props.settings} /> : null}
        <scrollbox ref={listBox} height={listHeight} flexShrink={0} scrollbarOptions={{ showArrows: false, trackOptions: { foregroundColor: theme.line, backgroundColor: theme.panel } }}>
          {list.map((row, position) => (
            <RowView
              key={row.id}
              row={row}
              active={position === index}
              first={position === 0}
              editing={editing?.id === row.id ? editing.buffer : null}
              onClick={() => {
                set({ index: position });
                activate(row);
              }}
            />
          ))}
        </scrollbox>
        {editing?.id === "oauth_code" ? (
          <text selectable={false} fg={theme.accent}>Authorization code: {"•".repeat(Math.min(editing.buffer.length, 24))}▏</text>
        ) : null}
        <box flexDirection="column" flexShrink={0} marginTop={1}>
          {status ? <text selectable={false} fg={toneColor(status.tone)}>{status.text}</text> : <text selectable={false} fg={theme.muted}>{selected?.hint ?? ""}</text>}
          <text selectable={false} fg={theme.dim} wrapMode="none">
            {editing
              ? "type or paste · enter to keep · esc to cancel"
              : narrow
                ? "tab · ↑↓ · ←→ · enter · esc close"
                : "tab next tab · ↑↓ select · ←→ change · enter apply · esc close"}
          </text>
          <text selectable={false} fg={theme.dim} wrapMode="none">
            agent: {props.agent || "unknown"}
          </text>
        </box>
      </box>
    </box>
  );
}

function Value({ row, editing }: { row: Row; editing: string | null }) {
  if (editing !== null) {
    const shown = row.kind === "secret" ? maskKey(editing === "" ? "" : editing).replace("not set", "") : editing;
    return (
      <text selectable={false} fg={theme.accent}>
        {shown}▏
      </text>
    );
  }
  const chevrons = row.kind === "choice" && row.enabled;
  return (
    <text selectable={false} fg={row.enabled ? theme.text : theme.dim}>
      {chevrons ? "‹ " : ""}
      {row.value}
      {chevrons ? " ›" : ""}
    </text>
  );
}

function RowView({ row, active, editing, first, onClick }: { row: Row; active: boolean; editing: string | null; first: boolean; onClick: () => void }) {
  if (isTitle(row)) {
    return (
      <box marginTop={first ? 0 : 1} flexShrink={0}>
        <text selectable={false} fg={theme.muted}>
          <b>{row.label}</b>
        </text>
      </box>
    );
  }
  if (row.kind === "header") {
    return (
      <box marginTop={first ? 0 : 1} flexShrink={0}>
        <text selectable={false} fg={theme.muted}>
          <b>{row.label.toUpperCase()}</b>
        </text>
      </box>
    );
  }
  return (
    <box flexDirection="column" flexShrink={0} backgroundColor={active ? theme.bubble : undefined}>
      <RowBody row={row} active={active} editing={editing} onClick={onClick} />
    </box>
  );
}

function RowBody({ row, active, editing, onClick }: { row: Row; active: boolean; editing: string | null; onClick: () => void }) {
  const color = !row.enabled ? theme.dim : active ? theme.text : theme.muted;
  const marker = active ? "› " : "  ";
  if (row.kind === "note") {
    return <text selectable={false} fg={theme.dim}>{row.label}</text>;
  }
  if (row.kind === "radio") {
    return (
      <box flexDirection="column" onMouseDown={onClick}>
        <text selectable={false} fg={color}>
          {marker}
          {row.selected ? "(●) " : "( ) "}
          {row.label}
        </text>
        <box paddingLeft={DETAIL_INDENT}>
          <text selectable={false} fg={theme.dim} wrapMode="word">
            {row.description}
          </text>
        </box>
      </box>
    );
  }
  if (row.kind === "swatch") {
    return (
      <box flexDirection="row" justifyContent="space-between" onMouseDown={onClick}>
        <text selectable={false} fg={color}>
          {marker}
          {row.selected ? "(●) " : "( ) "}
          {row.label}
        </text>
        <text selectable={false}>
          {(row.colors ?? []).map((value, position) => (
            <span key={position} fg={value}>
              ██
            </span>
          ))}
        </text>
      </box>
    );
  }
  if (row.kind === "action") {
    return (
      <box onMouseDown={onClick}>
        <text selectable={false} fg={color}>
          {marker}
          {row.enabled ? "[ " : "  "}
          {row.label}
          {row.enabled ? " ]" : ""}
        </text>
      </box>
    );
  }
  return (
    <box flexDirection="row" justifyContent="space-between" onMouseDown={onClick}>
      <text selectable={false} fg={color}>
        {marker}
        {row.label}
      </text>
      <Value row={row} editing={editing} />
    </box>
  );
}

function ReadyLine({ choice, apiKey, settings }: { choice: AgentChoice; apiKey: string; settings: Settings }) {
  const preset = presetOf(choice.preset);
  const step = stepFor(preset, apiKey, hasOAuth(), settings.agentChoices);
  if (preset.provider === "fake") {
    return <text selectable={false} fg={theme.dim}>○ the demo agent follows a script. Pick a provider to use a real model</text>;
  }
  if (step.kind === "use") {
    return (
      <text selectable={false}>
        <span fg={theme.ok}>● </span>
        <span fg={theme.text}>{preset.label} is ready</span>
        <span fg={theme.dim}> · Save and use switches to it</span>
      </text>
    );
  }
  return (
    <text selectable={false}>
      <span fg={theme.warn}>○ </span>
      <span fg={theme.text}>{preset.label} needs a step: </span>
      <span fg={theme.warn}>{actionFor(preset, step).label}</span>
      <span fg={theme.dim}> · enter on Provider sets it up</span>
    </text>
  );
}
