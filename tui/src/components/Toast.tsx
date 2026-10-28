import { theme } from "../theme";

export interface ToastMessage {
  id: number;
  title: string;
  detail: string | null;
}

export const TOAST_MS = 2200;

export function preview(text: string, limit = 36): string {
  const line = text.split("\n").find((entry) => entry.trim() !== "")?.trim() ?? "";
  return line.length > limit ? `${line.slice(0, limit - 1)}…` : line;
}

export function Toast({ message, right }: { message: ToastMessage; right: number }) {
  return (
    <box
      position="absolute"
      top={1}
      right={right}
      zIndex={15}
      border
      borderStyle="rounded"
      borderColor={theme.ok}
      backgroundColor={theme.panel}
      paddingX={1}
      flexDirection="column"
    >
      <text fg={theme.text}>
        <span fg={theme.ok}>✓ </span>
        {message.title}
      </text>
      {message.detail ? <text fg={theme.dim}>{message.detail}</text> : null}
    </box>
  );
}
