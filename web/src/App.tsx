import { useEffect, useState, type CSSProperties } from "react";
import { Alert } from "@heroui/react";
import { firstSession, parseLink, type JoinLink, type SessionCard } from "@plural/client";
import { JoinFlow } from "./components/JoinFlow";
import { Rail } from "./components/Rail";
import { JoinScreen } from "./screens/JoinScreen";
import { RoomScreen } from "./screens/RoomScreen";
import { unlockAudio } from "./lib/alert";
import { useAccount } from "./hooks/useAccount";
import { useTeam } from "./hooks/useTeam";
import type { Team } from "./lib/team";
import { isNarrow, RAIL_WIDTH, SIDE_WIDTH, useTucked, useWidth } from "./lib/panels";
import { ResizeHandle } from "./components/ResizeHandle";

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
  const account = useAccount();
  // Whether the right side shows the form for joining another room.
  const [adding, setAdding] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [railTucked, setRailTucked] = useTucked("plural.rail.tucked");
  const [railWidth, setRailWidth] = useWidth("plural.rail.width", 288, RAIL_WIDTH);
  const [sideTucked, setSideTucked] = useTucked("plural.side.tucked");
  const [sideWidth, setSideWidth] = useWidth("plural.side.width", 290, SIDE_WIDTH);
  // Right after joining a team, the first session someone shares opens on its own, as in the terminal.
  const [entering, setEntering] = useState(false);

  const open = (space: Space) => {
    unlockAudio();
    setNotice(null);
    setAdding(false);
    setRailOpen(false);
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

  useEffect(() => {
    if (!entering) {
      return;
    }
    // Nobody shares anything yet: after a minute the choice is left to this person.
    const giveUp = setTimeout(() => setEntering(false), 60_000);
    return () => clearTimeout(giveUp);
  }, [entering]);
  useEffect(() => {
    if (!entering || team.team === null) {
      return;
    }
    const first = firstSession(team.sessions, team.team.profile.member.id, window.location.protocol);
    if (first !== null) {
      setEntering(false);
      watch(first.card, first.url);
    }
  }, [entering, team.team, team.sessions]);

  if (team.loading) {
    return null;
  }
  if (team.team === null && spaces.length === 0) {
    return <JoinScreen notice={notice} team={team} account={account} onJoin={join} onTeamJoined={() => setEntering(true)} />;
  }
  const showForm = adding || (active === null && team.team === null);
  return (
    <div className="workspace" data-rail={railOpen ? "open" : "closed"} data-rail-tucked={railTucked} style={{ "--rail-w": `${railWidth}px` } as CSSProperties} data-room={active === null ? "none" : "open"}>
      <Rail
        team={team}
        account={account}
        spaces={spaces}
        active={active}
        onSwitch={(room) => {
          setAdding(false);
          setRailOpen(false);
          setActive(room);
        }}
        onWatch={watch}
        onAdd={() => {
          setAdding(true);
          setRailOpen(false);
        }}
        onHide={() => (isNarrow() ? setRailOpen(false) : setRailTucked(true))}
      />
      {railTucked ? null : <ResizeHandle label="Width of the sessions" width={railWidth} bounds={RAIL_WIDTH} direction={1} onResize={setRailWidth} style={{ left: 8 + railWidth }} />}
      <button type="button" className="rail-scrim" aria-label="Close the list of sessions" onClick={() => setRailOpen(false)} />
      <div className="workspace-main" data-adding={showForm}>
        {spaces.map((space) => (
          <div key={space.link.room} style={{ display: space.link.room === active && !showForm ? "contents" : "none" }}>
            <RoomScreen
              link={space.link}
              name={space.name}
              member={space.team}
              active={space.link.room === active && !showForm}
              notice={space.link.room === active ? notice : null}
              railTucked={railTucked}
              side={{ tucked: sideTucked, width: sideWidth, setTucked: setSideTucked, setWidth: setSideWidth }}
              onToggleRail={() => (isNarrow() ? setRailOpen(true) : setRailTucked(!railTucked))}
              onHost={(owner) => setSpaces((current) => current.map((item) => (item.link.room === space.link.room && item.owner !== owner ? { ...item, owner } : item)))}
              onLeave={(reason) => close(space.link.room, reason)}
            />
          </div>
        ))}
        {showForm ? (
          <div className="flex h-full items-center justify-center overflow-y-auto p-6">
            <div className="w-full max-w-[26rem]">
              <h2 className="mb-5 text-3xl font-medium tracking-[-0.022em]">Join another room</h2>
              <JoinFlow team={team} account={account} onJoin={join} onTeamJoined={() => setEntering(true)} />
              {spaces.length > 0 ? <button type="button" className="link-button mt-4" onClick={() => setAdding(false)}>Back to the room</button> : null}
            </div>
          </div>
        ) : active === null ? (
          <div className="relative isolate flex h-full flex-col items-center justify-center overflow-hidden p-6 text-center">
            <div className="pixel-grid" aria-hidden="true" />
            <h2 className="text-4xl font-medium leading-[1.05] tracking-[-0.022em]">
              Pick a session
              <br />
              <span className="tone-2">on the left.</span>
            </h2>
            {notice ? (
              <Alert status="warning" className="mt-5 max-w-md text-left">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Description>{notice}</Alert.Description>
                </Alert.Content>
              </Alert>
            ) : null}
            <p className="mt-4 max-w-[42ch] text-[15px] leading-relaxed text-muted text-pretty">
              {(entering ? "You are in. The first session someone shares opens here on its own." : "Open anyone's session to read it from the start. Ask the host when you want to write.")}
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
