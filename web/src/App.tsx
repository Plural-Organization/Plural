import { useEffect, useState } from "react";
import { parseLink, type JoinLink } from "@plural/client";
import { JoinScreen } from "./screens/JoinScreen";
import { RoomScreen } from "./screens/RoomScreen";
import { unlockAudio } from "./lib/alert";
import { useTeam } from "./hooks/useTeam";
import type { SessionCard, Team } from "./lib/team";

export interface Space {
  link: JoinLink;
  name: string;
  team: Team | null;
  // Who runs it, for the list of open spaces.
  owner: string | null;
}

// Like the terminal's spaces: every session opened here stays connected, so moving between them is
// instant; the oldest one in the background closes past this many.
const MAX_SPACES = 6;

export function App() {
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const team = useTeam();

  const open = (space: Space) => {
    unlockAudio();
    setNotice(null);
    setSpaces((current) => {
      if (current.some((item) => item.link.room === space.link.room)) {
        return current;
      }
      const next = [...current, space];
      const extra = next.length - MAX_SPACES;
      if (extra <= 0) {
        return next;
      }
      // The oldest ones in the background make way; the one in view and the new one stay.
      const drop = new Set(next.filter((item) => item.link.room !== active && item.link.room !== space.link.room).slice(0, extra).map((item) => item.link.room));
      return next.filter((item) => !drop.has(item.link.room));
    });
    setActive(space.link.room);
  };
  const join = (link: JoinLink, name: string) => open({ link, name, team: null, owner: null });
  // A teammate's session opens with the team's word for this person instead of an invite.
  const watch = (card: SessionCard, url: string) => {
    if (team.team !== null) {
      open({ link: parseLink(url), name: team.team.profile.member.name, team: team.team, owner: card.owner });
    }
  };
  // Called from a session's own callbacks too, so it reads the latest spaces through the updaters.
  const close = (room: string, reason: string | null) => {
    setSpaces((current) => {
      const rest = current.filter((item) => item.link.room !== room);
      setActive((shown) => (shown === room ? (rest.at(-1)?.link.room ?? null) : shown));
      return rest;
    });
    setNotice(reason);
  };

  // alt+← and alt+→ move between open spaces, as in the terminal.
  useEffect(() => {
    if (spaces.length < 2) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (!event.altKey || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) {
        return;
      }
      // In a text field alt+arrows move by word.
      if (event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable]") !== null) {
        return;
      }
      const index = spaces.findIndex((item) => item.link.room === active);
      const step = event.key === "ArrowLeft" ? -1 : 1;
      event.preventDefault();
      setActive(spaces[(index + step + spaces.length) % spaces.length]!.link.room);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [spaces, active]);

  if (spaces.length === 0 || active === null) {
    return <JoinScreen notice={notice} team={team} onJoin={join} onWatch={watch} />;
  }
  return (
    <>
      {spaces.map((space) => (
        <div key={space.link.room} style={{ display: space.link.room === active ? "contents" : "none" }}>
          <RoomScreen
            link={space.link}
            name={space.name}
            member={space.team}
            team={team}
            active={space.link.room === active}
            notice={space.link.room === active ? notice : null}
            spaces={spaces}
            onSwitch={setActive}
            onClose={(room) => close(room, null)}
            onWatch={watch}
            onLeave={(reason) => close(space.link.room, reason)}
          />
        </div>
      ))}
    </>
  );
}
