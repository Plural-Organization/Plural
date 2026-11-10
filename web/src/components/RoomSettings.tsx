import { Button, Modal, ToggleButton, ToggleButtonGroup, type Key } from "@heroui/react";
import type { Command, Projection } from "@plural/client";
import { type Option, ADMISSION, BRIEFINGS, PERMISSIONS, PROMPTS, saysOf } from "../lib/roomSettings";
import { AgentLogo } from "./AgentLogo";

interface ChoiceProps<T extends string> {
  title: string;
  options: Option<T>[];
  value: T;
  onChange: (next: T) => void;
}

// One setting: its name, the choices, and a line that says what the current choice means.
function Choice<T extends string>({ title, options, value, onChange }: ChoiceProps<T>) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-[15px] font-medium">{title}</h3>
      <ToggleButtonGroup
        size="sm"
        selectionMode="single"
        disallowEmptySelection
        aria-label={title}
        selectedKeys={new Set<Key>([value])}
        onSelectionChange={(keys) => {
          const next = [...keys][0] as T | undefined;
          if (next !== undefined && next !== value) {
            onChange(next);
          }
        }}
      >
        {options.map((option, index) => (
          <ToggleButton key={option.id} id={option.id}>
            {index > 0 ? <ToggleButtonGroup.Separator /> : null}
            {option.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
      <p className="text-sm leading-relaxed text-muted text-pretty">{saysOf(options, value)}</p>
    </section>
  );
}

interface RoomSettingsProps {
  projection: Projection;
  send: (command: Command) => void;
  onClose: () => void;
}

// What the host can change while the room runs. Changes apply at once and everyone sees them.
export function RoomSettings({ projection, send, onClose }: RoomSettingsProps) {
  const { state, agentLabel } = projection;
  return (
    <Modal.Backdrop isOpen onOpenChange={(open) => !open && onClose()}>
      <Modal.Container>
        <Modal.Dialog className="sm:max-w-[34rem]">
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">Room settings</Modal.Heading>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-6">
            <section className="flex flex-col gap-2">
              <h3 className="text-[15px] font-medium">Agent</h3>
              <div className="flex items-center gap-3 rounded-2xl border border-border bg-background px-3.5 py-3">
                <AgentLogo label={agentLabel} size={20} />
                <p className="min-w-0 flex-1 truncate text-[15px]">{agentLabel || "No agent"}</p>
              </div>
              <p className="text-sm leading-relaxed text-muted text-pretty">
                It is chosen where the room runs. Choosing it from this page comes next.
              </p>
            </section>
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
