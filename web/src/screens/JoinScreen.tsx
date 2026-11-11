import { useState } from "react";
import type { JoinLink } from "@plural/client";
import { JoinFlow } from "../components/JoinFlow";
import { LogoMark } from "../components/LogoMark";
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
}

// The page for someone with no room open and no team yet.
export function JoinScreen({ notice, team, account, onJoin, onTeamJoined }: JoinScreenProps) {
  const [rooms, setRooms] = useState<SavedRoom[]>(savedRooms);
  // While someone sets up a room the big title steps aside, so the setup fits one screen.
  const [compact, setCompact] = useState(false);
  return (
    <main className="relative isolate flex min-h-full flex-col items-center justify-center overflow-hidden px-4 py-12">
      <div className="pixel-grid" aria-hidden="true" />
      <div className="w-full max-w-[28rem]">
        <div className="text-center">
          <LogoMark size={compact ? 40 : 56} className="mx-auto text-foreground" />
          {compact ? null : (
            <h1 className="mt-6 text-[2.6rem] font-medium leading-[1.05] tracking-[-0.022em] sm:text-5xl">
              Join a room,
              <br />
              <span className="tone-2">or start your own.</span>
            </h1>
          )}
        </div>
        {notice ?? account.loginError ? (
          <p className="mt-6 rounded-2xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">{notice ?? account.loginError}</p>
        ) : null}
        {/* Double bezel, as on the landing: a thin outer tray holding the form. */}
        <div className={`${compact ? "mt-5" : "mt-8"} rounded-[2rem] border border-white/[0.08] bg-white/[0.02] p-2`}>
          <div className="rounded-[calc(2rem-0.5rem)] bg-[#0b0b0d] p-5 shadow-[inset_0_1px_0_rgb(255_255_255/0.06)] sm:p-6">
            <JoinFlow team={team} account={account} onJoin={onJoin} onTeamJoined={onTeamJoined} onStarting={setCompact} />
          </div>
        </div>
        <RecentRooms
          rooms={rooms}
          onReopen={(room) => onJoin(linkOf(room), room.name)}
          onForget={() => {
            rooms.forEach((room) => forgetRoom(room.room));
            setRooms([]);
          }}
        />
        <p className="mt-8 text-center text-sm text-muted">
          <a href="https://plrl.host" className="text-muted underline-offset-4 hover:text-foreground hover:underline">What is Plural?</a>
        </p>
      </div>
    </main>
  );
}
