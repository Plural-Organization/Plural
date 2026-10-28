import { expect, test } from "vitest";
import { emptyFeed, Projection, type Feed, type FeedItem, type SessionState } from "@plural/client";
import { activity } from "./activity";

const call = { id: "c1", name: "bash", subject: "npm test", args: {}, risk: "exec" };

function projection(state: Partial<SessionState>, meRole: "host" | "participant" = "host"): Projection {
  const view = new Projection();
  view.meId = "p_me";
  view.state = {
    ...view.state,
    participants: { p_me: { id: "p_me", name: "me", role: meRole, connected: true } },
    ...state,
  } as SessionState;
  return view;
}

const running = { id: "r1" } as unknown as SessionState["run"];
const feedOf = (...items: FeedItem[]): Feed => ({ ...emptyFeed(), items });

test("nothing shows while the agent is idle", () => {
  expect(activity(projection({}), emptyFeed())).toBeNull();
});

test("an approval asks the host and tells the others who decides", () => {
  const approvals = { a1: { id: "a1", call } } as unknown as SessionState["approvals"];
  expect(activity(projection({ run: running, approvals }), emptyFeed())).toMatchObject({ kind: "approval", text: "Asks your permission" });
  expect(activity(projection({ run: running, approvals }, "participant"), emptyFeed())?.text).toBe("Waits for the host's permission");
});

test("a running tool and a streaming reply name what the agent does", () => {
  const tool: FeedItem = { kind: "tool", id: "t1", call: call as never, status: "running", output: "", diff: null, live: "" };
  expect(activity(projection({ run: running }), feedOf(tool))?.text).toBe("Running a command");
  const reply: FeedItem = { kind: "assistant", id: "m1", text: "Hi", streaming: true };
  expect(activity(projection({ run: running }), feedOf(reply))?.kind).toBe("writing");
  expect(activity(projection({ run: running }), emptyFeed())?.text).toBe("Thinking");
});
