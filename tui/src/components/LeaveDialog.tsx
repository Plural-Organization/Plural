import { useKeyboard } from "@opentui/react";
import { useState } from "react";
import { truncate } from "../lib/wrap";
import { theme } from "../theme";

interface LeaveDialogProps {
  width: number;
  height: number;
  teamName: string;
  owner: boolean;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}

const DIALOG_WIDTH = 64;

export function LeaveDialog({ width, height, teamName, owner, onConfirm, onClose }: LeaveDialogProps) {
  // The destructive answer is never the one enter picks on its own.
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = (): void => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError(null);
    onConfirm().then(
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
    if (key.name === "escape" || key.name === "n") {
      onClose();
    } else if (key.name === "left" || key.name === "right" || key.name === "tab") {
      setAgree((current) => !current);
    } else if (key.name === "y") {
      confirm();
    } else if (key.name === "return") {
      if (agree) {
        confirm();
      } else {
        onClose();
      }
    }
  });

  const boxWidth = Math.min(DIALOG_WIDTH, Math.max(36, width - 4));
  const verb = owner ? "disband" : "leave";

  return (
    <box position="absolute" top={0} left={0} width={width} height={height} zIndex={20} onMouseDown={onClose} alignItems="center" justifyContent="center">
      <box
        width={boxWidth}
        flexDirection="column"
        border
        borderStyle="rounded"
        borderColor={theme.warn}
        backgroundColor={theme.panel}
        paddingX={2}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <box flexDirection="row" justifyContent="space-between">
          <text fg={theme.warn}>
            <b>{`${verb} team · ${truncate(teamName, boxWidth - 24)}`}</b>
          </text>
          <box onMouseDown={onClose}>
            <text fg={theme.dim}>✕ esc</text>
          </box>
        </box>
        <text>{" "}</text>
        {owner ? (
          <>
            <text fg={theme.text} wrapMode="word">
              {`Delete ${teamName} for everyone?`}
            </text>
            <text>{" "}</text>
            <text fg={theme.dim} wrapMode="word">
              • every member is removed and their invite codes stop working
            </text>
            <text fg={theme.dim} wrapMode="word">
              • all shared sessions disappear from the team's spaces
            </text>
            <text fg={theme.dim} wrapMode="word">
              • this cannot be undone
            </text>
          </>
        ) : (
          <>
            <text fg={theme.text} wrapMode="word">
              {`Leave ${teamName}?`}
            </text>
            <text>{" "}</text>
            <text fg={theme.dim} wrapMode="word">
              • you stop seeing the team's sessions
            </text>
            <text fg={theme.dim} wrapMode="word">
              • your own sessions stay, but are no longer shared with it
            </text>
            <text fg={theme.dim} wrapMode="word">
              • to come back you need a new invite from the owner
            </text>
          </>
        )}
        <text>{" "}</text>
        <box flexDirection="row" gap={2}>
          <box border borderStyle="rounded" borderColor={agree ? theme.warn : theme.line} paddingX={2} onMouseDown={confirm}>
            <text fg={agree ? theme.warn : theme.dim}>{busy ? `${verb === "leave" ? "leaving" : "deleting"}…` : `${verb} (y)`}</text>
          </box>
          <box border borderStyle="rounded" borderColor={agree ? theme.line : theme.ok} paddingX={2} onMouseDown={onClose}>
            <text fg={agree ? theme.dim : theme.ok}>cancel (n)</text>
          </box>
        </box>
        {error !== null ? (
          <text fg={theme.danger} wrapMode="word">
            {error}
          </text>
        ) : null}
        <text fg={theme.dim}>←→ choose · enter confirms · esc cancels</text>
      </box>
    </box>
  );
}
