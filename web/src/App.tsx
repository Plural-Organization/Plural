import { useState } from "react";
import type { JoinLink } from "@plural/client";
import { JoinScreen } from "./screens/JoinScreen";
import { RoomScreen } from "./screens/RoomScreen";
import { unlockAudio } from "./lib/alert";

interface Joined {
  link: JoinLink;
  name: string;
  key: number;
}

export function App() {
  const [joined, setJoined] = useState<Joined | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (joined === null) {
    return (
      <JoinScreen
        notice={notice}
        onJoin={(link, name) => {
          unlockAudio();
          setNotice(null);
          setJoined({ link, name, key: Date.now() });
        }}
      />
    );
  }
  return (
    <RoomScreen
      key={joined.key}
      link={joined.link}
      name={joined.name}
      onLeave={(reason) => {
        setNotice(reason);
        setJoined(null);
      }}
    />
  );
}
