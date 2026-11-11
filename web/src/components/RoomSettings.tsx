import { Alert, Button, Card, Description, Label, Modal, Radio, RadioGroup, Spinner } from "@heroui/react";
import type { Command, Projection } from "@plural/client";
import { useEffect, useState } from "react";
import { useAgentSetup } from "../hooks/useAgentSetup";
import { useDaemon } from "../hooks/useDaemon";
import { runningRooms, setRoomAgent } from "../lib/agent";
import { DaemonError, daemonMessage } from "../lib/daemon";
import { type Option, ADMISSION, BRIEFINGS, PERMISSIONS, PROMPTS } from "../lib/roomSettings";
import { AgentSetup } from "./AgentSetup";
import { AgentLogo } from "./AgentLogo";

interface ChoiceProps<T extends string> {
  title: string;
  options: Option<T>[];
  value: T;
  onChange: (next: T) => void;
}

// One setting: its name and the choices, each saying what it does. A change reaches the room at once.
function Choice<T extends string>({ title, options, value, onChange }: ChoiceProps<T>) {
  return (
    <RadioGroup aria-label={title} value={value} onChange={(next) => onChange(next as T)}>
      <Label className="text-[15px] font-medium">{title}</Label>
      {options.map((option) => (
        <Radio key={option.id} value={option.id}>
          <Radio.Control>
            <Radio.Indicator />
          </Radio.Control>
          <Radio.Content>
            <Label>{option.label}</Label>
            <Description>{option.says}</Description>
          </Radio.Content>
        </Radio>
      ))}
    </RadioGroup>
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

  return (
    <Card variant="secondary">
      <Card.Header>
        <Card.Title className="text-[15px]">Agent</Card.Title>
      </Card.Header>
      <Card.Content className="gap-4">
        <div className="flex items-center gap-3">
          <AgentLogo label={now ?? label} size={20} />
          <p className="min-w-0 flex-1 truncate text-[15px]">{now ?? (label || "No agent")}</p>
        </div>
        {mine === true ? (
          <>
            <AgentSetup setup={setup} />
            {problem === null ? null : (
              <Alert status="danger">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Description>{problem}</Alert.Description>
                </Alert.Content>
              </Alert>
            )}
            <Button className="self-start" onPress={apply} isDisabled={busy || setup.blocker !== null}>
              {busy ? <Spinner size="sm" color="current" /> : null}
              {busy ? "Switching…" : "Switch agent"}
            </Button>
          </>
        ) : (
          <Description>{phase === "checking" || (phase === "ready" && mine === null) ? "Looking for this room on your computer…" : "The agent is chosen on the computer that runs this room."}</Description>
        )}
      </Card.Content>
    </Card>
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
  return (
    <Modal.Backdrop isOpen onOpenChange={(open) => !open && onClose()}>
      <Modal.Container scroll="inside">
        <Modal.Dialog className="sm:max-w-[34rem]">
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">Room settings</Modal.Heading>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-6">
            <AgentSection room={room} label={agentLabel} />
            <Choice title="Who may prompt" options={PROMPTS} value={state.prompt_mode} onChange={(mode) => send({ type: "session.set_prompt_mode", mode })} />
            <Choice title="What the agent may do" options={PERMISSIONS} value={state.permission_mode} onChange={(mode) => send({ type: "session.set_permission_mode", mode })} />
            <Choice title="Who gets in with the room link" options={ADMISSION} value={state.admission} onChange={(mode) => send({ type: "link.set_admission", mode })} />
            <Choice title="Briefings of this session" options={BRIEFINGS} value={state.briefing_sharing} onChange={(mode) => send({ type: "session.set_briefing_sharing", mode })} />
          </Modal.Body>
          <Modal.Footer>
            <Button slot="close">Done</Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
