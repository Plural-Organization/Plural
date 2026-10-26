import type { Projection } from "./projection";
import type { Event, Participant, PolicyRuleView, PromptMode, SessionState, TranscriptEntry } from "./protocol";

export const PREVIEW_LINES = 12;

export const PROMPT_MODE_HINT: Record<PromptMode, string> = {
  open: "open: participants prompt the agent directly",
  review: "review: the host approves participants' prompts",
};

export interface Line {
  style: string;
  text: string;
}

export function history(state: SessionState): Line[] {
  return state.transcript.flatMap((entry) => entryLines(entry, state));
}

function entryLines(entry: TranscriptEntry, state: SessionState): Line[] {
  switch (entry.kind) {
    case "prompt":
      return [{ style: "bold", text: `${nameOf(state, entry.author_id)} › ${entry.text}` }];
    case "assistant":
      return entry.text ? [{ style: "", text: entry.text }] : [];
    case "tool": {
      if (entry.tool === null) {
        return [];
      }
      const mark = entry.ok === true ? "✓" : entry.ok === false ? "✗" : "…";
      const style = entry.ok === false ? "red" : "cyan";
      const lines: Line[] = [{ style, text: `⚙ ${entry.tool.name} ${entry.tool.subject} ${mark}` }];
      if (entry.output) {
        lines.push({ style: entry.ok ? "green" : "red", text: preview(entry.output) });
      }
      return lines;
    }
    case "compaction":
      return [{ style: "dim", text: `⟲ ${entry.text}` }];
  }
}

function preview(output: string): string {
  return output.split(/\r?\n/).slice(0, PREVIEW_LINES).join("\n");
}

export function label(state: SessionState, participant: Participant): string {
  const twins = Object.values(state.participants).filter((other) => other.name === participant.name);
  return twins.length < 2 ? participant.name : `${participant.name} #${participant.id.slice(-4)}`;
}

function nameOf(state: SessionState, participantId: string | null): string {
  const participant = state.participants[participantId ?? ""];
  return participant ? label(state, participant) : (participantId ?? "system");
}

export function ruleLine(rule: PolicyRuleView): string {
  return `${rule.action.padEnd(5)} ${rule.tool} ${rule.pattern}`;
}

export function live(projection: Projection): string {
  const streamed = Object.values(projection.streaming).join("");
  return streamed || status(projection);
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

export function describe(event: Event, state: SessionState): Line | null {
  const name = (participantId: string | null) => nameOf(state, participantId);
  switch (event.type) {
    case "participant.joined":
      return { style: "dim", text: `→ ${label(state, event.participant)} joined as ${event.participant.role}` };
    case "participant.left":
      return { style: "dim", text: `← ${name(event.participant_id)} left` };
    case "participant.role_changed":
      return { style: "dim", text: `${name(event.participant_id)} is now ${event.role}` };
    case "participant.revoked":
      return { style: "red", text: `✗ access revoked for ${event.participant_id}` };
    case "session.prompt_mode_changed":
      return { style: "magenta", text: `prompts are now ${PROMPT_MODE_HINT[event.mode]}` };
    case "proposal.created":
      return { style: "yellow", text: `? ${name(event.proposal.author_id)} proposes: ${event.proposal.text}` };
    case "proposal.approved":
      return { style: "green", text: `✓ proposal approved: ${event.text}` };
    case "proposal.rejected":
      return { style: "red", text: "✗ proposal rejected" };
    case "prompt.accepted": {
      const via = event.provenance.origin === "proposal" ? " (via proposal)" : "";
      return { style: "bold", text: `${name(event.author_id)}${via} › ${event.text}` };
    }
    case "run.started":
      return { style: "dim", text: "agent started" };
    case "run.ended":
      return {
        style: "dim",
        text: `agent finished: ${event.reason}${event.error ? ` (${event.error})` : ""}`,
      };
    case "message.ended":
      return event.text ? { style: "", text: event.text } : null;
    case "tool.started":
      return { style: "cyan", text: `⚙ ${event.call.name} ${event.call.subject}`.trimEnd() };
    case "tool.ended":
      return { style: event.ok ? "green" : "red", text: preview(event.output) };
    case "approval.requested": {
      const call = event.approval.call;
      return { style: "magenta", text: `! approval needed: ${call.name} ${call.subject} [${call.risk}]` };
    }
    case "approval.resolved": {
      const who = event.resolved_by === null ? "timeout" : name(event.resolved_by);
      return { style: "magenta", text: `! approval ${event.decision} (${who})` };
    }
    case "context.compacted":
      return { style: "dim", text: `⟲ context compacted (${event.tokens_before} tokens summarized)` };
    case "policy.rule_added":
      return { style: "magenta", text: `policy + ${ruleLine(event.rule)}  [${event.rule.id}]` };
    case "policy.rule_removed":
      return { style: "magenta", text: `policy - ${event.rule_id}` };
    case "attachment.added":
      return { style: "dim", text: `📎 ${name(event.attachment.owner_id)} attached ${event.attachment.name}` };
    case "invite.created":
      return { style: "green", text: `invite (${event.role}): ${event.link}` };
    case "error":
      return { style: "red", text: event.message };
    default:
      return null;
  }
}
