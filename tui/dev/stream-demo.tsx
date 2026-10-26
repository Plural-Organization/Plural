import { render } from "ink";
import { App } from "../src/App";
import { FakeSession, HOST } from "../test/support/fake-session";

const fake = new FakeSession();
const direct = { initiator_id: "p_host", initiator_role: "host", origin: "direct" } as const;
fake.emit({ type: "session.welcome", room: "r_demo", token: "t", participant: HOST, base_policy: [] });
fake.emit({ type: "participant.joined", participant: HOST });

const section = (n: number): string =>
  [
    `## Section ${n}`,
    "",
    `This is paragraph ${n} with **bold** text, \`inline code\` and a [link](https://example.com). It runs long enough to wrap over several terminal columns.`,
    "",
    `- item one of ${n}`,
    `- item two of ${n}`,
    "",
    "```python",
    `def f${n}(x):`,
    `    return x * ${n}`,
    "```",
    "",
    "",
  ].join("\n");

const reply = Array.from({ length: Number(process.env["SECTIONS"] ?? 12) }, (_, index) => section(index + 1)).join("");

render(<App client={fake} room="r_demo" version="demo" guestLink={null} />, { exitOnCtrlC: false });
fake.emit({ type: "prompt.accepted", prompt_id: "pm1", author_id: "p_host", text: "write a long document", delivery: "now", provenance: direct, attachments: [] });
fake.emit({ type: "run.started", run_id: "r", prompt_id: "pm1", provenance: direct });
fake.emit({ type: "message.started", run_id: "r", message_id: "m1" });

let at = 0;
const timer = setInterval(() => {
  const piece = reply.slice(at, at + 40);
  at += 40;
  if (piece) {
    fake.emit({ type: "message.delta", message_id: "m1", text: piece, thinking: false });
    return;
  }
  clearInterval(timer);
  fake.emit({ type: "message.ended", run_id: "r", message_id: "m1", text: reply, thinking: "" });
  fake.emit({
    type: "run.ended",
    run_id: "r",
    reason: "stop",
    usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
    error: null,
  });
}, 12);
