import { afterEach, expect, mock, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { HOST, FakeSession } from "./support/fake-session";

const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);
let clipboard: Buffer | null = PNG;
mock.module("../src/lib/clipboard", () => ({
  copyToClipboard: async () => undefined,
  pasteImage: async () => clipboard,
  IMAGE_LIMIT_BYTES: 2_500_000,
}));
const { App } = await import("../src/App");

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

async function until(setup: Setup, check: () => boolean, timeout = 3000): Promise<void> {
  const deadline = Date.now() + timeout;
  while (!check()) {
    if (Date.now() > deadline) {
      throw new Error(`timed out in:\n${setup.captureCharFrame()}`);
    }
    await setup.renderOnce();
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

async function mount(): Promise<{ fake: FakeSession; setup: Setup }> {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "demo" });
  fake.emit({ type: "participant.joined", participant: HOST });
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.0" guestLink={null} onQuit={() => undefined} />,
    { width: 120, height: 36 },
  );
  open.push(setup);
  await until(setup, () => setup.captureCharFrame().includes("Message the agent"));
  return { fake, setup };
}

test("ctrl+v uploads the clipboard image and the next prompt carries it", async () => {
  clipboard = PNG;
  const { fake, setup } = await mount();
  await setup.mockInput.pressKey("v", { ctrl: true });
  await until(setup, () => setup.captureCharFrame().includes("[image-1.png]"));
  const attach = fake.commands.find((command) => command.type === "file.attach");
  expect(attach).toMatchObject({ name: "image-1.png", content_b64: PNG.toString("base64") });
  if (attach?.type !== "file.attach") {
    throw new Error("no upload");
  }
  fake.emit({
    type: "attachment.added",
    attachment: { id: "at_1", name: attach.name, size: PNG.length, sha256: attach.sha256, owner_id: HOST.id },
  });

  await setup.mockInput.typeText("what is on it?");
  await setup.mockInput.pressEnter();
  await until(setup, () => fake.commands.some((command) => command.type === "prompt.submit"));
  expect(fake.commands.find((command) => command.type === "prompt.submit")).toMatchObject({
    text: "what is on it?",
    attachments: ["at_1"],
  });
  await until(setup, () => !setup.captureCharFrame().includes("[image-1.png]"));
});

test("backspace on an empty composer drops the last image, and an empty clipboard says so", async () => {
  clipboard = PNG;
  const { setup } = await mount();
  await setup.mockInput.pressKey("v", { ctrl: true });
  await until(setup, () => setup.captureCharFrame().includes("[image-1.png]"));
  await setup.mockInput.pressBackspace();
  await until(setup, () => !setup.captureCharFrame().includes("[image-1.png]"));

  clipboard = null;
  await setup.mockInput.pressKey("v", { ctrl: true });
  await until(setup, () => setup.captureCharFrame().includes("no image in the clipboard"));
});
