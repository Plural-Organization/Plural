import { createContext, useEffect, useState } from "react";

// Orbkit's own orbs (MIT, see src/vendor/orbkit/LICENSE), handed out to people one each.
export const ORB_NAMES = ["shdr-11", "shdr-12", "shdr-13", "shdr-14", "shdr-16", "shdr-17", "shdr-21", "shdr-23", "shdr-24", "shdr-27", "shdr-29", "shdr-30", "shdr-32", "shdr-33"] as const;
export type OrbName = (typeof ORB_NAMES)[number];

// What a person is doing, as their orb shows it.
export type Mood = "idle" | "thinking" | "speaking" | "away";
export const Moods = createContext<ReadonlyMap<string, Mood>>(new Map());

export function seedHash(seed: string): number {
  let hash = 0;
  for (const char of seed) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return hash;
}

const given = new Map<string, OrbName | null>();
const taken = new Set<OrbName>();

// The orb a person keeps for the whole visit: the one their seed points at, or the next free one.
// Once all of them are taken, people who come later get the plain gradient.
export function orbOf(seed: string): OrbName | null {
  const known = given.get(seed);
  if (known !== undefined) return known;
  const start = seedHash(seed) % ORB_NAMES.length;
  let orb: OrbName | null = null;
  for (let step = 0; step < ORB_NAMES.length; step++) {
    const candidate = ORB_NAMES[(start + step) % ORB_NAMES.length]!;
    if (!taken.has(candidate)) {
      orb = candidate;
      taken.add(candidate);
      break;
    }
  }
  given.set(seed, orb);
  return orb;
}

// A browser keeps about sixteen WebGL contexts per page and silently drops the oldest past that, so only
// this many orbs run at once; the rest, and any scrolled out of view, show the gradient until one frees up.
// The feed's many avatars draw from a pool of their own, so they never crowd out the list of who is here.
class Pool {
  live = 0;
  readonly waiting = new Set<() => void>();
  constructor(readonly size: number) {}
}
const MAIN = new Pool(9);
const MINOR = new Pool(5);

export function useLiveSlot(enabled: boolean, minor = false): [boolean, (element: HTMLElement | null) => void] {
  const pool = minor ? MINOR : MAIN;
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [held, setHeld] = useState(false);

  useEffect(() => {
    if (element === null || !enabled) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry?.isIntersecting ?? false));
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, enabled]);

  useEffect(() => {
    if (!enabled || !visible) return;
    let mine = false;
    const attempt = () => {
      if (!mine && pool.live < pool.size) {
        pool.live += 1;
        mine = true;
        pool.waiting.delete(attempt);
        setHeld(true);
      }
    };
    attempt();
    if (!mine) pool.waiting.add(attempt);
    return () => {
      pool.waiting.delete(attempt);
      if (!mine) return;
      pool.live -= 1;
      setHeld(false);
      for (const next of [...pool.waiting]) {
        if (pool.live >= pool.size) break;
        next();
      }
    };
  }, [enabled, visible, pool]);

  return [held, setElement];
}
