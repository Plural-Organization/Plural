import { useState } from "react";
import type { JoinLink } from "@plural/client";
import { JoinFlow } from "../components/JoinFlow";
import { LogoMark } from "../components/LogoMark";
import { PersonAvatar } from "../components/PersonAvatar";
import { RecentRooms } from "../components/RecentRooms";
import type { AccountState } from "../hooks/useAccount";
import type { TeamState } from "../hooks/useTeam";
import { forgetRoom, linkOf, savedRooms, type SavedRoom } from "../lib/saved";

interface JoinScreenProps {
  notice: string | null;
  team: TeamState;
  account: AccountState;
  onJoin: (link: JoinLink, name: string) => void;
  onTeamJoined: () => void;
  onCreateTeam: () => void;
}

// The page for someone with no room open and no team yet. Every action sits in the one centred
// column: people do not read the bottom of a page.
export function JoinScreen({ notice, team, account, onJoin, onTeamJoined, onCreateTeam }: JoinScreenProps) {
  const [rooms, setRooms] = useState<SavedRoom[]>(savedRooms);
  // In a step (signing in, setting up a room, joining) the headline and the recent rooms step aside.
  const [inStep, setInStep] = useState(false);
  const problem = notice ?? account.loginError;
  return (
    <div className="relative isolate flex min-h-full flex-col overflow-x-hidden">
      <div className="pixel-grid" aria-hidden="true" />
      {account.status === "in" && account.account !== null ? (
        <header className="flex h-14 flex-none items-center justify-end gap-2 px-[clamp(12px,2.2vw,32px)]">
          <PersonAvatar seed={account.account.email} size="sm" />
          <span className="max-w-[220px] truncate text-sm">{account.account.email}</span>
          <button type="button" className="pl-quiet-button text-sm" onClick={() => void account.signOut()}>
            Sign out
          </button>
        </header>
      ) : null}
      <main className="flex flex-[1_0_auto] flex-col px-4 py-12">
        <div className="m-auto flex w-full max-w-[560px] flex-col gap-[clamp(16px,1.6vw,22px)]">
          <div className="text-center">
            <LogoMark size={inStep ? 40 : 56} className="mx-auto text-foreground" />
            {inStep ? null : (
              <h1 className="pl-in mt-6 mb-0 font-display text-[2.6rem] font-medium leading-[1.05] tracking-[-0.022em] sm:text-5xl">
                Start a room,
                <br />
                <span className="tone-2">or join one.</span>
              </h1>
            )}
          </div>
          {problem ? (
            <p role="alert" className="m-0 rounded-2xl border border-white/40 px-4 py-3 text-sm">{problem}</p>
          ) : null}
          <div className={`pl-tray pl-in ${inStep ? "mx-auto w-full max-w-[440px]" : ""}`} style={{ animationDelay: inStep ? "0ms" : "70ms" }}>
            <div className={`pl-panel ${inStep ? "p-[clamp(16px,2vw,28px)]" : "p-[clamp(12px,1.3vw,18px)]"}`}>
              <JoinFlow team={team} account={account} onJoin={onJoin} onTeamJoined={onTeamJoined} onStep={setInStep} onCreateTeam={onCreateTeam} />
            </div>
          </div>
          {inStep ? null : (
            <RecentRooms
              rooms={rooms}
              onReopen={(room) => onJoin(linkOf(room), room.name)}
              onForget={() => {
                rooms.forEach((room) => forgetRoom(room.room));
                setRooms([]);
              }}
            />
          )}
          <p className="text-center text-sm text-muted">
            <a href="https://plrl.host" className="text-muted underline-offset-4 hover:text-foreground hover:underline">What is Plural?</a>
          </p>
        </div>
      </main>

    </div>
  );
}
