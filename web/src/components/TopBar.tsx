import { Avatar, AvatarGroup, Button, Chip, Kbd, ProgressBar, Spinner, Tooltip } from "@heroui/react";
import { Graph, SidebarSimple, SignOut } from "@phosphor-icons/react";
import { contextMeter, type ConnectionStatus, type Projection } from "@plural/client";
import { orbFor, PersonAvatar } from "./PersonAvatar";
import { AgentLogo } from "./AgentLogo";

interface TopBarProps {
  room: string;
  projection: Projection;
  connection: ConnectionStatus;
  panelOpen: boolean;
  // Whether the room panel is slid over the room on a narrow screen.
  panelShown?: boolean;
  // Whether the list of sessions shows beside the room on a wide screen.
  railOpen: boolean;
  onCopyRoom: () => void;
  onTogglePanel: () => void;
  onLeave: () => void;
  // Shows or hides the list of sessions; a narrow screen slides it over the room.
  onToggleRail: () => void;
  // Opens or closes what the agent's runs did, step by step.
  traceOpen?: boolean;
  onToggleTrace?: () => void;
}

const METER_COLOR = { ok: "accent", warn: "warning", danger: "danger" } as const;

export function TopBar({ room, projection, connection, panelOpen, panelShown = false, railOpen, onCopyRoom, onTogglePanel, onLeave, onToggleRail, traceOpen = false, onToggleTrace }: TopBarProps) {
  const state = projection.state;
  const meter = contextMeter(state);
  const people = Object.values(state.participants);
  const here = people.filter((person) => person.connected);
  const host = people.find((person) => person.role === "host");
  const review = state.prompt_mode === "review";
  return (
    <header className="col-span-full flex h-14 min-w-0 flex-none items-center gap-3 px-2 sm:px-3">
      <Tooltip delay={300}>
        <Button isIconOnly variant="ghost" size="sm" className={railOpen ? "min-[981px]:hidden" : ""} aria-label="Show the sessions" onPress={onToggleRail}>
          <SidebarSimple size={18} />
        </Button>
        <Tooltip.Content>Show the sessions</Tooltip.Content>
      </Tooltip>
      {host ? <PersonAvatar seed={host.name} /> : null}
      <div className="flex min-w-0 flex-col leading-tight">
        <span className="truncate font-display text-base font-semibold tracking-[-0.01em]">{host ? `${host.name}'s session` : "Room"}</span>
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
        <Chip size="sm" variant="secondary" className="hidden max-w-[16rem] lg:inline-flex">
          <i className="status-dot" data-status={state.run ? "running" : "idle"} />
          <AgentLogo label={projection.agentLabel} size={14} decorative />
          <Chip.Label className="truncate">{projection.agentLabel}</Chip.Label>
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
      {onToggleTrace ? (
        <Tooltip delay={300}>
          <Button isIconOnly variant={traceOpen ? "secondary" : "ghost"} size="sm" aria-label="Trace" aria-pressed={traceOpen} onPress={onToggleTrace}>
            <Graph size={18} />
          </Button>
          <Tooltip.Content>
            Trace: what each run did and spent <Kbd className="ml-1 h-5 px-1 text-[11px]"><Kbd.Content>t</Kbd.Content></Kbd>
          </Tooltip.Content>
        </Tooltip>
      ) : null}
      <Tooltip delay={300}>
        <Button isIconOnly variant="ghost" size="sm" className={panelOpen ? "min-[981px]:hidden" : ""} aria-label="The room panel" aria-expanded={panelShown} onPress={onTogglePanel}>
          <SidebarSimple size={18} className="-scale-x-100" />
        </Button>
        <Tooltip.Content>Show the room panel</Tooltip.Content>
      </Tooltip>
      <Button variant="ghost" size="sm" onPress={onLeave}>
        <SignOut size={16} />
        <span className="hidden sm:inline">Leave</span>
      </Button>
    </header>
  );
}
