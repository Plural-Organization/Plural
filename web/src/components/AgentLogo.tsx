import type { CSSProperties } from "react";
import { agentMark } from "../lib/agents";

// The mark of the agent a session runs, in its maker's colour; nothing when the label names none.
// `decorative` when the name is written beside it, so it is not read twice.
export function AgentLogo({ label, size = 16, className, decorative = false }: { label: string | null | undefined; size?: number; className?: string; decorative?: boolean }) {
  const mark = agentMark(label);
  if (mark === null) return null;
  const style: CSSProperties = {
    display: "inline-block",
    flex: "none",
    width: size,
    height: size,
    backgroundColor: mark.color,
    mask: `url("${mark.icon}") center / contain no-repeat`,
    WebkitMask: `url("${mark.icon}") center / contain no-repeat`,
  };
  return decorative ? <span aria-hidden className={className} style={style} /> : <span role="img" aria-label={mark.name} title={mark.name} className={className} style={style} />;
}
