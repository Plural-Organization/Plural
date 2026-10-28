import { createHash } from "node:crypto";
import { expect, test } from "vitest";
import { sha256Fallback } from "./sha256";

test("the fallback hash matches the real one", () => {
  for (const size of [0, 3, 55, 56, 64, 1000, 70_000]) {
    const data = new Uint8Array(size).map((_, index) => (index * 31 + 7) % 256);
    expect(sha256Fallback(data)).toBe(createHash("sha256").update(data).digest("hex"));
  }
});

test("binary files are told apart from text", async () => {
  const { looksLikeText } = await import("../hooks/useAttachments");
  const bytes = (text: string) => new TextEncoder().encode(text);
  expect(looksLikeText(bytes("def main():\n    print('hi')\n"))).toBe(true);
  expect(looksLikeText(bytes("%PDF-1.7\n%âãÏÓ\n1 0 obj"))).toBe(false);
  expect(looksLikeText(new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x14, 0x00]))).toBe(false);
  expect(looksLikeText(new Uint8Array(200).fill(1))).toBe(false);
});
