import { decodePasteBytes } from "@opentui/core";
import { useKeyboard, usePaste } from "@opentui/react";
import { useReducer, useRef, type ReactNode } from "react";
import { beginOAuth, exchangeCode, hasOAuth, openOAuth, saveOAuth, type OAuthAttempt } from "../anthropicOAuth";
import type { AgentControl } from "../control";
import type { Keys } from "../credentials";
import { setExtras } from "../extras";
import { truncate } from "../lib/wrap";
import { presets, toConfig, type AgentChoice, type Preset } from "../presets";
import type { Settings } from "../settings";
import { friendlyError, maskKey } from "../settingsModel";
import { actionFor, checklist, choiceFor, flat, listing, MORE, readiness, stepFor, type Mark, type Readiness, type Step } from "../setup";
import { theme } from "../theme";
import { setTools } from "../tools";

export interface SetupDialogProps {
  width: number;
  height: number;
  control: AgentControl;
  settings: Settings;
  keys: Keys;
  first: boolean;
  current: string;
  onApplied: (choice: AgentChoice, key: string, label: string) => void;
  onSettings: (preset: string) => void;
  onClose: () => void;
}

type Tone = "ok" | "error" | "info";

interface Editing {
  id: "key" | "oauth_code";
  buffer: string;
}

interface Local {
  index: number;
  showAll: boolean;
  query: string;
  editing: Editing | null;
  keys: Keys;
  busy: boolean;
  status: { tone: Tone; text: string } | null;
  attempt: OAuthAttempt | null;
  signedIn: boolean;
}

type Line = { kind: "header"; text: string } | { kind: "item"; item: Preset | typeof MORE; at: number };

const TONE = { ok: theme.ok, error: theme.danger, info: theme.dim } as const;
const LEFT = 32;
const MAX_WIDTH = 104;
const MAX_HEIGHT = 30;

function glyphOf(state: Readiness): { mark: string; color: string } {
  return state === "ready" ? { mark: "●", color: theme.ok } : state === "install" ? { mark: "↓", color: theme.accent } : { mark: "○", color: theme.dim };
}

function markOf(mark: Mark): { glyph: string; color: string } {
  return mark === "ok" ? { glyph: "✓", color: theme.ok } : mark === "todo" ? { glyph: "✕", color: theme.warn } : { glyph: "·", color: theme.dim };
}

