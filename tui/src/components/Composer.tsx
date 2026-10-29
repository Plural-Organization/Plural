import type { KeyBinding, TextareaRenderable } from "@opentui/core";
import { useKeyboard } from "@opentui/react";
import { useEffect, useRef, useState } from "react";
import type { Role } from "@plural/client";
import { suggestions as suggest, visibleSuggestionWindow, type CommandHint } from "../commands";
import { theme } from "../theme";

interface ComposerProps {
  focused: boolean;
  disabled: string | null;
  placeholder: string;
  role: Role | undefined;
  commands?: CommandHint[];
  seed: { text: string; key: number } | null;
  label: string | null;
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
  remember?: boolean;
  tips?: boolean;
}

const TIPS = [
  "shift+tab switches between ask, accept edits, plan and auto",
  "/skills search react finds skills to install",
  "/who shows who is in the room",
  "esc stops the agent mid-run",
  "ctrl+o opens every tool call",
  "shift+enter starts a new line",
];
const TIP_MS = 7000;

const MAX_HISTORY = 100;

const BINDINGS: KeyBinding[] = [
  { name: "return", action: "submit" },
  { name: "return", shift: true, action: "newline" },
  { name: "linefeed", action: "newline" },
  { name: "j", ctrl: true, action: "newline" },
];

export function Composer(props: ComposerProps) {
  const { focused, disabled, placeholder, role, seed, label } = props;
  const area = useRef<TextareaRenderable>(null);
  const [value, setValue] = useState("");
  const [choice, setChoice] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [tip, setTip] = useState(0);
  const history = useRef<string[]>([]);
  const position = useRef(-1);
  const draft = useRef("");

  const hints = dismissed ? [] : suggest(value, role, props.commands);
  const selected: CommandHint | undefined = hints[Math.min(choice, Math.max(0, hints.length - 1))];
  const hintWindow = visibleSuggestionWindow(hints, choice);

  const put = (text: string): void => {
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

  useEffect(() => {
    if (value !== "" || disabled) {
      return;
    }
    const timer = setInterval(() => setTip((current) => (current + 1) % TIPS.length), TIP_MS);
    return () => clearInterval(timer);
  }, [value === "", disabled]);

  const submit = (): void => {
    const text = (area.current?.plainText ?? "").trim();
    if (text === "") {
      return;
    }
    if (props.remember !== false) {
      history.current = [text, ...history.current.filter((entry) => entry !== text)].slice(0, MAX_HISTORY);
    }
    position.current = -1;
    put("");
    props.onSubmit(text);
  };

  const recall = (direction: 1 | -1): void => {
    const entries = history.current;
    if (direction === 1 && position.current + 1 < entries.length) {
      if (position.current === -1) {
        draft.current = value;
      }
      position.current += 1;
      put(entries[position.current] ?? "");
    } else if (direction === -1 && position.current >= 0) {
      position.current -= 1;
      put(position.current === -1 ? draft.current : (entries[position.current] ?? ""));
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
    const idle = (area.current?.plainText ?? value) === "" && hints.length === 0 && !key.meta && !key.shift;
    const action = key.ctrl ? (["g", "r"].includes(key.name) ? `ctrl+${key.name}` : null) : ["up", "down", "return"].includes(key.name) ? key.name : null;
    if (idle && action && props.onIdleKey?.(action)) {
      key.preventDefault();
      return;
    }
    if (key.name === "escape") {
      key.preventDefault();
      if (hints.length > 0) {
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
        put(`/${selected.name} `);
      } else {
        props.onTab();
      }
      return;
    }
    if (key.name === "return" && !key.shift && selected && value !== `/${selected.name}` && value !== `/${selected.name} `) {
      key.preventDefault();
      put(`/${selected.name} `);
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

  const color = disabled ? theme.line : focused ? theme.accent : theme.dim;
  const lines = value === "" ? 0 : value.split("\n").length;
  const shown = disabled ?? (focused ? (props.remember === false || props.tips === false ? placeholder : `${placeholder}  ·  tip: ${TIPS[tip]}`) : `${placeholder}  ·  click or press tab to type`);
  return (
    <box flexDirection="column" flexShrink={0} paddingX={1} onMouseDown={() => props.onFocus()}>
      <box
        flexDirection="column"
        border
        borderStyle="rounded"
        borderColor={color}
        backgroundColor={theme.panel}
        paddingX={1}
        title={label ? ` ${label} ` : undefined}
        titleAlignment="left"
      >
        <box flexDirection="row">
          <text fg={color}>{focused ? "❯ " : "› "}</text>
          <textarea
            ref={area}
            flexGrow={1}
            minHeight={2}
            maxHeight={8}
            focused={focused && !disabled}
            placeholder={shown}
            placeholderColor={theme.dim}
            textColor={theme.text}
            backgroundColor={theme.panel}
            focusedBackgroundColor={theme.panel}
            keyBindings={BINDINGS}
            onContentChange={() => {
              const text = area.current?.plainText ?? "";
              setValue(text);
              props.onActivity(text);
              setChoice(0);
              setDismissed(false);
              position.current = -1;
            }}
            onSubmit={submit}
          />
        </box>
        <box flexDirection="row" justifyContent="flex-end" height={1}>
          <text fg={theme.dim}>
            {lines > 1 ? `${lines} lines · ` : ""}
            {value.length > 0 ? `${value.length} chars · ` : ""}
            <span fg={focused ? theme.accent : theme.dim}>↵</span> send · <span fg={focused ? theme.accent : theme.dim}>⇧↵</span> new line
          </text>
        </box>
      </box>
      {hints.length > 0 ? (
        <box flexDirection="column" paddingLeft={4}>
          {hintWindow.items.map((hint, index) => {
            const on = index === hintWindow.selectedIndex;
            return (
              <text key={hint.name} fg={on ? theme.accent : theme.dim}>
                {on ? "› " : "  "}
                {hint.usage.padEnd(34)} {hint.description}
              </text>
            );
          })}
        </box>
      ) : null}
    </box>
  );
}
