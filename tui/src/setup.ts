import { missingFor, type ExtraStatus } from "./extras";
import { problemWith, type AgentChoice, type Preset } from "./presets";
import { toolFor, type ToolStatus } from "./tools";

export const POPULAR: readonly string[] = ["claude_code", "codex_cli", "anthropic", "openai", "gemini", "openrouter", "ollama", "demo"];

export const MORE = "__more";

export interface Group {
  title: string;
  items: Preset[];
}

const CONNECTION_TITLE = { oauth: "Your account", api_key: "API key", local: "Local" } as const;

export function listing(all: readonly Preset[], showAll: boolean, query: string): Group[] {
  const needle = query.trim().toLowerCase();
  if (needle !== "") {
    const found = all.filter((preset) => `${preset.label} ${preset.id} ${preset.hint}`.toLowerCase().includes(needle));
    return found.length === 0 ? [] : [{ title: "Matches", items: found }];
  }
  if (!showAll) {
    const items = POPULAR.map((id) => all.find((preset) => preset.id === id)).filter((preset): preset is Preset => preset !== undefined);
    return [{ title: "Popular", items }];
  }
  const groups: Group[] = (["oauth", "api_key", "local"] as const).map((connection) => ({
    title: CONNECTION_TITLE[connection],
    items: all.filter((preset) => preset.connection === connection && preset.provider !== "fake"),
  }));
  groups.push({ title: "Try it", items: all.filter((preset) => preset.provider === "fake") });
  return groups.filter((group) => group.items.length > 0);
}

export function flat(groups: readonly Group[], showAll: boolean, query: string): (Preset | typeof MORE)[] {
  const items: (Preset | typeof MORE)[] = groups.flatMap((group) => group.items);
  return showAll || query.trim() !== "" ? items : [...items, MORE];
}

export type Step =
  | { kind: "install_tool"; tool: ToolStatus }
  | { kind: "install_extra"; extra: ExtraStatus }
  | { kind: "oauth" }
  | { kind: "key" }
  | { kind: "settings"; problem: string }
  | { kind: "use" };

export function choiceFor(preset: Preset, saved: Partial<Record<string, AgentChoice>>): AgentChoice {
  return saved[preset.id] ?? { preset: preset.id, model: "", baseUrl: "", contextWindow: "" };
}

export function stepFor(preset: Preset, key: string, signedIn: boolean, saved: Partial<Record<string, AgentChoice>> = {}): Step {
  const tool = toolFor(preset);
  if (tool !== null && !tool.installed) {
    return { kind: "install_tool", tool };
  }
  const extra = missingFor(preset);
  if (extra !== null) {
    return { kind: "install_extra", extra };
  }
  if (preset.id === "anthropic_oauth" && !signedIn) {
    return { kind: "oauth" };
  }
  if (preset.needsKey && key.trim() === "") {
    return { kind: "key" };
  }
  const problem = problemWith(choiceFor(preset, saved), key);
  return problem === null ? { kind: "use" } : { kind: "settings", problem };
}

export type Mark = "ok" | "todo" | "info";

export interface Requirement {
  mark: Mark;
  label: string;
  detail: string;
}

export function checklist(preset: Preset, key: string, signedIn: boolean): Requirement[] {
  const items: Requirement[] = [];
  const tool = toolFor(preset);
  if (tool !== null) {
    items.push({ mark: tool.installed ? "ok" : "todo", label: tool.label, detail: tool.installed ? "installed" : "not installed" });
  }
  const extra = missingFor(preset);
  if (preset.extra) {
    items.push({ mark: extra === null ? "ok" : "todo", label: "Model SDK", detail: extra === null ? "installed" : "not installed" });
  }
  if (preset.id === "anthropic_oauth") {
    items.push({ mark: signedIn ? "ok" : "todo", label: "Claude account", detail: signedIn ? "signed in" : "not signed in" });
  }
  if (preset.needsKey) {
    items.push({ mark: key.trim() === "" ? "todo" : "ok", label: "API key", detail: key.trim() === "" ? "not set" : "saved on this machine" });
  }
  if (tool !== null && tool.installed) {
    items.push({ mark: "info", label: "Sign in", detail: `run ${tool.login} once, Plural checks it before switching` });
  }
  if (items.length === 0) {
    items.push({ mark: "ok", label: "Nothing to set up", detail: preset.provider === "fake" ? "a scripted agent to try the interface" : "ready" });
  }
  return items;
}

export interface Action {
  label: string;
  hint: string;
  enabled: boolean;
}

export function actionFor(preset: Preset, step: Step): Action {
  switch (step.kind) {
    case "install_tool":
      return step.tool.canInstall
        ? { label: `Install ${step.tool.label}`, hint: step.tool.command, enabled: true }
        : { label: `Install ${step.tool.label}`, hint: `npm was not found. Install Node.js, then run: ${step.tool.command}`, enabled: false };
    case "install_extra":
      return { label: `Install ${step.extra.label.split(" (")[0]}`, hint: "adds the SDK to the host, it takes a minute", enabled: true };
    case "oauth":
      return { label: "Sign in with Claude", hint: "opens your browser, then paste the code shown", enabled: true };
    case "key":
      return { label: "Enter your API key", hint: "it stays on this machine and goes only to your own host", enabled: true };
    case "settings":
      return { label: "Set it up in the menu", hint: step.problem, enabled: true };
    case "use":
      return preset.provider === "fake"
        ? { label: "Keep the demo agent", hint: "you can pick a real model any time in the menu", enabled: true }
        : { label: `Use ${preset.label}`, hint: "Plural sends one short test request first", enabled: true };
  }
}

export type Readiness = "ready" | "install" | "setup";

export function readiness(step: Step): Readiness {
  return step.kind === "use" ? "ready" : step.kind === "install_tool" || step.kind === "install_extra" ? "install" : "setup";
}
