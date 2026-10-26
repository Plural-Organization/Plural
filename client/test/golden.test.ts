import { describe as suite, expect, test } from "vitest";
import golden from "./fixtures/golden.json";
import {
  describe,
  history,
  live,
  Projection,
  type Event,
  type EventRecord,
} from "../src";

interface Step {
  kind: "record" | "observe";
  record?: EventRecord;
  event?: Event;
  state: unknown;
  streaming: Record<string, string>;
  reasoning: number;
  live: string;
  line: { style: string; text: string } | null;
  history: { style: string; text: string }[];
}

const steps = golden.steps as unknown as Step[];

suite("reducer and presenter match the Python reference", () => {
  test("replaying the events reproduces every intermediate state", () => {
    const projection = new Projection();
    steps.forEach((step, index) => {
      const event = step.record ? step.record.event : (step.event as Event);
      if (step.record) {
        expect(projection.apply(step.record), `step ${index} applied`).toBe(true);
      } else {
        projection.observe(event);
      }
      expect(projection.state, `state after step ${index} (${event.type})`).toEqual(step.state);
      expect(projection.streaming, `streaming after step ${index}`).toEqual(step.streaming);
      expect(projection.reasoning, `reasoning after step ${index}`).toBe(step.reasoning);
      expect(live(projection), `live after step ${index}`).toBe(step.live);
      expect(describe(event, projection.state), `line for step ${index}`).toEqual(step.line);
      expect(history(projection.state), `history after step ${index}`).toEqual(step.history);
    });
  });

  test("transient events are described like the reference", () => {
    const state = (steps.at(-1) as Step).state as Parameters<typeof describe>[1];
    for (const item of golden.transient) {
      expect(describe(item.event as unknown as Event, state)).toEqual(item.line);
    }
  });

  test("a replayed record is ignored", () => {
    const projection = new Projection();
    const first = steps[0]?.record as EventRecord;
    expect(projection.apply(first)).toBe(true);
    expect(projection.apply(first)).toBe(false);
  });
});
