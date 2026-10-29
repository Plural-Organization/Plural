import type { Role } from "@plural/client";
import type { Keys } from "./credentials";
import { PRESETS, presetOf, type AgentChoice, type PresetId } from "./presets";
import type { Settings } from "./settings";
import type { UpdateState } from "./update";
import { relayProblem, type ShareMode } from "./share";
import { THEMES, THEME_NAMES } from "./theme";

export type Tab = "model" | "session" | "appearance";

export const TABS: { id: Tab; label: string }[] = [
  { id: "model", label: "Model" },
  { id: "session", label: "Session" },
  { id: "appearance", label: "Appearance" },
];

export type RowKind = "choice" | "toggle" | "text" | "secret" | "action" | "radio" | "swatch" | "note";

export interface Row {
  id: string;
  kind: RowKind;
  label: string;
  value: string;
  hint: string;
  enabled: boolean;
  description?: string;
  selected?: boolean;
  colors?: string[];
}

export interface ModelState {
  settings: Settings;
  choice: AgentChoice;
  keys: Keys;
  mode: "open" | "review";
  admission?: "approve" | "open";
  role: Role | undefined;
  canConfigure: boolean;
  oauthLoggedIn?: boolean;
  update?: UpdateState | null;
}

export function updateRows(update: UpdateState | null | undefined): Row[] {
  if (!update) {
    return [];
  }
  const hint = {
    ready: "install it now, then start plural again",
    installing: "downloading and installing, this takes a moment",
    installed: "installed, quit and start plural again to use it",
    failed: `the installer exited with code ${update.phase === "failed" ? update.code : 0}, press enter to try again or run plural update`,
  }[update.phase];
  const label = {
    ready: `● update ready · ${update.version}`,
    installing: `↻ updating to ${update.version}…`,
    installed: `✓ ${update.version} installed · restart plural`,
    failed: `✕ update to ${update.version} failed`,
  }[update.phase];
  return [{ id: "update", kind: "action", label, value: "", hint, enabled: update.phase === "ready" || update.phase === "failed" }];
}

export function maskKey(key: string): string {
  if (key === "") {
    return "not set";
  }
  return key.length <= 8 ? "•".repeat(key.length) : `${"•".repeat(Math.min(key.length - 4, 16))}${key.slice(-4)}`;
}

function toggle(id: string, label: string, value: boolean, hint: string, enabled = true): Row {
  return { id, kind: "toggle", label, value: value ? "on" : "off", hint, enabled };
}

