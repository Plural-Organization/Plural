import { Button, Description, Header, Label, ListBox, Separator, type Selection } from "@heroui/react";
import { Eye, GearSix, Plus, Warning, SidebarSimple } from "@phosphor-icons/react";
import { useState } from "react";
import { reachable, type SessionCard } from "@plural/client";
import type { Space } from "../App";
import type { AccountState } from "../hooks/useAccount";
import type { TeamState } from "../hooks/useTeam";
import { AccountModal } from "./AccountModal";
import { CreateTeam } from "./CreateTeam";
import { TeamSwitcher } from "./TeamSwitcher";
import { TeamWindow } from "./TeamWindow";
import { LogoMark } from "./LogoMark";
import { PersonAvatar } from "./PersonAvatar";
import { AgentLogo } from "./AgentLogo";
import { agentMark } from "../lib/agents";

const STATUS = { running: "Working", waiting: "Waiting for its host", idle: "Idle" } as const;

interface RailProps {
  team: TeamState;
  account: AccountState;
  spaces: Space[];
  active: string | null;
  onSwitch: (room: string) => void;
  onWatch: (card: SessionCard, url: string) => void;
  onAdd: () => void;
  onStart: () => void;
  onHide: () => void;
}

// The left column: the team's live sessions and the rooms joined by link. Picking one opens it on the right, and
// a room stays connected once opened, so moving back is instant.
export function Rail({ team, account, spaces, active, onSwitch, onWatch, onAdd, onStart, onHide }: RailProps) {
  const [note, setNote] = useState<string | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [managing, setManaging] = useState(false);
  const profile = team.team?.profile ?? null;
  const email = account.status === "in" ? (account.account?.email ?? null) : null;
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

  return (
    <aside className="rail frame flex h-full min-h-0 flex-col" aria-label="Sessions">
      <div className="flex h-14 flex-none items-center gap-2.5 px-4">
        <LogoMark size={26} className="text-foreground" />
        <span className="font-display text-lg font-semibold tracking-[-0.03em]">plural</span>
        <Button isIconOnly variant="ghost" size="sm" className="ml-auto" aria-label="Hide the sessions" onPress={onHide}>
          <SidebarSimple size={18} />
        </Button>
      </div>
      <div className="flex flex-none items-center gap-1 px-2 pb-2">
        <div className="min-w-0 flex-1">
          <TeamSwitcher team={team} onCreate={() => setCreating(true)} onJoin={onAdd} />
        </div>
        {profile !== null ? (
          <Button isIconOnly variant="ghost" size="sm" aria-label={`Manage ${profile.team_name}`} onPress={() => setManaging(true)}>
            <GearSix size={17} />
          </Button>
        ) : null}
      </div>
      <Separator />
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {profile !== null ? (
          <section aria-label={profile.team_name}>
            {team.sessions.length === 0 ? (
              <div className="flex flex-col items-start gap-3 px-2.5 py-2">
                <p className="text-sm leading-relaxed text-muted">Nobody shares a session in {profile.team_name} right now. Start one, or wait: sessions show up here the moment someone does.</p>
                {account.status === "in" && account.account !== null ? (
                  <Button size="sm" onPress={onStart}>
                    <Plus size={15} />
                    Start a room in {profile.team_name}
                  </Button>
                ) : (
                  <p className="text-sm leading-relaxed text-muted">Sign in to start a room from here.</p>
                )}
              </div>
            ) : (
              <ListBox aria-label={`${profile.team_name} sessions`} selectionMode="single" selectedKeys={selected} onSelectionChange={pick}>
                {team.sessions.map((card) => (
                  <ListBox.Item key={card.room} id={card.room} textValue={card.owner}>
                    <span className="relative flex-none">
                      <PersonAvatar seed={card.owner} />
                      {agentMark(card.agent) ? (
                        <span className="absolute -right-1 -bottom-1 grid size-[18px] place-items-center rounded-full border-2 border-surface bg-surface-secondary">
                          <AgentLogo label={card.agent} size={10} />
                        </span>
                      ) : null}
                    </span>
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
        {account.status === "in" && account.account !== null ? (
          <Button size="sm" fullWidth onPress={onStart}>
            <Plus size={15} />
            {profile === null ? "Start a room" : `Start a room in ${profile.team_name}`}
          </Button>
        ) : null}
        <Button variant="tertiary" size="sm" fullWidth onPress={onAdd}>
          <Plus size={15} />
          Join a room
        </Button>
        {account.status === "in" && account.account !== null ? (
          <Button variant="ghost" size="sm" fullWidth className="justify-start gap-2.5" onPress={() => setAccountOpen(true)}>
            <PersonAvatar seed={account.account.email} />
            <span className="min-w-0 flex-1 truncate text-left text-sm">{account.account.email}</span>
          </Button>
        ) : null}
      </div>
      {accountOpen ? <AccountModal state={account} onClose={() => setAccountOpen(false)} /> : null}
      {creating ? <CreateTeam team={team} email={email} onClose={() => setCreating(false)} /> : null}
      {managing && profile !== null ? <TeamWindow team={team} onClose={() => setManaging(false)} /> : null}
    </aside>
  );
}
