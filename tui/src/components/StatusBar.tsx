import { Box, Text } from "ink";
import { label, type ConnectionStatus, type SessionState, type Participant } from "@plural/client";
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
  return (
    <Box justifyContent="space-between">
      <Text color={theme.dim}>
        <Text color={dot}>●</Text> {connection === "online" ? (me ? `${me.name} (${me.role})` : "connected") : connection === "connecting" ? "connecting…" : "reconnecting…"}
        {" · "}
        <Text color={state.prompt_mode === "review" ? theme.warn : theme.dim}>{state.prompt_mode}</Text>
        {names.length > 0 ? ` · with ${names.join(", ")}${extra > 0 ? ` +${extra}` : ""}` : ""}
      </Text>
      <Text color={theme.dim}>{hint ?? (inbox > 0 ? (focused ? "answer above · tab: back to the prompt" : `tab: ${inbox} waiting for you`) : "/help")}</Text>
    </Box>
  );
}
