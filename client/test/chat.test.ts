import { describe, expect, test } from "vitest";
import { emptyState, mentionable, mentionsIn, mentionsMe, parseChat, routeOf, SlashError, type SessionState } from "../src";

function room(): SessionState {
  const state = emptyState();
  state.participants = {
    p_me: { id: "p_me", name: "vlad", role: "host", connected: true },
    p_alia: { id: "p_alia", name: "Alia", role: "participant", connected: true },
    p_bek1: { id: "p_bek1", name: "Bek", role: "participant", connected: false },
    p_bek2: { id: "p_bek2", name: "Bek", role: "participant", connected: true },
    p_ann: { id: "p_ann", name: "Ann Lee", role: "participant", connected: true },
    p_view: { id: "p_view", name: "Cleo", role: "viewer", connected: true },
  };
  return state;
}

describe("who can be tagged", () => {
  test("everyone but me, people online first, twins told apart", () => {
    const names = mentionable(room(), "p_me").map((person) => person.label);
    expect(names).toEqual(["Alia", "Ann Lee", "Bek #bek2", "Cleo", "Bek #bek1"]);
  });
});

describe("a private message", () => {
  test("starts with @name and the rest goes to that person", () => {
    const intent = parseChat("@alia can you review this?", room(), "p_me");
    expect(intent?.command).toEqual({ type: "chat.send", text: "can you review this?", to: "p_alia", mentions: [] });
    expect(intent?.to?.label).toBe("Alia");
  });

  test("a name with a space and a twin are matched by their whole label", () => {
    expect(parseChat("@Ann Lee hello", room(), "p_me")?.command.to).toBe("p_ann");
    expect(parseChat("@Bek #bek2 hello", room(), "p_me")?.command.to).toBe("p_bek2");
  });

  test("a name must end where the word ends", () => {
    expect(parseChat("@Aliana hello", room(), "p_me")).toBeNull();
    expect(parseChat("@alia, hello", room(), "p_me")?.command.text).toBe("hello");
    expect(parseChat("@alia: hello", room(), "p_me")?.command.text).toBe("hello");
  });

  test("a token that is no one in the room stays a prompt for the agent", () => {
    expect(parseChat("@src/app.ts is broken", room(), "p_me")).toBeNull();
    expect(parseChat("fix @alia's bug", room(), "p_me")).toBeNull();
  });

  test("an empty message and a watcher are explained", () => {
    expect(() => parseChat("@Alia", room(), "p_me")).toThrow(SlashError);
    expect(() => parseChat("@Cleo hi", room(), "p_me")).toThrow(/cannot get private messages/);
  });
});

describe("a message for the room", () => {
  test("/team, /to-team and /chat all write to the room", () => {
    for (const name of ["team", "to-team", "chat"]) {
      const intent = parseChat(`/${name} lunch at one`, room(), "p_me");
      expect(intent?.command).toEqual({ type: "chat.send", text: "lunch at one", to: null, mentions: [] });
      expect(intent?.to).toBeNull();
    }
  });

  test("a tag inside it rings that person and everyone still reads it", () => {
    const intent = parseChat("/team @Alia and @Ann Lee please look, not@Bek", room(), "p_me");
    expect(intent?.command.to).toBeNull();
    expect(intent?.command.mentions).toEqual(["p_alia", "p_ann"]);
  });

  test("without a message the usage is shown", () => {
    expect(() => parseChat("/team", room(), "p_me")).toThrow(/usage: \/team/);
    expect(() => parseChat("/team   ", room(), "p_me")).toThrow(SlashError);
  });

  test("other commands and plain text are not chat", () => {
    expect(parseChat("/mode open", room(), "p_me")).toBeNull();
    expect(parseChat("hello team", room(), "p_me")).toBeNull();
  });
});

describe("who is addressed", () => {
  const people = mentionable(room(), "p_me");
  test("tags are found where a word begins", () => {
    expect(mentionsIn("hi @Alia, and (@Cleo) but a@Ann Lee", people)).toEqual(["p_alia", "p_view"]);
  });

  test("I am addressed by a private message or a tag, never by myself", () => {
    expect(mentionsMe({ author_id: "p_alia", to: "p_me", mentions: [] }, "p_me")).toBe(true);
    expect(mentionsMe({ author_id: "p_alia", to: null, mentions: ["p_me"] }, "p_me")).toBe(true);
    expect(mentionsMe({ author_id: "p_alia", to: null, mentions: [] }, "p_me")).toBe(false);
    expect(mentionsMe({ author_id: "p_me", to: "p_alia", mentions: ["p_me"] }, "p_me")).toBe(false);
    expect(mentionsMe({ author_id: "p_alia", to: "p_me", mentions: [] }, null)).toBe(false);
  });
});

describe("who will see what I am typing", () => {
  test("plain text goes to the agent and the room sees it", () => {
    expect(routeOf("fix the tests", room(), "p_me")).toMatchObject({ kind: "agent", label: "agent", note: "everyone in the room sees it" });
  });

  test("a participant in review mode is told the host approves it", () => {
    const state = { ...room(), prompt_mode: "review" as const };
    expect(routeOf("fix the tests", state, "p_alia").note).toBe("the host approves it first");
    expect(routeOf("fix the tests", state, "p_me").note).toBe("everyone in the room sees it");
  });

  test("/team goes to the room and the agent does not see it", () => {
    expect(routeOf("/team standup", room(), "p_me")).toMatchObject({ kind: "room", label: "room" });
    expect(routeOf("/chat", room(), "p_me").kind).toBe("room");
  });

  test("@name goes to one person, and says when they are away", () => {
    expect(routeOf("@alia hi", room(), "p_me")).toMatchObject({ kind: "person", label: "@Alia", blocked: false });
    expect(routeOf("@Bek #bek1 hi", room(), "p_me").note).toContain("offline");
  });

  test("a watcher cannot get a private message and the route says so", () => {
    expect(routeOf("@cleo hi", room(), "p_me")).toMatchObject({ kind: "person", blocked: true });
  });

  test("an unknown @name and a half-typed one go to the agent", () => {
    expect(routeOf("@nobody hi", room(), "p_me").kind).toBe("agent");
    expect(routeOf("@", room(), "p_me").kind).toBe("agent");
  });

  test("other slash commands are not prompts", () => {
    expect(routeOf("/compact", room(), "p_me")).toMatchObject({ kind: "command", label: "/compact" });
  });
});
