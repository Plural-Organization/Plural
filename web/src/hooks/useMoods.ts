import { useEffect, useMemo, useRef, useState } from "react";
import type { Feed, Projection } from "@plural/client";
import type { Mood } from "../lib/orbs";

const SPEAKING_MS = 4000;

// How each person's orb should look: away when they left, stirring while they type, lit for a moment after they speak.
// Keyed by participant id, as avatars in a room are.
export function useMoods(projection: Projection, feed: Feed): ReadonlyMap<string, Mood> {
  const [speaking, setSpeaking] = useState<ReadonlySet<string>>(new Set());
  const seen = useRef<string | null | undefined>(undefined);
  // One timer per person, restarted by each message they send.
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const last = feed.items.at(-1);
  const said = last !== undefined && (last.kind === "user" || last.kind === "chat") ? last : null;

  useEffect(() => {
    // The history that arrives on joining, or again on reconnecting, is not anyone speaking now.
    if (!projection.ready) {
      seen.current = undefined;
      return;
    }
    if (seen.current === undefined) {
      seen.current = said?.id ?? null;
      return;
    }
    if (said === null || said.id === seen.current) return;
    seen.current = said.id;
    const who = said.kind === "user" ? said.participantId : said.authorId;
    setSpeaking((current) => new Set(current).add(who));
    clearTimeout(timers.current.get(who));
    timers.current.set(
      who,
      setTimeout(() => {
        timers.current.delete(who);
        setSpeaking((current) => new Set([...current].filter((item) => item !== who)));
      }, SPEAKING_MS),
    );
  }, [said?.id, projection.ready]);

  const state = projection.state;
  const typingKey = [...projection.typing].join();
  return useMemo(() => {
    const moods = new Map<string, Mood>();
    for (const person of Object.values(state.participants)) {
      moods.set(person.id, !person.connected ? "away" : projection.typing.has(person.id) ? "thinking" : speaking.has(person.id) ? "speaking" : "idle");
    }
    return moods;
  }, [state.participants, typingKey, speaking]);
}
