import { Alert, Button, Chip, Label, Modal, Radio, RadioGroup, Spinner } from "@heroui/react";
import { ArrowsClockwise, At, ChatsCircle, ChatsTeardrop, Desktop, DoorOpen, EyeSlash, GearSix, HandPalm, Lightning, ListChecks, MapTrifold, PencilSimpleLine, Question, Robot, ShieldCheck, UserCheck, UsersThree, Warning, type Icon } from "@phosphor-icons/react";
import type { ChatMode, Command, PermissionMode, Projection, PromptMode } from "@plural/client";
import { useEffect, useState, type ReactNode } from "react";
import { useAgentSetup } from "../hooks/useAgentSetup";
import { useDaemon } from "../hooks/useDaemon";
import { runningRooms, setRoomAgent } from "../lib/agent";
import { DaemonError, daemonMessage } from "../lib/daemon";
import { type AdmissionMode, type BriefingSharing, type Option, ADMISSION, BRIEFINGS, DANGER_TITLE, DANGER_WARNING, PERMISSIONS, PROMPTS, REPLIES } from "../lib/roomSettings";
import { Confirm } from "./Confirm";
import { AgentSetup } from "./AgentSetup";
import { AgentLogo } from "./AgentLogo";
import { agentMark } from "../lib/agents";

// Each option's picture, so a choice reads at a glance before its words do.
const PROMPT_ICONS: Record<PromptMode, Icon> = { open: ChatsCircle, review: ListChecks };
const REPLY_ICONS: Record<ChatMode, Icon> = { mention: At, all: ChatsTeardrop };
const PERMISSION_ICONS: Record<PermissionMode, Icon> = { plan: MapTrifold, default: HandPalm, accept_edits: PencilSimpleLine, auto: Lightning, danger: Warning };
const ADMISSION_ICONS: Record<AdmissionMode, Icon> = { approve: UserCheck, open: DoorOpen };
const BRIEFING_ICONS: Record<BriefingSharing, Icon> = { off: EyeSlash, ask: Question, team: UsersThree };

// How much each permission mode lets run without the host: the ladder is drawn in this order, safest first.
const RISK: Record<PermissionMode, number> = { plan: 1, default: 2, accept_edits: 3, auto: 4, danger: 5 };
const LADDER = [...PERMISSIONS].sort((a, b) => RISK[a.id] - RISK[b.id]);

interface ChoiceProps<T extends string> {
  title: string;
  hint?: string;
  options: Option<T>[];
  icons: Record<T, Icon>;
  value: T;
  onChange: (next: T) => void;
  // Tiles side by side (a short choice) or one under another (a ladder).
  layout?: "grid" | "ladder";
}

// One setting as a set of tiles: a picture, the name and what it does, and a check on the one in force.
// A change reaches the room at once.
function Choice<T extends string>({ title, hint, options, icons, value, onChange, layout = "grid" }: ChoiceProps<T>) {
  return (
    <RadioGroup aria-label={title} value={value} onChange={(next) => onChange(next as T)} className="setting">
      <div className="setting__head">
        <Label className="setting__title">{title}</Label>
        {hint ? <span className="setting__hint">{hint}</span> : null}
      </div>
      <div className={layout === "grid" ? "setting__grid" : "setting__ladder"} data-count={options.length}>
        {options.map((option) => {
          const Picture: Icon = icons[option.id];
          return (
            <Radio key={option.id} value={option.id} className="setting-tile" data-danger={option.danger === true}>
              <Radio.Content className="setting-tile__body">
                <span className="setting-tile__icon" aria-hidden="true"><Picture size={18} weight="duotone" /></span>
                <span className="setting-tile__text">
                  <span className="setting-tile__label">{option.label}</span>
                  <span className="setting-tile__says">{option.says}</span>
                </span>
                {layout === "ladder" ? <Risk level={RISK[option.id as PermissionMode] ?? 0} /> : null}
                <Radio.Control className="setting-tile__check"><Radio.Indicator /></Radio.Control>
              </Radio.Content>
            </Radio>
          );
        })}
      </div>
    </RadioGroup>
  );
}

// Five bars, as many lit as the mode lets run without asking.
function Risk({ level }: { level: number }) {
  return (
    <span className="setting-risk" aria-hidden="true" data-level={level}>
      {[1, 2, 3, 4, 5].map((bar) => <i key={bar} data-on={bar <= level} />)}
    </span>
  );
}

function Group({ icon: Picture, title, children }: { icon: Icon; title: string; children: ReactNode }) {
  return (
    <section className="setting-group">
      <h3 className="setting-group__title"><Picture size={14} weight="bold" aria-hidden="true" />{title}</h3>
      {children}
    </section>
  );
}