export function modelRows(state: ModelState): Row[] {
  const { choice, settings, keys } = state;
  if (!state.canConfigure) {
    return [
      {
        id: "owned",
        kind: "note",
        label: "The agent belongs to the host",
        value: "",
        hint: "only the host chooses the model and holds its credentials",
        enabled: false,
      },
    ];
  }
  const preset = presetOf(choice.preset);
  const rows: Row[] = [
    { id: "connection", kind: "choice", label: "Connection type", value: connectionLabel(preset.connection), hint: "OAuth sign-in, API key, or a local model", enabled: true },
    { id: "preset", kind: "choice", label: "Provider", value: preset.label, hint: preset.hint, enabled: true },
  ];
  if (preset.needsKey || choice.preset === "custom") {
    rows.push({
      id: "key",
      kind: "secret",
      label: preset.needsKey ? "API key" : "API key (optional)",
      value: maskKey(keys[choice.preset] ?? ""),
      hint: "enter to type or paste, it stays on this machine and goes only to your own host",
      enabled: true,
    });
  }
  if (choice.preset === "anthropic_oauth") {
    rows.push({
      id: "oauth-login", kind: "action", label: state.oauthLoggedIn ? "Sign in again" : "Sign in with Claude",
      value: state.oauthLoggedIn ? "connected" : "", hint: "open Claude in your browser; paste the code shown after sign in",
      enabled: true,
    });
    if (state.oauthLoggedIn) {
      rows.push({ id: "oauth-logout", kind: "action", label: "Sign out", value: "", hint: "remove the saved Claude login from this machine", enabled: true });
    }
  }
  if (choice.preset === "claude_code") {
    rows.push({
      id: "claude-code-login", kind: "note", label: "Login: run claude auth login in a terminal",
      value: "", hint: "Claude Code uses its own saved sign-in", enabled: false,
    });
  }
  if (choice.preset === "codex_cli") {
    rows.push({
      id: "codex-cli-login", kind: "note", label: "Install: npm install -g @openai/codex",
      value: "", hint: "install on the host, then run codex login; Save checks both before switching", enabled: false,
    });
  }
  if (preset.provider !== "fake") {
    rows.push({
      id: "model",
      kind: preset.models.length > 0 ? "choice" : "text",
      label: "Model",
      value: choice.model || preset.models[0] || "not set",
      hint: preset.id === "azure"
        ? "enter the Azure deployment name"
        : preset.models.length > 0 ? `← → choose a model (${preset.models.length} options); press e to type another ID` : "enter to type the model id",
      enabled: true,
    });
  }
  if (preset.provider !== "fake") {
    const fast = choice.fastModel ?? "";
    rows.push({
      id: "fast",
      kind: "choice",
      label: "Fast model",
      value: fast === "" ? "auto" : fast,
      hint:
        fast === ""
          ? "← → choose · auto picks a cheaper model you can reach for summaries and sub-agents"
          : fast === "off"
            ? "← → choose · off keeps summaries and sub-agents on the main model"
            : "← → choose · summaries and sub-agents run on this model",
      enabled: true,
    });
  }
  if (preset.editableUrl) {
    rows.push({
      id: "url",
      kind: "text",
      label: "Endpoint",
      value: choice.baseUrl || preset.baseUrl || "not set",
      hint: preset.id === "azure"
        ? "Azure resource URL ending in /openai/v1/"
        : preset.id === "amazon_bedrock"
          ? "Bedrock runtime URL for your region, ending in /openai/v1"
          : "the address of an OpenAI-compatible server, for example http://127.0.0.1:11434/v1",
      enabled: true,
    });
  }
  if (preset.contextWindow) {
    rows.push({
      id: "window",
      kind: "text",
      label: "Context window",
      value: choice.contextWindow || "default (128000)",
      hint: "tokens the server really accepts, so long chats are summarised in time",
      enabled: true,
    });
  }
  if (preset.needsKey || choice.preset === "custom") {
    rows.push(toggle("remember", "Remember the key", settings.rememberKey, "keep it in ~/.plural/credentials.json, readable only by you"));
  }
  rows.push({ id: "test", kind: "action", label: "Test connection", value: "", hint: "send a short real request and see if the model answers", enabled: preset.provider !== "fake" });
  rows.push({ id: "save", kind: "action", label: "Save and use", value: "", hint: "switch the agent now, the conversation is kept", enabled: true });
  return rows;
}

const SHARING: { mode: ShareMode; label: string; description: string }[] = [
  { mode: "local", label: "This machine", description: "only you. Invite links work on this computer, good for trying things out" },
  { mode: "network", label: "Same network", description: "teammates on your Wi-Fi, office network or VPN join with a link that carries your network address" },
  { mode: "relay", label: "Over the internet", description: "through a relay server, so nobody needs an open port. Needs the address of a relay" },
];

function joiningRows(state: ModelState, host: boolean): Row[] {
  const admission = state.admission ?? "approve";
  const hint = host ? "applies to the next person who uses the room link" : "only the host chooses who may join";
  return [
    { id: "joining-title", kind: "note", label: "People who use the room link", value: "", hint: "/invite copies it, it never expires", enabled: false },
    {
      id: "join-approve",
      kind: "radio",
      label: "I let each person in",
      value: "",
      description: "they wait until you answer, and you choose whether they take part or only watch",
      hint,
      selected: admission === "approve",
      enabled: host,
    },
    {
      id: "join-open",
      kind: "radio",
      label: "Anyone with the link joins at once",
      value: "",
      description: "for a team you trust: the link is as good as a password, so keep it private",
      hint,
      selected: admission === "open",
      enabled: host,
    },
  ];
}

