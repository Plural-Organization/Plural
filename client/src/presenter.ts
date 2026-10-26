import type { Projection } from "./projection";
import type { Participant, PolicyRuleView, SessionState } from "./protocol";

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
