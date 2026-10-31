import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { ShareDialog } from "../src/components/ShareDialog";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  while (open.length) open.pop()?.renderer.destroy();
});

async function settle(setup: Setup): Promise<string> {
  await new Promise((resolve) => setTimeout(resolve, 50));
  await setup.renderOnce();
  return setup.captureCharFrame();
}

for (const action of ["y", "click", "enter"] as const) {
  test(`share confirmation after selecting cancel: ${action}`, async () => {
    const shared: string[] = [];
    let closed = 0;
    const setup = await testRender(
      <ShareDialog
        width={120}
        height={40}
        teamName="Backend"
        folders={[{ path: "/repo", name: "repo", detail: "test repository" }]}
        onShare={async (path) => { shared.push(path); }}
        onClose={() => { closed += 1; }}
      />,
      { width: 120, height: 40 },
    );
    open.push(setup);
    await settle(setup);
    await setup.mockInput.pressEnter();
    expect(await settle(setup)).toContain("share my host · confirm");
    await setup.mockInput.pressArrow("right");
    const frame = await settle(setup);
    expect(shared).toEqual([]);
    expect(closed).toBe(0);
    if (action === "click") {
      const lines = frame.split("\n");
      const row = lines.findIndex((line) => line.includes("I agree · share"));
      expect(row).toBeGreaterThanOrEqual(0);
      await setup.mockMouse.click(lines[row]!.indexOf("I agree") + 2, row);
    } else if (action === "y") {
      await setup.mockInput.typeText("y");
    } else {
      await setup.mockInput.pressEnter();
    }
    await settle(setup);
    expect(shared).toEqual(action === "enter" ? [] : ["/repo"]);
    expect(closed).toBe(1);
  });
}
