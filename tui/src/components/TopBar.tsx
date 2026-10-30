import { useState } from "react";
import type { SessionState } from "@plural/client";
import { theme } from "../theme";
import type { UpdateState } from "../update";
import { UpdateDot } from "./UpdateDot";

export function TopBar({ room, state, update, onSettings }: { room: string; state: SessionState; update: UpdateState | null; onSettings: () => void }) {
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
        {update && update.phase !== "failed" ? (
          <text fg={update.phase === "installed" ? theme.ok : theme.accent}>
            {update.phase === "installed" ? "✓ restart to update" : update.phase === "installing" ? "↻ updating" : `update ${update.version}`}
            {"  "}
          </text>
        ) : null}
        <box onMouseDown={onSettings} onMouseOver={() => setHover(true)} onMouseOut={() => setHover(false)}>
          <text fg={hover ? theme.accent : theme.dim}>
            ⚙
            {update?.phase === "ready" ? <UpdateDot /> : null}
          </text>
        </box>
      </box>
    </box>
  );
}
