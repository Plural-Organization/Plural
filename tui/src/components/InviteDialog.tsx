import { useKeyboard } from "@opentui/react";
import { useState } from "react";
import { theme } from "../theme";

interface InviteDialogProps {
  width: number;
  height: number;
  canTeam: boolean;
  teamName: string | null;
  onRoom: () => void;
  onTeam: () => Promise<void>;
  onClose: () => void;
}

const DIALOG_WIDTH = 60;

export function InviteDialog({ width, height, canTeam, teamName, onRoom, onTeam, onClose }: InviteDialogProps) {
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const options = [
    { id: "room", icon: "◉", title: "Invite to this room", detail: "copies the room link · anyone with it joins this session" },
    ...(canTeam ? [{ id: "team", icon: "◆", title: `Invite to team${teamName ? ` ${teamName}` : ""}`, detail: "copies a team join command · one use, valid for an hour" }] : []),
  ];

  const choose = (position: number): void => {
    if (busy) {
      return;
    }
    const option = options[position];
    if (option?.id === "room") {
      onRoom();
    } else if (option?.id === "team") {
      setBusy(true);
      setError(null);
      onTeam().then(
        () => onClose(),
        (failure: unknown) => {
          setBusy(false);
          setError(failure instanceof Error ? failure.message : String(failure));
        },
      );
    }
  };

  useKeyboard((key) => {
    key.preventDefault();
    if (key.name === "escape") {
      onClose();
    } else if (key.name === "up" || key.name === "left" || (key.name === "tab" && key.shift)) {
      setIndex((current) => (current + options.length - 1) % options.length);
    } else if (key.name === "down" || key.name === "right" || key.name === "tab") {
      setIndex((current) => (current + 1) % options.length);
    } else if (key.name === "return" || key.name === "space") {
      choose(index);
    }
  });

  const boxWidth = Math.min(DIALOG_WIDTH, Math.max(34, width - 4));

  return (
    <box position="absolute" top={0} left={0} width={width} height={height} zIndex={20} onMouseDown={onClose} alignItems="center" justifyContent="center">
      <box
        width={boxWidth}
        flexDirection="column"
        border
        borderStyle="rounded"
        borderColor={theme.accent}
        backgroundColor={theme.panel}
        paddingX={2}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <box flexDirection="row" justifyContent="space-between">
          <text fg={theme.accent}>
            <b>+ invite</b>
          </text>
          <box onMouseDown={onClose}>
            <text fg={theme.dim}>✕ esc</text>
          </box>
        </box>
        <text>{" "}</text>
        {options.map((option, position) => {
          const selected = position === index;
          return (
            <box
              key={option.id}
              flexDirection="column"
              border
              borderStyle="rounded"
              borderColor={selected ? theme.accent : theme.line}
              backgroundColor={selected ? theme.bubble : theme.panel}
              paddingX={1}
              marginBottom={1}
              onMouseDown={() => {
                setIndex(position);
                choose(position);
              }}
            >
              <text fg={selected ? theme.accent : theme.text}>
                {option.icon} <b>{option.title}</b>
              </text>
              <text fg={theme.dim} wrapMode="word">
                {busy && selected ? "creating the invite…" : option.detail}
              </text>
            </box>
          );
        })}
        {error !== null ? (
          <text fg={theme.danger} wrapMode="word">
            {error}
          </text>
        ) : null}
        <text fg={theme.dim}>↑↓ choose · enter or click copies · esc closes</text>
      </box>
    </box>
  );
}
