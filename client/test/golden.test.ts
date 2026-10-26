import { describe as suite, expect, test } from "vitest";
import golden from "./fixtures/golden.json";
import { Projection, type Event, type EventRecord } from "../src";

interface Step {
  kind: "record" | "observe";
  record?: EventRecord;
  event?: Event;
  state: unknown;
  streaming: Record<string, string>;
  reasoning: number;
}

const steps = golden.steps as unknown as Step[];

suite("reducer and projection match the Python reference", () => {
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
    });
  });

  test("a replayed record is ignored", () => {
    const projection = new Projection();
    const first = steps[0]?.record as EventRecord;
    expect(projection.apply(first)).toBe(true);
    expect(projection.apply(first)).toBe(false);
  });
});
