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

test("the agent label follows a change and falls back to the one from the welcome", () => {
  const projection = new Projection();
  expect(projection.agentLabel).toBe("");
  projection.agent = "demo agent (scripted)";
  expect(projection.agentLabel).toBe("demo agent (scripted)");
  projection.apply({
    seq: 1,
    id: "e1",
    ts: "2026-10-28T12:00:00Z",
    actor_id: null,
    event: { type: "agent.changed", agent: "Ollama · qwen3-coder", fast: "" },
  });
  expect(projection.agentLabel).toBe("Ollama · qwen3-coder");
});

test("selections follow the events and end when someone leaves", () => {
  const projection = new Projection();
  const pick = { anchor: "m_1", start: 2, end: 9 };
  projection.observe({ type: "participant.selected", participant_id: "p_alia", selection: pick });
  projection.observe({ type: "participant.selected", participant_id: "p_bek", selection: pick });
  projection.observe({ type: "participant.selected", participant_id: "p_bek", selection: null });
  expect([...projection.selections]).toEqual([["p_alia", pick]]);
  projection.apply({
    seq: 1,
    id: "e1",
    ts: "2026-10-28T12:00:00Z",
    actor_id: null,
    event: { type: "participant.left", participant_id: "p_alia" },
  });
  expect(projection.selections.size).toBe(0);
});

test("the board keeps strokes, erases one and clears", () => {
  const projection = new Projection();
  const stroke = { id: "st_1", author_id: "p_alia", kind: "pen" as const, text: null, color: "#ffffff", width: 2, points: [0.1, 0.1, 0.2, 0.2] as [number, number, ...number[]] };
  const record = (seq: number, event: EventRecord["event"]): EventRecord => ({ seq, id: `e${seq}`, ts: "2026-10-28T12:00:00Z", actor_id: null, event });
  projection.apply(record(1, { type: "board.opened", open: true, by: "p_alia" }));
  projection.apply(record(2, { type: "board.stroked", stroke }));
  projection.apply(record(3, { type: "board.stroked", stroke: { ...stroke, id: "st_2" } }));
  projection.apply(record(4, { type: "board.erased", stroke_id: "st_1" }));
  expect(projection.state.board.open).toBe(true);
  expect(projection.state.board.strokes.map((item) => item.id)).toEqual(["st_2"]);
  projection.apply(record(5, { type: "board.cleared", by: "p_host", author_id: null }));
  expect(projection.state.board.strokes).toEqual([]);
  projection.observe({ type: "participant.cursor", participant_id: "p_alia", cursor: { x: 0.5, y: 0.5, ink: false, color: null, width: null } });
  expect(projection.cursors.get("p_alia")?.x).toBe(0.5);
});
