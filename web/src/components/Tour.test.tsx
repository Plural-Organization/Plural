import { expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { tourSteps } from "../lib/onboarding";
import { TourCard } from "./Tour";

const steps = tourSteps(true);
const card = (index: number, back = index > 0) =>
  renderToStaticMarkup(<TourCard step={steps[index]!} index={index} count={steps.length} onBack={back ? () => undefined : undefined} onNext={() => undefined} onSkip={() => undefined} />);

test("the first card says where it is, can be skipped and has no way back", () => {
  const html = card(0);
  expect(html).toContain(`Step 1 of ${steps.length}`);
  expect(html).toContain("Skip tour");
  expect(html).toContain("Show me");
  expect(html).not.toContain('aria-label="Back"');
});

test("a middle card goes back and forward and lights its own dot", () => {
  const html = card(2);
  expect(html).toContain('aria-label="Back"');
  expect(html).toContain("Next");
  expect(html.match(/data-on="true"/g)).toHaveLength(1);
});

test("the last card ends the tour instead of offering to skip it", () => {
  const html = card(steps.length - 1);
  expect(html).toContain("Start working");
  expect(html).not.toContain("Skip tour");
});

test("a step that compares choices lists them, the dangerous one marked", () => {
  const index = steps.findIndex((step) => step.id === "permissions");
  const html = card(index);
  expect(html).toContain("Danger zone");
  expect(html).toContain('data-tone="danger"');
});
