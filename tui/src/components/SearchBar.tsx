import { useKeyboard } from "@opentui/react";
import { theme } from "../theme";

interface SearchBarProps {
  query: string;
  count: number;
  position: number;
  preview: string;
  onQuery: (query: string) => void;
  onStep: (direction: 1 | -1) => void;
  onClose: () => void;
}

export function SearchBar({ query, count, position, preview, onQuery, onStep, onClose }: SearchBarProps) {
  useKeyboard((key) => {
    if (key.name === "escape" || (key.ctrl && (key.name === "f" || key.name === "c"))) {
      key.preventDefault();
      onClose();
    } else if (key.name === "return" || key.name === "linefeed") {
      key.preventDefault();
      onStep(key.shift ? -1 : 1);
    } else if (key.name === "down" || (key.ctrl && key.name === "n")) {
      key.preventDefault();
      onStep(1);
    } else if (key.name === "up" || (key.ctrl && key.name === "p")) {
      key.preventDefault();
      onStep(-1);
    }
  });
  const result = query.trim() === "" ? "" : count === 0 ? "no matches" : `${position + 1}/${count}`;
  return (
    <box flexDirection="row" flexShrink={0} height={1} paddingX={2} backgroundColor={theme.panel}>
      <text fg={theme.accent}>search </text>
      <input
        focused
        flexGrow={1}
        value={query}
        placeholder="text, command, path · is:failed is:prompt by:name"
        placeholderColor={theme.dim}
        textColor={theme.text}
        backgroundColor={theme.panel}
        focusedBackgroundColor={theme.panel}
        onInput={onQuery}
      />
      <text fg={theme.dim} wrapMode="none">
        {preview}{"  "}
      </text>
      <text fg={count === 0 && query.trim() !== "" ? theme.warn : theme.text}>{result}</text>
      <text fg={theme.dim}>{"  ↵ older · ⇧↵ newer · esc close"}</text>
    </box>
  );
}
