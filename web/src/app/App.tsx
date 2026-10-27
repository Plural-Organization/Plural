import { useState } from "react";
import type { JoinLink } from "@plural/client";
import { JoinScreen } from "./JoinScreen";
import { Room } from "./Room";

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
          setNotice(null);
          setJoined({ link, name, key: Date.now() });
        }}
      />
    );
  }
  return (
    <Room
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
