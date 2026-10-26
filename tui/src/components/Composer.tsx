import { Box, Text, useInput, usePaste } from "ink";
import { useEffect, useRef, useState } from "react";
import { suggestions as suggest, type CommandHint } from "../commands";
import * as ed from "../lib/editor";
import { theme } from "../theme";
import type { Role } from "@plural/client";

interface ComposerProps {
  active: boolean;
  disabled: string | null;
  placeholder: string;
  role: Role | undefined;
  columns: number;
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

export function Composer(props: ComposerProps) {
  const { active, disabled, placeholder, role, columns, seed, label } = props;
  const [editor, setEditor] = useState<ed.Editor>(ed.emptyEditor);
  const [choice, setChoice] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const history = useRef<string[]>([]);
  const position = useRef(-1);
  const draft = useRef("");

  useEffect(() => {
    if (seed) {
      setEditor(ed.setValue(seed.text));
    }
  }, [seed?.key]);

  useEffect(() => {
    props.onDirty(editor.value !== "");
  }, [editor.value === ""]);

  const hints = dismissed ? [] : suggest(editor.value, role);
  const selected = hints[Math.min(choice, Math.max(0, hints.length - 1))];

  const update = (next: ed.Editor): void => {
    setEditor(next);
    setChoice(0);
    setDismissed(false);
    position.current = -1;
  };

  const submit = (): void => {
    const text = editor.value.trim();
    if (text === "") {
      return;
    }
    history.current = [text, ...history.current.filter((entry) => entry !== text)].slice(0, MAX_HISTORY);
    position.current = -1;
    setEditor(ed.emptyEditor);
    props.onSubmit(text);
  };

  const complete = (hint: CommandHint): void => {
    setEditor(ed.setValue(`/${hint.name} `));
    setChoice(0);
  };

  const recall = (direction: 1 | -1): void => {
    const entries = history.current;
    if (direction === 1 && position.current + 1 < entries.length) {
      if (position.current === -1) {
        draft.current = editor.value;
      }
      position.current += 1;
      setEditor(ed.setValue(entries[position.current] ?? ""));
    } else if (direction === -1 && position.current >= 0) {
      position.current -= 1;
      setEditor(ed.setValue(position.current === -1 ? draft.current : (entries[position.current] ?? "")));
    }
  };

  usePaste(
    (text) => {
      if (!disabled) {
        update(ed.insert(editor, text));
      }
    },
    { isActive: active },
  );

  useInput(
    (input, key) => {
      if (key.ctrl && input === "c") {
        if (editor.value !== "") {
          update(ed.emptyEditor);
        } else {
          props.onInterrupt();
        }
        return;
      }
      if (key.ctrl && input === "d" && editor.value === "") {
        props.onInterrupt();
        return;
      }
      if (key.ctrl && input === "y") {
        props.onCopy();
        return;
      }
      if (key.escape) {
        if (hints.length > 0) {
          setDismissed(true);
        } else {
          props.onEscape();
        }
        return;
      }
      if (key.tab) {
        if (selected) {
          complete(selected);
        } else {
          props.onTab();
        }
        return;
      }
      if (disabled) {
        return;
      }
      if (key.return) {
        if (key.shift || (key.meta && editor.value !== "")) {
          update(ed.insert(editor, "\n"));
        } else if (editor.value.slice(0, editor.cursor).endsWith("\\")) {
          update(ed.insert(ed.backspace(editor), "\n"));
        } else if (selected && editor.value !== `/${selected.name}` && editor.value !== `/${selected.name} `) {
          complete(selected);
        } else {
          submit();
        }
        return;
      }
      if (key.ctrl && input === "j") {
        update(ed.insert(editor, "\n"));
      } else if (key.upArrow) {
        if (hints.length > 0) {
          setChoice((value) => (value + hints.length - 1) % hints.length);
        } else if (ed.onFirstLine(editor)) {
          recall(1);
        } else {
          setEditor(ed.up(editor));
        }
      } else if (key.downArrow) {
        if (hints.length > 0) {
          setChoice((value) => (value + 1) % hints.length);
        } else if (ed.onLastLine(editor)) {
          recall(-1);
        } else {
          setEditor(ed.down(editor));
        }
      } else if (key.leftArrow) {
        setEditor(key.ctrl || key.meta ? ed.wordLeft(editor) : ed.left(editor));
      } else if (key.rightArrow) {
        setEditor(key.ctrl || key.meta ? ed.wordRight(editor) : ed.right(editor));
      } else if (key.home || (key.ctrl && input === "a")) {
        setEditor(ed.lineStart(editor));
      } else if (key.end || (key.ctrl && input === "e")) {
        setEditor(ed.lineEnd(editor));
      } else if (key.backspace) {
        update(key.meta || key.ctrl ? ed.deleteWord(editor) : ed.backspace(editor));
      } else if (key.delete) {
        update(ed.remove(editor));
      } else if (key.ctrl && input === "w") {
        update(ed.deleteWord(editor));
      } else if (key.ctrl && input === "u") {
        update(ed.deleteToLineStart(editor));
      } else if (key.ctrl && input === "k") {
        update(ed.deleteToLineEnd(editor));
      } else if (key.meta && input === "b") {
        setEditor(ed.wordLeft(editor));
      } else if (key.meta && input === "f") {
        setEditor(ed.wordRight(editor));
      } else if (input !== "" && !key.ctrl && !key.meta) {
        update(ed.insert(editor, input));
      }
    },
    { isActive: active },
  );

  const rule = "─".repeat(Math.max(10, columns));
  const color = disabled ? theme.dim : active ? theme.accent : theme.dim;
  const lines = editor.value.split("\n");
  let remaining = editor.cursor;
  const rendered = lines.map((line, index) => {
    const here = remaining >= 0 && remaining <= line.length;
    const cursorAt = here ? remaining : -1;
    remaining -= line.length + 1;
    return { line, cursorAt, index };
  });

  return (
    <Box flexDirection="column">
      <Text color={color}>{rule}</Text>
      {label ? <Text color={theme.warn}>{label}</Text> : null}
      <Box flexDirection="column">
        {editor.value === "" ? (
          <Text>
            <Text color={color}>❯ </Text>
            {active && !disabled ? (
              <>
                <Text inverse>{(placeholder[0] ?? " ")}</Text>
                <Text color={theme.dim}>{placeholder.slice(1)}</Text>
              </>
            ) : (
              <Text color={theme.dim}>{disabled ?? placeholder}</Text>
            )}
          </Text>
        ) : (
          rendered.map(({ line, cursorAt, index }) => (
            <Text key={index}>
              <Text color={color}>{index === 0 ? "❯ " : "  "}</Text>
              {cursorAt === -1 || !active ? (
                line
              ) : (
                <>
                  {line.slice(0, cursorAt)}
                  <Text inverse>{line[cursorAt] ?? " "}</Text>
                  {line.slice(cursorAt + 1)}
                </>
              )}
            </Text>
          ))
        )}
      </Box>
      <Text color={color}>{rule}</Text>
      {hints.length > 0 ? (
        <Box flexDirection="column" paddingLeft={2}>
          {hints.slice(0, 6).map((hint, index) => {
            const on = hint === selected;
            return (
              <Text key={hint.name} color={on ? theme.accent : theme.dim}>
                {on ? "› " : "  "}
                {hint.usage.padEnd(34)} {hint.description}
              </Text>
            );
          })}
        </Box>
      ) : null}
    </Box>
  );
}
