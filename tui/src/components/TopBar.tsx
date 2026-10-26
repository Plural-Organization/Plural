import { useState } from "react";
import type { SessionState } from "@plural/client";
import { theme } from "../theme";

export function TopBar({ room, state, onSettings }: { room: string; state: SessionState; onSettings: () => void }) {
  const [hover, setHover] = useState(false);
  return (
    <box flexDirection="row" justifyContent="space-between" paddingX={2} height={1} flexShrink={0} backgroundColor={theme.panel}>
      <text>
        <span fg={theme.accent}>
          <b>◆ plural</b>
        </span>
        <span fg={theme.dim}>  {room.slice(0, 16)}…</span>
      </text>
      <box flexDirection="row">
        <text fg={theme.dim}>
          prompts <span fg={state.prompt_mode === "open" ? theme.ok : theme.warn}>{state.prompt_mode}</span>
          {"  "}
        </text>
        <box onMouseDown={onSettings} onMouseOver={() => setHover(true)} onMouseOut={() => setHover(false)}>
          <text fg={hover ? theme.accent : theme.dim}>⚙</text>
        </box>
      </box>
    </box>
  );
}
