import { useEffect, useState } from "react";
import { PERMISSION_LABELS, shortTokens, type PermissionMode } from "@plural/client";
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

const SQUEEZE = 22;

// A bar that squeezes toward the middle while the agent summarizes the conversation.
export function Compacting({ tokens }: { tokens: number }) {
  const elapsed = useElapsed(true);
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setFrame((value) => value + 1), 70);
    return () => clearInterval(timer);
  }, []);
  const phase = (frame % 24) / 24;
  const squeeze = 0.5 - 0.5 * Math.cos(phase * Math.PI * 2);
  const filled = Math.max(2, Math.round(SQUEEZE * (1 - 0.8 * squeeze)));
  const side = Math.floor((SQUEEZE - filled) / 2);
  return (
    <box paddingX={2} height={1} flexShrink={0}>
      <text fg={theme.dim}>
        <span fg={theme.accent}>{"›".repeat(side)}</span>
        <span fg={theme.info}>{"█".repeat(filled)}</span>
        <span fg={theme.accent}>{"‹".repeat(SQUEEZE - filled - side)}</span>
        <span fg={theme.info}> compacting the context</span>
        {` · ${shortTokens(tokens)} tokens into a summary · ${elapsed}s`}
      </text>
    </box>
  );
}

export function Busy({ text }: { text: string }) {
  const elapsed = useElapsed(true);
  return (
    <box paddingX={2} height={1} flexShrink={0}>
      <text fg={theme.dim}>
        <Spinner color={theme.info} />
        <span fg={theme.info}> {text}…</span>
        {elapsed > 0 ? ` ${elapsed}s` : ""}
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
