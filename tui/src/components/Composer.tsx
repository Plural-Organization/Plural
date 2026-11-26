import { decodePasteBytes, stripAnsiSequences, type KeyBinding, type PasteEvent, type TextareaRenderable } from "@opentui/core";
import { useKeyboard } from "@opentui/react";
import { useEffect, useRef, useState } from "react";
import { historyView, leave, MAX_HISTORY, newer, NOT_BROWSING, older, remember, type Browsing, type Mentionable, type Role, type Route } from "@plural/client";
import { suggestions as suggest, visibleSuggestionWindow, type AskTarget, type CommandHint } from "../commands";
import { imagePath } from "../lib/image-paste";
import { expandPastes, pasteLabel, shouldCollapse } from "../lib/paste";
import { theme } from "../theme";

export type Delivery = { state: "sending" } | { state: "sent" } | { state: "failed"; reason: string; restored: boolean };

const ROUTE_COLORS = (): Record<Route["kind"], string> => ({ agent: theme.accent, room: theme.info, person: theme.ok, command: theme.dim });

function Failure({ delivery }: { delivery: Extract<Delivery, { state: "failed" }> }) {
  return (
    <box flexDirection="row" height={1}>
      <text fg={theme.danger} wrapMode="none">
        ✕ not sent: {delivery.reason.slice(0, 60)} · {delivery.restored ? "your text is back in the box" : "↑ brings it back"}
      </text>
    </box>
  );
}

interface ComposerProps {
  focused: boolean;
  placeholder: string;
  role: Role | undefined;
  people?: Mentionable[];
  commands?: CommandHint[];
  askTargets?: AskTarget[];
  seed: { text: string; key: number } | null;
  label: string | null;
  route?: (text: string) => Route | null;
  delivery?: Delivery | null;
  onSubmit: (text: string) => void;
  onEscape: () => void;
  onTab: () => void;
  onCycleMode: () => void;
  onInterrupt: () => void;
  onCopy: () => void;
  onDirty: (dirty: boolean) => void;
  onActivity: (text: string) => void;
  onFocus: () => void;
  onIdleKey?: (key: string) => boolean;
  images?: string[];
  onPasteImage?: () => void;
  onPasteImageFile?: (path: string) => Promise<boolean>;
  onDropImage?: () => void;
  remember?: boolean;
  /** The prompts sent before, newest first, and where to keep them for the next time. Without it they last until the program closes. */
  history?: PromptHistory;
}

export interface PromptHistory {
  initial: string[];
  save: (entries: string[]) => void;
}

const BINDINGS: KeyBinding[] = [
  { name: "return", action: "submit" },
  { name: "return", shift: true, action: "newline" },
  { name: "linefeed", action: "newline" },
  { name: "j", ctrl: true, action: "newline" },
];

