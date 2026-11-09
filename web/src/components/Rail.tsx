import { Button, Chip, Description, Header, Label, ListBox, Separator, type Selection } from "@heroui/react";
import { Eye, Plus, UserPlus, Warning } from "@phosphor-icons/react";
import { useState } from "react";
import { reachable, teamJoinLink, type SessionCard } from "@plural/client";
import type { Space } from "../App";
import type { TeamState } from "../hooks/useTeam";
import { copyText } from "../lib/clipboard";
import { LogoMark } from "./LogoMark";
import { PersonAvatar } from "./PersonAvatar";

const STATUS = { running: "Working", waiting: "Waiting for its host", idle: "Idle" } as const;

interface RailProps {
  team: TeamState;
  spaces: Space[];
  active: string | null;
  onSwitch: (room: string) => void;
  onWatch: (card: SessionCard, url: string) => void;
  onAdd: () => void;
}

// The left column: the team's live sessions and the rooms joined by link. Picking one opens it on the right, and
// a room stays connected once opened, so moving back is instant.
export function Rail({ team, spaces, active, onSwitch, onWatch, onAdd }: RailProps) {
  const [note, setNote] = useState<string | null>(null);
  const profile = team.team?.profile ?? null;
  const open = new Set(spaces.map((space) => space.link.room));
  const teamRooms = new Set(team.sessions.map((card) => card.room));
  const byLink = spaces.filter((space) => !teamRooms.has(space.link.room));
  const selected = new Set(active === null ? [] : [active]);

  const pick = (keys: Selection) => {
    if (keys === "all") {
      return;
    }
    const room = String([...keys][0] ?? "");
    if (room === "" || room === active) {
      return;
    }
    if (open.has(room)) {
      onSwitch(room);
      return;
    }
    const card = team.sessions.find((item) => item.room === room);
    if (card === undefined) {
      return;
    }
    const url = reachable(card, window.location.protocol);
    if (url === null) {
      setNote(`${card.owner}'s session is reached only over plain ws://, which an https page cannot open.`);
      return;
    }
    setNote(null);
    onWatch(card, url);
  };

  const invite = () => {
    if (profile === null) {
      return;
    }
    team
      .invite()
      .then(({ code }) => copyText(teamJoinLink(profile, code, window.location)))
      .then((ok) => setNote(ok ? "Invite link copied. It is reusable and does not expire." : "Could not copy the invite link."))
      .catch((problem: unknown) => setNote(problem instanceof Error ? problem.message : String(problem)));
  };

  const leave = () => {
    if (profile !== null && window.confirm(`Leave ${profile.team_name}? You need a new invite to come back.`)) {
      void team.leave();
    }
  };

  return (
    <aside className="rail flex h-full min-h-0 flex-col border-r border-border bg-surface" aria-label="Sessions">
      <div className="flex h-14 flex-none items-center gap-2.5 px-4">
        <LogoMark size={26} className="text-foreground" />
        <span className="font-display text-lg font-semibold tracking-[-0.03em]">plural</span>
      </div>
      <Separator />
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {profile !== null ? (
          <section aria-label={profile.team_name}>
            <div className="flex items-center justify-between gap-2 px-2.5 pt-2 pb-1.5">
              <span className="truncate text-sm font-medium text-foreground">{profile.team_name}</span>
              <Chip size="sm" variant="soft"><Chip.Label>{team.sessions.length} live</Chip.Label></Chip>
            </div>
            {team.sessions.length === 0 ? (
              <p className="px-2.5 py-2 text-sm leading-relaxed text-muted">Nobody shares a session right now. Sessions show up here the moment someone starts one.</p>
            ) : (
              <ListBox aria-label={`${profile.team_name} sessions`} selectionMode="single" selectedKeys={selected} onSelectionChange={pick}>
                {team.sessions.map((card) => (
                  <ListBox.Item key={card.room} id={card.room} textValue={card.owner}>
                    <PersonAvatar seed={card.owner} />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <Label className="truncate">{card.owner}</Label>
                      <Description className="truncate">{card.title ?? `${card.repo}${card.branch ? ` on ${card.branch}` : ""}`}</Description>
                    </div>
                    <span className="flex flex-none items-center gap-2">
                      {(card.conflicts?.length ?? 0) > 0 ? <Warning size={14} weight="fill" className="text-warning" aria-label="Same files changed elsewhere" /> : null}
                      {card.viewers > 0 ? <span className="flex items-center gap-1 text-xs text-muted"><Eye size={13} />{card.viewers}</span> : null}
                      <i className="status-dot" data-status={card.status} title={STATUS[card.status] ?? STATUS.idle} />
                    </span>
                  </ListBox.Item>
                ))}
              </ListBox>
            )}
          </section>
        ) : null}

        {byLink.length > 0 ? (
          <ListBox aria-label="Rooms joined by link" selectionMode="single" selectedKeys={selected} onSelectionChange={pick} className={profile !== null ? "mt-3" : ""}>
            <ListBox.Section>
              <Header>Joined by link</Header>
              {byLink.map((space) => (
                <ListBox.Item key={space.link.room} id={space.link.room} textValue={space.owner ?? space.link.room}>
                  <PersonAvatar seed={space.link.room} />
                  <div className="flex min-w-0 flex-col">
                    <Label className="truncate">{space.owner ?? "Room"}</Label>
                    <Description className="truncate font-mono">{space.link.room}</Description>
                  </div>
                </ListBox.Item>
              ))}
            </ListBox.Section>
          </ListBox>
        ) : null}
      </div>

      {note !== null ? <p className="px-4 pb-2 text-[13px] leading-snug text-muted">{note}</p> : null}
      {team.error !== null ? <p className="px-4 pb-2 text-[13px] leading-snug text-warning">{team.error}</p> : null}
      <Separator />
      <div className="flex flex-none flex-col gap-2 p-3">
        <div className="flex gap-2">
          <Button variant="tertiary" size="sm" className="flex-1" onPress={onAdd}>
            <Plus size={15} />
            Join a room
          </Button>
          {profile?.member.role === "owner" ? (
            <Button variant="tertiary" size="sm" className="flex-1" onPress={invite}>
              <UserPlus size={15} />
              Invite
            </Button>
          ) : null}
        </div>
        {profile !== null ? (
          <div className="flex items-center gap-2.5 px-1 pt-1">
            <PersonAvatar seed={profile.member.name} />
            <span className="min-w-0 flex-1 truncate text-sm">{profile.member.name}</span>
            <button type="button" className="link-button" onClick={leave}>Leave team</button>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
