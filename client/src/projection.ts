import type { BoardCursor, Event, EventRecord, Participant, PolicyRuleView, SessionState, TextSelection } from "./protocol";
import { emptyState, reduce } from "./reduce";

export class Projection {
  state: SessionState = emptyState();
  streaming: Record<string, string> = {};
  reasoning = 0;
  typing = new Set<string>();
  selections = new Map<string, TextSelection>();
  cursors = new Map<string, BoardCursor>();
  compacting: { tokens: number; since: number } | null = null;
  basePolicy: PolicyRuleView[] = [];
  agent = "";
  waiting = false;
  meId: string | null = null;
  ready = false;

  get agentLabel(): string {
    return this.state.agent || this.agent;
  }

  get me(): Participant | undefined {
    return this.meId === null ? undefined : this.state.participants[this.meId];
  }

  load(state: SessionState, streaming: Record<string, string>, typing: string[] = []): void {
    this.state = state;
    this.streaming = { ...streaming };
    this.typing = new Set(typing);
    this.selections = new Map();
    this.cursors = new Map();
    this.reasoning = 0;
    this.compacting = null;
    this.ready = true;
  }

  apply(record: EventRecord): boolean {
    if (record.seq <= this.state.last_seq) {
      return false;
    }
    this.state = reduce(this.state, record);
    const event = record.event;
    switch (event.type) {
      case "message.started":
        this.streaming[event.message_id] = "";
        break;
      case "message.ended":
        delete this.streaming[event.message_id];
        this.reasoning = 0;
        break;
      case "run.ended":
        this.streaming = {};
        this.reasoning = 0;
        this.compacting = null;
        break;
      case "context.compacted":
        this.compacting = null;
        break;
      case "participant.revoked":
        this.typing.delete(event.participant_id);
        this.selections.delete(event.participant_id);
        this.cursors.delete(event.participant_id);
        break;
      case "participant.left":
        this.selections.delete(event.participant_id);
        this.cursors.delete(event.participant_id);
        break;
      default:
        break;
    }
    return true;
  }

  observe(event: Event): void {
    if (event.type === "context.compacting") {
      this.compacting = { tokens: event.tokens_before, since: Date.now() };
      return;
    }
    if (event.type === "participant.typing") {
      if (event.typing) {
        this.typing.add(event.participant_id);
      } else {
        this.typing.delete(event.participant_id);
      }
      return;
    }
    if (event.type === "participant.selected") {
      if (event.selection === null) {
        this.selections.delete(event.participant_id);
      } else {
        this.selections.set(event.participant_id, event.selection);
      }
      return;
    }
    if (event.type === "participant.cursor") {
      if (event.cursor === null) {
        this.cursors.delete(event.participant_id);
      } else {
        this.cursors.set(event.participant_id, event.cursor);
      }
      return;
    }
    if (event.type !== "message.delta") {
      return;
    }
    if (event.thinking) {
      this.reasoning += event.text.length;
    } else {
      this.streaming[event.message_id] = (this.streaming[event.message_id] ?? "") + event.text;
    }
  }
}
