import type { Event, EventRecord, Participant, PolicyRuleView, SessionState } from "./protocol";
import { emptyState, reduce } from "./reduce";

export class Projection {
  state: SessionState = emptyState();
  streaming: Record<string, string> = {};
  reasoning = 0;
  basePolicy: PolicyRuleView[] = [];
  meId: string | null = null;
  ready = false;

  get me(): Participant | undefined {
    return this.meId === null ? undefined : this.state.participants[this.meId];
  }

  load(state: SessionState, streaming: Record<string, string>): void {
    this.state = state;
    this.streaming = { ...streaming };
    this.reasoning = 0;
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
        break;
      default:
        break;
    }
    return true;
  }

  observe(event: Event): void {
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
