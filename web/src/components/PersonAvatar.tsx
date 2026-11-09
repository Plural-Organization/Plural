import { Avatar } from "@heroui/react";
import { useContext, type CSSProperties } from "react";
import { Moods, orbOf, seedHash, useLiveSlot } from "../lib/orbs";
import { PersonOrb } from "./PersonOrb";

// The still orb of colour behind everyone's avatar, the same one every time for the same person.
const ORBS: [string, string, string][] = [
  ["#b4e1ee", "#35b6e6", "#6c63f2"],
  ["#b6ecd0", "#3fcf8e", "#2f7fe0"],
  ["#d9c8f5", "#a56cf0", "#5b45e6"],
  ["#f7d9bd", "#f59a4a", "#e0503a"],
  ["#f6c9d6", "#ee6a9a", "#a13fd8"],
  ["#f3ecb4", "#e8c53a", "#39b57a"],
  ["#c5d4f7", "#5a86f0", "#30c4c0"],
  ["#f4c7bd", "#ea6a4f", "#d9367a"],
  ["#c9f0e6", "#34c7a8", "#8a5cf0"],
  ["#e6d3f2", "#c76ee0", "#ec6a7a"],
  ["#d6e9b8", "#8ccb45", "#2fa8c9"],
];

const PIXELS = { sm: 32, md: 40, lg: 48 } as const;
const ROUND = { "--avatar-radius": "9999px" } as CSSProperties;

export function orbFor(seed: string): CSSProperties {
  const hash = seedHash(seed);
  const [base, middle, core] = ORBS[hash % ORBS.length]!;
  return { background: `radial-gradient(circle at ${54 + (hash % 24)}% ${58 + (hash % 19)}%, ${core} 0, ${middle} 34%, transparent 68%), ${base}` };
}

// A person is an orb of their own. It holds still at rest, so a full room costs little,
// and comes alive while they type or just after they speak.
// `still` outside a room, where orbs would be spent on people not here; `minor` for the many in the feed.
export function PersonAvatar({ seed, size = "sm", still = false, minor = false }: { seed: string; size?: "sm" | "md" | "lg"; still?: boolean; minor?: boolean }) {
  const orb = still ? null : orbOf(seed);
  const mood = useContext(Moods).get(seed) ?? "idle";
  const [live, track] = useLiveSlot(orb !== null, minor);
  return (
    <Avatar ref={track} size={size} className="rounded-full" style={ROUND}>
      <Avatar.Fallback style={orbFor(seed)}>
        {live && orb !== null ? <PersonOrb orb={orb} state={mood === "speaking" ? "speaking" : "thinking"} paused={mood === "idle" || mood === "away"} size={PIXELS[size]} /> : ""}
      </Avatar.Fallback>
    </Avatar>
  );
}
