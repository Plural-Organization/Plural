import { Button, Card, Description, Label, Modal, Radio, RadioGroup } from "@heroui/react";
import type { Command, Projection } from "@plural/client";
import { type Option, ADMISSION, BRIEFINGS, PERMISSIONS, PROMPTS } from "../lib/roomSettings";
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

interface RoomSettingsProps {
  projection: Projection;
  send: (command: Command) => void;
  onClose: () => void;
}

// What the host can change while the room runs.
export function RoomSettings({ projection, send, onClose }: RoomSettingsProps) {
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
            <Card variant="secondary">
              <Card.Header>
                <Card.Title className="text-[15px]">Agent</Card.Title>
              </Card.Header>
              <Card.Content className="flex-row items-center gap-3">
                <AgentLogo label={agentLabel} size={20} />
                <p className="min-w-0 flex-1 truncate text-[15px]">{agentLabel || "No agent"}</p>
              </Card.Content>
              <Card.Footer>
                <Card.Description>It is chosen where the room runs. Choosing it from this page comes next.</Card.Description>
              </Card.Footer>
            </Card>
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
