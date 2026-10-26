import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import { App } from "../src/App";
import { FakeSession } from "../test/support/fake-session";

const fake = new FakeSession();
const person = (id: string, name: string, role: "host" | "participant" | "viewer", connected = true) =>
  ({ id, name, role, connected }) as const;
const vlad = person("p_vlad", "vlad", "host");
const alia = person("p_alia", "alia", "participant");
const bek = person("p_bek", "bek", "participant");
const cleo = person("p_cleo", "cleo", "viewer");
const dan = person("p_dan", "dan", "participant", false);
const direct = (p: typeof vlad) => ({ initiator_id: p.id, initiator_role: p.role, origin: "direct" }) as const;
const usage = { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 };

fake.emit({ type: "session.welcome", room: "r_01M5W7ACDDJR7954MF354JW85W", token: "t", participant: vlad, base_policy: [] });
for (const p of [vlad, alia, bek, cleo, dan]) {
  fake.emit({ type: "participant.joined", participant: p });
}
fake.emit({ type: "participant.left", participant_id: "p_dan" });
fake.emit({ type: "prompt.accepted", prompt_id: "pm1", author_id: "p_vlad", text: "Fix the failing test in calc.py and show me the diff", delivery: "now", provenance: direct(vlad), attachments: [] });
fake.emit({ type: "run.started", run_id: "r1", prompt_id: "pm1", provenance: direct(vlad) });
const read = { id: "t1", name: "read", risk: "read", subject: "calc.py", args: {} } as const;
fake.emit({ type: "tool.started", run_id: "r1", call: read });
fake.emit({ type: "tool.ended", run_id: "r1", call_id: "t1", ok: true, output: "def add(a, b):\n    return a - b\n", diff: null });
const test = { id: "t2", name: "bash", risk: "exec", subject: "pytest -q", args: {} } as const;
fake.emit({ type: "tool.started", run_id: "r1", call: test });
fake.emit({ type: "tool.ended", run_id: "r1", call_id: "t2", ok: false, output: "FAILED test_calc.py::test_add - assert 1 == 3\n1 failed in 0.02s\n[exit 1]", diff: null });
const edit = { id: "t3", name: "edit", risk: "write", subject: "calc.py", args: {} } as const;
fake.emit({ type: "tool.started", run_id: "r1", call: edit });
fake.emit({
  type: "tool.ended",
  run_id: "r1",
  call_id: "t3",
  ok: true,
  output: "edited calc.py",
  diff: "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n",
});
fake.emit({ type: "message.started", run_id: "r1", message_id: "m1" });
const reply = `The bug was the operator in **\`add\`**. I changed it and the test passes now.

\`\`\`python
def add(a, b):
    """Return the sum of two numbers."""
    return a + b  # was: a - b
\`\`\`

Next steps:

1. run the whole suite
2. add a test for negative numbers

\`\`\`ts
export const add = (a: number, b: number): number => a + b;
\`\`\`

| file | change | author |
|------|--------|--------|
| calc.py | fix \`add\` | vlad |
`;
fake.emit({ type: "message.delta", message_id: "m1", text: reply, thinking: false });
fake.emit({ type: "message.ended", run_id: "r1", message_id: "m1", text: reply, thinking: "" });
fake.emit({ type: "run.ended", run_id: "r1", reason: "stop", usage, error: null });
fake.emit({ type: "prompt.accepted", prompt_id: "pm2", author_id: "p_alia", text: "also remove the temp files please", delivery: "now", provenance: direct(alia), attachments: [] });
fake.emit({ type: "run.started", run_id: "r2", prompt_id: "pm2", provenance: direct(alia) });
const rm = { id: "t4", name: "bash", risk: "exec", subject: "rm -f tmp/*.log", args: {} } as const;
fake.emit({ type: "tool.started", run_id: "r2", call: rm });
fake.emit({
  type: "approval.requested",
  approval: { id: "ap1", call: rm, provenance: direct(alia), timeout_at: new Date(Date.now() + 110_000).toISOString(), suggested_patterns: ["rm *"] },
});
fake.emit({ type: "proposal.created", proposal: { id: "pr1", author_id: "p_bek", text: "add a README for the project", delivery: "now", attachments: [] } });

const renderer = await createCliRenderer({ exitOnCtrlC: false, useMouse: true });
createRoot(renderer).render(
  <App client={fake} room="r_01M5W7ACDDJR7954MF354JW85W" version="0.2.0" guestLink="ws://127.0.0.1:7777/r_01M5W7ACDDJR7954MF354JW85W?invite=abc" onQuit={() => renderer.destroy()} />,
);
