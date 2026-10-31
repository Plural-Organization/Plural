import { useState } from "react";
import { parseLink, type JoinLink } from "@plural/client";
import { JoinScreen } from "./screens/JoinScreen";
import { RoomScreen } from "./screens/RoomScreen";
import { unlockAudio } from "./lib/alert";
import { useTeam } from "./hooks/useTeam";
import type { SessionCard, Team } from "./lib/team";

interface Joined {
  link: JoinLink;
  name: string;
  key: number;
  team: Team | null;
}

export function App() {
  const [joined, setJoined] = useState<Joined | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const team = useTeam();

  const join = (link: JoinLink, name: string, member: Team | null = null) => {
    unlockAudio();
    setNotice(null);
    setJoined({ link, name, key: Date.now(), team: member });
  };
  // A teammate's session opens with the team's word for this person instead of an invite.
  const watch = (_card: SessionCard, url: string) => {
    if (team.team !== null) {
      join(parseLink(url), team.team.profile.member.name, team.team);
    }
  };

  if (joined === null) {
    return <JoinScreen notice={notice} team={team} onJoin={(link, name) => join(link, name)} onWatch={watch} />;
  }
  return (
    <RoomScreen
      key={joined.key}
      link={joined.link}
      name={joined.name}
      member={joined.team}
      team={team}
      onWatch={watch}
      onLeave={(reason) => {
        setNotice(reason);
        setJoined(null);
      }}
    />
  );
}
