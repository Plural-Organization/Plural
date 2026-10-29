import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { emptyState, type ApprovalView } from "@plural/client";
import { ApprovalCard } from "./ApprovalCard";

const approval: ApprovalView = {
  id: "a_1",
  call: { id: "t1", name: "edit", risk: "write", subject: "src/auth.py", args: {} },
  provenance: { initiator_id: "p_host", initiator_role: "host", origin: "direct" },
  timeout_at: new Date(Date.now() + 60_000).toISOString(),
  suggested_patterns: [],
  warnings: [],
};

const render = (view: ApprovalView) => renderToStaticMarkup(<ApprovalCard approval={view} state={emptyState()} now={Date.now()} send={() => undefined} />);

test("a file a teammate also changed is flagged on the card", () => {
  const html = render({ ...approval, warnings: ["src/auth.py was also changed by alia 3 min ago on feat/x"] });
  expect(html).toContain("alia");
  expect(html).toContain("3 min ago on feat/x");
  expect(html).toContain('role="alert"');
});

test("a card with nothing to warn about has no alert, and an older host without the field still renders", () => {
  expect(render(approval)).not.toContain('role="alert"');
  const { warnings: _omitted, ...older } = approval;
  expect(render(older as ApprovalView)).not.toContain('role="alert"');
});

test("a warning is shown as text, never as markup", () => {
  const html = render({ ...approval, warnings: ["<img src=x onerror=alert(1)>"] });
  expect(html).not.toContain("<img");
  expect(html).toContain("&lt;img");
});
