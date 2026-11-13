import { expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Projection } from "@plural/client";
import { TopBar } from "./TopBar";

test("OAuth hides the context meter and returning to an API connection restores it", () => {
  const projection = new Projection();
  projection.state = { ...projection.state, agent: "Claude OAuth · claude-haiku-4-5", context: { tokens: 96000, window: 128000, compact_at: 0.75, parts: [], hit: null } };
  const render = () => renderToStaticMarkup(<TopBar room="r_test" projection={projection} connection="online" panelOpen={false} railOpen onToggleRail={() => undefined} onCopyRoom={() => undefined} onTogglePanel={() => undefined} onLeave={() => undefined} />);
  expect(render()).not.toContain("context 75%");
  projection.state = { ...projection.state, agent: "Anthropic · claude-opus-5-5" };
  expect(render()).toContain("context 75%");
});

test("everyone sees whether a plain message reaches the agent", () => {
  const projection = new Projection();
  const render = () => renderToStaticMarkup(<TopBar room="r_test" projection={projection} connection="online" panelOpen={false} railOpen onToggleRail={() => undefined} onCopyRoom={() => undefined} onTogglePanel={() => undefined} onLeave={() => undefined} />);
  projection.state = { ...projection.state, chat_mode: "mention" };
  expect(render()).toContain("agent answers @plrl");
  projection.state = { ...projection.state, chat_mode: "all" };
  expect(render()).toContain("agent answers all");
});
