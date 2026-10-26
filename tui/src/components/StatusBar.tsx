import { label, type ConnectionStatus, type Participant, type SessionState } from "@plural/client";
import { theme } from "../theme";

interface StatusBarProps {
  me: Participant | undefined;
  state: SessionState;
  connection: ConnectionStatus;
  inbox: number;
  focused: boolean;
  hint: string | null;
}

export function StatusBar({ me, state, connection, inbox, focused, hint }: StatusBarProps) {
  const others = Object.values(state.participants).filter((participant) => participant.connected && participant.id !== me?.id);
  const names = others.slice(0, 3).map((participant) => label(state, participant));
  const extra = others.length - names.length;
  const dot = connection === "online" ? theme.ok : connection === "connecting" ? theme.warn : theme.danger;
  const who = connection === "online" ? (me ? `${me.name} (${me.role})` : "connected") : connection === "connecting" ? "connecting…" : "reconnecting…";
  const right = hint ?? (inbox > 0 ? (focused ? "answer above · tab: back to the prompt" : `tab: ${inbox} waiting for you`) : "/help");
  return (
    <box flexDirection="row" justifyContent="space-between" paddingX={2} height={1} flexShrink={0} backgroundColor={theme.panel}>
      <text fg={theme.dim}>
        <span fg={dot}>●</span> {who} · <span fg={state.prompt_mode === "review" ? theme.warn : theme.dim}>{state.prompt_mode}</span>
        {names.length > 0 ? ` · with ${names.join(", ")}${extra > 0 ? ` +${extra}` : ""}` : ""}
      </text>
      <text fg={theme.dim}>{right}</text>
    </box>
  );
}
