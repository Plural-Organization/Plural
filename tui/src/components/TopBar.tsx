import { useState } from "react";
import type { SessionState } from "@plural/client";
import { theme } from "../theme";
import type { UpdateState } from "../update";
import { UpdateDot } from "./UpdateDot";

export function TopBar({ state, update, team, onSettings }: { state: SessionState; update: UpdateState | null; team: string | null; onSettings: () => void }) {
  const [hover, setHover] = useState(false);
  return (
    <box flexDirection="row" paddingX={2} height={1} flexShrink={0} backgroundColor={theme.panel}>
      <box flexGrow={1} flexBasis={0}>
        {team ? (
          <text fg={theme.accent} wrapMode="none">
            ◆ {team}
          </text>
        ) : null}
      </box>
      <text fg={theme.text}>
        <b>Plural</b>
      </text>
      <box flexGrow={1} flexBasis={0} flexDirection="row" justifyContent="flex-end">
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
