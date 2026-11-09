import { Avatar, AvatarGroup, Button, Chip, ProgressBar, Spinner, Tooltip } from "@heroui/react";
import { List, SidebarSimple, SignOut } from "@phosphor-icons/react";
import { contextMeter, type ConnectionStatus, type Projection } from "@plural/client";
import { orbFor, PersonAvatar } from "./PersonAvatar";

interface TopBarProps {
  room: string;
  projection: Projection;
  connection: ConnectionStatus;
  panelOpen: boolean;
  onCopyRoom: () => void;
  onTogglePanel: () => void;
  onLeave: () => void;
  // Opens the list of sessions, which a narrow screen keeps out of the way.
  onOpenRail?: () => void;
}

const METER_COLOR = { ok: "accent", warn: "warning", danger: "danger" } as const;

export function TopBar({ room, projection, connection, panelOpen, onCopyRoom, onTogglePanel, onLeave, onOpenRail }: TopBarProps) {
  const state = projection.state;
  const meter = contextMeter(state);
  const people = Object.values(state.participants);
  const here = people.filter((person) => person.connected);
  const host = people.find((person) => person.role === "host");
  const review = state.prompt_mode === "review";
  return (
    <header className="col-span-full flex h-14 min-w-0 flex-none items-center gap-3 border-b border-border px-3 sm:px-4">
      <Button isIconOnly variant="ghost" size="sm" className="min-[981px]:hidden" aria-label="sessions" onPress={onOpenRail}>
        <List size={18} />
      </Button>
      {host ? <PersonAvatar seed={host.name} /> : null}
      <div className="flex min-w-0 flex-col leading-tight">
        <span className="truncate text-[15px] font-medium">{host ? `${host.name}'s session` : "Room"}</span>
        <Tooltip delay={300}>
          <button type="button" className="max-w-[16ch] cursor-pointer truncate text-left font-mono text-xs text-muted hover:text-foreground" onClick={onCopyRoom}>
            {room}
          </button>
          <Tooltip.Content>Copy the room id</Tooltip.Content>
        </Tooltip>
      </div>
      <Chip size="sm" variant="soft" color={review ? "warning" : "default"} className="hidden sm:inline-flex">
        <Chip.Label><span className="cap">{state.prompt_mode} mode</span></Chip.Label>
      </Chip>
      <span className="grow" />
      {meter ? (
        <Tooltip delay={300}>
          <div className="hidden items-center gap-2.5 md:flex">
            <ProgressBar aria-label="Context used" value={meter.percent} size="sm" color={METER_COLOR[meter.level as keyof typeof METER_COLOR] ?? "accent"} className="w-16">
              <ProgressBar.Track><ProgressBar.Fill /></ProgressBar.Track>
            </ProgressBar>
            <span className="text-xs text-muted whitespace-nowrap"><span className="cap">context {meter.percent}%</span></span>
          </div>
          <Tooltip.Content>{meter.tokens} of {meter.window} tokens in the context</Tooltip.Content>
        </Tooltip>
      ) : null}
      {projection.agentLabel ? (
        <Chip size="sm" variant="secondary" className="hidden max-w-[14rem] lg:inline-flex">
          <Chip.Label className="truncate font-mono">{projection.agentLabel}</Chip.Label>
        </Chip>
      ) : null}
      {connection === "online" ? (
        <Tooltip delay={300}>
          <AvatarGroup className="hidden sm:flex" max={4}>
            {here.map((person) => (
              <Avatar key={person.id} size="sm">
                <Avatar.Fallback style={orbFor(person.name)}>{""}</Avatar.Fallback>
              </Avatar>
            ))}
          </AvatarGroup>
          <Tooltip.Content>{here.length} in the room</Tooltip.Content>
        </Tooltip>
      ) : (
        <Chip size="sm" variant="soft" color="warning">
          <Spinner size="sm" color="current" />
          <Chip.Label>{connection === "connecting" ? "Connecting" : "Reconnecting"}</Chip.Label>
        </Chip>
      )}
      <Button isIconOnly variant="ghost" size="sm" className="min-[981px]:hidden" aria-label="room" aria-expanded={panelOpen} onPress={onTogglePanel}>
        <SidebarSimple size={18} />
      </Button>
      <Button variant="ghost" size="sm" onPress={onLeave}>
        <SignOut size={16} />
        <span className="hidden sm:inline">Leave</span>
      </Button>
    </header>
  );
}
