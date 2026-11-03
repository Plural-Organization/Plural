import { useEffect, useState } from "react";
import { shortTokens } from "@plural/client";
import { theme } from "../theme";
import { VERBS, verbAt } from "../verbs";
import { Spinner, useElapsed } from "./Spinner";

const GLYPHS = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"];
const GENERIC = /^(waiting for the model|thinking)/;

export function Working({ status, verb, canAbort, queued }: { status: string; verb: number; canAbort: boolean; queued: number }) {
  const elapsed = useElapsed(true);
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setFrame((value) => (value + 1) % GLYPHS.length), 110);
    return () => clearInterval(timer);
  }, []);
  const word = VERBS[verbAt(verb, elapsed * 1000)]?.[0] ?? "Working";
  const detail = status.replace(/^…\s*/, "");
  return (
    <box paddingX={2} height={1} flexShrink={0}>
      <text fg={theme.dim}>
        <span fg={theme.accent}>
          {GLYPHS[frame]} {word}…
        </span>
        {` (${elapsed}s`}
        {canAbort ? " · esc to interrupt" : ""}
        {detail && !GENERIC.test(detail) ? ` · ${detail}` : ""}
        {")"}
        {queued > 0 ? <span fg={theme.warn}> · {queued} queued</span> : null}
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
