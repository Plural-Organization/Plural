import { contextMeter, label, PERMISSION_LABELS, type ConnectionStatus, type Participant, type PermissionMode, type SessionState } from "@plural/client";
import { theme } from "../theme";
import { Spinner } from "./Spinner";

const MARKS: Record<PermissionMode, string> = { default: "⏵", accept_edits: "⏵⏵", plan: "⏸", auto: "⏵⏵⏵" };

function modeColor(mode: PermissionMode): string {
  return mode === "plan" ? theme.info : mode === "auto" ? theme.danger : mode === "accept_edits" ? theme.warn : theme.dim;
}

interface StatusBarProps {
  mode: PermissionMode;
  canCycle: boolean;
  me: Participant | undefined;
  state: SessionState;
  connection: ConnectionStatus;
  inbox: number;
  focused: boolean;
  hint: string | null;
}

export function StatusBar({ mode, canCycle, me, state, connection, inbox, focused, hint }: StatusBarProps) {
  const others = Object.values(state.participants).filter((participant) => participant.connected && participant.id !== me?.id);
  const names = others.slice(0, 3).map((participant) => label(state, participant));
  const extra = others.length - names.length;
  const dot = connection === "online" ? theme.ok : connection === "connecting" ? theme.warn : theme.danger;
  const who =
    connection === "online"
      ? me
        ? `${me.name} (${me.role})`
        : "joining the session…"
      : connection === "connecting"
        ? "connecting to the session…"
        : "connection lost, reconnecting…";
  const loading = connection !== "online" || me === undefined;
  const right = hint ?? (inbox > 0 ? (focused ? "answer above · tab: prompt" : `tab: ${inbox} waiting for you`) : "/help");
  const showMode = canCycle || mode !== "default";
  return (
    <box flexDirection="row" justifyContent="space-between" gap={2} paddingX={2} height={1} flexShrink={0} backgroundColor={theme.panel}>
      <text fg={theme.dim} flexShrink={1} wrapMode="none">
        {showMode ? (
          <span fg={modeColor(mode)}>
            {MARKS[mode]} {PERMISSION_LABELS[mode]}
            {mode === "default" ? "" : " on"}
            <span fg={theme.dim}> · </span>
          </span>
        ) : null}
        {loading ? <Spinner color={dot} /> : <span fg={dot}>●</span>} {who} · <span fg={state.prompt_mode === "review" ? theme.warn : theme.dim}>{state.prompt_mode}</span>
        {names.length > 0 ? ` · with ${names.join(", ")}${extra > 0 ? ` +${extra}` : ""}` : ""}
      </text>
      <box flexDirection="row" flexShrink={0}>
        <ContextMeterView state={state} />
        <text fg={theme.dim}>
          {contextMeter(state) !== null ? "  ·  " : ""}
          {right}
        </text>
      </box>
    </box>
  );
}

const METER = 10;

export function ContextMeterView({ state, width = METER }: { state: SessionState; width?: number }) {
  const meter = contextMeter(state);
  if (meter === null) {
    return null;
  }
  const color = meter.level === "danger" ? theme.danger : meter.level === "warn" ? theme.warn : theme.ok;
  const filled = Math.min(width, Math.round((meter.percent / 100) * width));
  return (
    <text fg={theme.dim}>
      context <span fg={color}>{"▰".repeat(filled)}</span>
      <span fg={theme.line}>{"▱".repeat(width - filled)}</span> <span fg={color}>{meter.percent}%</span>
      {` · ${meter.tokens}/${meter.window}`}
    </text>
  );
}
