export type AskIntent =
  // Hand the latest briefing to my own agent.
  | { kind: "give" }
  // The host's setting for who may ask this session; null shows it.
  | { kind: "share"; mode: "off" | "ask" | "team" | null }
  // `target` is `name` or `name:repo` of a teammate; null means the session this view belongs to.
  | { kind: "ask"; target: string | null; focus: string | null; update: boolean };

const SHARING = ["off", "ask", "team"] as const;

// What follows `/ask` (or its older name `/brief`): `give`, `share [off|ask|team]`, or an optional `@name[:repo]`, an
// optional `--update` (or a leading `update`), and the question.
export function parseAsk(words: string[]): AskIntent {
  const [first, second] = words;
  if (first === "give") {
    return { kind: "give" };
  }
  if (first === "share") {
    return { kind: "share", mode: SHARING.find((mode) => mode === second) ?? null };
  }
  const rest = [...words];
  const target = first?.startsWith("@") && first.length > 1 ? (rest.shift() as string).slice(1) : null;
  const marked = rest.indexOf("--update");
  if (marked !== -1) {
    rest.splice(marked, 1);
  }
  const update = marked !== -1 || rest[0] === "update";
  if (rest[0] === "update") {
    rest.shift();
  }
  const focus = rest.join(" ").trim();
  return { kind: "ask", target, focus: focus === "" ? null : focus, update };
}
