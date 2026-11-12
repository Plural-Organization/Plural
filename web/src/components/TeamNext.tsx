import { Button, Card, Spinner } from "@heroui/react";
import { teamJoinLink } from "@plural/client";
import { Check, Copy, Play, UserPlus } from "@phosphor-icons/react";
import { useState } from "react";
import type { TeamState } from "../hooks/useTeam";
import { copyText } from "../lib/clipboard";

function Step({ n, title, body, children }: { n: number; title: string; body: string; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-3">
      <span className="mt-0.5 grid size-6 flex-none place-items-center rounded-full bg-surface-secondary text-xs font-medium text-muted">{n}</span>
      <div className="flex min-w-0 flex-1 flex-col items-start gap-2">
        <div>
          <p className="text-[15px] font-medium">{title}</p>
          <p className="text-sm leading-relaxed text-muted">{body}</p>
        </div>
        {children}
      </div>
    </li>
  );
}

// What to do in a team nobody shares a session in yet: bring people in, then start the first room.
export function TeamNext({ team, onStart, canStart }: { team: TeamState; onStart: () => void; canStart: boolean }) {
  const profile = team.team?.profile ?? null;
  const [state, setState] = useState<"idle" | "busy" | "copied" | "failed">("idle");
  if (profile === null) return null;
  const owner = profile.member.role === "owner";

  const invite = () => {
    setState("busy");
    team
      .invite()
      .then(({ code }) => copyText(teamJoinLink(profile, code, window.location)))
      .then((ok) => {
        setState(ok ? "copied" : "failed");
        setTimeout(() => setState("idle"), 2400);
      })
      .catch(() => setState("failed"));
  };

  return (
    <Card variant="secondary" className="w-full max-w-[28rem] text-left">
      <Card.Header>
        <Card.Title className="font-display text-xl tracking-[-0.02em]">{profile.team_name} is ready</Card.Title>
        <Card.Description>Two things and your team is working together.</Card.Description>
      </Card.Header>
      <Card.Content>
        <ol className="flex flex-col gap-5">
          {owner ? (
            <Step n={1} title="Invite your team" body="Send the link to the people who should see your rooms. They join from their browser or terminal.">
              <Button size="sm" variant="secondary" onPress={invite} isDisabled={state === "busy"}>
                {state === "busy" ? <Spinner size="sm" color="current" /> : state === "copied" ? <Check size={15} /> : state === "failed" ? <UserPlus size={15} /> : <Copy size={15} />}
                {state === "copied" ? "Link copied" : state === "failed" ? "Could not copy, try again" : "Copy the invite link"}
              </Button>
            </Step>
          ) : null}
          <Step n={owner ? 2 : 1} title="Start the first room" body={canStart ? "Pick a folder and an agent on your computer. The team sees the room the moment it starts." : "Sign in to start a room from your computer, or wait for a teammate to share one."}>
            {canStart ? (
              <Button size="sm" onPress={onStart}>
                <Play size={15} weight="fill" />
                Start a room in {profile.team_name}
              </Button>
            ) : null}
          </Step>
        </ol>
      </Card.Content>
    </Card>
  );
}
