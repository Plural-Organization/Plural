import { describe, expect, test } from "bun:test";
import { parseAsk } from "../src/lib/ask";

const words = (text: string): string[] => text.split(" ").filter((word) => word !== "");

describe("what follows /ask", () => {
  test("a question to a teammate's agent", () => {
    expect(parseAsk(words("@alia how does /orders work?"))).toEqual({ kind: "ask", target: "alia", focus: "how does /orders work?", update: false });
    expect(parseAsk(words("@alia:api"))).toEqual({ kind: "ask", target: "alia:api", focus: null, update: false });
  });

  test("without a name it is the session this view belongs to, as /brief always was", () => {
    expect(parseAsk(words("how was the login fixed?"))).toEqual({ kind: "ask", target: null, focus: "how was the login fixed?", update: false });
    expect(parseAsk([])).toEqual({ kind: "ask", target: null, focus: null, update: false });
  });

  test("an update is asked with the flag anywhere, or with the word first", () => {
    expect(parseAsk(words("@alia --update"))).toEqual({ kind: "ask", target: "alia", focus: null, update: true });
    expect(parseAsk(words("@alia what is left? --update"))).toEqual({ kind: "ask", target: "alia", focus: "what is left?", update: true });
    expect(parseAsk(words("update what is left?"))).toEqual({ kind: "ask", target: null, focus: "what is left?", update: true });
    expect(parseAsk(words("@alia update"))).toEqual({ kind: "ask", target: "alia", focus: null, update: true });
  });

  test("a lone @ is not a name, and give and share are words of their own", () => {
    expect(parseAsk(words("@"))).toEqual({ kind: "ask", target: null, focus: "@", update: false });
    expect(parseAsk(words("give"))).toEqual({ kind: "give" });
    expect(parseAsk(words("share team"))).toEqual({ kind: "share", mode: "team" });
    expect(parseAsk(words("share"))).toEqual({ kind: "share", mode: null });
    expect(parseAsk(words("share everyone"))).toEqual({ kind: "share", mode: null });
  });
});