// The agent this room runs. It can be changed here only when the room runs on the computer this page
// can reach, because the key and the agent's tools live there.
function AgentSection({ room, label }: { room: string; label: string }) {
  const { phase } = useDaemon(true);
  const [mine, setMine] = useState<boolean | null>(null);
  const [now, setNow] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const setup = useAgentSetup(phase === "ready" && mine === true);

  useEffect(() => {
    if (phase !== "ready") return;
    let live = true;
    runningRooms()
      .then((found) => live && setMine(found.rooms.some((item) => item.room === room)))
      .catch(() => live && setMine(false));
    return () => {
      live = false;
    };
  }, [phase, room]);

  // Nothing to switch while the chosen provider and model are the ones the room runs.
  const running = now ?? label;
  const same = setup.provider !== null && setup.choice !== null && running.includes(setup.provider.label) && (setup.choice.model === "" || running.includes(setup.choice.model));

  const apply = () => {
    setProblem(null);
    setBusy(true);
    setup
      .commit()
      .then((choice) => setRoomAgent(room, choice))
      .then((done) => setNow(done.agent))
      .catch((error: unknown) => setProblem(error instanceof DaemonError ? daemonMessage(error) : error instanceof Error ? error.message : "Something went wrong."))
      .finally(() => setBusy(false));
  };

  const shown = now ?? label;
  const [name, ...model] = (shown || "No agent").split(" · ");
  return (
    <section className="setting-agent">
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-3">
        <span className="setting-agent__logo">{agentMark(shown) ? <AgentLogo label={shown} size={22} decorative /> : <Robot size={22} weight="duotone" aria-hidden="true" />}</span>
        <div className="flex min-w-[8rem] flex-1 flex-col leading-tight">
          <span className="truncate font-display text-[17px] font-semibold text-foreground tracking-[-0.01em]">{name}</span>
          {model.length > 0 ? <span className="truncate font-mono text-xs text-muted">{model.join(" · ")}</span> : null}
        </div>
        <Chip size="sm" variant="soft" color={mine === true ? "accent" : "default"} className="max-sm:order-last">
          <Chip.Label>{mine === true ? "On this computer" : "On the host's computer"}</Chip.Label>
        </Chip>
      </div>
      {mine === true ? (
        <div className="mt-4 flex flex-col gap-4 border-t border-separator pt-4">
          <AgentSetup setup={setup} />
          {problem === null ? null : (
            <Alert status="danger">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Description>{problem}</Alert.Description>
              </Alert.Content>
            </Alert>
          )}
          <Button className="self-start" onPress={apply} isDisabled={busy || setup.provider === null || setup.blocker !== null || same}>
            {busy ? <Spinner size="sm" color="current" /> : <ArrowsClockwise size={15} />}
            {busy ? "Switching…" : "Switch agent"}
          </Button>
        </div>
      ) : (
        <p className="mt-3 flex items-center gap-2 text-[13px] text-muted">
          {phase === "checking" || (phase === "ready" && mine === null) ? <Spinner size="sm" color="current" /> : <Desktop size={15} aria-hidden="true" />}
          {phase === "checking" || (phase === "ready" && mine === null) ? "Looking for this room on your computer…" : "The agent is picked on the computer that runs this room. Open this page there to switch it."}
        </p>
      )}
    </section>
  );
}

interface RoomSettingsProps {
  room: string;
  projection: Projection;
  send: (command: Command) => void;
  onClose: () => void;
}

// What the host can change while the room runs.
export function RoomSettings({ room, projection, send, onClose }: RoomSettingsProps) {
  const { state, agentLabel } = projection;
  // The danger zone is the one choice that is asked twice: turning it off is one tap, turning it on is a warning first.
  const [warning, setWarning] = useState(false);
  const setPermission = (mode: PermissionMode) => (mode === "danger" && state.permission_mode !== "danger" ? setWarning(true) : send({ type: "session.set_permission_mode", mode }));
  return (
    <>
    <Modal.Backdrop isOpen onOpenChange={(open) => !open && onClose()}>
      <Modal.Container scroll="inside">
        <Modal.Dialog className="settings-dialog sm:max-w-[42rem]">
          <Modal.CloseTrigger />
          <Modal.Header className="flex-row items-center gap-3.5">
            <span className="setting-agent__logo" aria-hidden="true"><GearSix size={20} weight="duotone" /></span>
            <div className="flex flex-col">
              <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">Room settings</Modal.Heading>
              <p className="text-[13px] text-muted">Every change reaches the whole room at once.</p>
            </div>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-7">
            <AgentSection room={room} label={agentLabel} />
            <Group icon={ChatsCircle} title="Conversation">
              <Choice title="Who may prompt" options={PROMPTS} icons={PROMPT_ICONS} value={state.prompt_mode} onChange={(mode) => send({ type: "session.set_prompt_mode", mode })} />
              <Choice title="When the agent answers" options={REPLIES} icons={REPLY_ICONS} value={state.chat_mode} onChange={(mode) => send({ type: "session.set_chat_mode", mode })} />
            </Group>
            <Group icon={ShieldCheck} title="What the agent may do">
              <Choice title="Without asking you" hint="Safest first" layout="ladder" options={LADDER} icons={PERMISSION_ICONS} value={state.permission_mode} onChange={setPermission} />
            </Group>
            <Group icon={DoorOpen} title="Access">
              <Choice title="Who gets in with the room link" options={ADMISSION} icons={ADMISSION_ICONS} value={state.admission} onChange={(mode) => send({ type: "link.set_admission", mode })} />
              <Choice title="Briefings of this session" options={BRIEFINGS} icons={BRIEFING_ICONS} value={state.briefing_sharing} onChange={(mode) => send({ type: "session.set_briefing_sharing", mode })} />
            </Group>
          </Modal.Body>
          <Modal.Footer>
            <Button slot="close">Done</Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
    {warning ? (
      <Confirm
        title={DANGER_TITLE}
        body={DANGER_WARNING}
        action="I take responsibility"
        onConfirm={async () => send({ type: "session.set_permission_mode", mode: "danger" })}
        onClose={() => setWarning(false)}
      />
    ) : null}
    </>
  );
}