function shareRows(state: ModelState, host: boolean): Row[] {
  const rows: Row[] = [
    { id: "share-title", kind: "note", label: "Who can join", value: "", hint: "how the invite link reaches your teammates", enabled: false },
    ...SHARING.map(
    (entry): Row => ({
      id: `share-${entry.mode}`,
      kind: "radio",
      label: entry.label,
      value: "",
      description: entry.description,
      hint: host ? "takes effect the next time you start plural" : "only the host chooses how the room is shared",
      selected: state.settings.share === entry.mode,
      enabled: host,
    }),
    ),
  ];
  if (state.settings.share === "relay") {
    const problem = state.settings.relayUrl === "" ? null : relayProblem(state.settings.relayUrl);
    rows.push({
      id: "relay",
      kind: "text",
      label: "Relay address",
      value: state.settings.relayUrl || "not set",
      hint: problem ?? "for example wss://relay.example.com, see docs/self-hosting.md",
      enabled: host,
    });
  }
  return rows;
}

export function sessionRows(state: ModelState): Row[] {
  const host = state.role === "host";
  const viewer = state.role === "viewer";
  return [
    {
      id: "mode-open",
      kind: "radio",
      label: "Open",
      value: "",
      description: "everyone in the room prompts the agent directly. Tool calls still wait for you",
      hint: host ? "best for a team that trusts each other" : "only the host can change this",
      selected: state.mode === "open",
      enabled: host,
    },
    {
      id: "mode-review",
      kind: "radio",
      label: "Host approves",
      value: "",
      description: "participants propose, you approve, edit or reject every prompt first",
      hint: host ? "the most careful mode" : "only the host can change this",
      selected: state.mode === "review",
      enabled: host,
    },
    ...joiningRows(state, host),
    ...shareRows(state, host),
    toggle("typing", "Show my typing", state.settings.announceTyping, "let others see when you are writing", !viewer),
    toggle("mention-bell", "Bell on mentions", state.settings.mentionBell, "play a sound when someone tags you or writes to you privately", !viewer),
    toggle("bell", "Bell on requests", state.settings.bell, "play a sound when something needs the host", host),
    toggle("join-bell", "Bell on joins", state.settings.joinBell, "play a sound when someone joins your room", host),
  ];
}

export function appearanceRows(state: ModelState): Row[] {
  const themes = THEME_NAMES.map((name): Row => {
    const colors = THEMES[name].colors;
    return {
      id: `theme:${name}`,
      kind: "swatch",
      label: THEMES[name].label,
      value: "",
      hint: "colours of the whole interface",
      selected: state.settings.theme === name,
      enabled: true,
      colors: [colors.accent, colors.ok, colors.warn, colors.danger, colors.info, colors.code],
    };
  });
  return [
    ...themes,
    toggle("panel", "Side panel", state.settings.panel, "participants, queue and approvals (ctrl+b)"),
    toggle("copy", "Copy on select", state.settings.copyOnSelect, "selecting text puts it on the clipboard"),
    { id: "reply", kind: "action", label: "Copy the last reply", value: "", hint: "put the agent's last answer on the clipboard", enabled: true },
    { id: "invite", kind: "action", label: "Copy the room link", value: "", hint: "the permanent link, you let people in", enabled: state.role === "host" },
  ];
}

export function rowsFor(tab: Tab, state: ModelState): Row[] {
  return [...updateRows(state.update), ...tabRows(tab, state)];
}

function tabRows(tab: Tab, state: ModelState): Row[] {
  switch (tab) {
    case "model":
      return modelRows(state);
    case "session":
      return sessionRows(state);
    case "appearance":
      return appearanceRows(state);
  }
}

