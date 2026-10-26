import type { KeyBinding, TextareaRenderable } from "@opentui/core";
import { useKeyboard } from "@opentui/react";
import { useEffect, useRef, useState } from "react";
import type { Role } from "@plural/client";
import { suggestions as suggest, type CommandHint } from "../commands";
import { theme } from "../theme";

interface ComposerProps {
  focused: boolean;
  disabled: string | null;
  placeholder: string;
  role: Role | undefined;
  seed: { text: string; key: number } | null;
  label: string | null;
  onSubmit: (text: string) => void;
  onEscape: () => void;
  onTab: () => void;
  onInterrupt: () => void;
  onCopy: () => void;
  onDirty: (dirty: boolean) => void;
}

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
  const history = useRef<string[]>([]);
  const position = useRef(-1);
  const draft = useRef("");

  const hints = dismissed ? [] : suggest(value, role);
  const selected: CommandHint | undefined = hints[Math.min(choice, Math.max(0, hints.length - 1))];

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

  const submit = (): void => {
    const text = (area.current?.plainText ?? "").trim();
    if (text === "") {
      return;
    }
    history.current = [text, ...history.current.filter((entry) => entry !== text)].slice(0, MAX_HISTORY);
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
    if (key.name === "escape") {
      key.preventDefault();
      if (hints.length > 0) {
        setDismissed(true);
      } else {
        props.onEscape();
      }
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

  const color = disabled ? theme.dim : focused ? theme.accent : theme.dim;
  return (
    <box flexDirection="column" flexShrink={0}>
      <box flexDirection="column" border={["top"]} borderColor={color} paddingX={2}>
        {label ? <text fg={theme.warn}>{label}</text> : null}
        <box flexDirection="row">
          <text fg={color}>❯ </text>
          <textarea
            ref={area}
            flexGrow={1}
            minHeight={1}
            maxHeight={6}
            focused={focused && !disabled}
            placeholder={disabled ?? placeholder}
            placeholderColor={theme.dim}
            textColor={theme.text}
            keyBindings={BINDINGS}
            onContentChange={() => {
              const text = area.current?.plainText ?? "";
              setValue(text);
              setChoice(0);
              setDismissed(false);
              position.current = -1;
            }}
            onSubmit={submit}
          />
        </box>
      </box>
      {hints.length > 0 ? (
        <box flexDirection="column" paddingLeft={4}>
          {hints.slice(0, 6).map((hint) => {
            const on = hint === selected;
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