export function Composer(props: ComposerProps) {
  const { focused, placeholder, role, seed, label } = props;
  const area = useRef<TextareaRenderable>(null);
  const [value, setValue] = useState("");
  const [choice, setChoice] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const history = useRef<string[]>(props.history?.initial.slice(0, MAX_HISTORY) ?? []);
  const browsing = useRef<Browsing>(NOT_BROWSING);
  // What the arrows last put in the box. The box reports that as a change, which is not the person typing over it.
  const recalled = useRef<string | null>(null);
  const pasted = useRef(new Map<string, string>());
  const pasteCount = useRef(0);

  const hints = dismissed ? [] : suggest(value, role, props.people ?? [], props.commands, props.askTargets);
  const selected: CommandHint | undefined = hints[Math.min(choice, Math.max(0, hints.length - 1))];
  const hintWindow = visibleSuggestionWindow(hints, choice);
  const completion = selected ? (selected.insert ?? `/${selected.name} `) : "";

  const put = (text: string): void => {
    if (text === "") {
      pasted.current.clear();
    }
    area.current?.setText(text);
    area.current?.gotoBufferEnd();
    setValue(text);
    setChoice(0);
  };

  useEffect(() => {
    if (seed) {
      put(seed.text);
    }
  }, [seed?.key]);

  useEffect(() => {
    props.onDirty(value !== "");
  }, [value === ""]);

  const submit = (): void => {
    const text = expandPastes(area.current?.plainText ?? "", pasted.current).trim();
    if (text === "" && (props.images ?? []).length === 0) {
      return;
    }
    if (props.remember !== false) {
      history.current = remember(history.current, text);
      props.history?.save(history.current);
    }
    browsing.current = NOT_BROWSING;
    put("");
    props.onSubmit(text);
  };

  // Cmd+V with an image on the clipboard pastes nothing, so the image is taken from the clipboard as with
  // Ctrl+V; a pasted or dragged image file is attached, and a path to no image stays text. A long text paste
  // shows as a short label and is sent in full.
  const paste = (event: PasteEvent): void => {
    const raw = decodePasteBytes(event.bytes);
    if (raw.trim() === "" && props.onPasteImage) {
      event.preventDefault();
      props.onPasteImage();
      return;
    }
    const path = imagePath(raw);
    if (path !== null && props.onPasteImageFile) {
      event.preventDefault();
      void props.onPasteImageFile(path).then((attached) => {
        if (!attached) {
          area.current?.insertText(raw);
        }
      });
      return;
    }
    const text = stripAnsiSequences(raw).replace(/\r\n?/g, "\n");
    if (!shouldCollapse(text)) {
      return;
    }
    event.preventDefault();
    pasteCount.current += 1;
    const label = pasteLabel(pasteCount.current, text);
    pasted.current.set(label, text);
    area.current?.insertText(label);
  };

  const recall = (direction: 1 | -1): void => {
    // The box itself, not the state: a key pressed right after typing sees the state of the render before.
    const typed = area.current?.plainText ?? value;
    const step = direction === 1 ? older(history.current, browsing.current, typed) : newer(history.current, browsing.current);
    if (step.value !== null) {
      browsing.current = step.browsing;
      recalled.current = step.value;
      put(step.value);
    }
  };

  useKeyboard((key) => {
    if (!focused) {
      return;
    }
    if (key.ctrl && key.name === "c") {
      key.preventDefault();
      if (value !== "") {
        put("");
      } else {
        props.onInterrupt();
      }
      return;
    }
    if (key.ctrl && key.name === "d" && value === "") {
      key.preventDefault();
      props.onInterrupt();
      return;
    }
    if (key.ctrl && key.name === "y") {
      key.preventDefault();
      props.onCopy();
      return;
    }
    if (key.ctrl && key.name === "v" && props.onPasteImage) {
      key.preventDefault();
      props.onPasteImage();
      return;
    }
    if (key.name === "backspace" && value === "" && (props.images ?? []).length > 0) {
      key.preventDefault();
      props.onDropImage?.();
      return;
    }
    const idle = (area.current?.plainText ?? value) === "" && hints.length === 0 && !key.meta && !key.shift;
    const action = key.ctrl ? (["g", "r"].includes(key.name) ? `ctrl+${key.name}` : null) : ["up", "down", "return"].includes(key.name) ? key.name : null;
    if (idle && action && props.onIdleKey?.(action)) {
      key.preventDefault();
      return;
    }
    if (key.name === "escape") {
      key.preventDefault();
      if (browsing.current.position >= 0) {
        const back = leave(browsing.current);
        browsing.current = back.browsing;
        recalled.current = back.value;
        put(back.value ?? "");
      } else if (hints.length > 0) {
        setDismissed(true);
      } else {
        props.onEscape();
      }
      return;
    }
    if (key.name === "tab" && key.shift) {
      key.preventDefault();
      props.onCycleMode();
      return;
    }
    if (key.name === "tab") {
      key.preventDefault();
      if (selected) {
        put(completion);
      } else {
        props.onTab();
      }
      return;
    }
    if (key.name === "return" && !key.shift && selected && value !== completion.trimEnd() && value !== completion) {
      key.preventDefault();
      put(completion);
      return;
    }
    if (key.name === "up" || key.name === "down") {
      const direction = key.name === "up" ? 1 : -1;
      if (hints.length > 0) {
        key.preventDefault();
        setChoice((current) => (current + (direction === 1 ? hints.length - 1 : 1)) % hints.length);
      } else if (!value.includes("\n")) {
        key.preventDefault();
        recall(direction);
      }
    }
  });

  const route = props.route?.(value.trimStart()) ?? null;
  const routeColor = route === null ? theme.accent : route.blocked ? theme.warn : ROUTE_COLORS()[route.kind];
  const color = focused ? routeColor : theme.dim;
  const lines = value === "" ? 0 : value.split("\n").length;
  const shown = focused ? placeholder : `${placeholder}  ·  click or press tab to type`;
  const progress = props.delivery?.state === "sending" ? " · sending…" : props.delivery?.state === "sent" ? " · ✓ delivered" : "";
  const head = route !== null ? `→ ${route.label} · ${route.note}` : (label ?? "");
  const more = value === "" ? "" : `${lines > 1 ? ` · ${lines} lines` : ""} · ⇧↵ new line`;
  const past = historyView(history.current, browsing.current);
  const rest = `${head}${more}${progress}`;
  // Counts down from the newest as each step goes further back: "history 100/100", then 99/100.
  const title = past === null ? rest : `history ${past.at}/${past.of}${rest === "" ? "" : ` · ${rest}`}`;
  return (
    <box flexDirection="column" flexShrink={0} paddingX={1} onMouseDown={() => props.onFocus()}>
      <box
        flexDirection="column"
        border
        borderStyle="rounded"
        borderColor={color}
        backgroundColor={theme.panel}
        paddingX={1}
        title={title === "" ? undefined : ` ${title} `}
        titleAlignment="left"
      >
        {props.delivery?.state === "failed" ? <Failure delivery={props.delivery} /> : null}
        {(props.images ?? []).length > 0 ? (
          <box flexDirection="row" height={1}>
            <text fg={theme.accent}>
              {(props.images ?? []).map((name) => `[${name}]`).join(" ")}
              <span fg={theme.dim}>  backspace removes the last one</span>
            </text>
          </box>
        ) : null}
        <box flexDirection="row">
          <text fg={focused ? routeColor : theme.dim}>{focused ? "❯ " : "› "}</text>
          <textarea
            ref={area}
            flexGrow={1}
            minHeight={1}
            maxHeight={8}
            focused={focused}
            placeholder={shown}
            placeholderColor={theme.dim}
            textColor={theme.text}
            backgroundColor={theme.panel}
            focusedBackgroundColor={theme.panel}
            keyBindings={BINDINGS}
            onPaste={paste}
            onContentChange={() => {
              const text = area.current?.plainText ?? "";
              setValue(text);
              props.onActivity(text);
              setChoice(0);
              setDismissed(false);
              if (text !== recalled.current) {
                browsing.current = NOT_BROWSING;
              }
            }}
            onSubmit={submit}
          />
        </box>
      </box>
      {past !== null ? (
        <box flexDirection="column" paddingLeft={4}>
          {past.rows.map((row) => {
            const line = (row.text.split("\n")[0] ?? "").slice(0, 80);
            const extra = row.text.split("\n").length - 1;
            return (
              <text key={row.index} fg={row.current ? theme.accent : theme.dim} wrapMode="none">
                {row.current ? "› " : "  "}
                {line}
                {extra > 0 ? <span fg={theme.dim}> +{extra} lines</span> : null}
              </text>
            );
          })}
          <text fg={theme.dim}>  ↑↓ browse · enter sends · esc back to what you were typing</text>
        </box>
      ) : null}
      {hints.length > 0 ? (
        <box flexDirection="column" paddingLeft={4}>
          {hintWindow.items.map((hint, index) => {
            const on = index === hintWindow.selectedIndex;
            return (
              <text key={hint.name} fg={on ? theme.text : theme.muted} bg={on ? theme.bubble : undefined} wrapMode="none">
                {on ? "› " : "  "}
                {hint.usage.padEnd(34)} <span fg={on ? theme.text : theme.dim}>{hint.description}</span>
              </text>
            );
          })}
        </box>
      ) : null}
    </box>
  );
}
