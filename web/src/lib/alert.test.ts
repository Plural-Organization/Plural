import { afterEach, beforeEach, expect, test, vi } from "vitest";

const started: number[] = [];

class FakeAudio {
  currentTime = 0;
  destination = {};
  resume = vi.fn(async () => undefined);
  createOscillator() {
    const node = { type: "", frequency: { setValueAtTime: vi.fn() }, connect: () => ({ connect: () => undefined }), start: () => started.push(1), stop: vi.fn() };
    return node;
  }
  createGain() {
    return { gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: () => ({ connect: () => undefined }) };
  }
}

beforeEach(() => {
  started.length = 0;
  vi.resetModules();
  vi.stubGlobal("AudioContext", FakeAudio);
  vi.stubGlobal("window", { addEventListener: vi.fn(), removeEventListener: vi.fn() });
  vi.stubGlobal("document", { hidden: true, title: "plural", addEventListener: vi.fn(), removeEventListener: vi.fn() });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("a mention plays a sound and marks the tab when the page is hidden", async () => {
  const { alertMention } = await import("./alert");
  alertMention("Alia", true);
  expect(started).toHaveLength(1);
  expect(document.title).toBe("✉ Alia wrote to you");
});

test("a tag reads differently and a visible page keeps its title", async () => {
  const { alertMention } = await import("./alert");
  alertMention("Bek", false);
  expect(document.title).toBe("✉ Bek mentioned you");
  vi.stubGlobal("document", { hidden: false, title: "plural", addEventListener: vi.fn(), removeEventListener: vi.fn() });
  vi.resetModules();
  const fresh = await import("./alert");
  fresh.alertMention("Cleo", true);
  expect(document.title).toBe("plural");
  expect(started).toHaveLength(2);
});

test("a browser without audio does not break the page", async () => {
  vi.stubGlobal("AudioContext", undefined);
  const { alertMention } = await import("./alert");
  expect(() => alertMention("Alia", true)).not.toThrow();
});
