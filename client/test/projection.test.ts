import { expect, test } from "vitest";
import { emptyState, Projection, type EventRecord } from "../src";

test("typing follows the events and a snapshot replaces it", () => {
  const projection = new Projection();
  projection.observe({ type: "participant.typing", participant_id: "p_alia", typing: true });
  projection.observe({ type: "participant.typing", participant_id: "p_bek", typing: true });
  projection.observe({ type: "participant.typing", participant_id: "p_alia", typing: false });
  expect([...projection.typing]).toEqual(["p_bek"]);

  projection.load(emptyState(), {}, ["p_cleo"]);
  expect([...projection.typing]).toEqual(["p_cleo"]);
  projection.load(emptyState(), {});
  expect(projection.typing.size).toBe(0);
});

test("someone who is revoked stops typing", () => {
  const projection = new Projection();
  projection.observe({ type: "participant.typing", participant_id: "p_alia", typing: true });
  const record: EventRecord = {
    seq: 1,
    id: "e1",
    ts: "2026-10-26T12:00:00Z",
    actor_id: null,
    event: { type: "participant.revoked", participant_id: "p_alia" },
  };
  projection.apply(record);
  expect(projection.typing.size).toBe(0);
});
