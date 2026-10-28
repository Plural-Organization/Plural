import { createHash } from "node:crypto";
import { expect, test } from "vitest";
import { sha256Fallback } from "./sha256";

test("the fallback hash matches the real one", () => {
  for (const size of [0, 3, 55, 56, 64, 1000, 70_000]) {
    const data = new Uint8Array(size).map((_, index) => (index * 31 + 7) % 256);
    expect(sha256Fallback(data)).toBe(createHash("sha256").update(data).digest("hex"));
  }
});