export function nextPreset(current: AgentChoice["preset"], direction: 1 | -1): AgentChoice["preset"] {
  const index = PRESETS.findIndex((preset) => preset.id === current);
  return (PRESETS[(index + direction + PRESETS.length) % PRESETS.length] ?? PRESETS[0]!).id;
}

export type ConnectionType = "oauth" | "api_key" | "local";

export function connectionLabel(connection: ConnectionType): string {
  return connection === "oauth" ? "OAuth / account" : connection === "api_key" ? "API key" : "Local / demo";
}

export function nextConnection(current: AgentChoice["preset"], direction: 1 | -1): AgentChoice["preset"] {
  const groups: ConnectionType[] = ["oauth", "api_key", "local"];
  const currentGroup = presetOf(current).connection;
  const currentIndex = groups.indexOf(currentGroup);
  for (let offset = 1; offset <= groups.length; offset++) {
    const group = groups[(currentIndex + direction * offset + groups.length * 2) % groups.length]!;
    const candidate = PRESETS.find((preset) => preset.connection === group);
    if (candidate) return candidate.id;
  }
  return current;
}

export function nextPresetInConnection(current: AgentChoice["preset"], direction: 1 | -1): AgentChoice["preset"] {
  const choices = PRESETS.filter((preset) => preset.connection === presetOf(current).connection);
  const index = choices.findIndex((preset) => preset.id === current);
  return choices[(index + direction + choices.length) % choices.length]!.id;
}

export function fastOptions(choice: AgentChoice): string[] {
  return ["", "off", ...presetOf(choice.preset).models.filter((model) => model !== (choice.model || presetOf(choice.preset).models[0]))];
}

export function nextFast(choice: AgentChoice, direction: 1 | -1): string {
  const options = fastOptions(choice);
  const index = Math.max(0, options.indexOf(choice.fastModel ?? ""));
  return options[(index + direction + options.length) % options.length] as string;
}

export function nextModel(choice: AgentChoice, direction: 1 | -1): string {
  const models = presetOf(choice.preset).models;
  if (models.length === 0) {
    return choice.model;
  }
  const index = models.indexOf(choice.model);
  return models[(index === -1 ? (direction === 1 ? 0 : models.length - 1) : (index + direction + models.length) % models.length)] as string;
}

export function switchPreset(
  choice: AgentChoice,
  saved: Partial<Record<PresetId, AgentChoice>>,
  direction: 1 | -1,
  withinConnection = false,
): { choice: AgentChoice; saved: Partial<Record<PresetId, AgentChoice>> } {
  const preset = withinConnection
    ? nextPresetInConnection(choice.preset, direction)
    : nextPreset(choice.preset, direction);
  const nextSaved = { ...saved, [choice.preset]: choice };
  return {
    choice: nextSaved[preset] ?? { preset, model: presetOf(preset).models[0] ?? "", baseUrl: "", contextWindow: "" },
    saved: nextSaved,
  };
}

export function switchConnection(
  choice: AgentChoice,
  saved: Partial<Record<PresetId, AgentChoice>>,
  direction: 1 | -1,
): { choice: AgentChoice; saved: Partial<Record<PresetId, AgentChoice>> } {
  const preset = nextConnection(choice.preset, direction);
  return {
    choice: saved[preset] ?? { preset, model: presetOf(preset).models[0] ?? "", baseUrl: "", contextWindow: "" },
    saved: { ...saved, [choice.preset]: choice },
  };
}

export function friendlyError(text: string): string {
  const status = /\b([45]\d\d)\b/.exec(text)?.[1];
  const message = /'message': '([^']+)'/.exec(text)?.[1] ?? /"message": "([^"]+)"/.exec(text)?.[1];
  if (status === "401" || status === "403") {
    return `the key was refused (${status})${message ? `: ${message}` : ""}`;
  }
  if (message) {
    return status ? `${status}: ${message}` : message;
  }
  return text.length > 200 ? `${text.slice(0, 199)}…` : text;
}
