import { expect, test } from "vitest";
import { finishTour, isNewcomer, tourSteps } from "./onboarding";

function memory(entries: Record<string, string> = {}) {
  const data = new Map(Object.entries(entries));
  return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => void data.set(key, value), data };
}

test("a browser with nothing of Plural in it is new", () => {
  expect(isNewcomer(memory())).toBe(true);
});

test("someone who used Plural before the tour existed is not shown it, and stays that way", () => {
  const store = memory({ "plural.rooms": "[]" });
  expect(isNewcomer(store)).toBe(false);
  expect(store.data.get("plural.toured")).toBe("returning");
  store.data.delete("plural.rooms");
  expect(isNewcomer(store)).toBe(false);
});

test("skipping counts as seen: the tour does not come back", () => {
  const store = memory();
  expect(isNewcomer(store)).toBe(true);
  finishTour("skipped", store);
  expect(isNewcomer(store)).toBe(false);
});

test("without storage nobody is pestered", () => {
  expect(isNewcomer(null)).toBe(false);
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => undefined };
  expect(isNewcomer(broken)).toBe(false);
});

test("the host is shown the agent switch; a guest, who cannot use it, is not", () => {
  const host = tourSteps(true).map((step) => step.target);
  const guest = tourSteps(false).map((step) => step.target);
  expect(host).toContain("agent");
  expect(guest).not.toContain("agent");
  for (const steps of [tourSteps(true), tourSteps(false)]) {
    expect(steps[0]!.target).toBeNull();
    expect(steps.at(-1)!.target).toBeNull();
    expect(new Set(steps.map((step) => step.id)).size).toBe(steps.length);
  }
});

test("host and guest are both told what the danger zone means before they meet it", () => {
  for (const isHost of [true, false]) {
    const step = tourSteps(isHost).find((item) => item.target === "permissions");
    expect(step?.points?.some((point) => point.tone === "danger" && point.label === "Danger zone")).toBe(true);
  }
});
