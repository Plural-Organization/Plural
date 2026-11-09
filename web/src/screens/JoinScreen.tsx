import { Description, Header, Label, ListBox, type Key } from "@heroui/react";
import { useState } from "react";
import type { JoinLink } from "@plural/client";
import { JoinFlow } from "../components/JoinFlow";
import { LogoMark } from "../components/LogoMark";
import { PersonAvatar } from "../components/PersonAvatar";
import type { TeamState } from "../hooks/useTeam";
import { hostOf } from "../lib/links";
import { forgetRoom, linkOf, savedRooms, type SavedRoom } from "../lib/saved";

interface JoinScreenProps {
  notice: string | null;
  team: TeamState;
  onJoin: (link: JoinLink, name: string) => void;
  onTeamJoined: () => void;
}

// The page for someone with no room open and no team yet.
export function JoinScreen({ notice, team, onJoin, onTeamJoined }: JoinScreenProps) {
  const [rooms, setRooms] = useState<SavedRoom[]>(savedRooms);
  const reopen = (key: Key) => {
    const room = rooms.find((item) => item.room === key);
    if (room !== undefined) {
      onJoin(linkOf(room), room.name);
    }
  };
  return (
    <main className="relative isolate flex min-h-full flex-col items-center justify-center overflow-hidden px-4 py-12">
      <div className="pixel-grid" aria-hidden="true" />
      <div className="w-full max-w-[28rem]">
        <div className="text-center">
          <LogoMark size={56} className="mx-auto text-foreground" />
          <h1 className="mt-6 text-[2.6rem] font-medium leading-[1.05] tracking-[-0.022em] sm:text-5xl">
            Join a room,
            <br />
            <span className="tone-2">or start your own.</span>
          </h1>
        </div>
        {notice ? <p className="mt-6 rounded-2xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">{notice}</p> : null}
        {/* Double bezel, as on the landing: a thin outer tray holding the form. */}
        <div className="mt-8 rounded-[2rem] border border-white/[0.08] bg-white/[0.02] p-2">
          <div className="rounded-[calc(2rem-0.5rem)] bg-[#0b0b0d] p-5 shadow-[inset_0_1px_0_rgb(255_255_255/0.06)] sm:p-6">
            <JoinFlow team={team} onJoin={onJoin} onTeamJoined={onTeamJoined} />
          </div>
        </div>
        {rooms.length > 0 ? (
          <div className="mt-6">
            <ListBox aria-label="Rooms you were in" selectionMode="none" onAction={reopen}>
              <ListBox.Section>
                <Header>Rooms you were in</Header>
                {rooms.map((room) => (
                  <ListBox.Item key={room.room} id={room.room} textValue={room.room}>
                    <PersonAvatar seed={room.room} />
                    <div className="flex min-w-0 flex-col">
                      <Label className="truncate font-mono text-[13px]">{room.room}</Label>
                      <Description className="truncate">as {room.name} on {hostOf(room.url)}</Description>
                    </div>
                  </ListBox.Item>
                ))}
              </ListBox.Section>
            </ListBox>
            <button
              type="button"
              className="link-button mt-1 ml-3"
              onClick={() => {
                rooms.forEach((room) => forgetRoom(room.room));
                setRooms([]);
              }}
            >
              Forget these rooms
            </button>
          </div>
        ) : null}
        <p className="mt-8 text-center text-sm text-muted">
          <a href="https://plrl.host" className="text-muted underline-offset-4 hover:text-foreground hover:underline">What is Plural?</a>
        </p>
      </div>
    </main>
  );
}
