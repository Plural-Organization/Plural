import { decodePasteBytes } from "@opentui/core";
import { useKeyboard, usePaste } from "@opentui/react";
import { useReducer, useRef } from "react";
import type { Role } from "@plural/client";
import type { AgentControl } from "../control";
import { beginOAuth, clearOAuth, exchangeCode, hasOAuth, openOAuth, saveOAuth, type OAuthAttempt } from "../anthropicOAuth";
import type { Keys } from "../credentials";
import { presetOf, problemWith, toConfig, type AgentChoice, type PresetId } from "../presets";
import type { Settings } from "../settings";
import { relayProblem, type ShareMode } from "../share";
import {
  friendlyError,
  maskKey,
  nextFast,
  nextModel,
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

export const DIALOG_WIDTH = 72;

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
}

export interface DialogProps {
  width: number;
  height: number;
  settings: Settings;
  mode: "open" | "review";
  role: Role | undefined;
  agent: string;
  room: string;
  control: AgentControl | null;
  keys: Keys;
  initialTab: Tab;
  welcome: boolean;
  onSettings: (next: Settings) => void;
  onKeys: (preset: PresetId, key: string, remember: boolean) => void;
  onMode: (mode: "open" | "review") => void;
  onInvite: () => void;
  admission?: "approve" | "open";
  onAdmission?: (mode: "approve" | "open") => void;
  onCopyReply: () => void;
  update?: UpdateState | null;
  onUpdate?: () => void;
  onClose: () => void;
}

const TONE = { ok: theme.ok, error: theme.danger, info: theme.dim } as const;

export function SettingsDialog(props: DialogProps) {
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
  });
  const live = useRef(props);
  live.current = props;

  const state = (): ModelState => ({
    settings: live.current.settings,
    choice: local.current.choice,
    keys: local.current.keys,
    mode: live.current.mode,
    admission: live.current.admission,
    role: live.current.role,
    canConfigure: live.current.control !== null && live.current.role === "host",
    oauthLoggedIn: hasOAuth(),
    update: live.current.update,
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
    if (editing.id === "oauth_code") {
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
      const switched = switchPreset(choice, local.current.savedChoices, direction, true);
      set({ choice: switched.choice, savedChoices: switched.saved, status: null });
    } else if (row.id === "model") {
      set({ choice: { ...choice, model: nextModel(choice, direction) }, status: null });
    } else if (row.id === "fast") {
      set({ choice: { ...choice, fastModel: nextFast(choice, direction) }, status: null });
    } else if (row.kind === "toggle") {
      toggleSetting(row.id);
    }
  };

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
        change(row, 1);
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
        if (row.id === "update") {
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

  const switchTab = (tab: Tab): void => set({ tab, index: 0, editing: null, status: null });

  useKeyboard((key) => {
    key.preventDefault();
    const { editing, tab, index } = local.current;
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
    const row = list[index];
    if (key.name === "escape" || key.name === "f2") {
      live.current.onClose();
    } else if (key.name === "tab") {
      const at = TABS.findIndex((entry) => entry.id === tab);
      switchTab((TABS[(at + (key.shift ? TABS.length - 1 : 1)) % TABS.length] as { id: Tab }).id);
    } else if (key.name === "up") {
      set({ index: (index + list.length - 1) % list.length });
    } else if (key.name === "down") {
      set({ index: (index + 1) % list.length });
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
  const { tab, index, editing, status } = local.current;
  const selected = list[index];
  void height;

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
        borderColor={theme.accent}
        backgroundColor={theme.panel}
        paddingX={2}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <box flexDirection="row" justifyContent="space-between">
          <text>
            <span fg={theme.accent}>
              <b>⚙ settings</b>
            </span>
          </text>
          <box onMouseDown={props.onClose}>
            <text fg={theme.dim}>✕ esc</text>
          </box>
        </box>
        {props.welcome ? (
          <text fg={theme.warn}>Welcome. Pick a model to start, or keep the demo agent for now.</text>
        ) : null}
        <text>{" "}</text>
        <box flexDirection="row">
          {TABS.map((entry) => (
            <box key={entry.id} marginRight={3} onMouseDown={() => switchTab(entry.id)}>
              <text fg={entry.id === tab ? theme.accent : theme.dim}>
                {entry.id === tab ? "● " : "○ "}
                {entry.id === tab ? <b>{entry.label}</b> : entry.label}
              </text>
            </box>
          ))}
        </box>
        <text fg={theme.line}>{"─".repeat(Math.max(10, boxWidth - 6))}</text>
        {list.map((row, position) => (
          <RowView
            key={row.id}
            row={row}
            active={position === index}
            editing={editing?.id === row.id ? editing.buffer : null}
            onClick={() => {
              set({ index: position });
              activate(row);
            }}
          />
        ))}
        {editing?.id === "oauth_code" ? (
          <text fg={theme.accent}>Authorization code: {"•".repeat(Math.min(editing.buffer.length, 24))}▏</text>
        ) : null}
        <text>{" "}</text>
        {status ? <text fg={TONE[status.tone]}>{status.text}</text> : <text fg={theme.dim}>{selected?.hint ?? ""}</text>}
        <text fg={theme.dim}>
          {editing ? "type or paste · enter to keep · esc to cancel" : "tab next tab · ↑↓ select · ←→ change · enter apply · esc close"}
        </text>
        <text fg={theme.dim}>agent: {props.agent || "unknown"}</text>
      </box>
    </box>
  );
}

function Value({ row, editing }: { row: Row; editing: string | null }) {
  if (editing !== null) {
    const shown = row.kind === "secret" ? maskKey(editing === "" ? "" : editing).replace("not set", "") : editing;
    return (
      <text fg={theme.accent}>
        {shown}▏
      </text>
    );
  }
  const chevrons = row.kind === "choice" && row.enabled;
  return (
    <text fg={row.enabled ? theme.text : theme.dim}>
      {chevrons ? "‹ " : ""}
      {row.value}
      {chevrons ? " ›" : ""}
    </text>
  );
}

function RowView({ row, active, editing, onClick }: { row: Row; active: boolean; editing: string | null; onClick: () => void }) {
  const color = !row.enabled ? theme.dim : active ? theme.accent : theme.text;
  const marker = active ? "› " : "  ";
  if (row.kind === "note") {
    return <text fg={theme.dim}>{row.label}</text>;
  }
  if (row.kind === "radio") {
    return (
      <box flexDirection="column" onMouseDown={onClick}>
        <text fg={color}>
          {marker}
          {row.selected ? "(●) " : "( ) "}
          {row.label}
        </text>
        <text fg={theme.dim}>
          {"      "}
          {row.description}
        </text>
      </box>
    );
  }
  if (row.kind === "swatch") {
    return (
      <box flexDirection="row" justifyContent="space-between" onMouseDown={onClick}>
        <text fg={color}>
          {marker}
          {row.selected ? "(●) " : "( ) "}
          {row.label}
        </text>
        <text>
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
        <text fg={color}>
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
      <text fg={color}>
        {marker}
        {row.label}
      </text>
      <Value row={row} editing={editing} />
    </box>
  );
}

export { THEME_NAMES };
