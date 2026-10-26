import { expect, test } from "vitest";
import { emptyState, Projection, label, ruleLine, status, type Participant } from "../src";

const alia: Participant = { id: "p_alia1111", name: "Alia", role: "participant", connected: true };
const twin: Participant = { id: "p_alia2222", name: "Alia", role: "viewer", connected: true };

test("a name shared by two participants gets an id suffix", () => {
  const state = { ...emptyState(), participants: { [alia.id]: alia } };
  expect(label(state, alia)).toBe("Alia");
  const twins = { ...state, participants: { ...state.participants, [twin.id]: twin } };
  expect(label(twins, alia)).toBe("Alia #1111");
  expect(label(twins, twin)).toBe("Alia #2222");
});

test("a rule is shown with its action padded", () => {
  expect(ruleLine({ id: "pl_1", tool: "bash", pattern: "make *", action: "allow" })).toBe("allow bash make *");
  expect(ruleLine({ id: "pl_2", tool: "bash", pattern: "rm *", action: "ask" })).toBe("ask   bash rm *");
});

test("the run status follows what the run is waiting for", () => {
  const projection = new Projection();
  expect(status(projection)).toBe("");
  const provenance = { initiator_id: "p_host", initiator_role: "host", origin: "direct" } as const;
  projection.state = { ...projection.state, run: { id: "r", prompt_id: "pm", provenance } };
  expect(status(projection)).toBe("… waiting for the model");
  projection.reasoning = 40;
  expect(status(projection)).toBe("… thinking (40 chars)");
  const call = { id: "t1", name: "bash", risk: "exec", subject: "ls", args: {} } as const;
  projection.state = {
    ...projection.state,
    transcript: [{ id: "t1", kind: "tool", author_id: null, text: "", tool: call, ok: null, output: "" }],
  };
  expect(status(projection)).toBe("… running bash");
  const approval = { id: "ap", call, provenance, timeout_at: "2026-10-26T12:00:00Z", suggested_patterns: [] };
  projection.state = { ...projection.state, approvals: { ap: approval } };
  expect(status(projection)).toBe("… waiting for host approval");
});
