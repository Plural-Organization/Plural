import { PERMISSION_LABELS, type PermissionMode } from "@plural/client";
import { theme } from "../theme";
import { Spinner, useElapsed } from "./Spinner";

export function Working({ status, canAbort, queued }: { status: string; canAbort: boolean; queued: number }) {
  const elapsed = useElapsed(true);
  const text = status.replace(/^…\s*/, "") || "working";
  const verb = text === "waiting for the model" ? "thinking" : text;
  return (
    <box paddingX={2} height={1} flexShrink={0}>
      <text fg={theme.dim}>
        <Spinner color={theme.accent} />
        <span fg={theme.accent}> {verb}…</span>
        {` ${elapsed}s`}
        {queued > 0 ? <span fg={theme.warn}> · {queued} queued</span> : null}
        {canAbort ? " · esc to interrupt" : ""}
      </text>
    </box>
  );
}

const MARKS: Record<PermissionMode, string> = { default: "⏵", accept_edits: "⏵⏵", plan: "⏸", auto: "⏵⏵⏵" };

export function ModeLine({ mode, canCycle }: { mode: PermissionMode; canCycle: boolean }) {
  if (mode === "default" && !canCycle) {
    return null;
  }
  const color = mode === "plan" ? theme.info : mode === "auto" ? theme.danger : mode === "accept_edits" ? theme.warn : theme.dim;
  return (
    <box paddingX={2} height={1} flexShrink={0} backgroundColor={theme.panel}>
      <text fg={theme.dim}>
        <span fg={color}>
          {MARKS[mode]} {PERMISSION_LABELS[mode]}
          {mode === "default" ? "" : " on"}
        </span>
        {canCycle ? " (shift+tab to cycle)" : ""}
      </text>
    </box>
  );
}
