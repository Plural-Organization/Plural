import { Cpu } from "@phosphor-icons/react";
import type { CSSProperties } from "react";
import { agentMark } from "../lib/agents";

// The mark of the agent a session runs, in its maker's colour; nothing when the label names none.
// `decorative` when the name is written beside it, so it is not read twice.
export function AgentLogo({ label, size = 16, className, decorative = false, fallback = false }: { label: string | null | undefined; size?: number; className?: string; decorative?: boolean; fallback?: boolean }) {
  const mark = agentMark(label);
  // `fallback`: a provider with no mark of its own still takes the same room, so rows line up.
  if (mark === null) return fallback ? <Cpu aria-hidden size={size} className="flex-none text-muted" /> : null;
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
