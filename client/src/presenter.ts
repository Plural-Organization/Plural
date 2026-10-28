import type { Projection } from "./projection";
import type { Participant, PermissionMode, PolicyRuleView, SessionState } from "./protocol";

export const PERMISSION_MODES: readonly PermissionMode[] = ["default", "accept_edits", "plan", "auto"];

export const PERMISSION_LABELS: Record<PermissionMode, string> = {
  default: "ask before changes",
  accept_edits: "accept edits",
  plan: "plan mode",
  auto: "auto mode",
};

export function nextPermissionMode(mode: PermissionMode): PermissionMode {
  return PERMISSION_MODES[(PERMISSION_MODES.indexOf(mode) + 1) % PERMISSION_MODES.length] ?? "default";
}

export function label(state: SessionState, participant: Participant): string {
  const twins = Object.values(state.participants).filter((other) => other.name === participant.name);
  return twins.length < 2 ? participant.name : `${participant.name} #${participant.id.slice(-4)}`;
}

export function ruleLine(rule: PolicyRuleView): string {
  return `${rule.action.padEnd(5)} ${rule.tool} ${rule.pattern}`;
}

export function status(projection: Projection): string {
  const state = projection.state;
  if (state.run === null) {
    return "";
  }
  if (projection.compacting !== null) {
    return "… compacting the context";
  }
  if (Object.keys(state.approvals).length > 0) {
    return "… waiting for host approval";
  }
  const last = state.transcript.at(-1);
  if (last !== undefined && last.tool !== null && last.ok === null) {
    return `… running ${last.tool.name}`;
  }
  if (projection.reasoning > 0) {
    return `… thinking (${projection.reasoning} chars)`;
  }
  return "… waiting for the model";
}

export interface ContextMeter {
  percent: number;
  tokens: string;
  window: string;
  level: "ok" | "warn" | "danger";
}

export function contextMeter(state: SessionState): ContextMeter | null {
  const context = state.context;
  // These are the host's canonical labels for the OAuth connection presets.
  const oauth = /^(Claude OAuth|Claude Code|Codex CLI)(?: ·|$)/.test(state.agent);
  if (oauth || context === null || context.window <= 0) {
    return null;
  }
  const share = context.tokens / context.window;
  return {
    percent: Math.min(100, Math.round(share * 100)),
    tokens: shortTokens(context.tokens),
    window: shortTokens(context.window),
    level: share >= context.compact_at ? "danger" : share >= context.compact_at * 0.75 ? "warn" : "ok",
  };
}

export function shortTokens(count: number): string {
  return count >= 1_000_000 ? `${(count / 1_000_000).toFixed(1)}M` : count >= 1000 ? `${Math.round(count / 1000)}K` : String(count);
}
