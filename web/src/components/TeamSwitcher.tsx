import { Chip, Description, Dropdown, Header, Label, type Key } from "@heroui/react";
import { CaretUpDown, Check, Plus, SignIn } from "@phosphor-icons/react";
import type { TeamState } from "../hooks/useTeam";
import { PersonAvatar } from "./PersonAvatar";

const LINKS = "__links";
const CREATE = "__create";
const JOIN = "__join";

interface TeamSwitcherProps {
  team: TeamState;
  onCreate: () => void;
  onJoin: () => void;
}

// Which space the rail shows: one of the teams, or the rooms joined by link. Creating or joining a team
// starts here too.
export function TeamSwitcher({ team, onCreate, onJoin }: TeamSwitcherProps) {
  const current = team.team?.profile ?? null;
  const act = (key: Key) => {
    const id = String(key);
    if (id === CREATE) onCreate();
    else if (id === JOIN) onJoin();
    else team.select(id === LINKS ? null : id);
  };
  return (
    <Dropdown>
      <Dropdown.Trigger aria-label="Switch team" className="flex w-full min-w-0 items-center gap-2.5 rounded-xl px-2.5 py-2 text-left outline-none transition-colors hover:bg-surface-secondary data-[focus-visible=true]:ring-2 data-[focus-visible=true]:ring-focus">
        <PersonAvatar seed={current?.team_name ?? "rooms"} />
        <span className="flex min-w-0 flex-1 flex-col leading-tight">
          <span className="truncate text-sm font-medium text-foreground">{current?.team_name ?? "Rooms you joined"}</span>
          <span className="truncate text-xs text-muted">{current === null ? (team.teams.length === 0 ? "No team yet" : `${team.teams.length} team${team.teams.length === 1 ? "" : "s"}`) : `as ${current.member.name}`}</span>
        </span>
        {current === null ? null : (
          <Chip size="sm" variant="soft" className="flex-none">
            <Chip.Label>{team.sessions.length} live</Chip.Label>
          </Chip>
        )}
        <CaretUpDown size={14} className="flex-none text-muted" />
      </Dropdown.Trigger>
      <Dropdown.Popover className="min-w-[17rem]">
        <Dropdown.Menu aria-label="Teams" onAction={act}>
          {team.teams.length === 0 ? null : (
            <Dropdown.Section>
              <Header>Teams</Header>
              {team.teams.map(({ profile }) => (
                <Dropdown.Item key={profile.team_id} id={profile.team_id} textValue={profile.team_name}>
                  <PersonAvatar seed={profile.team_name} />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <Label className="truncate">{profile.team_name}</Label>
                    <Description className="truncate">{profile.member.role === "owner" ? "Owner" : "Member"} · {new URL(profile.relay).host}</Description>
                  </div>
                  {profile.team_id === current?.team_id ? <Check size={14} weight="bold" className="flex-none" /> : null}
                </Dropdown.Item>
              ))}
            </Dropdown.Section>
          )}
          <Dropdown.Section>
            <Dropdown.Item id={LINKS} textValue="Rooms you joined by link">
              <Label>Rooms you joined by link</Label>
              {current === null ? <Check size={14} weight="bold" className="ml-auto flex-none" /> : null}
            </Dropdown.Item>
            <Dropdown.Item id={CREATE} textValue="Create a team">
              <Plus size={15} className="flex-none" />
              <Label>Create a team</Label>
            </Dropdown.Item>
            <Dropdown.Item id={JOIN} textValue="Join with an invite">
              <SignIn size={15} className="flex-none" />
              <Label>Join with an invite</Label>
            </Dropdown.Item>
          </Dropdown.Section>
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  );
}
