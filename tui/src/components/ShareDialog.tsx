import { useKeyboard } from "@opentui/react";
import { useState } from "react";
import { checkFolder, type Folder } from "../folders";
import { truncate } from "../lib/wrap";
import { theme } from "../theme";

interface ShareDialogProps {
  width: number;
  height: number;
  teamName: string | null;
  folders: Folder[];
  onShare: (path: string) => Promise<void>;
  onClose: () => void;
}

const DIALOG_WIDTH = 64;

export function ShareDialog({ width, height, teamName, folders, onShare, onClose }: ShareDialogProps) {
  const [index, setIndex] = useState(0);
  const [typed, setTyped] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const [agree, setAgree] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = (): void => {
    if (typed.trim() !== "") {
      const checked = checkFolder(typed);
      if ("error" in checked) {
        setError(checked.error);
        return;
      }
      setError(null);
      setChosen(checked.path);
      return;
    }
    const folder = folders[index];
    if (folder !== undefined) {
      setError(null);
      setChosen(folder.path);
    }
  };

  const confirm = (accepted = agree): void => {
    if (busy || chosen === null) {
      return;
    }
    if (!accepted) {
      onClose();
      return;
    }
    setBusy(true);
    setError(null);
    onShare(chosen).then(
      () => onClose(),
      (failure: unknown) => {
        setBusy(false);
        setError(failure instanceof Error ? failure.message : String(failure));
      },
    );
  };

  useKeyboard((key) => {
    key.preventDefault();
    if (busy) {
      return;
    }
    if (key.name === "escape") {
      if (chosen !== null) {
        setChosen(null);
        setError(null);
      } else {
        onClose();
      }
      return;
    }
    if (chosen !== null) {
      if (key.name === "left" || key.name === "right" || key.name === "tab") {
        setAgree((current) => !current);
      } else if (key.name === "y") {
        setAgree(true);
        confirm(true);
      } else if (key.name === "n") {
        onClose();
      } else if (key.name === "return") {
        confirm();
      }
      return;
    }
    if (key.name === "up") {
      setIndex((current) => (current + folders.length - 1) % Math.max(1, folders.length));
      setTyped("");
    } else if (key.name === "down") {
      setIndex((current) => (current + 1) % Math.max(1, folders.length));
      setTyped("");
    } else if (key.name === "return") {
      pick();
    } else if (key.name === "backspace") {
      setTyped((current) => current.slice(0, -1));
      setError(null);
    } else if (!key.ctrl && !key.meta && key.sequence.length === 1 && key.sequence >= " ") {
      setTyped((current) => current + key.sequence);
      setError(null);
    }
  });

  const boxWidth = Math.min(DIALOG_WIDTH, Math.max(36, width - 4));
  const inner = boxWidth - 8;
  const team = teamName ?? "your team";

  return (
    <box position="absolute" top={0} left={0} width={width} height={height} zIndex={20} onMouseDown={onClose} alignItems="center" justifyContent="center">
      <box
        width={boxWidth}
        flexDirection="column"
        border
        borderStyle="rounded"
        borderColor={chosen === null ? theme.accent : theme.warn}
        backgroundColor={theme.panel}
        paddingX={2}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <box flexDirection="row" justifyContent="space-between">
          <text fg={theme.accent}>
            <b>{chosen === null ? "share my host · choose a folder" : "share my host · confirm"}</b>
          </text>
          <box onMouseDown={onClose}>
            <text fg={theme.dim}>✕ esc</text>
          </box>
        </box>
        <text>{" "}</text>
        {chosen === null ? (
          <>
            <text fg={theme.dim}>Which repository should the host open?</text>
            <text>{" "}</text>
            {folders.map((folder, position) => {
              const selected = typed === "" && position === index;
              return (
                <box
                  key={folder.path}
                  flexDirection="column"
                  backgroundColor={selected ? theme.bubble : undefined}
                  onMouseDown={() => {
                    setIndex(position);
                    setTyped("");
                    setChosen(folder.path);
                  }}
                >
                  <text fg={selected ? theme.accent : theme.text}>
                    {selected ? "› " : "  "}
                    <b>{truncate(folder.name, inner - 2)}</b>
                  </text>
                  <text fg={theme.dim}>{`  ${truncate(folder.detail, inner - 2)}`}</text>
                </box>
              );
            })}
            <text>{" "}</text>
            <text fg={typed === "" ? theme.dim : theme.text}>{`path: ${typed === "" ? "or type a path here" : truncate(typed, inner - 8)}`}</text>
          </>
        ) : (
          <>
            <text fg={theme.text} wrapMode="word">
              {`Share ${truncate(chosen, inner)} with ${team}?`}
            </text>
            <text>{" "}</text>
            <text fg={theme.dim} wrapMode="word">
              • everyone in {team} sees this session in their spaces
            </text>
            <text fg={theme.dim} wrapMode="word">
              • they can read the chat and the agent's work, not write
            </text>
            <text fg={theme.dim} wrapMode="word">
              • anyone asking for write access waits for your approval
            </text>
            <text fg={theme.dim} wrapMode="word">
              • the host stops when you quit plural
            </text>
            <text>{" "}</text>
            <box flexDirection="row" gap={2}>
              <box
                border
                borderStyle="rounded"
                borderColor={agree ? theme.ok : theme.line}
                paddingX={2}
                onMouseDown={() => {
                  setAgree(true);
                  confirm(true);
                }}
              >
                <text fg={agree ? theme.ok : theme.dim}>{busy ? "starting…" : "I agree · share (y)"}</text>
              </box>
              <box border borderStyle="rounded" borderColor={agree ? theme.line : theme.warn} paddingX={2} onMouseDown={onClose}>
                <text fg={agree ? theme.dim : theme.warn}>cancel (n)</text>
              </box>
            </box>
          </>
        )}
        {error !== null ? (
          <text fg={theme.danger} wrapMode="word">
            {error}
          </text>
        ) : null}
        <text fg={theme.dim}>{chosen === null ? "↑↓ choose · enter next · type a path · esc closes" : "←→ choose · enter confirms · esc goes back"}</text>
      </box>
    </box>
  );
}
