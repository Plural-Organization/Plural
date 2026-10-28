import { theme } from "../theme";

export interface ToastMessage {
  id: number;
  title: string;
  detail: string | null;
  tone?: "ok" | "accent";
  icon?: string;
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
      borderColor={message.tone === "accent" ? theme.accent : theme.ok}
      backgroundColor={theme.panel}
      paddingX={1}
      flexDirection="column"
    >
      <text fg={theme.text}>
        <span fg={message.tone === "accent" ? theme.accent : theme.ok}>{message.icon ?? "✓"} </span>
        {message.title}
      </text>
      {message.detail ? <text fg={theme.dim}>{message.detail}</text> : null}
    </box>
  );
}
