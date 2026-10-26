import type { SessionState } from "@plural/client";
import { theme } from "../theme";

export function TopBar({ room, state }: { room: string; state: SessionState }) {
  return (
    <box flexDirection="row" justifyContent="space-between" paddingX={2} height={1} flexShrink={0} backgroundColor={theme.panel}>
      <text>
        <span fg={theme.accent}>
          <b>◆ plural</b>
        </span>
        <span fg={theme.dim}>  {room.slice(0, 16)}…</span>
      </text>
      <text fg={theme.dim}>
        prompts <span fg={state.prompt_mode === "open" ? theme.ok : theme.warn}>{state.prompt_mode}</span>
      </text>
    </box>
  );
}
