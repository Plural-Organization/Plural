import { afterEach, beforeEach, expect, test, vi } from "vitest";

const started: number[] = [];

class FakeAudio {
  state = "running";
  currentTime = 0;
  destination = {};
  resume = vi.fn(async (): Promise<void> => undefined);
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
  const { alertMention, unlockAudio } = await import("./alert");
  expect(() => unlockAudio()).not.toThrow();
  expect(() => alertMention("Alia", true)).not.toThrow();
});

test("joining unlocks audio without playing a notification", async () => {
  const instance = new FakeAudio();
  vi.stubGlobal("AudioContext", function () { return instance; });
  const { unlockAudio, beep } = await import("./alert");
  unlockAudio();
  expect(instance.resume).toHaveBeenCalledOnce();
  expect(started).toHaveLength(0);
  beep();
  expect(started).toHaveLength(1);
});

test("a suspended context starts the tone only after resuming", async () => {
  const instance = new FakeAudio();
  instance.state = "suspended";
  let finish!: () => void;
  instance.resume = vi.fn(() => new Promise<void>((resolve) => { finish = () => { instance.state = "running"; resolve(); }; }));
  vi.stubGlobal("AudioContext", function () { return instance; });
  const { beep } = await import("./alert");
  beep();
  expect(started).toHaveLength(0);
  finish();
  await Promise.resolve();
  expect(started).toHaveLength(1);
});

test("blocked audio does not reject or prevent the tab notification", async () => {
  const instance = new FakeAudio();
  instance.state = "suspended";
  instance.resume = vi.fn(async () => { throw new Error("blocked"); });
  vi.stubGlobal("AudioContext", function () { return instance; });
  const { unlockAudio, alertNotice } = await import("./alert");
  unlockAudio();
  alertNotice("Alia joined");
  await Promise.resolve();
  await Promise.resolve();
  expect(started).toHaveLength(0);
  expect(document.title).toBe("✉ Alia joined");
});