export function SetupDialog(props: SetupDialogProps) {
  const [, redraw] = useReducer((value: number) => value + 1, 0);
  const local = useRef<Local>({
    index: 0,
    showAll: !props.first,
    query: "",
    editing: null,
    keys: { ...props.keys },
    busy: false,
    status: null,
    attempt: null,
    signedIn: hasOAuth(),
  });
  const live = useRef(props);
  live.current = props;
  if (local.current.index === 0 && !props.first && local.current.query === "" && local.current.status === null) {
    const at = flat(listing(presets(), true, ""), true, "").findIndex((item) => item !== MORE && item.id === props.current);
    local.current = { ...local.current, index: Math.max(0, at) };
  }

  const set = (patch: Partial<Local>): void => {
    local.current = { ...local.current, ...patch };
    redraw();
  };
  const say = (tone: Tone, text: string): void => set({ status: { tone, text } });

  const items = () => {
    const { showAll, query } = local.current;
    return flat(listing(presets(), showAll, query), showAll, query);
  };
  const selected = (): Preset | typeof MORE | undefined => {
    const all = items();
    return all[Math.min(local.current.index, Math.max(0, all.length - 1))];
  };
  const stepOf = (preset: Preset): Step => stepFor(preset, local.current.keys[preset.id] ?? "", local.current.signedIn, live.current.settings.agentChoices);

  const refresh = async (): Promise<void> => {
    const control = live.current.control;
    setTools((await control.tools?.()) ?? []);
    setExtras(await control.extras());
  };

  const install = async (label: string, run: () => Promise<{ ok: boolean; error?: string }>): Promise<void> => {
    set({ busy: true, status: { tone: "info", text: `installing ${label}… this can take a minute` } });
    const result = await run();
    await refresh();
    set({ busy: false, status: result.ok ? { tone: "ok", text: `✓ ${label} installed` } : { tone: "error", text: friendlyError(result.error ?? "the install did not work") } });
  };

  const apply = async (preset: Preset): Promise<void> => {
    const control = live.current.control;
    const key = local.current.keys[preset.id] ?? "";
    const choice = choiceFor(preset, live.current.settings.agentChoices);
    const config = toConfig(choice, key);
    set({ busy: true, status: { tone: "info", text: preset.provider === "fake" ? "switching…" : "checking the connection…" } });
    if (preset.provider !== "fake") {
      const test = await control.test(config);
      if (!test.ok) {
        set({ busy: false, status: { tone: "error", text: friendlyError(test.error ?? "the model did not answer") } });
        return;
      }
    }
    const result = await control.configure(config);
    if (!result.ok) {
      set({ busy: false, status: { tone: "error", text: friendlyError(result.error ?? "it did not work") } });
      return;
    }
    set({ busy: false });
    live.current.onApplied({ ...choice, model: choice.model || preset.models[0] || "" }, key, result.agent ?? preset.label);
  };

  const perform = async (): Promise<void> => {
    const item = selected();
    if (item === undefined || local.current.busy) {
      return;
    }
    if (item === MORE) {
      set({ showAll: true, index: 0, status: null });
      return;
    }
    const step = stepOf(item);
    const control = live.current.control;
    switch (step.kind) {
      case "install_tool":
        if (!step.tool.canInstall) {
          say("error", `npm was not found. Install Node.js, then run: ${step.tool.command}`);
        } else if (control.installTool === undefined) {
          say("error", `this host cannot install it, run: ${step.tool.command}`);
        } else {
          await install(step.tool.label, () => control.installTool!(step.tool.id));
        }
        break;
      case "install_extra":
        await install(step.extra.label.split(" (")[0] ?? step.extra.label, () => control.install(step.extra.id));
        break;
      case "oauth": {
        const attempt = beginOAuth();
        set({ attempt, editing: { id: "oauth_code", buffer: "" }, status: { tone: "info", text: "Claude sign in opened and its address copied. Paste the code here" } });
        void openOAuth(attempt);
        break;
      }
      case "key":
        set({ editing: { id: "key", buffer: "" }, status: null });
        break;
      case "settings":
        live.current.onSettings(item.id);
        break;
      case "use":
        await apply(item);
        break;
    }
  };

  const commit = (editing: Editing): void => {
    const item = selected();
    const value = editing.buffer.trim();
    if (editing.id === "key" && item !== undefined && item !== MORE) {
      set({ editing: null, keys: { ...local.current.keys, [item.id]: value }, status: null });
    } else if (editing.id === "oauth_code") {
      const attempt = local.current.attempt;
      if (attempt === null) {
        return;
      }
      set({ editing: null, busy: true, status: { tone: "info", text: "finishing Claude sign in…" } });
      void exchangeCode(value, attempt.verifier)
        .then((credentials) => {
          saveOAuth(credentials);
          set({ busy: false, attempt: null, signedIn: true, status: { tone: "ok", text: "✓ signed in to Claude" } });
        })
        .catch((error: unknown) => {
          set({ busy: false, attempt: null, status: { tone: "error", text: friendlyError(error instanceof Error ? error.message : String(error)) } });
        });
    }
  };

  useKeyboard((key) => {
    key.preventDefault();
    const { editing, busy, query, index, showAll } = local.current;
    if (busy) {
      return;
    }
    if (editing) {
      if (key.name === "escape") {
        set({ editing: null, attempt: editing.id === "oauth_code" ? null : local.current.attempt });
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
    const count = items().length;
    if (key.name === "escape") {
      if (query !== "") {
        set({ query: "", index: 0 });
      } else {
        live.current.onClose();
      }
    } else if (key.name === "up") {
      set({ index: (index + count - 1) % Math.max(1, count) });
    } else if (key.name === "down") {
      set({ index: (index + 1) % Math.max(1, count) });
    } else if (key.name === "return") {
      void perform();
    } else if (key.name === "tab") {
      set({ showAll: !showAll, index: 0, query: "" });
    } else if (key.name === "backspace") {
      set({ query: query.slice(0, -1), index: 0 });
    } else if (!key.ctrl && !key.meta && key.sequence.length === 1 && key.sequence >= " ") {
      set({ query: query + key.sequence, index: 0 });
    }
  });

  usePaste((event) => {
    const editing = local.current.editing;
    if (editing) {
      set({ editing: { ...editing, buffer: editing.buffer + decodePasteBytes(event.bytes).replace(/[\r\n]+/g, "").trim() } });
    }
  });

  const boxWidth = Math.min(MAX_WIDTH, Math.max(50, props.width - 4));
  const { showAll, query, editing, busy, status } = local.current;
  const groups = listing(presets(), showAll, query);
  const listLines = groups.reduce((sum, group) => sum + 1 + group.items.length, 0) + (showAll || query.trim() !== "" ? 0 : 1);
  const boxHeight = Math.min(MAX_HEIGHT, Math.max(24, listLines + 9), Math.max(14, props.height - 2));
  const all = items();
  const sel = Math.min(local.current.index, Math.max(0, all.length - 1));
  const item = all[sel];

  const lines: Line[] = [];
  let at = 0;
  for (const group of groups) {
    lines.push({ kind: "header", text: group.title });
    for (const preset of group.items) {
      lines.push({ kind: "item", item: preset, at: at++ });
    }
  }
  if (!showAll && query.trim() === "") {
    lines.push({ kind: "item", item: MORE, at: at++ });
  }
  const room = Math.max(5, boxHeight - 9);
  const selectedLine = Math.max(0, lines.findIndex((line) => line.kind === "item" && line.at === sel));
  const first = Math.max(0, Math.min(selectedLine - Math.floor(room / 2), lines.length - room));
  const visible = lines.slice(first, first + room);

  const detail = (): ReactNode => {
    if (item === undefined) {
      return <text fg={theme.dim}>No provider matches "{query}".</text>;
    }
    if (item === MORE) {
      return (
        <>
          <text fg={theme.text}>
            <b>More providers</b>
          </text>
          <text fg={theme.dim} wrapMode="word">
            Every provider the host supports: API-key services, accounts, local models. Enter or tab shows them all.
          </text>
          <text> </text>
          <Button label="Show all providers" enabled onPress={() => void perform()} />
        </>
      );
    }
    const key = local.current.keys[item.id] ?? "";
    const step = stepOf(item);
    const action = actionFor(item, step);
    const prompt = editing?.id === "oauth_code" ? "Claude code" : "API key";
    return (
      <>
        <text fg={theme.text}>
          <b>{item.label}</b>
        </text>
        <text fg={theme.dim} wrapMode="word">
          {item.hint}
        </text>
        <text> </text>
        {checklist(item, key, local.current.signedIn).map((requirement) => {
          const mark = markOf(requirement.mark);
          return (
            <text key={requirement.label} wrapMode="word">
              <span fg={mark.color}>{mark.glyph} </span>
              <span fg={theme.text}>{requirement.label}</span>
              <span fg={theme.dim}>  {requirement.detail}</span>
            </text>
          );
        })}
        <text> </text>
        {editing ? (
          <text fg={theme.accent}>
            {prompt}: {"•".repeat(Math.min(editing.buffer.length, 28))}▏
          </text>
        ) : (
          <Button label={action.label} enabled={action.enabled && !busy} onPress={() => void perform()} />
        )}
        <text fg={theme.dim} wrapMode="word">
          {editing ? "paste or type, enter to keep, esc to cancel" : key !== "" && item.needsKey ? `${action.hint} · key ${maskKey(key)}` : action.hint}
        </text>
      </>
    );
  };

  return (
    <box position="absolute" top={0} left={0} width={props.width} height={props.height} zIndex={30} alignItems="center" justifyContent="center" backgroundColor={theme.bg}>
      <box width={boxWidth} height={boxHeight} flexDirection="column" border borderStyle="rounded" borderColor={theme.accent} backgroundColor={theme.panel} paddingX={2} paddingY={1} onMouseDown={(event) => event.stopPropagation()}>
        <text flexShrink={0}>
          <span fg={theme.accent}>
            <b>{props.first ? "Welcome to Plural" : "Choose a provider"}</b>
          </span>
        </text>
        <text fg={theme.dim} flexShrink={0}>
          {props.first ? "Pick the agent that will do the work. You can change it any time in the menu." : "Plural shows what a provider still needs and sets it up for you."}
        </text>
        {query !== "" ? (
          <text fg={theme.info} flexShrink={0}>
            search: {query}
          </text>
        ) : (
          <text flexShrink={0}> </text>
        )}
        <box flexDirection="row" flexGrow={1}>
          <box width={LEFT} flexShrink={0} flexDirection="column" paddingRight={1} border={["right"]} borderStyle="single" borderColor={theme.line}>
            {visible.map((line, position) =>
              line.kind === "header" ? (
                <text key={`h${position}`} fg={theme.dim}>
                  {line.text.toUpperCase()}
                </text>
              ) : (
                <ProviderRow key={line.item === MORE ? MORE : line.item.id} item={line.item} on={line.at === sel} state={line.item === MORE ? null : readiness(stepOf(line.item))} onPress={() => set({ index: line.at })} />
              ),
            )}
            {lines.length === 0 ? <text fg={theme.dim}>nothing found</text> : null}
          </box>
          <box flexGrow={1} flexShrink={1} flexDirection="column" paddingLeft={2}>
            {detail()}
            {status ? (
              <>
                <text> </text>
                <text fg={TONE[status.tone]} wrapMode="word">
                  {status.text}
                </text>
              </>
            ) : null}
          </box>
        </box>
        <text fg={theme.dim} flexShrink={0}>
          {busy ? "working, please wait" : `↑↓ choose · enter continue · tab ${showAll ? "popular" : "all providers"} · type to search · esc ${props.first ? "skip for now" : "close"}`}
        </text>
      </box>
    </box>
  );
}

function ProviderRow({ item, on, state, onPress }: { item: Preset | typeof MORE; on: boolean; state: Readiness | null; onPress: () => void }) {
  const glyph = state === null ? { mark: "→", color: theme.dim } : glyphOf(state);
  const label = item === MORE ? "More providers…" : item.label;
  return (
    <box flexDirection="row" justifyContent="space-between" backgroundColor={on ? theme.bg : undefined} onMouseDown={onPress}>
      <text fg={on ? theme.accent : theme.text}>
        {on ? "› " : "  "}
        {truncate(label, LEFT - 8)}
      </text>
      <text fg={glyph.color}>{glyph.mark}</text>
    </box>
  );
}

function Button({ label, enabled, onPress }: { label: string; enabled: boolean; onPress: () => void }) {
  return (
    <box alignSelf="flex-start" paddingX={2} backgroundColor={enabled ? theme.accent : theme.line} onMouseDown={onPress}>
      <text fg={enabled ? theme.bg : theme.dim}>
        <b>{label}</b>
      </text>
    </box>
  );
}
