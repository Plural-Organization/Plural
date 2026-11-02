import { afterAll, afterEach, describe, expect, mock, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { testRender } from "@opentui/react/test-utils";
import { imageKind, imagePath } from "../src/lib/image-paste";
import { HOST, FakeSession } from "./support/fake-session";

const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);
const GIF = Buffer.from("GIF89a....", "latin1");
let clipboard: Buffer | null = PNG;
mock.module("../src/lib/clipboard", () => ({
  copyToClipboard: async () => undefined,
  pasteImage: async () => clipboard,
  IMAGE_LIMIT_BYTES: 2_500_000,
}));
const { App } = await import("../src/App");

const dir = mkdtempSync(join(tmpdir(), "plural-image-paste-"));
const gifFile = join(dir, "my shot.gif");
writeFileSync(gifFile, GIF);
afterAll(() => rmSync(dir, { recursive: true, force: true }));

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

describe("a pasted path to an image", () => {
  test("is read the way terminals and Finder write it", () => {
    expect(imagePath("/tmp/a.png")).toBe("/tmp/a.png");
    expect(imagePath("/tmp/my\\ shot.JPG ")).toBe("/tmp/my shot.JPG");
    expect(imagePath("'/tmp/my shot.webp'")).toBe("/tmp/my shot.webp");
    expect(imagePath("file:///tmp/my%20shot.gif")).toBe("/tmp/my shot.gif");
    expect(imagePath("~/a.jpeg")).toBe(`${homedir()}/a.jpeg`);
  });

  test("anything else stays text", () => {
    expect(imagePath("look at /tmp/a.png")).toBeNull();
    expect(imagePath("/tmp/a.txt")).toBeNull();
    expect(imagePath("a.png")).toBeNull();
    expect(imagePath("/tmp/a.png\n/tmp/b.png")).toBeNull();
  });

  test("the kind comes from the bytes", () => {
    expect(imageKind(PNG)).toBe("png");
    expect(imageKind(Buffer.from([0xff, 0xd8, 0xff, 0]))).toBe("jpg");
    expect(imageKind(GIF)).toBe("gif");
    expect(imageKind(Buffer.from("RIFF....WEBP", "latin1"))).toBe("webp");
    expect(imageKind(Buffer.from("hello"))).toBeNull();
  });
});

test("cmd+v with an image on the clipboard attaches it", async () => {
  clipboard = PNG;
  const { fake, setup } = await mount();
  await setup.mockInput.pasteBracketedText("");
  await until(setup, () => setup.captureCharFrame().includes("[image-1.png]"));
  expect(fake.commands.find((command) => command.type === "file.attach")).toMatchObject({ content_b64: PNG.toString("base64") });
});

test("a dragged image file is attached instead of its path", async () => {
  const { fake, setup } = await mount();
  await setup.mockInput.pasteBracketedText(gifFile.replace(/ /g, "\\ "));
  await until(setup, () => setup.captureCharFrame().includes("[image-1.gif]"));
  expect(fake.commands.find((command) => command.type === "file.attach")).toMatchObject({ name: "image-1.gif", content_b64: GIF.toString("base64") });
  expect(setup.captureCharFrame()).not.toContain("my shot");
});

test("a path to no file stays in the box as text", async () => {
  const { fake, setup } = await mount();
  await setup.mockInput.pasteBracketedText("/nowhere/missing.png");
  await until(setup, () => setup.captureCharFrame().includes("/nowhere/missing.png"));
  expect(fake.commands.some((command) => command.type === "file.attach")).toBe(false);
});
